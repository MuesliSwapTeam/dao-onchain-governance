"""
This transaction demonstrates how to mint Vault FTs while opening a Vault position.

Do not execute this on mainnet, as it will lock the tokens irretrievably for the given period,
and you will not accrue rewards. Execute on testnet only. Certain testnet values have been
hardcoded here to facilitate this distinction.
"""

from datetime import datetime

from opshin.prelude import Token
from pycardano import (
    Address,
    AlonzoMetadata,
    AuxiliaryData,
    Metadata,
    Network,
    Redeemer,
    TransactionBuilder,
    TransactionInput,
    TransactionOutput,
)

from muesliswap_onchain_governance.offchain.util import (
    amount_of_token_in_value,
    asset_from_token,
    value_from_token,
    with_min_lovelace,
)
from muesliswap_onchain_governance.offchain.vault.util import (
    get_ref_utxo_from_input_id,
    mainnet_vault_address,
    mainnet_vault_contract,
)
from muesliswap_onchain_governance.onchain.staking import vault_ft
from muesliswap_onchain_governance.onchain.vault import vault
from muesliswap_onchain_governance.utils.network import context

from ...utils import get_signing_info, network
from ...utils.contracts import get_contract, get_ref_utxo, module_name
from ..schema import SignedTxResponse
from .util import get_collateral_signing_info, get_collateral_utxo, get_goverance_token


