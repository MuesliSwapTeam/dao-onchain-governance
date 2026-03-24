"""
Transaction builders for sub-DAO creation.

Two-step workflow
-----------------
1. POST /api/v1/gov/create-sub-dao-tally
   Creates a tally in the parent DAO proposing the creation of a new sub-DAO.
   The nft_utxo is NOT spent here — it is pre-committed to derive the future
   sub-DAO NFT token name deterministically.

2. POST /api/v1/gov/execute-sub-dao
   After the tally passes (expired + quorum met), executes the winning proposal:
   spends the nft_utxo, mints the sub-DAO NFT, and creates the initial sub-DAO
   GovStateDatum UTxO at the address specified in the proposal.
"""

import datetime
from fractions import Fraction

import pycardano
from opshin.prelude import Token
from pycardano import (
    Address,
    AlonzoMetadata,
    AuxiliaryData,
    Metadata,
    Redeemer,
    TransactionBuilder,
    TransactionOutput,
    Value,
)

from muesliswap_onchain_governance.onchain.delegation import delegated_staking
from muesliswap_onchain_governance.onchain.gov_state import gov_state, gov_state_nft
from muesliswap_onchain_governance.onchain.gov_state.gov_state_nft import (
    SubDaoMintRedeemer,
)
from muesliswap_onchain_governance.onchain.staking import vault_ft, staking_vote_nft
from muesliswap_onchain_governance.onchain.tally import tally, tally_auth_nft
from muesliswap_onchain_governance.utils.from_script_context import from_address
from muesliswap_onchain_governance.utils.network import context, evaluation_context
from muesliswap_onchain_governance.utils.to_script_context import (
    to_address,
    to_fraction,
    to_tx_out_ref,
)

from ...utils import network
from ...utils.contracts import get_contract, get_ref_utxo, module_name
from ..schema import CreateSubDaoTallyResponse, SignedTxResponse
from ..cardano.util import get_collateral_signing_info, get_collateral_utxo
from ...offchain.util import (
    TALLY_METADATA_KEY,
    asset_from_token,
    sorted_utxos,
    with_min_lovelace,
)


