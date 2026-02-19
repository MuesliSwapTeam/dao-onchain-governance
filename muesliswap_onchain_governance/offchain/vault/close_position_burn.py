"""
This transaction demonstrates how to burn Vault FTs while closing a Vault position.

It is not mandatory (with the current Vault implementation) to burn Vault FTs when
you close the Vault position. However, this is the best and most canonical time to do
so as they no longer have any use past the release time.
"""

import fire

from muesliswap_onchain_governance.onchain.treasury import (
    treasurer_nft,
    treasurer,
    value_store,
)
from muesliswap_onchain_governance.utils.network import show_tx, context
from opshin.ledger.api_v2 import (
    POSIXTime,
)
from opshin.prelude import Token
from pycardano import (
    TransactionBuilder,
    Redeemer,
    AuxiliaryData,
    AlonzoMetadata,
    Metadata,
    TransactionOutput,
    Value,
    Network,
)
from datetime import datetime, timedelta

from ..util import (
    token_from_string,
    asset_from_token,
    with_min_lovelace,
    value_from_token,
    amount_of_token_in_value,
    GOV_STATE_NFT_TK_NAME,
)
from muesliswap_onchain_governance.onchain.staking import (
    staking_vote_nft,
    staking,
    vault_ft,
)
from muesliswap_onchain_governance.onchain.vault import vault
from muesliswap_onchain_governance.onchain.tally import tally_auth_nft, tally
from muesliswap_onchain_governance.onchain.gov_state import gov_state_nft, gov_state
from ...utils import get_signing_info, ogmios_url, network, kupo_url
from ...utils.contracts import get_contract, get_ref_utxo, module_name
from ...utils.to_script_context import to_address, to_tx_out_ref
from .util import (
    get_ref_utxo_from_input_id,
    mainnet_vault_address,
    mainnet_vault_contract,
)


def main(
    open_position_tx_id: str,
    open_position_tx_index: int = 0,
    wallet: str = "voter",
    governance_token: str = "bd976e131cfc3956b806967b06530e48c20ed5498b46a5eb836b61c2.744d494c4b7632",
):
    (
        vault_script,
        vault_policy_id,
        vault_address,
    ) = get_contract(module_name(vault), True)
    (
        vault_ft_script,
        vault_ft_policy_id,
        _,
    ) = get_contract(module_name(vault_ft), True)

    # The vault contract on mainnet is different
    if network == Network.MAINNET:
        vault_address = mainnet_vault_address
        vault_script = mainnet_vault_contract

    governance_token = token_from_string(governance_token)

    payment_vkey, payment_skey, payment_address = get_signing_info(
        wallet, network=Network.TESTNET
    )

    vault_ft_ref_utxo = get_ref_utxo(vault_ft_script, context)
    vault_ref_utxo = get_ref_utxo(vault_script, context)

    open_vault_position = get_ref_utxo_from_input_id(
        vault_address, open_position_tx_id, open_position_tx_index, context
    )

    vault_datum: vault.VaultDatum = vault.VaultDatum.from_cbor(
        open_vault_position.output.datum.cbor
    )

    locked_amount = amount_of_token_in_value(
        token=governance_token, value=open_vault_position.output.amount
    )

    builder = TransactionBuilder(context)
    builder.auxiliary_data = AuxiliaryData(
        data=AlonzoMetadata(
            metadata=Metadata({674: {"msg": ["Close Vault Position + Burn Vault FT"]}})
        )
    )
    builder.add_input_address(payment_address)

    vault_ft_token = Token(
        policy_id=vault_ft_policy_id.payload,
        token_name=vault_ft.vault_ft_token_name(vault_datum),
    )
    builder.mint = asset_from_token(vault_ft_token, -locked_amount)
    builder.add_output(
        with_min_lovelace(
            TransactionOutput(
                address=payment_address,
                amount=value_from_token(governance_token, locked_amount),
            ),
            context,
        )
    )

    builder.add_minting_script(
        vault_ft_ref_utxo or vault_ft_script,
        Redeemer(vault_ft.BurnVaultFT()),
    )

    builder.add_script_input(
        open_vault_position,
        vault_ref_utxo or vault_script,
        redeemer=Redeemer(vault.UnlockRedeemer()),
    )

    builder.fee_buffer = 50_000
    builder.validity_start = context.last_block_slot

    signed_tx = builder.build_and_sign(
        [payment_skey], change_address=payment_address, merge_change=True
    )

    context.submit_tx(signed_tx)
    show_tx(signed_tx)
    return signed_tx


if __name__ == "__main__":
    fire.Fire(main)