async def construct_open_vault_position_tx(
    address: str, locked_weeks: int, locked_amount: int
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

    user_address = Address.from_primitive(bytes.fromhex(address))

    governance_token = get_goverance_token()

    vault_ft_ref_utxo = get_ref_utxo(vault_ft_script, context)

    vault_datum = vault.VaultDatum(
        owner=user_address.payment_part.payload,
        release_time=(int(datetime.now().timestamp()) + locked_weeks * 7 * 24 * 60 * 60)
        * 1000,
    )

    builder = TransactionBuilder(context)
    builder.auxiliary_data = AuxiliaryData(
        data=AlonzoMetadata(
            metadata=Metadata({674: {"msg": ["Open Vault Position + Mint Vault FT"]}})
        )
    )
    builder.add_input_address(user_address)
    builder.add_output(
        with_min_lovelace(
            TransactionOutput(
                address=vault_address,
                amount=value_from_token(governance_token, locked_amount),
                datum=vault_datum,
            ),
            context,
        )
    )

    vault_ft_token = Token(
        policy_id=vault_ft_policy_id.payload,
        token_name=vault_ft.vault_ft_token_name(vault_datum),
    )
    builder.mint = asset_from_token(vault_ft_token, locked_amount)
    builder.add_output(
        with_min_lovelace(
            TransactionOutput(
                address=user_address,
                amount=value_from_token(vault_ft_token, locked_amount),
            ),
            context,
        )
    )

    builder.add_minting_script(
        vault_ft_ref_utxo or vault_ft_script,
        Redeemer(vault_ft.NewVaultFTMint(vault_output_index=0)),
    )

    builder.fee_buffer = 100
    builder.collaterals = [get_collateral_utxo(network)]
    _, skey, collateral_address = get_collateral_signing_info(network)
    signed_tx = builder.build_and_sign(
        signing_keys=[skey],
        change_address=user_address,
        merge_change=True,
        collateral_change_address=collateral_address,
    )

    return SignedTxResponse(
        signed_tx=signed_tx.to_cbor_hex(),
        tx_body=signed_tx.transaction_body.to_cbor_hex(),
    ).model_dump()


async def construct_mint_vault_ft_tx(address: str, tx_hash: int, output_index: int):
    reference_input_ids: list[TransactionInput] = []

    user_address = Address.from_primitive(bytes.fromhex(address))
    (
        vault_script,
        _,
        vault_address,
    ) = get_contract(module_name(vault), True)

    # The vault contract on mainnet is different
    if network == Network.MAINNET:
        vault_address = mainnet_vault_address
        vault_script = mainnet_vault_contract

    (
        vault_ft_script,
        vault_ft_policy_id,
        _,
    ) = get_contract(module_name(vault_ft), True)

    governance_token = get_goverance_token()

    vault_admin_vkey, vault_admin_skey, vault_admin_address = get_signing_info(
        "vault_admin", network=network
    )

    vault_ft_ref_utxo = get_ref_utxo(vault_ft_script, context)

    if vault_ft_ref_utxo is not None:
        reference_input_ids.append(vault_ft_ref_utxo.input)

    open_vault_position = get_ref_utxo_from_input_id(
        vault_address, tx_hash, output_index, context
    )
    reference_input_ids.append(open_vault_position.input)

    vault_datum: vault.VaultDatum = vault.VaultDatum.from_cbor(
        open_vault_position.output.datum.cbor
    )

    locked_amount = amount_of_token_in_value(
        token=governance_token, value=open_vault_position.output.amount
    )

    builder = TransactionBuilder(context)
    builder.auxiliary_data = AuxiliaryData(
        data=AlonzoMetadata(metadata=Metadata({674: {"msg": ["Mint Vault FT"]}}))
    )
    builder.add_input_address(user_address)

    vault_ft_token = Token(
        policy_id=vault_ft_policy_id.payload,
        token_name=vault_ft.vault_ft_token_name(vault_datum),
    )
    builder.mint = asset_from_token(vault_ft_token, locked_amount)
    builder.add_output(
        with_min_lovelace(
            TransactionOutput(
                address=user_address,
                amount=value_from_token(vault_ft_token, locked_amount),
            ),
            context,
        )
    )

    builder.reference_inputs.add(open_vault_position)

    reference_input_ids = sorted(
        reference_input_ids, key=lambda i: (i.transaction_id.payload, i.index)
    )

    open_position_index = None
    for i, _input in enumerate(reference_input_ids):
        if _input == open_vault_position.input:
            open_position_index = i
            break

    builder.add_minting_script(
        vault_ft_ref_utxo or vault_ft_script,
        Redeemer(
            vault_ft.ExistingVaultFTMint(vault_ref_input_index=open_position_index),
            # ex_units=ExecutionUnits(mem=600000, steps=200000000),
        ),
    )

    # Vault admin must sign in order to manually prevent duplicate minting
    builder.required_signers = [vault_admin_vkey.hash()]

    builder.fee_buffer = 100
    builder.collaterals = [get_collateral_utxo(network)]
    _, collateral_skey, collateral_address = get_collateral_signing_info(network)

    signed_tx = builder.build_and_sign(
        [vault_admin_skey, collateral_skey],
        change_address=user_address,
        merge_change=True,
        collateral_change_address=collateral_address,
    )

    return SignedTxResponse(
        signed_tx=signed_tx.to_cbor_hex(),
        tx_body=signed_tx.transaction_body.to_cbor_hex(),
    ).model_dump()


async def construct_close_vault_position_tx(
    address: str, tx_hash: str, output_index: int, burn_tokens: bool = False
):
    user_address = Address.from_primitive(bytes.fromhex(address))
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

    governance_token = get_goverance_token()

    vault_ft_ref_utxo = get_ref_utxo(vault_ft_script, context)
    vault_ref_utxo = get_ref_utxo(vault_script, context)

    open_vault_position = get_ref_utxo_from_input_id(
        vault_address, tx_hash, output_index, context
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
    builder.add_input_address(user_address)

    vault_ft_token = Token(
        policy_id=vault_ft_policy_id.payload,
        token_name=vault_ft.vault_ft_token_name(vault_datum),
    )
    builder.add_output(
        with_min_lovelace(
            TransactionOutput(
                address=user_address,
                amount=value_from_token(governance_token, locked_amount),
            ),
            context,
        )
    )

    if burn_tokens:
        builder.mint = asset_from_token(vault_ft_token, -locked_amount)
        builder.add_minting_script(
            vault_ft_ref_utxo or vault_ft_script,
            Redeemer(vault_ft.BurnVaultFT()),
        )

    builder.add_script_input(
        open_vault_position,
        vault_ref_utxo or vault_script,
        redeemer=Redeemer(vault.UnlockRedeemer()),
    )

    builder.fee_buffer = 100
    builder.validity_start = context.last_block_slot
    builder.collaterals = [get_collateral_utxo(network)]
    _, collateral_skey, collateral_address = get_collateral_signing_info(network)

    signed_tx = builder.build_and_sign(
        signing_keys=[collateral_skey],
        change_address=user_address,
        merge_change=True,
        collateral_change_address=collateral_address,
    )

    return SignedTxResponse(
        signed_tx=signed_tx.to_cbor_hex(),
        tx_body=signed_tx.transaction_body.to_cbor_hex(),
    ).model_dump()


if __name__ == "__main__":
    import asyncio

    import ipdb

    try:
        response = asyncio.run(
            construct_open_vault_position_tx(
                "00418bb4a5aa2b84335ee3235d099bb838a2bfb7f39c400164af56aed927a80f06dc7c4507371bc1f0d0c582e6d385632706a2f0eb6204af6c",
                10000000,
                26,
            )
        )

        response = asyncio.run(
            construct_close_vault_position_tx(
                "00418bb4a5aa2b84335ee3235d099bb838a2bfb7f39c400164af56aed927a80f06dc7c4507371bc1f0d0c582e6d385632706a2f0eb6204af6c",
                "f03da39159c53c83012f513787789848d6e50e6c76edebaa2cf189800ce92211",
                0,
            )
        )
    except Exception as e:
        print(e)
        ipdb.post_mortem()
