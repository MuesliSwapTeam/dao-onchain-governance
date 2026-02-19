import dataclasses
from typing import NamedTuple, Union

import pycardano
from fastapi import HTTPException

from muesliswap_onchain_governance.api.db_models.db import TransactionOutput
from muesliswap_onchain_governance.api.db_models.delegation import DelegationPosition
from muesliswap_onchain_governance.api.schema import (
    RevokeDelegationRequest,
    UpdateDelegationRequest,
)
from muesliswap_onchain_governance.api.tx_processor.from_db import from_address
from muesliswap_onchain_governance.utils.network import Network, network

GOVERNANCE_TOKEN = (
    "bd976e131cfc3956b806967b06530e48c20ed5498b46a5eb836b61c2.744d494c4b7632"
    if network == Network.TESTNET
    else "afbe91c0b44b3040e360057bf8354ead8c49c4979ae6ab7c4fbdc9eb.4d494c4b7632"
)


@dataclasses.dataclass
class FixedTxHashTransaction:
    """
    Substrate type because pycardano does not support fixed tx hashes
    and always computes them live, but may generate imprecise deserializations of transactions
    """

    transaction: pycardano.Transaction
    hash: str

    @property
    def id(self):
        return pycardano.TransactionId.from_primitive(bytes.fromhex(self.hash))

    @property
    def transaction_body(self):
        return self.transaction.transaction_body

    @property
    def transaction_witness_set(self):
        return self.transaction.transaction_witness_set

    @property
    def valid(self):
        return self.transaction.valid

    @property
    def auxiliary_data(self):
        return self.transaction.auxiliary_data


class KnownException(HTTPException):
    def __init__(self, detail: str):
        super().__init__(status_code=400, detail=detail)


def slot_to_timestamp(slot: int, network: Network = network):
    if network == Network.TESTNET:
        offset = 1655769600 - 86400
    else:
        offset = 1596059091 - 4492800
    return slot + offset


def parse_address(address: str) -> pycardano.Address:
    try:
        return pycardano.Address.decode(address)
    except Exception:
        raise KnownException(f"Invalid address: {address}")


class OpenDelegationPositionInfo(NamedTuple):
    tx_hash: bytes
    output_idx: int
    staked_amount: int
    attached_lvl: int
    expiry_timestamp: int
    owner: str
    representative: str


async def fetch_delegation_position_info(
    request: Union[UpdateDelegationRequest, RevokeDelegationRequest],
):
    transaction_output: TransactionOutput = TransactionOutput.get_or_none(
        TransactionOutput.transaction_hash == request.open_position_tx_hash
    )

    if transaction_output is None:
        raise KnownException(
            f"Delegation position not found for transaction hash: {request.open_position_tx_hash}"
        )

    if transaction_output.spent_in_block is not None:
        raise KnownException(
            f"Delegation position already spent in block {transaction_output.spent_in_block}"
        )

    delegation_position: DelegationPosition = DelegationPosition.get_or_none(
        DelegationPosition.transaction_output == transaction_output
    )

    if delegation_position is None:
        raise KnownException(
            f"Delegation position not found for transaction output: {request.open_position_tx_hash}"
        )

    attached_lvl = None
    staked_amount = None
    for asset_value in transaction_output.assets:
        if asset_value.token.policy_id == "":
            attached_lvl = asset_value.amount
        elif (
            f"{asset_value.token.policy_id}.{asset_value.token.asset_name}"
            == GOVERNANCE_TOKEN
        ):
            staked_amount = asset_value.amount
        else:
            raise KnownException(
                f"Unexpected asset found in delegation position: {asset_value.token.policy_id}.{asset_value.token.asset_name}"
            )

    if attached_lvl is None or staked_amount is None:
        raise KnownException(
            "Delegation position is missing either ADA or staked governance token"
        )

    # datum = transaction_output.datum_hash.data

    # try:
    #     delegation_datum = delegated_staking.DelegationDatum.from_cbor(datum)
    # except Exception:
    #     raise KnownException("Failed to parse delegation datum from transaction output")
    representative = from_address(delegation_position.delegatee)

    return OpenDelegationPositionInfo(
        tx_hash=bytes.fromhex(request.open_position_tx_hash),
        output_idx=transaction_output.output_index,
        staked_amount=staked_amount,
        attached_lvl=attached_lvl,
        expiry_timestamp=delegation_position.expiry,
        owner=delegation_position.owner,
        representative=representative,
    )
