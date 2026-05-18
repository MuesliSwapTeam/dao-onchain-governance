import os

import blockfrost
import pycardano
from pycardano import BlockFrostChainContext, Network
from pycardano.backend.ogmios_v6 import OgmiosV6ChainContext

ogmios_host = os.getenv("OGMIOS_API_HOST", "localhost")
ogmios_port = os.getenv("OGMIOS_API_PORT", "1338")
ogmios_protocol = os.getenv("OGMIOS_API_PROTOCOL", "ws")
ogmios_url = f"{ogmios_protocol}://{ogmios_host}:{ogmios_port}"

kupo_host = os.getenv("KUPO_API_HOST", None)
kupo_port = os.getenv("KUPO_API_PORT", "6669")
kupo_protocol = os.getenv("KUPO_API_PROTOCOL", "http")
kupo_url = (
    f"{kupo_protocol}://{kupo_host}:{kupo_port}" if kupo_host is not None else None
)

explorer = os.getenv("EXPLORER_TX", "http://localhost:5173/transactions")

network = Network.TESTNET

blockfrost_project_id = os.getenv(
    "BLOCKFROST_PROJECT_ID", "preprodLFNwFkORcmvKF2ml3wCBjB6jMkXSE5IX"
)
blockfrost_client = blockfrost.BlockFrostApi(
    blockfrost_project_id,
    base_url=(
        blockfrost.ApiUrls.mainnet.value
        if network == Network.MAINNET
        else blockfrost.ApiUrls.preprod.value
    ),
)


# Load chain context
try:
    context = BlockFrostChainContext(project_id=blockfrost_project_id, network=network)
except Exception:
    print("No Blockfrost project ID configured — BlockFrost context unavailable")
    context = None

try:
    evaluation_context = OgmiosV6ChainContext(
        host=ogmios_host,
        port=int(ogmios_port),
        secure=ogmios_protocol == "wss",
        network=network,
    )
    mainnet_evaluation_context = OgmiosV6ChainContext(
        host=ogmios_host,
        port=int(ogmios_port) - 1,
        secure=ogmios_protocol == "wss",
        network=Network.MAINNET,
    )
except Exception:
    print(f"No ogmios available at {ogmios_url} — evaluation_context unavailable")
    evaluation_context = None
    mainnet_evaluation_context = None


def show_tx(signed_tx: pycardano.Transaction):
    print(f"transaction id: {signed_tx.id}")
    if network == Network.TESTNET:
        print(f"Explorer: {explorer}/{signed_tx.id}")
    else:
        print(f"Explorer: https://cexplorer.io/tx/{signed_tx.id}")
        print(f"Explorer: https://cardanoscan.io/transaction/{signed_tx.id}")
