import logging
from typing import Union

import pycardano

from muesliswap_onchain_governance.onchain.delegation import delegated_staking
from muesliswap_onchain_governance.utils.contracts import get_contract
from muesliswap_onchain_governance.utils.from_script_context import from_address

from ..db_models import Block, TrackedGovStates, TransactionOutput
from ..db_models.delegation import (
    Consolidation,
    ConsolidationPosition,
    DelegationAction,
    DelegationPosition,
    DelegationRevoke,
)
from . import from_db
from .to_db import add_address, add_output, add_transaction
from .util import resolve_redeemers

_LOGGER = logging.getLogger(__name__)

_, _, delegation_contract_address = get_contract("delegated_staking", compressed=True)


def get_relevant_redeemer(
    redeemers, tx: pycardano.Transaction, contract_address: pycardano.Address
):
    script_hash = contract_address.payment_part
    for redeemer_key, redeemer_value in redeemers:
        if redeemer_key.tag != pycardano.RedeemerTag.MINT:
            continue
        if (
            sorted(tx.transaction_body.mint, key=lambda x: x.payload)[
                redeemer_key.index
            ]
            != script_hash
        ):
            continue
        return redeemer_value.data
    return None


def parse_delegation_redeemer(
    raw_redeemer: pycardano.plutus.RawPlutusData,
) -> Union[
    delegated_staking.OpenDelegationPositionRedeemer,
    delegated_staking.RenewDelegationBeforeExpiry,
    delegated_staking.RenewDelegationAfterExpiry,
    None,
]:
    redeemer_cbor_tag = raw_redeemer.data
    try:
        redeemer = delegated_staking.OpenDelegationPositionRedeemer.from_primitive(
            redeemer_cbor_tag
        )
        return redeemer
    except Exception:
        pass

    try:
        redeemer = delegated_staking.RenewDelegationBeforeExpiry.from_primitive(
            redeemer_cbor_tag
        )
        return redeemer
    except Exception:
        pass

    try:
        redeemer = delegated_staking.RenewDelegationAfterExpiry.from_primitive(
            redeemer_cbor_tag
        )
        return redeemer
    except Exception:
        pass

    return None


def process_tx(
    tx: pycardano.Transaction,
    block: Block,
    block_index: int,
    tracked_gov_states: TrackedGovStates,
):
    """
    Process a transaction and update the database accordingly.
    """

    delegation_contract_addresses = set(
        from_db.from_address(gs.gov_params.delegation_address).to_primitive()
        for gs in tracked_gov_states
    ) | set([delegation_contract_address.to_primitive()])

    created_delegation_position = None
    created_consolidation_position = None

    for i, output in enumerate(tx.transaction_body.outputs):
        if output.address.to_primitive() in delegation_contract_addresses:
            _LOGGER.debug(f"Delegation transaction: {tx.id.payload.hex()}")
            delegation_output = add_output(
                output, i, tx.id.payload.hex(), block, block_index
            )
            redeemers = resolve_redeemers(tx)
            datum = None
            try:
                datum = delegated_staking.DelegationDatum.from_primitive(
                    output.datum.data
                )
            except Exception:
                pass

            try:
                datum = delegated_staking.ConsolidationDatum.from_primitive(
                    output.datum.data
                )

            except Exception:
                pass

            if datum is None:
                _LOGGER.info(
                    f"Invalid delegated staking datum at {tx.id.payload.hex()}"
                )
                continue

            if isinstance(datum, delegated_staking.DelegationDatum):
                redeemer = parse_delegation_redeemer(
                    get_relevant_redeemer(redeemers, tx, output.address)
                )

                assert redeemer is not None, (
                    f"Redeemer not parsed correctly for delegation in tx {tx.id.payload.hex()}"
                )

                delegation_position = DelegationPosition.create(
                    transaction_output=delegation_output,
                    owner=datum.owner.hex(),
                    expiry=datum.delegation_expiry,
                    delegatee=add_address(from_address(redeemer.delegatee_address)),
                )
                created_delegation_position = delegation_position

            elif isinstance(datum, delegated_staking.ConsolidationDatum):
                consolidation_position = ConsolidationPosition.create(
                    transaction_output=delegation_output,
                    owner=datum.owner.hex(),
                    lower_bound=datum.lower_bound,
                    amount=datum.amount,
                )
                created_consolidation_position = consolidation_position

    # Track continuing delegation positions (eg. from extensions)
    # Consolidation positions do not continue, so we do not track them here
    spent_state = None
    if created_delegation_position:
        for input in tx.transaction_body.inputs:
            delegation_position = (
                DelegationPosition.select()
                .join(TransactionOutput)
                .where(
                    TransactionOutput.transaction_hash
                    == input.transaction_id.payload.hex(),
                    TransactionOutput.output_index == input.index,
                )
                .first()
            )
            if delegation_position:
                spent_state = delegation_position

        DelegationAction.create(
            transaction=add_transaction(tx.id.payload.hex(), block, block_index),
            prev_delegation_position=spent_state,
            next_delegation_position=created_delegation_position,
        )

    if created_consolidation_position:
        Consolidation.create(
            transaction=add_transaction(tx.id.payload.hex(), block, block_index),
            consolidation_position=created_consolidation_position,
        )

    # Track revokes: delegation position spent without creating a new one
    if created_delegation_position is None:
        for input in tx.transaction_body.inputs:
            delegation_position = (
                DelegationPosition.select()
                .join(TransactionOutput)
                .where(
                    TransactionOutput.transaction_hash
                    == input.transaction_id.payload.hex(),
                    TransactionOutput.output_index == input.index,
                )
                .first()
            )
            if delegation_position:
                DelegationRevoke.create(
                    transaction=add_transaction(tx.id.payload.hex(), block, block_index),
                    prev_delegation_position=delegation_position,
                )
