"""
Execute a winning CreateSubDaoParams tally to bootstrap a new sub-DAO.

Workflow
--------
1.  Run create_sub_dao_tally.py to submit the proposal and record the
    sub-DAO NFT token name it prints.
2.  Wait for the tally's voting period to end and quorum to be reached.
3.  Run this script to execute the winning proposal:
      - Spends the parent gov state UTxO (CreateSubDao redeemer).
      - Mints the sub-DAO's gov_state_nft (one-shot policy, same as parent's).
      - Creates the initial sub-DAO GovStateDatum UTxO at the address that
        was pre-committed in the proposal.
      - Updates the parent's latest_applied_proposal_id.

The UTxO identified by nft_utxo_txhash / nft_utxo_index MUST be the same one
chosen when create_sub_dao_tally.py was run (the NFT name is its hash).
"""

import datetime

import fire
import pycardano
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

from muesliswap_onchain_governance.onchain.gov_state import gov_state, gov_state_nft
from muesliswap_onchain_governance.onchain.gov_state.gov_state_nft import (
    SubDaoMintRedeemer,
)
from muesliswap_onchain_governance.onchain.tally import tally
from muesliswap_onchain_governance.utils.from_script_context import from_address
from muesliswap_onchain_governance.utils.network import context, show_tx, evaluation_context
from muesliswap_onchain_governance.utils.to_script_context import to_tx_out_ref

from ...utils import get_signing_info, network
from ...utils.contracts import get_contract, get_ref_utxo, module_name
from ..util import (
    GOV_STATE_NFT_TK_NAME,
    asset_from_token,
    sorted_utxos,
    with_min_lovelace,
)


