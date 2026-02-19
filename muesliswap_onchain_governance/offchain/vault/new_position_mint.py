"""
This transaction demonstrates how to mint Vault FTs while opening a Vault position.

Do not execute this on mainnet, as it will lock the tokens irretrievably for the given period,
and you will not accrue rewards. Execute on testnet only. Certain testnet values have been
hardcoded here to facilitate this distinction.
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


def main(wallet: str = "voter", locked_seconds: int = 30 * 24 * 60 * 60, lock_amount=3):
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

    governance_token = token_from_string(
        "bd976e131cfc3956b806967b06530e48c20ed5498b46a5eb836b61c2.744d494c4b7632"
    )

    payment_vkey, payment_skey, payment_address = get_signing_info(
        wallet, network=Network.TESTNET
    )

    vault_ft_ref_utxo = get_ref_utxo(vault_ft_script, context)

    vault_datum = vault.VaultDatum(
        owner=payment_address.payment_part.payload,
        release_time=(int(datetime.now().timestamp()) + locked_seconds) * 1000,
    )

    builder = TransactionBuilder(context)
    builder.auxiliary_data = AuxiliaryData(
        data=AlonzoMetadata(
            metadata=Metadata({674: {"msg": ["Open Vault Position + Mint Vault FT"]}})
        )
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

    vault_ft_token = Token(
        policy_id=vault_ft_policy_id.payload,
        token_name=vault_ft.vault_ft_token_name(vault_datum),
    )
    builder.mint = asset_from_token(vault_ft_token, lock_amount)
    builder.add_output(
        with_min_lovelace(
            TransactionOutput(
                address=payment_address,
                amount=value_from_token(vault_ft_token, lock_amount),
            ),
            context,
        )
    )

    builder.add_minting_script(
        vault_ft_ref_utxo or vault_ft_script,
        Redeemer(vault_ft.NewVaultFTMint(vault_output_index=0)),
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
