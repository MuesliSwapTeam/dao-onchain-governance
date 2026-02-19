"""
This transaction demonstrates opens a Vault position without minting Vault FTs.
Its only purpose is to be used as an input for the `existing_position_mint` transaction.

Do not execute this on mainnet, as it will lock the tokens irretrievably for the given period,
and you will not accrue rewards. Execute on testnet only. Certain testnet values have been
hardcoded here to facilitate this distinction.
"""

from datetime import datetime

import fire
from pycardano import (
    AlonzoMetadata,
    AuxiliaryData,
    Metadata,
    Network,
    TransactionBuilder,
    TransactionOutput,
)

from muesliswap_onchain_governance.onchain.staking import vault_ft
from muesliswap_onchain_governance.onchain.vault import vault
from muesliswap_onchain_governance.utils.network import context, show_tx

from ...utils import get_signing_info
from ...utils.contracts import get_contract, module_name
from ..util import token_from_string, value_from_token, with_min_lovelace


def main(wallet: str = "voter", locked_seconds: int = 30 * 24 * 60 * 60, lock_amount=3):
    (
        vault_script,
        vault_policy_id,
        vault_address,
    ) = get_contract(module_name(vault), True)
    (
        vault_ft_script,
        _,
        _,
    ) = get_contract(module_name(vault_ft), True)

    governance_token = token_from_string(
        "bd976e131cfc3956b806967b06530e48c20ed5498b46a5eb836b61c2.744d494c4b7632"
    )

    payment_vkey, payment_skey, payment_address = get_signing_info(
        wallet, network=Network.TESTNET
    )

    vault_datum = vault.VaultDatum(
        owner=payment_address.payment_part.payload,
        release_time=(int(datetime.now().timestamp()) + locked_seconds) * 1000,
    )

    builder = TransactionBuilder(context)
    builder.auxiliary_data = AuxiliaryData(
        data=AlonzoMetadata(metadata=Metadata({674: {"msg": ["Open Vault Position"]}}))
    )
    builder.add_input_address(payment_address)
    builder.add_output(
        with_min_lovelace(
            TransactionOutput(
                address=vault_address,
                amount=value_from_token(governance_token, lock_amount),
                datum=vault_datum,
            ),
            context,
        )
    )

    builder.fee_buffer = 50_000

    signed_tx = builder.build_and_sign(
        [payment_skey], change_address=payment_address, merge_change=True
    )

    context.submit_tx(signed_tx)
    show_tx(signed_tx)
    return signed_tx


if __name__ == "__main__":
    fire.Fire(main)
