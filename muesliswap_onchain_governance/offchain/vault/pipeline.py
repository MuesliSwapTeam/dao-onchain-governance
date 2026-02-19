"""
Executes the three main Vault transactions on the testnet
"""

from time import sleep
from pycardano import Network
import fire

from . import (
    close_position_burn,
    existing_position_mint,
    new_position_mint,
    new_position_no_mint,
)

from ...utils import network


def main():

    assert network == Network.TESTNET, "This script should only be run on testnet"

    # Open a new vault position and mint Vault FTs. This position is open for
    # 30 days and the resulting Vault FTs can be used to test staking.
    new_position_mint.main()

    sleep(120)

    # Open a new vault position without minting Vault FTs.
    tx = new_position_no_mint.main(locked_seconds=300)

    sleep(120)

    # Use the resulting UTxO from the previous transaction to mint Vault FTs.
    existing_position_mint.main(
        open_position_tx_id=tx.id.payload.hex(),
    )

    # Ensure that the position is now able to be unlocked.
    sleep(300)
    close_position_burn.main(
        open_position_tx_id=tx.id.payload.hex(),
    )


if __name__ == "__main__":
    fire.Fire(main)
