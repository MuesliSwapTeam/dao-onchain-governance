import json
import logging

from muesliswap_onchain_governance.onchain.licenses import licenses
from muesliswap_onchain_governance.onchain.simple_pool import simple_pool
from muesliswap_onchain_governance.onchain.treasury import (
    treasurer,
    treasurer_nft,
    value_store,
)
from muesliswap_onchain_governance.onchain.tally import tally_auth_nft, tally
from muesliswap_onchain_governance.onchain.gov_state import gov_state_nft, gov_state
from muesliswap_onchain_governance.onchain.staking import (
    staking,
    staking_vote_nft,
    vote_permission_nft,
    vault_ft,
)
from muesliswap_onchain_governance.onchain.vault import vault
from muesliswap_onchain_governance.utils.contracts import (
    get_contract,
    get_ref_utxo,
    module_name,
)
from muesliswap_onchain_governance.utils.network import context

from muesliswap_onchain_governance.offchain.util import (
    GOV_STATE_NFT_TK_NAME,
    TREASURER_STATE_NFT_TK_NAME,
)


from ..config import DATA_DIR

_LOGGER = logging.getLogger(__name__)


def fetch_constants() -> dict:
    result = {}
    result["policy_ids"] = {}
    result["addresses"] = {}
    result["script_sizes"] = {}
    result["reference_inputs"] = fetch_reference_inputs()
    result["nfts"] = {
        "gov_state_nft": GOV_STATE_NFT_TK_NAME,
        "treasurer_nft": TREASURER_STATE_NFT_TK_NAME,
    }
    result["governance_token"] = {
        "policy_id": "bd976e131cfc3956b806967b06530e48c20ed5498b46a5eb836b61c2",
        "token_name": "744d494c4b7632",
        "decimals": 6,
        "symbol": "MILK",
    }
    for contract in [
        simple_pool,
        tally,
        tally_auth_nft,
        staking_vote_nft,
        staking,
        treasurer,
        value_store,
        licenses,
        treasurer_nft,
        gov_state_nft,
        gov_state,
        vote_permission_nft,
        vault_ft,
        vault,
    ]:
        script, policy_id, script_address = get_contract(module_name(contract))
        result["policy_ids"][module_name(contract)] = policy_id.payload.hex()
        result["addresses"][module_name(contract)] = script_address.encode()
        result["script_sizes"][module_name(contract)] = len(script)

    return result


async def store_reference_inputs():
    # def store_reference_inputs():
    result = {}

    for contract in [
        simple_pool,
        tally,
        tally_auth_nft,
        staking_vote_nft,
        staking,
        treasurer,
        value_store,
        licenses,
        treasurer_nft,
        gov_state_nft,
        gov_state,
        vote_permission_nft,
        vault_ft,
        vault,
    ]:
        contract_script, _, _ = get_contract(module_name(contract), compressed=True)
        ref_utxo = get_ref_utxo(contract_script, context)
        if ref_utxo:
            result[module_name(contract)] = {
                "tx_hash": ref_utxo.input.transaction_id.payload.hex(),
                "index": ref_utxo.input.index,
                # "cbor": ref_utxo.to_cbor_hex(),
            }

    if result:
        with open(DATA_DIR / "reference_inputs.json", "w") as f:
            json.dump(result, f)
        _LOGGER.info("Stored reference inputs to disk")


def fetch_reference_inputs() -> dict:
    try:
        with open(DATA_DIR / "reference_inputs.json", "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


if __name__ == "__main__":
    import asyncio
    import ipdb

    try:
        asyncio.run(store_reference_inputs())
        print(fetch_constants())
    except Exception as e:
        print(e)
        ipdb.post_mortem()