def main(
    wallet: str = "creator",
    gov_state_nft_tk_name: str = GOV_STATE_NFT_TK_NAME,
    # The UTxO pre-committed in create_sub_dao_tally.py for NFT minting
    nft_utxo_txhash: str = "",
    nft_utxo_index: int = 0,
    allow_non_expired_tally: bool = False,
):
    """
    Execute an approved CreateSubDaoParams tally and bootstrap the sub-DAO.
    """
    # ------------------------------------------------------------------
    # Load script info
    # ------------------------------------------------------------------
    (gov_state_script, _, gov_state_address) = get_contract(
        module_name(gov_state), True
    )
    gov_state_script_ref_utxo = get_ref_utxo(gov_state_script, context)
    (gov_state_nft_script, gov_state_nft_policy_id, _) = get_contract(
        module_name(gov_state_nft), True
    )
    gov_state_nft_ref_utxo = get_ref_utxo(gov_state_nft_script, context)
    (_, _, tally_address) = get_contract(module_name(tally), True)

    # ------------------------------------------------------------------
    # Resolve payment signer
    # ------------------------------------------------------------------
    payment_vkey, payment_skey, payment_address = get_signing_info(
        wallet, network=network
    )

    # ------------------------------------------------------------------
    # Find parent governance thread UTxO
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
    assert gov_state_utxo, "No parent governance thread UTxO found"

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
    tally_state = None

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
        if not allow_non_expired_tally and (
            not isinstance(datum.params.end_time, tally.FinitePOSIXTime)
            or datum.params.end_time.time > datetime.datetime.now().timestamp() * 1000
        ):
            continue
        winning_proposal_index = max(
            enumerate(datum.votes), key=lambda x: x[1]
        )[0]
        candidate = datum.params.proposals[winning_proposal_index]
        try:
            candidate = gov_state.CreateSubDaoParams.from_cbor(candidate.to_cbor())
        except Exception:
            continue
        tally_state = datum
        winning_proposal = candidate
        tally_state_utxo = u
        break

    assert tally_state_utxo, (
        "No winning CreateSubDaoParams tally found for this governance thread"
    )

    # ------------------------------------------------------------------
    # Locate the pre-committed wallet UTxO (for NFT minting)
    # ------------------------------------------------------------------
    assert nft_utxo_txhash, (
        "nft_utxo_txhash is required — it must be the UTxO committed to in "
        "create_sub_dao_tally.py"
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

    # Verify the NFT name matches the winning proposal
    expected_nft_name = gov_state_nft.gov_state_nft_name(
        to_tx_out_ref(nft_utxo.input)
    )
    assert expected_nft_name == winning_proposal.params.gov_state_nft.token_name, (
        f"NFT name mismatch: UTxO produces {expected_nft_name.hex()} but "
        f"proposal expects "
        f"{winning_proposal.params.gov_state_nft.token_name.hex()}"
    )
    sub_dao_nft_token = winning_proposal.params.gov_state_nft

    # ------------------------------------------------------------------
    # Compute sorted input order so the redeemer indices are correct.
    #
    # Inputs:
    #   - parent gov state UTxO  (script input)
    #   - nft_utxo               (wallet input, provides the one-shot NFT)
    #   - remaining payment UTxOs (fee / change)
    # ------------------------------------------------------------------
    other_payment_utxos = [u for u in payment_utxos if u != nft_utxo]
    all_inputs = sorted_utxos(
        [gov_state_utxo, nft_utxo] + other_payment_utxos
    )
    parent_gov_input_index = all_inputs.index(gov_state_utxo)
    nft_utxo_sorted_index = all_inputs.index(nft_utxo)

    # Reference inputs (for tally and optionally the gov_state_nft scripts)
    all_reference_utxos = sorted_utxos(
        [tally_state_utxo]
        + (
            [gov_state_script_ref_utxo]
            if isinstance(gov_state_script_ref_utxo, pycardano.UTxO)
            else []
        )
        + (
            [gov_state_nft_ref_utxo]
            if isinstance(gov_state_nft_ref_utxo, pycardano.UTxO)
            else []
        )
    )
    tally_input_index = all_reference_utxos.index(tally_state_utxo)

    # ------------------------------------------------------------------
    # Determine output indices.
    # Layout:
    #   output 0 — sub-DAO GovStateDatum  (sub_dao_output_index = 0)
    #   output 1 — parent continuing UTxO (gov_state_output_index = 1)
    # ------------------------------------------------------------------
    sub_dao_output_index = 0
    parent_output_index = 1

    # ------------------------------------------------------------------
    # Build parent continuing datum (only latest_applied_proposal_id advances)
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
        latest_applied_proposal_id=tally_state.params.proposal_id,
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

    # Add all inputs explicitly so the sorted order is deterministic
    builder.add_script_input(
        gov_state_utxo,
        gov_state_script_ref_utxo if gov_state_script_ref_utxo else gov_state_script,
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

    # Mint the sub-DAO gov_state_nft via the one-shot policy.
    # SubDaoMintRedeemer triggers the extended validation in gov_state_nft.py
    # (parent-reference correctness, initial datum, address-differs check).
    builder.add_minting_script(
        gov_state_nft_ref_utxo if gov_state_nft_ref_utxo else gov_state_nft_script,
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

    # Output 0: new sub-DAO governance state
    builder.add_output(
        with_min_lovelace(
            TransactionOutput(
                address=sub_dao_pycardano_address,
                amount=Value(
                    coin=2_000_000,
                    multi_asset=asset_from_token(sub_dao_nft_token, 1),
                ),
                datum=initial_sub_dao_state,
            ),
            context,
        )
    )
    # Output 1: parent governance state continuing
    builder.add_output(
        pycardano.TransactionOutput(
            address=gov_state_address,
            amount=gov_state_utxo.output.amount,
            datum=new_parent_gov_state,
        )
    )

    builder.reference_inputs.add(tally_state_utxo)
    builder.validity_start = context.last_block_slot

    signed_tx = builder.build_and_sign(
        signing_keys=[payment_skey],
        change_address=payment_address,
    )
    evaluation_context.submit_tx(signed_tx)
    show_tx(signed_tx)

    print(f"Sub-DAO created successfully.")
    print(f"Sub-DAO gov_state_nft: {sub_dao_nft_token.token_name.hex()}")
    print(f"Sub-DAO address:       {sub_dao_pycardano_address}")
    return signed_tx, sub_dao_nft_token.token_name.hex()


if __name__ == "__main__":
    fire.Fire(main)
