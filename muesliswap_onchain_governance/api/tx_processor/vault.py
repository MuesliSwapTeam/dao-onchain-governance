import pycardano

from .to_db import add_output, add_address, add_transaction
from ..db_models import Block, TransactionOutput
from ..db_models import VaultPosition, MintVaultFTExistingPosition

from ...onchain.vault import vault as onchain_vault
from ...onchain.staking import vault_ft as onchain_vault_ft

import logging

_LOGGER = logging.getLogger(__name__)

VAULT_ADDRESS_TO_NAME = {
    "addr1wyz9gd2m8y3q9ev5ee6tut6llxhxf34vp7a5tjm8d7q83gsu6r426": "Milk Vault [Mainnet]",
    "addr_test1wqdxx9gv6s9t4tkp4qxw8najeujuxxmj430pa9ypum4v3wqlax6g6": "Milk Vault [Testnet]",
}

VAULT_ADDRESS_TO_VAULT_FT_POLICY = {
    # "addr1wyz9gd2m8y3q9ev5ee6tut6llxhxf34vp7a5tjm8d7q83gsu6r426": "",
    "addr_test1wqdxx9gv6s9t4tkp4qxw8najeujuxxmj430pa9ypum4v3wqlax6g6": "083288ce68f0ed033982bf7d7fbbc1024a2b4e24326f7b74a215e7f3",
}


def process_tx(
    tx: pycardano.Transaction,
    block: Block,
    block_index: int,
):
    """
    Processes a transaction involving the Vault contract and minting of Vault FTs.
    Recall that Vault FTs can either be minted during creation of the vault position,
    or subsequently by referencing the open vault position.

    Ensuring that Vault FTs are only minted for existing vault positions if not minted previously
    is the responsibility of the vault admin, so duplicate minting is possible unless states are
    carefully tracked.

    It is possible to burn Vault FTs arbitrarily. This action is not tracked so it is not
    an excuse for duplicate minting.

    Only one vault position can be used for minting Vault FTs per Tx, which
    simplifies the logic.
    """
    # NOTE: Minted amounts do not have to be checked here because they are enforced
    # by the smart contract

    # NOTE: We use hardcoded values here because the vault preexists the governance
    # infrastructure in general
    vault_position = None
    for i, output in enumerate(tx.transaction_body.outputs):
        if output.address.encode() in VAULT_ADDRESS_TO_NAME:
            _LOGGER.info(f"Vault transaction: {tx.id.payload.hex()}")
            try:
                vault_datum: onchain_vault.VaultDatum = (
                    onchain_vault.VaultDatum.from_primitive(output.datum.data)
                )
            except Exception as e:
                _LOGGER.info(f"Invalid vault datum at Vault {tx.id.payload.hex()}")
                continue
            vault_output = add_output(
                output, i, tx.id.payload.hex(), block, block_index
            )
            vault_address = add_address(output.address)
            vault_ft_policy_id = VAULT_ADDRESS_TO_VAULT_FT_POLICY[
                output.address.encode()
            ]
            token_name = onchain_vault_ft.vault_ft_token_name(vault_datum)

            minted_ft = False
            if (
                tx.transaction_body.mint
                and tx.transaction_body.mint.get(
                    pycardano.ScriptHash(bytes.fromhex(vault_ft_policy_id)), {}
                ).get(pycardano.AssetName(token_name))
                is not None
            ):
                minted_ft = True

            vault_position = VaultPosition.create(
                transaction_output=vault_output,
                owner=vault_datum.owner.hex(),
                release_timestamp=vault_datum.release_time,
                minted_ft=minted_ft,
                vault_address=vault_address,
            )

    # Check if Vault FTs are minted for an existing position
    if vault_position is None:
        # Check if any vault FTs were minted. If not, no need
        # to go to db
        existing_mint_tx = tx.transaction_body.mint and any(
            [
                tx.transaction_body.mint.get(pycardano.ScriptHash(bytes.fromhex(pid)))
                for pid in VAULT_ADDRESS_TO_VAULT_FT_POLICY.values()
            ]
        )
        if existing_mint_tx:
            for input in tx.transaction_body.reference_inputs:
                vault_position: VaultPosition = (
                    VaultPosition.select()
                    .join(TransactionOutput)
                    .where(
                        TransactionOutput.transaction_hash
                        == input.transaction_id.payload.hex(),
                        TransactionOutput.output_index == input.index,
                    )
                    .first()
                )
                if vault_position is None:
                    continue

                if vault_position.minted_ft:
                    _LOGGER.warning(
                        f"Duplicate Vault FT minting at {tx.id.payload.hex()}"
                    )

                vault_position.minted_ft = True
                vault_position.save()
                MintVaultFTExistingPosition.create(
                    transaction=add_transaction(
                        tx.id.payload.hex(), block, block_index
                    ),
                    open_position=vault_position,
                )
