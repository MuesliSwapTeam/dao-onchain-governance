import fire
from opshin.prelude import Nothing, Token
from pycardano import (
    AlonzoMetadata,
    AuxiliaryData,
    Metadata,
    Redeemer,
    TransactionBuilder,
)

from muesliswap_onchain_governance.utils.network import context, show_tx

from ..utils import get_signing_info
from ..utils.contracts import get_contract
from .util import asset_from_token


def main(
    wallet: str = "creator",
    token_name: str = b"tMILK".hex(),
    amount: int = 1000000,
):
    # Load script info
    free_mint_script, free_mint_policy, _ = get_contract("free_mint", compressed=True)
    free_token = Token(
        policy_id=free_mint_policy.payload, token_name=bytes.fromhex(token_name)
    )

    payment_vkey, payment_skey, payment_address = get_signing_info(wallet)

    # Build the transaction
    builder = TransactionBuilder(context)
    builder.auxiliary_data = AuxiliaryData(
        data=AlonzoMetadata(
            metadata=Metadata({674: {"msg": ["Create Governance Token"]}})
        )
    )
    builder.add_input_address(payment_address)
    builder.add_minting_script(free_mint_script, Redeemer(Nothing()))
    builder.mint = asset_from_token(free_token, amount)

    # Sign the transaction
    signed_tx = builder.build_and_sign(
        signing_keys=[payment_skey],
        change_address=payment_address,
    )

    # Submit the transaction
    context.submit_tx(signed_tx)

    print("Created governance token")

    show_tx(signed_tx)

    return signed_tx


if __name__ == "__main__":
    fire.Fire(main)
