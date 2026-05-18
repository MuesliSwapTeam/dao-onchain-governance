from pathlib import Path

import pycardano
from pycardano import Network

from ..onchain.gov_state import gov_state_nft
from ..onchain.licenses import licenses
from ..onchain.staking import vote_permission_nft
from ..onchain.treasury import treasurer_nft
from ..utils import contracts, network
from ..utils.contracts import module_name

# Only these scripts need to be hardcoded
# And should also change seldomly

# Governance NFT policy from the deployed contracts (with reputation_policy in GovStateParams)
gov_state_nft_policy_id = pycardano.ScriptHash(
    bytes.fromhex("966a1c82181378295b0c9fa7cf076127f02882ad0d65d1bc397daadc")
)
_, vote_permission_nft_policy_id, _ = contracts.get_contract(
    module_name(vote_permission_nft), compressed=True
)
_, licenses_policy_id, _ = contracts.get_contract(
    module_name(licenses), compressed=True
)
_, treasurer_nft_policy_id, _ = contracts.get_contract(
    module_name(treasurer_nft), compressed=True
)


START_BLOCK_SLOT = 108821659 if network == Network.TESTNET else 125125931

START_BLOCK_HASH = (
    "9fef924e3eb40958c74026df3ed5d31e29325d77029111870dfe1f924ad2bfdf"
    if network == Network.TESTNET
    else "bde676ad40372bde8cd778c035ac606976c07ec7dde261f313f3ea39cc196c74"
)

TOKENS_BACKEND_URL = f"https://{'preprod.' if network == Network.TESTNET else ''}tokens-v2.muesliswap.com"
TOKENS_CACHE_TTL = 3600

DATA_DIR = Path("data")

DATA_DIR.mkdir(exist_ok=True)
