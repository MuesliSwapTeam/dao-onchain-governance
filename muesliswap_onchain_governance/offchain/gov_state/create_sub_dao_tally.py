"""
Create a tally in the parent DAO proposing the creation of a new sub-DAO.

Workflow
--------
1.  Pre-select a UTxO from your wallet whose hash will become the sub-DAO's
    gov_state_nft token name.  This UTxO is NOT spent here — it is preserved
    so it can be consumed later in create_sub_dao.py to derive the NFT name.
2.  Choose the address where the sub-DAO governance state will live.
    NOTE: This address MUST differ from the parent's gov_state address.
    Options:
      - A separately compiled/parameterised version of gov_state.py.
      - Any other script address with equivalent spend logic.
3.  Run this script to submit the tally.  After the voting period the winning
    proposal can be executed with offchain/gov_state/create_sub_dao.py.
"""

import datetime

import fire
import pycardano
from fractions import Fraction
from opshin.prelude import Token
from pycardano import (
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
from muesliswap_onchain_governance.onchain.staking import vault_ft, staking_vote_nft
from muesliswap_onchain_governance.onchain.tally import tally, tally_auth_nft
from muesliswap_onchain_governance.utils.network import context, show_tx, evaluation_context
from muesliswap_onchain_governance.utils.to_script_context import (
    to_address,
    to_fraction,
    to_tx_out_ref,
)

from ...utils import get_signing_info, network, get_address
from ...utils.contracts import get_contract, get_ref_utxo, module_name
from ..util import (
    GOV_STATE_NFT_TK_NAME,
    TALLY_METADATA_KEY,
    asset_from_token,
    sorted_utxos,
    with_min_lovelace,
)


def main(
    wallet: str = "creator",
    gov_state_nft_tk_name: str = GOV_STATE_NFT_TK_NAME,
    # UTxO pre-committed for sub-DAO NFT minting — must be spent in create_sub_dao.py
    nft_utxo_txhash: str = "",
    nft_utxo_index: int = 0,
    # Address where the sub-DAO governance state will be deployed.
    # MUST differ from the parent gov_state address.
    sub_dao_address: str = "",
    # Sub-DAO governance parameters — default to inheriting from parent
    sub_dao_min_quorum: int = None,
    sub_dao_min_winning_threshold_num: int = 1,
    sub_dao_min_winning_threshold_den: int = 4,
    sub_dao_min_proposal_duration: int = None,
    duration_open: int = 60 * 25,  # minutes the tally remains open
):
    """
    Submit a CreateSubDaoParams tally to the parent DAO.

    The sub-DAO NFT token name is derived from the UTxO identified by
    nft_utxo_txhash / nft_utxo_index.  Record the printed NFT name — you
    will need it when running create_sub_dao.py.
    """
    # ------------------------------------------------------------------
    # Load script info
    # ------------------------------------------------------------------
    (gov_state_script, _, gov_state_address) = get_contract(
        module_name(gov_state), True
    )
    gov_state_script_ref_utxo = get_ref_utxo(gov_state_script, context)
    (tally_script, _, tally_address) = get_contract(module_name(tally), True)
    tally_script_ref_utxo = get_ref_utxo(tally_script, context)
    (tally_auth_nft_script, tally_auth_nft_policy_id, _) = get_contract(
        module_name(tally_auth_nft), True
    )
    tally_auth_nft_script_ref_utxo = get_ref_utxo(tally_auth_nft_script, context)
    (_, gov_state_nft_policy_id, _) = get_contract(module_name(gov_state_nft), True)
    (_, vault_ft_policy_id, _) = get_contract(module_name(vault_ft), True)
    (_, delegated_staking_policy_id, _) = get_contract(
        module_name(delegated_staking), True
    )
    (_, staking_vote_nft_policy_id, _) = get_contract(
        module_name(staking_vote_nft), True
    )

    # ------------------------------------------------------------------
    # Resolve payment signer
    # ------------------------------------------------------------------
    payment_vkey, payment_skey, payment_address = get_signing_info(
        wallet, network=network
    )

    # ------------------------------------------------------------------
    # Find parent governance thread
    # ------------------------------------------------------------------
    gov_state_nft_tk = Token(
        gov_state_nft_policy_id.payload, bytes.fromhex(gov_state_nft_tk_name)
    )
    gov_utxos = context.utxos(gov_state_address)
    gov_state_utxo = None
    for u in gov_utxos:
        if u.output.amount.multi_asset.get(
            pycardano.ScriptHash(gov_state_nft_tk.policy_id), {}
        ).get(pycardano.AssetName(gov_state_nft_tk.token_name)):
            gov_state_utxo = u
            break
    assert gov_state_utxo, "No parent governance thread found"

    prev_gov_state_datum: gov_state.GovStateDatum = gov_state.GovStateDatum.from_cbor(
        gov_state_utxo.output.datum.cbor
    )
    parent_params = prev_gov_state_datum.params

    # ------------------------------------------------------------------
    # Locate the pre-committed wallet UTxO and derive sub-DAO NFT name
    # ------------------------------------------------------------------
    assert nft_utxo_txhash, (
        "nft_utxo_txhash is required — pick any UTxO you control and will "
        "spend in the subsequent create_sub_dao.py transaction"
    )
    payment_utxos = context.utxos(payment_address)
    nft_utxo = None
    for u in payment_utxos:
        if (
            u.input.transaction_id.payload.hex() == nft_utxo_txhash
            and u.input.index == nft_utxo_index
        ):
            nft_utxo = u
            break
    assert nft_utxo, (
        f"UTxO {nft_utxo_txhash}#{nft_utxo_index} not found in wallet {wallet}"
    )

    sub_dao_nft_name = gov_state_nft.gov_state_nft_name(
        to_tx_out_ref(nft_utxo.input)
    )
    sub_dao_nft_token = Token(
        policy_id=gov_state_nft_policy_id.payload,
        token_name=sub_dao_nft_name,
    )
    print(f"Sub-DAO gov_state_nft token name: {sub_dao_nft_name.hex()}")
    print(
        "Record this value — you will need it when calling create_sub_dao.py "
        "after the tally passes."
    )

    # ------------------------------------------------------------------
    # Resolve sub-DAO target address
    # ------------------------------------------------------------------
    assert sub_dao_address, (
        "sub_dao_address is required.  It must differ from the parent gov_state "
        "address.  Deploy a separately parameterised gov_state script and pass "
        "its bech32 address here."
    )
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
    # The sub-DAO's staking and tally addresses reuse the same contracts as
    # the parent in this demo.  In production you may deploy dedicated
    # instances.
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
        # parent reference — filled in by the on-chain validator; must match
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

    payment_utxos = context.utxos(payment_address)
    # Exclude nft_utxo from this transaction — it must remain unspent so it
    # can be consumed later in create_sub_dao.py to prove the one-shot NFT name.
    fee_utxos = [u for u in payment_utxos if u != nft_utxo]
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
            datetime.datetime.now() + datetime.timedelta(minutes=duration_open)
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
                        "title": "Create Sub-DAO",
                        "description": [
                            "This proposal creates a new sub-DAO governance thread.",
                        ],
                        "short_description": ["Create a new sub-DAO."],
                        "proposals": [
                            {"title": "Nothing", "description": ["No-op proposal."]},
                            {
                                "title": "Create Sub-DAO",
                                "description": [
                                    "Bootstrap new sub-DAO governance thread.",
                                ],
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
        gov_state_script_ref_utxo or gov_state_script,
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
        tally_auth_nft_script_ref_utxo or tally_auth_nft_script,
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

    signed_tx = builder.build_and_sign(
        signing_keys=[payment_skey],
        change_address=payment_address,
    )
    evaluation_context.submit_tx(signed_tx)
    show_tx(signed_tx)

    print(f"Sub-DAO creation tally submitted (proposal_id={new_proposal_id})")
    print(f"Sub-DAO NFT name (save this): {sub_dao_nft_name.hex()}")
    return signed_tx, sub_dao_nft_name.hex()


if __name__ == "__main__":
    fire.Fire(main)
