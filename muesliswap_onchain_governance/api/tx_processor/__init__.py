import peewee
import pycardano

from ..db_models import Block, TrackedTreasuryStates, TransactionOutput
from ..db_models.gov_state import TrackedGovStates
from ..util import FixedTxHashTransaction
from .delegation import process_tx as process_delegation_tx
from .gov_state import process_tx as process_gov_state_tx
from .licenses import process_tx as process_licenses_tx
from .staking import process_tx as process_staking_tx
from .tally import process_tx as process_tally_tx
from .treasury import process_tx as process_treasury_tx
from .vault import process_tx as process_vault_tx


def process_tx(
    tx: FixedTxHashTransaction,
    block: Block,
    block_index: int,
    tracked_gov_states: TrackedGovStates,
    tracked_treasury_states: TrackedTreasuryStates,
):
    """
    Process a transaction and update the database accordingly.
    """

    # mark all inputs to the transaction as spent
    spent_inputs = [
        (_input.transaction_id.payload.hex(), _input.index)
        for _, _input in enumerate(tx.transaction_body.inputs)
    ]
    for h, i in spent_inputs:
        TransactionOutput.update(spent_in_block=block).where(
            (TransactionOutput.transaction_hash == h)
            & (TransactionOutput.output_index == i)
        ).execute()

    # model specific processing
    process_gov_state_tx(tx, block, block_index, tracked_gov_states)
    process_staking_tx(tx, block, block_index, tracked_gov_states)
    process_tally_tx(tx, block, block_index, tracked_gov_states)
    process_licenses_tx(tx, block, block_index)
    process_treasury_tx(tx, block, block_index, tracked_treasury_states)
    process_vault_tx(tx, block, block_index)
    process_delegation_tx(tx, block, block_index, tracked_gov_states)
