"""
The main file containing the logic for starting the querier.
The querier syncs with the blockchain, listening for new blocks and updating the database accordingly.
"""

import logging
from datetime import datetime

import fire

from muesliswap_onchain_governance.api.tx_processor import process_tx

from ..utils.network import ogmios_url
from . import ogmios_iterator
from .db_models import Block, GovState, TransactionOutput, TreasurerState
from .util import slot_to_timestamp

_LOGGER = logging.getLogger(__name__)
logging.basicConfig(
    format="%(asctime)s %(levelname)-8s %(message)s", level=logging.INFO, force=True
)


def main(rollback_to_slot: int = None, debug_sql: bool = False):
    """
    Start the querier.
    """
    if debug_sql:
        logger = logging.getLogger("peewee")
        logger.addHandler(logging.StreamHandler())
        logger.setLevel(logging.DEBUG)

    _LOGGER.info("Starting the querier")
    if rollback_to_slot is not None:
        Block.delete().where(Block.slot > rollback_to_slot).execute()
    sync_blocks = [
        Block.select().order_by(Block.slot.desc()).first(),
        Block.select().order_by(Block.slot.desc()).offset(1).first(),
        Block.select().order_by(Block.slot.desc()).offset(5).first(),
        Block.select().order_by(Block.slot.desc()).offset(50).first(),
        Block.select().order_by(Block.slot.desc()).offset(1000).first(),
    ]

    tracked_gov_states = []
    tracked_treasury_states = []

    iterator = ogmios_iterator.OgmiosIterator(ogmios_url)

    try:
        for operation in iterator.iterate_blocks(
            [
                ogmios_iterator.Point(slot=block.slot, id=block.hash)
                for block in sync_blocks
                if block is not None
            ]
        ):
            if isinstance(operation, ogmios_iterator.Rollback):
                if isinstance(operation.tip, ogmios_iterator.Origin):
                    _LOGGER.info("Rollback to origin")
                    Block.delete().execute()
                    continue
                else:
                    _LOGGER.info(f"Rollback to tip {str(operation.tip)}")
                    Block.delete().where(Block.slot > operation.tip.slot).execute()
                    # At least one Rollback is executed once after each restart, so we can be sure this is initialized correctly
                    tracked_gov_states = list(
                        GovState.select()
                        .join(TransactionOutput)
                        .where(TransactionOutput.spent_in_block.is_null())
                    )
                    tracked_treasury_states = list(
                        TreasurerState.select()
                        .join(TransactionOutput)
                        .where(TransactionOutput.spent_in_block.is_null())
                    )
                    continue
            else:
                block = ogmios_iterator.tip_from_block(operation.block)
                db_block = Block(hash=block.id, slot=block.slot, height=block.height)
                db_block.save()
                try:
                    _LOGGER.info(
                        f"Processing block at {datetime.fromtimestamp(slot_to_timestamp(block.slot))}: {block.id}"
                    )
                    for i, tx in enumerate(
                        ogmios_iterator.txs_from_block(operation.block)
                    ):
                        process_tx(
                            tx, db_block, i, tracked_gov_states, tracked_treasury_states
                        )
                except Exception as e:
                    _LOGGER.warning(f"Error processing block {block.id}: {e}")
                    db_block.delete_instance()
                    raise
    finally:
        iterator.close()


if __name__ == "__main__":
    fire.Fire(main)
    fire.Fire(main)
