from typing import Union

import cbor2

import pycardano
from opshin import prelude

from ..db_models import (
    TransactionOutputValue,
    TransactionOutput,
    Address,
    Datum,
    Token,
    Block,
    Transaction,
)


def add_address_raw(address: bytes) -> Address:
    """
    Store the address in the database.
    """
    return Address.get_or_create(address_raw=address.hex())[0]


def add_address(address: pycardano.Address) -> Address:
    """
    Store the address in the database.
    """
    return add_address_raw(address.to_primitive())


def add_datum(datum: pycardano.Datum) -> Datum:
    """
    Store the datum in the database.
    """
    return Datum.get_or_create(
        hash=pycardano.datum_hash(datum).to_primitive().hex(),
        data=cbor2.dumps(datum, default=pycardano.default_encoder),
    )[0]


def add_token_token(token: prelude.Token) -> Token:
    """
    Store the token in the database.
    """
    return add_token(token.policy_id, token.token_name)


def add_token(
    policy_id: Union[pycardano.ScriptHash, bytes],
    asset_name: Union[pycardano.AssetName, bytes],
) -> Token:
    """
    Store the token in the database.
    """
    if isinstance(policy_id, pycardano.ScriptHash):
        policy_id = policy_id.payload
    if isinstance(asset_name, pycardano.AssetName):
        asset_name = asset_name.payload
    return Token.get_or_create(
        policy_id=policy_id.hex(),
        asset_name=asset_name.hex(),
    )[0]


def add_transaction(
    transaction_hash: str,
    block: Block,
    block_index: int,
):
    """
    Store the transaction in the database.
    """
    return Transaction.get_or_create(
        transaction_hash=transaction_hash,
        block=block,
        block_index=block_index,
    )[0]


def add_output(
    tx_output: pycardano.TransactionOutput,
    index: int,
    transaction_hash: str,
    block: Block,
    block_index: int,
) -> TransactionOutput:
    """
    Store the value of the output in the database.
    """
    if tx_output.datum is not None:
        datum_hash = add_datum(tx_output.datum).hash
    elif tx_output.datum_hash is not None:
        datum_hash = tx_output.datum_hash.to_primitive().hex()
    else:
        datum_hash = None
    output, created = TransactionOutput.get_or_create(
        output_index=index,
        address=add_address(tx_output.address),
        datum_hash=datum_hash,
        transaction_hash=transaction_hash,
        transaction=add_transaction(transaction_hash, block, block_index),
    )
    if not created:
        return output
    lovelace = tx_output.amount.coin
    TransactionOutputValue.create(
        transaction_output=output,
        token=add_token(b"", b""),
        amount=lovelace,
    )
    for policy_id, d in tx_output.amount.multi_asset.items():
        for asset_name, amount in d.items():
            token = add_token(policy_id, asset_name)
            TransactionOutputValue.create(
                transaction_output=output, token=token, amount=amount
            )
    return output