async def construct_create_sub_dao_tally_tx(
    proposer_address_hex: str,
    parent_gov_nft_name: str,
    nft_utxo_tx_hash: str,
    nft_utxo_index: int,
    sub_dao_address: str,
    duration_minutes: int = 1500,
    sub_dao_min_quorum: int = None,
    sub_dao_min_winning_threshold_num: int = 1,
    sub_dao_min_winning_threshold_den: int = 4,
    sub_dao_min_proposal_duration: int = None,
    title: str = "Create Sub-DAO",
    description: str = "This proposal creates a new sub-DAO governance thread.",
) -> dict:
    """
    Build an unsigned TX that creates a CreateSubDaoParams tally in the parent DAO.

    The nft_utxo identified by (nft_utxo_tx_hash, nft_utxo_index) is NOT spent
    in this transaction. It is used only to compute the future sub-DAO NFT token
    name. The proposer must keep this UTxO unspent until execute_sub_dao is called.

    Returns a CreateSubDaoTallyResponse dict with:
      signed_tx      — CBOR hex, partially signed by server collateral key
      tx_body        — CBOR hex of unsigned TX body
      sub_dao_nft_name — hex token name the sub-DAO NFT will have
    """
    # ------------------------------------------------------------------
    # Load contracts
    # ------------------------------------------------------------------
    gov_state_script, _, gov_state_address = get_contract(module_name(gov_state), True)
    gov_state_script_ref = get_ref_utxo(gov_state_script, context)
    tally_script, _, tally_address = get_contract(module_name(tally), True)
    tally_auth_nft_script, tally_auth_nft_policy_id, _ = get_contract(
        module_name(tally_auth_nft), True
    )
    tally_auth_nft_ref = get_ref_utxo(tally_auth_nft_script, context)
    _, gov_state_nft_policy_id, _ = get_contract(module_name(gov_state_nft), True)
    _, vault_ft_policy_id, _ = get_contract(module_name(vault_ft), True)
    _, delegated_staking_policy_id, _ = get_contract(
        module_name(delegated_staking), True
    )
    _, staking_vote_nft_policy_id, _ = get_contract(
        module_name(staking_vote_nft), True
    )

    # ------------------------------------------------------------------
    # Resolve proposer address
    # ------------------------------------------------------------------
    proposer = Address.from_primitive(bytes.fromhex(proposer_address_hex))

    # ------------------------------------------------------------------
    # Find parent governance thread
    # ------------------------------------------------------------------
    gov_state_nft_tk = Token(
        gov_state_nft_policy_id.payload, bytes.fromhex(parent_gov_nft_name)
    )
    gov_utxos = context.utxos(gov_state_address)
    gov_state_utxo = None
    for u in gov_utxos:
        if u.output.amount.multi_asset.get(
            pycardano.ScriptHash(gov_state_nft_tk.policy_id), {}
        ).get(pycardano.AssetName(gov_state_nft_tk.token_name)):
            gov_state_utxo = u
            break
    assert gov_state_utxo, f"No parent governance thread found for NFT {parent_gov_nft_name}"

    prev_gov_state_datum: gov_state.GovStateDatum = gov_state.GovStateDatum.from_cbor(
        gov_state_utxo.output.datum.cbor
    )
    parent_params = prev_gov_state_datum.params

    # ------------------------------------------------------------------
    # Locate the pre-committed UTxO and derive sub-DAO NFT name
    # ------------------------------------------------------------------
    proposer_utxos = context.utxos(proposer)
    nft_utxo = None
    for u in proposer_utxos:
        if (
            u.input.transaction_id.payload.hex() == nft_utxo_tx_hash
            and u.input.index == nft_utxo_index
        ):
            nft_utxo = u
            break
    assert nft_utxo, (
        f"UTxO {nft_utxo_tx_hash}#{nft_utxo_index} not found at proposer address"
    )

    sub_dao_nft_name = gov_state_nft.gov_state_nft_name(to_tx_out_ref(nft_utxo.input))
    sub_dao_nft_token = Token(
        policy_id=gov_state_nft_policy_id.payload,
        token_name=sub_dao_nft_name,
    )

    # ------------------------------------------------------------------
    # Resolve sub-DAO target address
    # ------------------------------------------------------------------
    pycardano_sub_dao_address = pycardano.Address.from_primitive(
        pycardano.Address.decode(sub_dao_address).to_primitive()
    )
    assert pycardano_sub_dao_address != gov_state_address, (
        "sub_dao_address must differ from the parent gov_state address"
    )

    # ------------------------------------------------------------------
    # Derive sub-DAO governance parameters (inherit from parent by default)
    # ------------------------------------------------------------------
    if sub_dao_min_quorum is None:
        sub_dao_min_quorum = parent_params.min_quorum
    if sub_dao_min_proposal_duration is None:
        sub_dao_min_proposal_duration = parent_params.min_proposal_duration

    # ------------------------------------------------------------------
    # Build the CreateSubDaoParams proposal
    # ------------------------------------------------------------------
    sub_dao_params = gov_state.GovStateParams(
        tally_address=parent_params.tally_address,
        staking_address=parent_params.staking_address,
        governance_token=parent_params.governance_token,
        vault_ft_policy=vault_ft_policy_id.payload,
        delegation_policy=delegated_staking_policy_id.payload,
        min_quorum=sub_dao_min_quorum,
        min_winning_threshold=to_fraction(
            Fraction(
                sub_dao_min_winning_threshold_num,
                sub_dao_min_winning_threshold_den,
            )
        ),
        min_proposal_duration=sub_dao_min_proposal_duration,
        gov_state_nft=sub_dao_nft_token,
        tally_auth_nft_policy=tally_auth_nft_policy_id.payload,
        staking_vote_nft_policy=staking_vote_nft_policy_id.payload,
        latest_applied_proposal_id=gov_state.ALWAYS_EARLY_PROPOSAL_ID,
        parent_gov_nft=parent_params.gov_state_nft,
        parent_tally_auth_nft_policy=parent_params.tally_auth_nft_policy,
        latest_applied_parent_proposal_id=gov_state.ALWAYS_EARLY_PROPOSAL_ID,
    )
    create_sub_dao_proposal = gov_state.CreateSubDaoParams(
        params=sub_dao_params,
        address=to_address(pycardano_sub_dao_address),
    )

    # ------------------------------------------------------------------
    # Build tally state
    # ------------------------------------------------------------------
    auth_nft_tk = Token(tally_auth_nft_policy_id.payload, gov_state_nft_tk.token_name)

    # Exclude nft_utxo from fee inputs — it must remain unspent until execute step
    fee_utxos = [u for u in proposer_utxos if u != nft_utxo]
    all_inputs = sorted_utxos([gov_state_utxo] + fee_utxos)
    gov_state_input_index = all_inputs.index(gov_state_utxo)
    new_proposal_id = gov_state.increment_proposal_id(
        prev_gov_state_datum.last_proposal_id
    )
    new_gov_state_datum = gov_state.GovStateDatum(
        params=prev_gov_state_datum.params,
        last_proposal_id=new_proposal_id,
    )

    end_time = int(
        (
            datetime.datetime.now() + datetime.timedelta(minutes=duration_minutes)
        ).timestamp()
    ) * 1000

    tally_state = tally.TallyState(
        votes=[0, 0],
        params=tally.ProposalParams(
            quorum=parent_params.min_quorum,
            winning_threshold=parent_params.min_winning_threshold,
            proposals=[
                tally.Nothing(),
                create_sub_dao_proposal,
            ],
            end_time=tally.FinitePOSIXTime(end_time),
            proposal_id=new_proposal_id,
            tally_auth_nft=auth_nft_tk,
            staking_vote_nft_policy=parent_params.staking_vote_nft_policy,
            staking_address=parent_params.staking_address,
            governance_token=parent_params.governance_token,
            vault_ft_policy=vault_ft_policy_id.payload,
            delegation_policy=delegated_staking_policy_id.payload,
        ),
    )

    # ------------------------------------------------------------------
    # Build transaction
    # ------------------------------------------------------------------
    builder = TransactionBuilder(evaluation_context)
    builder.auxiliary_data = AuxiliaryData(
        data=AlonzoMetadata(
            metadata=Metadata(
                {
                    674: {"msg": ["MuesliSwap DAO Sub-DAO Creation Tally"]},
                    TALLY_METADATA_KEY: {
                        "title": title,
                        "description": [description],
                        "short_description": ["Create a new sub-DAO."],
                        "proposals": [
                            {"title": "Nothing", "description": ["No-op proposal."]},
                            {
                                "title": "Create Sub-DAO",
                                "description": ["Bootstrap new sub-DAO governance thread."],
                            },
                        ],
                    },
                }
            )
        )
    )

    for u in fee_utxos:
        builder.add_input(u)
    builder.add_script_input(
        gov_state_utxo,
        gov_state_script_ref or gov_state_script,
        None,
        Redeemer(
            gov_state.CreateNewTally(
                gov_state_input_index=gov_state_input_index,
                gov_state_output_index=1,
                tally_output_index=0,
            )
        ),
    )
    builder.add_minting_script(
        tally_auth_nft_ref or tally_auth_nft_script,
        Redeemer(
            tally_auth_nft.AuthRedeemer(
                spent_utxo_index=gov_state_input_index,
                governance_nft_name=gov_state_nft_tk.token_name,
            )
        ),
    )
    builder.mint = asset_from_token(auth_nft_tk, 1)

    tally_output = with_min_lovelace(
        TransactionOutput(
            address=tally_address,
            amount=Value(coin=2_000_000, multi_asset=asset_from_token(auth_nft_tk, 1)),
            datum=tally_state,
        ),
        context,
    )
    builder.add_output(tally_output)
    builder.add_output(
        pycardano.TransactionOutput(
            address=gov_state_address,
            amount=gov_state_utxo.output.amount,
            datum=new_gov_state_datum,
        )
    )
    builder.ttl = context.last_block_slot + 100
    builder.fee_buffer = 100
    builder.collaterals = [get_collateral_utxo(network)]
    _, collateral_skey, collateral_address = get_collateral_signing_info(network)

    signed_tx = builder.build_and_sign(
        signing_keys=[collateral_skey],
        change_address=proposer,
        merge_change=True,
        collateral_change_address=collateral_address,
    )

    return CreateSubDaoTallyResponse(
        signed_tx=signed_tx.to_cbor_hex(),
        tx_body=signed_tx.transaction_body.to_cbor_hex(),
        sub_dao_nft_name=sub_dao_nft_name.hex(),
    ).model_dump()


