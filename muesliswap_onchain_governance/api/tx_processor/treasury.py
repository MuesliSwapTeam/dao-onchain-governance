import pycardano

from opshin.ledger.api_v2 import FinitePOSIXTime
from . import from_db
from .to_db import (
    add_output,
    add_address,
    add_datum,
    add_token_token,
    add_token,
    add_transaction,
)
from ..config import vote_permission_nft_policy_id, treasurer_nft_policy_id
from ..db_models import Block, TransactionOutput, Transaction, TrackedGovStates
from ..db_models.treasury import TrackedTreasuryStates

from ...onchain.treasury import treasurer as onchain_treasurer
from ..db_models import treasury as db_treasury

import logging

from ...utils.from_script_context import from_address

_LOGGER = logging.getLogger(__name__)


def process_tx(
    tx: pycardano.Transaction,
    block: Block,
    block_index: int,
    tracked_treasury_states: TrackedTreasuryStates,
):
    """
    Process a transaction and update the database accordingly.
    Updates the tracked treasury states.
    """
    value_stores = set(
        from_db.from_address(t.treasurer_params.value_store).to_primitive()
        for t in tracked_treasury_states
    )

    created_treasurer_states = []
    created_value_stores = []
    treasurer_nft = None
    for i, output in enumerate(tx.transaction_body.outputs):
        if output.address.to_primitive() in value_stores:
            _LOGGER.debug(f"Stores funds in value store: {tx.id.payload.hex()}")
            value_store_output = add_output(
                output, i, tx.id.payload.hex(), block, block_index
            )
            try:
                onchain_value_store_state: onchain_treasurer.ValueStoreState = (
                    onchain_treasurer.ValueStoreState.from_primitive(output.datum.data)
                )
            except Exception as e:
                _LOGGER.info(f"Invalid treasurer parameters at {tx.id.payload.hex()}")
                continue
            treasurer_nft = add_token_token(onchain_value_store_state.treasurer_nft)
            value_store_state = db_treasury.ValueStoreState.create(
                transaction_output=value_store_output,
                treasurer_nft=treasurer_nft,
            )
            created_value_stores.append(value_store_state)
        if output.amount.multi_asset.get(treasurer_nft_policy_id, {}):
            treasurer_output = add_output(
                output, i, tx.id.payload.hex(), block, block_index
            )
            try:
                onchain_treasurer_state: onchain_treasurer.TreasurerState = (
                    onchain_treasurer.TreasurerState.from_primitive(output.datum.data)
                )
            except Exception as e:
                _LOGGER.info(f"Invalid treasurer parameters at {tx.id.payload.hex()}")
                continue
            onchain_treasurer_params = onchain_treasurer_state.params
            treasurer_nft = add_token_token(onchain_treasurer_params.treasurer_nft)
            db_treasurer_params = db_treasury.TreasurerParams.get_or_create(
                auth_nft=add_token_token(onchain_treasurer_params.auth_nft),
                value_store=add_address(
                    from_address(onchain_treasurer_params.value_store)
                ),
                treasurer_nft=treasurer_nft,
            )[0]
            db_treasurer_state = db_treasury.TreasurerState.create(
                transaction_output=treasurer_output,
                treasurer_params=db_treasurer_params,
                last_applied_proposal_id=onchain_treasurer_state.last_applied_proposal_id,
            )
            created_treasurer_states.append(db_treasurer_state)
            tracked_treasury_states.append(db_treasurer_state)
    spent_value_store_states = []
    spent_treasurer_states = []
    ref_tally_states = []
    payout_output = None
    tally_input_index = None
    # we don't need to bother checking the inputs if no output treasurer is created
    # there is no way to spend a value store or treasurer without creating a treasurer
    if not (created_treasurer_states or created_value_stores):
        return
    for input_idx, tx_input in enumerate(tx.transaction_body.inputs):
        value_store_state: db_treasury.ValueStoreState = (
            db_treasury.ValueStoreState.select()
            .join(TransactionOutput)
            .where(
                TransactionOutput.transaction_hash
                == tx_input.transaction_id.payload.hex(),
                TransactionOutput.output_index == tx_input.index,
            )
            .first()
        )
        if value_store_state is not None:
            spent_value_store_states.append(value_store_state)
            treasurer_nft = value_store_state.treasurer_nft
        treasurer_state = (
            db_treasury.TreasurerState.select()
            .join(TransactionOutput)
            .where(
                TransactionOutput.transaction_hash
                == tx_input.transaction_id.payload.hex(),
                TransactionOutput.output_index == tx_input.index,
            )
            .first()
        )
        if treasurer_state is not None:
            treasurer_nft = treasurer_state.treasurer_params.treasurer_nft
            tracked_treasury_states.remove(treasurer_state)
            # fetch the redeemer for this treasurer state
            if isinstance(tx.transaction_witness_set.redeemer, pycardano.RedeemerMap):
                redeemers = tx.transaction_witness_set.redeemer.items()
            else:
                redeemers = [
                    (redeemer, redeemer)
                    for redeemer in tx.transaction_witness_set.redeemer
                ]

            spent_treasurer_redeemer = [
                r for r in redeemers if r[0].index == input_idx
            ][0][1].data
            spent_treasurer_states.append(treasurer_state)
            try:
                onchain_treasurer_redeemer: onchain_treasurer.PayoutFunds = (
                    onchain_treasurer.PayoutFunds.from_primitive(
                        spent_treasurer_redeemer
                    )
                )
            except Exception as e:
                _LOGGER.debug(f"Treasurer was spent with consolidate funds")
                continue
            payout_output = add_output(
                tx.transaction_body.outputs[onchain_treasurer_redeemer.payout_index],
                onchain_treasurer_redeemer.payout_index,
                tx.id.payload.hex(),
                block,
                block_index,
            )
            tally_input_index = onchain_treasurer_redeemer.tally_input_index

    if tally_input_index is not None:
        tally_input = sorted(
            tx.transaction_body.reference_inputs,
            key=lambda x: (x.transaction_id.payload, x.index),
        )[tally_input_index]
        tally_state = (
            db_treasury.TallyState.select()
            .join(TransactionOutput)
            .where(
                TransactionOutput.transaction_hash
                == tally_input.transaction_id.payload.hex(),
                TransactionOutput.output_index == tally_input.index,
            )
            .first()
        )
        if tally_state is not None:
            ref_tally_states.append(tally_state)

    treasury_delta = db_treasury.TreasuryDelta.create(
        transaction=add_transaction(tx.id.payload.hex(), block, block_index),
        treasurer_nft=treasurer_nft,
    )
    if spent_treasurer_states and ref_tally_states and payout_output is not None:
        db_treasury.TreasuryPayout.create(
            treasury_delta=treasury_delta,
            treasurer_state=(
                spent_treasurer_states[0] if spent_treasurer_states else None
            ),
            tally_state=ref_tally_states[0] if ref_tally_states else None,
            payout_output=payout_output,
        )
    delta_value = pycardano.Value()
    for state in created_value_stores:
        delta_value += from_db.from_output_values(state.transaction_output.assets)
    for state in spent_value_store_states:
        delta_value -= from_db.from_output_values(state.transaction_output.assets)
    lovelace = delta_value.coin
    if lovelace != 0:
        db_treasury.TreasuryDeltaValue.create(
            treasury_delta=treasury_delta,
            token=add_token(b"", b""),
            amount=lovelace,
        )
    for policy_id, d in delta_value.multi_asset.items():
        for asset_name, amount in d.items():
            if amount == 0:
                continue
            token = add_token(policy_id, asset_name)
            db_treasury.TreasuryDeltaValue.create(
                treasury_delta=treasury_delta, token=token, amount=amount
            )
