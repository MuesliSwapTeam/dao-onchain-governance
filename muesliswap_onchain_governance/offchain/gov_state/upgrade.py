import datetime

import fire
import pycardano

from muesliswap_onchain_governance.onchain.simple_pool import simple_pool, pool_nft
from muesliswap_onchain_governance.onchain.treasury import (
    treasurer_nft,
    treasurer,
    value_store,
)
from muesliswap_onchain_governance.utils.from_script_context import (
    from_value,
    from_output_datum,
    from_address,
)
from muesliswap_onchain_governance.utils.network import show_tx, context
from opshin.ledger.api_v2 import (
    POSIXTime,
)
from opshin.prelude import Token
from pycardano import (
    OgmiosChainContext,
    TransactionBuilder,
    Redeemer,
    AuxiliaryData,
    AlonzoMetadata,
    Metadata,
    TransactionOutput,
    Value,
)

from ..util import (
    token_from_string,
    asset_from_token,
    with_min_lovelace,
    TREASURER_STATE_NFT_TK_NAME,
    sorted_utxos,
    GOV_STATE_NFT_TK_NAME,
)
from muesliswap_onchain_governance.onchain.staking import (
    staking_vote_nft,
    staking,
    vault_ft,
)
from muesliswap_onchain_governance.onchain.tally import tally_auth_nft, tally
from muesliswap_onchain_governance.onchain.gov_state import gov_state_nft, gov_state
from ...utils import get_signing_info, ogmios_url, network, kupo_url
from ...utils.contracts import get_contract, get_ref_utxo, module_name
from ...utils.to_script_context import to_address, to_tx_out_ref


def main(
    wallet: str = "voter",
    gov_state_nft_tk_name: str = GOV_STATE_NFT_TK_NAME,
    allow_non_expired_tally: bool = False,
):
    # Load script info
    (
        _,
        _,
        tally_address,
    ) = get_contract(module_name(tally), True)
    (
        gov_state_script,
        _,
        gov_state_address,
    ) = get_contract(module_name(gov_state), True)
    (_, gov_state_nft_policy_id, _) = get_contract(module_name(gov_state_nft), True)
    gov_state_script_ref_utxo = get_ref_utxo(gov_state_script, context)

    # Get payment address
    payment_vkey, payment_skey, payment_address = get_signing_info(
        wallet, network=network
    )
    # Select governance thread
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
    assert gov_state_utxo, "No governance thread found"
    prev_gov_state_datum: gov_state.GovStateDatum = gov_state.GovStateDatum.from_cbor(
        gov_state_utxo.output.datum.cbor
    )

    # Select tally thread
    tally_utxos = context.utxos(tally_address)
    tally_state_utxo = None
    winning_proposal = None
    tally_state = None
    for u in tally_utxos:
        try:
            datum = tally.TallyState.from_cbor(u.output.datum.cbor)
        except Exception:
            continue
        if (
            datum.params.proposal_id
            <= prev_gov_state_datum.params.latest_applied_proposal_id
        ):
            continue
        if not allow_non_expired_tally and (
            not isinstance(datum.params.end_time, tally.FinitePOSIXTime)
            or datum.params.end_time.time > datetime.datetime.now().timestamp() * 1000
        ):
            continue
        if (
            datum.params.tally_auth_nft.policy_id
            != prev_gov_state_datum.params.tally_auth_nft_policy
        ):
            continue
        if datum.params.tally_auth_nft.token_name != gov_state_nft_tk.token_name:
            continue
        tally_state = datum
        winning_proposal_index = max(enumerate(tally_state.votes), key=lambda x: x[1])[
            0
        ]
        winning_proposal = tally_state.params.proposals[winning_proposal_index]
        try:
            winning_proposal: gov_state.GovStateUpdateParams = (
                gov_state.GovStateUpdateParams.from_cbor(winning_proposal.to_cbor())
            )
        except Exception as e:
            continue
        tally_state_utxo = u
        break
    assert tally_state_utxo, "No tally thread found"

    own_utxos = context.utxos(payment_address)
    all_utxos = sorted_utxos(
        [gov_state_utxo] + own_utxos,
    )
    gov_input_index = all_utxos.index(gov_state_utxo)

    all_reference_utxos = sorted_utxos(
        [tally_state_utxo]
        + (
            [gov_state_script_ref_utxo]
            if isinstance(gov_state_script_ref_utxo, pycardano.UTxO)
            else []
        )
    )
    tally_input_index = all_reference_utxos.index(tally_state_utxo)

    # construct new treasurer state
    new_gov_state = gov_state.GovStateDatum(
        params=winning_proposal.params,
        last_proposal_id=prev_gov_state_datum.last_proposal_id,
    )
    new_gov_address = from_address(winning_proposal.address)

    # Build the transaction
    builder = TransactionBuilder(context)
    builder.auxiliary_data = AuxiliaryData(
        data=AlonzoMetadata(metadata=Metadata({674: {"msg": ["Upgrade Gov State"]}}))
    )
    builder.add_input_address(payment_address)
    builder.add_script_input(
        gov_state_utxo,
        gov_state_script_ref_utxo if gov_state_script_ref_utxo else gov_state_script,
        None,
        Redeemer(
            gov_state.UpgradeGovState(
                gov_state_input_index=gov_input_index,
                gov_state_output_index=0,
                tally_input_index=tally_input_index,
            )
        ),
    )
    # Re-add the treasurer state with the new proposal id
    builder.add_output(
        with_min_lovelace(
            pycardano.TransactionOutput(
                address=new_gov_address,
                amount=gov_state_utxo.output.amount,
                datum=new_gov_state,
            ),
            context,
        )
    )
    builder.reference_inputs.add(tally_state_utxo)
    builder.validity_start = context.last_block_slot

    # Sign the transaction
    signed_tx = builder.build_and_sign(
        signing_keys=[payment_skey],
        change_address=payment_address,
    )

    # Submit the transaction
    context.submit_tx(signed_tx)

    show_tx(signed_tx)
    return signed_tx


if __name__ == "__main__":
    fire.Fire(main)
