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
    pool_nft_tk_name: str = "957223c6d5f448363b676d7469a26c12051397ea70cbeacbb8cfb293fc18c764",
    allow_non_expired_tally: bool = False,
):
    pool_nft_tk_name = bytes.fromhex(pool_nft_tk_name)
    # Load script info
    (
        _,
        _,
        tally_address,
    ) = get_contract(module_name(tally), True)
    (
        simple_pool_script,
        _,
        simple_pool_address,
    ) = get_contract(module_name(simple_pool), True)
    (
        _,
        pool_nft_policy_id,
        _,
    ) = get_contract(module_name(pool_nft), True)
    simple_pool_script = get_ref_utxo(simple_pool_script, context) or simple_pool_script

    # Get payment address
    payment_vkey, payment_skey, payment_address = get_signing_info(
        wallet, network=network
    )
    # select pool
    pool_utxos = context.utxos(simple_pool_address)
    pool_utxo = None
    pool_datum = None
    for u in pool_utxos:
        try:
            datum = simple_pool.PoolState.from_cbor(u.output.datum.cbor)
        except Exception:
            continue
        if datum.im_pool_params.pool_nft == Token(
            pool_nft_policy_id.payload, pool_nft_tk_name
        ):
            pool_utxo = u
            pool_datum = datum
            break
    assert pool_utxo, "No pool found"

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
        if str(u.input.transaction_id).startswith("0b88"):
            print("debug")
        if (
            datum.params.proposal_id
            <= pool_datum.up_pool_params.last_applied_proposal_id
        ):
            continue
        if not allow_non_expired_tally and (
            not isinstance(datum.params.end_time, tally.FinitePOSIXTime)
            or datum.params.end_time.time < datetime.datetime.now().timestamp() * 1000
        ):
            continue
        if datum.params.tally_auth_nft != pool_datum.up_pool_params.auth_nft:
            continue
        tally_state = datum
        winning_proposal_index = max(enumerate(tally_state.votes), key=lambda x: x[1])[
            0
        ]
        winning_proposal = tally_state.params.proposals[winning_proposal_index]
        try:
            winning_proposal: simple_pool.PoolUpgradeParams = (
                simple_pool.PoolUpgradeParams.from_cbor(winning_proposal.to_cbor())
            )
        except Exception as e:
            continue
        tally_state_utxo = u
        break
    assert tally_state_utxo, "No tally thread found"

    own_utxos = context.utxos(payment_address)
    all_utxos = sorted_utxos(
        [pool_utxo] + own_utxos,
    )
    pool_input_index = all_utxos.index(pool_utxo)

    all_reference_utxos = sorted_utxos(
        [tally_state_utxo]
        + (
            [simple_pool_script]
            if isinstance(simple_pool_script, pycardano.TransactionOutput)
            else []
        )
    )
    tally_input_index = all_reference_utxos.index(tally_state_utxo)
    if isinstance(winning_proposal.new_pool_params, simple_pool.Nothing):
        new_pool_params = pool_datum.up_pool_params
        new_pool_params.last_applied_proposal_id = tally_state.params.proposal_id
    else:
        new_pool_params = winning_proposal.new_pool_params

    # construct new treasurer state
    new_pool_state = simple_pool.PoolState(
        im_pool_params=pool_datum.im_pool_params,
        up_pool_params=new_pool_params,
        global_liquidity_tokens=pool_datum.global_liquidity_tokens,
        spent_for=to_tx_out_ref(pool_utxo.input),
    )
    new_pool_address = (
        pool_utxo.output.address
        if isinstance(winning_proposal.new_pool_address, simple_pool.Nothing)
        else from_address(winning_proposal.new_pool_address)
    )

    # Build the transaction
    builder = TransactionBuilder(context)
    builder.auxiliary_data = AuxiliaryData(
        data=AlonzoMetadata(metadata=Metadata({674: {"msg": ["Upgrade Pool"]}}))
    )
    builder.add_input_address(payment_address)
    builder.add_script_input(
        pool_utxo,
        simple_pool_script,
        None,
        Redeemer(
            simple_pool.PoolUpgrade(
                pool_input_index=pool_input_index,
                pool_output_index=0,
                tally_ref_index=tally_input_index,
            )
        ),
    )
    # Re-add the treasurer state with the new proposal id
    builder.add_output(
        with_min_lovelace(
            pycardano.TransactionOutput(
                address=new_pool_address,
                amount=pool_utxo.output.amount,
                datum=new_pool_state,
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


if __name__ == "__main__":
    fire.Fire(main)
