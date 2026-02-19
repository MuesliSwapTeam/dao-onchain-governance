import fire
from pycardano import Address, TransactionBuilder, TransactionOutput, Value

from muesliswap_onchain_governance.offchain.util import with_min_lovelace
from muesliswap_onchain_governance.utils import get_signing_info, network
from muesliswap_onchain_governance.utils.network import context, show_tx


def main(
    sender: str,  # Wallet name
    recipient: str,  # Bech32 address or wallet name
    value: Value,
):
    sender_vkey, sender_skey, sender_address = get_signing_info(sender, network=network)

    try:
        recipient_address = Address.from_primitive(recipient)
    except:
        _, _, recipient_address = get_signing_info(recipient, network=network)

    builder = TransactionBuilder(context)
    builder.add_output(
        with_min_lovelace(
            TransactionOutput(address=recipient_address, amount=value), context
        )
    )

    signed_tx = builder.build_and_sign(
        [sender_skey],
        change_address=sender_address,
    )

    context.submit_tx(signed_tx)
    show_tx(signed_tx)


if __name__ == "__main__":
    fire.Fire(main)