async def construct_execute_sub_dao_tx(
    proposer_address_hex: str,
    parent_gov_nft_name: str,
    nft_utxo_tx_hash: str,
    nft_utxo_index: int,
) -> dict:
    """
    Build a TX that executes a winning CreateSubDaoParams tally.

    The nft_utxo IS spent in this transaction. It must be the same UTxO that
    was passed to construct_create_sub_dao_tally_tx.

    Returns a SignedTxResponse dict.
    """
    # ------------------------------------------------------------------
    # Load contracts
    # ------------------------------------------------------------------
    gov_state_script, _, gov_state_address = get_contract(module_name(gov_state), True)
    gov_state_script_ref = get_ref_utxo(gov_state_script, context)
    gov_state_nft_script, gov_state_nft_policy_id, _ = get_contract(
        module_name(gov_state_nft), True
    )
    gov_state_nft_ref = get_ref_utxo(gov_state_nft_script, context)
    _, _, tally_address = get_contract(module_name(tally), True)

    # ------------------------------------------------------------------
    # Resolve proposer address
    # ------------------------------------------------------------------
    proposer = Address.from_primitive(bytes.fromhex(proposer_address_hex))

    # ------------------------------------------------------------------
    # Find parent governance thread UTxO
    # ------------------------------------------------------------------
    gov_state_nft_tk = Token(
        gov_state_nft_policy_id.payload, bytes.fromhex(parent_gov_nft_name)
    )
    gov_utxos = context.utxos(gov_state_address)
    gov_state_utxo = None
    for u in gov_utxos:
        if u.output.amount.multi_asset.get(
            pycardano.ScriptHash(gov_state_nft_tk.policy_id), {}
        ).get(pycardano.AssetName(gov_state_nft_tk.token_name)):
            gov_state_utxo = u
            break
    assert gov_state_utxo, f"No parent governance thread found for NFT {parent_gov_nft_name}"

    prev_gov_state_datum: gov_state.GovStateDatum = gov_state.GovStateDatum.from_cbor(
        gov_state_utxo.output.datum.cbor
    )
    parent_params = prev_gov_state_datum.params

    # ------------------------------------------------------------------
    # Find the winning CreateSubDaoParams tally
    # ------------------------------------------------------------------
    tally_utxos = context.utxos(tally_address)
    tally_state_utxo = None
    winning_proposal = None
    tally_state_datum = None

    for u in tally_utxos:
        try:
            datum = tally.TallyState.from_cbor(u.output.datum.cbor)
        except Exception:
            continue
        if datum.params.proposal_id <= parent_params.latest_applied_proposal_id:
            continue
        if datum.params.tally_auth_nft.policy_id != parent_params.tally_auth_nft_policy:
            continue
        if datum.params.tally_auth_nft.token_name != gov_state_nft_tk.token_name:
            continue
        if (
            not isinstance(datum.params.end_time, tally.FinitePOSIXTime)
            or datum.params.end_time.time > datetime.datetime.now().timestamp() * 1000
        ):
            continue
        winning_idx = max(enumerate(datum.votes), key=lambda x: x[1])[0]
        candidate = datum.params.proposals[winning_idx]
        try:
            candidate = gov_state.CreateSubDaoParams.from_cbor(candidate.to_cbor())
        except Exception:
            continue
        tally_state_datum = datum
        winning_proposal = candidate
        tally_state_utxo = u
        break

    assert tally_state_utxo, (
        "No winning CreateSubDaoParams tally found for this governance thread"
    )

    # ------------------------------------------------------------------
    # Locate the pre-committed UTxO
    # ------------------------------------------------------------------
    proposer_utxos = context.utxos(proposer)
    nft_utxo = None
    for u in proposer_utxos:
        if (
            u.input.transaction_id.payload.hex() == nft_utxo_tx_hash
            and u.input.index == nft_utxo_index
        ):
            nft_utxo = u
            break
    assert nft_utxo, (
        f"UTxO {nft_utxo_tx_hash}#{nft_utxo_index} not found at proposer address"
    )

    expected_nft_name = gov_state_nft.gov_state_nft_name(to_tx_out_ref(nft_utxo.input))
    assert expected_nft_name == winning_proposal.params.gov_state_nft.token_name, (
        f"NFT name mismatch: UTxO produces {expected_nft_name.hex()} but "
        f"proposal expects {winning_proposal.params.gov_state_nft.token_name.hex()}"
    )
    sub_dao_nft_token = winning_proposal.params.gov_state_nft

    # ------------------------------------------------------------------
    # Sort inputs for deterministic redeemer indices
    # ------------------------------------------------------------------
    other_payment_utxos = [u for u in proposer_utxos if u != nft_utxo]
    all_inputs = sorted_utxos([gov_state_utxo, nft_utxo] + other_payment_utxos)
    parent_gov_input_index = all_inputs.index(gov_state_utxo)
    nft_utxo_sorted_index = all_inputs.index(nft_utxo)

    all_ref_utxos = sorted_utxos(
        [tally_state_utxo]
        + ([gov_state_script_ref] if isinstance(gov_state_script_ref, pycardano.UTxO) else [])
    )
    tally_input_index = all_ref_utxos.index(tally_state_utxo)

    sub_dao_output_index = 0
    parent_output_index = 1

    # ------------------------------------------------------------------
    # Build parent continuing datum
    # ------------------------------------------------------------------
    updated_parent_params = gov_state.GovStateParams(
        tally_address=parent_params.tally_address,
        staking_address=parent_params.staking_address,
        governance_token=parent_params.governance_token,
        vault_ft_policy=parent_params.vault_ft_policy,
        delegation_policy=parent_params.delegation_policy,
        min_quorum=parent_params.min_quorum,
        min_winning_threshold=parent_params.min_winning_threshold,
        min_proposal_duration=parent_params.min_proposal_duration,
        gov_state_nft=parent_params.gov_state_nft,
        tally_auth_nft_policy=parent_params.tally_auth_nft_policy,
        staking_vote_nft_policy=parent_params.staking_vote_nft_policy,
        latest_applied_proposal_id=tally_state_datum.params.proposal_id,
        parent_gov_nft=parent_params.parent_gov_nft,
        parent_tally_auth_nft_policy=parent_params.parent_tally_auth_nft_policy,
        latest_applied_parent_proposal_id=parent_params.latest_applied_parent_proposal_id,
    )
    new_parent_gov_state = gov_state.GovStateDatum(
        params=updated_parent_params,
        last_proposal_id=prev_gov_state_datum.last_proposal_id,
    )

    # ------------------------------------------------------------------
    # Build initial sub-DAO datum
    # ------------------------------------------------------------------
    initial_sub_dao_state = gov_state.GovStateDatum(
        params=winning_proposal.params,
        last_proposal_id=gov_state.INITIAL_PROPOSAL_ID,
    )
    sub_dao_pycardano_address = from_address(winning_proposal.address)

    # ------------------------------------------------------------------
    # Build transaction
    # ------------------------------------------------------------------
    builder = TransactionBuilder(evaluation_context)
    builder.auxiliary_data = AuxiliaryData(
        data=AlonzoMetadata(
            metadata=Metadata({674: {"msg": ["MuesliSwap DAO Create Sub-DAO"]}})
        )
    )

    builder.add_script_input(
        gov_state_utxo,
        gov_state_script_ref or gov_state_script,
        None,
        Redeemer(
            gov_state.CreateSubDao(
                gov_state_input_index=parent_gov_input_index,
                gov_state_output_index=parent_output_index,
                tally_input_index=tally_input_index,
                sub_dao_output_index=sub_dao_output_index,
            )
        ),
    )
    builder.add_input(nft_utxo)
    for u in other_payment_utxos:
        builder.add_input(u)

    builder.add_minting_script(
        gov_state_nft_ref or gov_state_nft_script,
        Redeemer(
            SubDaoMintRedeemer(
                unique_utxo_index=nft_utxo_sorted_index,
                parent_gov_state_input_index=parent_gov_input_index,
                tally_ref_index=tally_input_index,
                sub_dao_output_index=sub_dao_output_index,
            )
        ),
    )
    builder.mint = asset_from_token(sub_dao_nft_token, 1)

    builder.add_output(
        with_min_lovelace(
            TransactionOutput(
                address=sub_dao_pycardano_address,
                amount=Value(coin=2_000_000, multi_asset=asset_from_token(sub_dao_nft_token, 1)),
                datum=initial_sub_dao_state,
            ),
            context,
        )
    )
    builder.add_output(
        pycardano.TransactionOutput(
            address=gov_state_address,
            amount=gov_state_utxo.output.amount,
            datum=new_parent_gov_state,
        )
    )

    builder.reference_inputs.add(tally_state_utxo)
    builder.validity_start = context.last_block_slot
    builder.fee_buffer = 100
    builder.collaterals = [get_collateral_utxo(network)]
    _, collateral_skey, collateral_address = get_collateral_signing_info(network)

    signed_tx = builder.build_and_sign(
        signing_keys=[collateral_skey],
        change_address=proposer,
        merge_change=True,
        collateral_change_address=collateral_address,
    )

    return SignedTxResponse(
        signed_tx=signed_tx.to_cbor_hex(),
        tx_body=signed_tx.transaction_body.to_cbor_hex(),
    ).model_dump()
