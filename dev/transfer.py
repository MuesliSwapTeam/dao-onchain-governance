from muesliswap_onchain_governance.utils import network, get_signing_info
from muesliswap_onchain_governance.utils.contracts import (
    get_contract,
    get_ref_utxo,
    module_name,
)
from muesliswap_onchain_governance.utils.network import context, show_tx

from pycardano import (
    TransactionBuilder,
    TransactionOutput,
    min_lovelace,
    Value,
    Address,
)


def main():
    sender = "creator"

    payment_vkey, payment_skey, payment_address = get_signing_info(
        sender, network=network
    )

    builder = TransactionBuilder(context)

    sender_utxos = context.utxos(payment_address)

    input_utxo = None
    for utxo in sender_utxos:
        if (
            utxo.input.transaction_id.payload.hex()
            == "83adcf4641077306ec65ba052d53bdecb0fc01ef8a9ea348ea4c9b9a7410edae"
        ) and utxo.input.index == 0:
            input_utxo = utxo
            break

    builder.add_input(input_utxo)

    builder.add_output(TransactionOutput(payment_address, amount=Value(1000000)))

    builder.fee_buffer = 200000

    transaction = builder.build_and_sign([payment_skey], change_address=payment_address)

    tx_id = context.submit_tx(transaction.to_cbor())
    print(f"Transaction submitted with hash: {tx_id}")


if __name__ == "__main__":
    main()
