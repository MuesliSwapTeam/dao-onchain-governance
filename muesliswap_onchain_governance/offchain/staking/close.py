import fire

import pycardano
from muesliswap_onchain_governance.utils.network import show_tx, context
from opshin.prelude import Token
from pycardano import (
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
    sorted_utxos,
    amount_of_token_in_value,
)
from muesliswap_onchain_governance.onchain.staking import staking
from muesliswap_onchain_governance.onchain.tally import tally_auth_nft
from ...utils import get_signing_info, ogmios_url, network, kupo_url
from ...utils.contracts import get_contract, get_ref_utxo, module_name
from ...utils.to_script_context import to_address, to_tx_out_ref


def main(
    wallet: str = "creator",
):
    # Load script info
    (
        staking_script,
        _,
        staking_address,
    ) = get_contract(module_name(staking), True)
    staking_script_ref_utxo = get_ref_utxo(staking_script, context)

    # Get payment address
    payment_vkey, payment_skey, payment_address = get_signing_info(
        wallet, network=network
    )

    # Make the datum of the GovState
    staking_utxo = None
    for utxo in context.utxos(staking_address):
        if utxo.output.datum is None:
            continue
        staking_datum = staking.StakingState.from_cbor(utxo.output.datum.cbor)
        if staking_datum.params.owner != to_address(payment_address):
            continue
        if not amount_of_token_in_value(
            staking_datum.params.governance_token, utxo.output.amount
        ):
            continue
        staking_utxo = utxo
        break
    assert staking_utxo is not None, "No staking state found"

    payment_utxos = context.utxos(payment_address)
    all_utxos = sorted_utxos(payment_utxos + [staking_utxo])

    redeemer = Redeemer(
        staking.WithdrawFunds(
            state_input_index=all_utxos.index(staking_utxo),
            state_output_index=0,
        )
    )

    # Build the transaction
    builder = TransactionBuilder(context)
    for u in payment_utxos:
        builder.add_input(u)
    builder.add_script_input(
        staking_utxo,
        staking_script_ref_utxo,
        None,
        redeemer,
    )
    builder.auxiliary_data = AuxiliaryData(
        data=AlonzoMetadata(
            metadata=Metadata({674: {"msg": ["Close Staking Position"]}})
        )
    )
    ### OUTPUT no longer necessary if no more active participations
    # output = TransactionOutput(
    #     address=staking_address,
    #     amount=Value(
    #         coin=2000000,
    #     ),
    #     datum=staking_datum,
    # )
    # builder.add_output(with_min_lovelace(output, context))

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
