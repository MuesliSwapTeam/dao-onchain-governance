from datetime import datetime
from typing import List

import pycardano
from opshin.prelude import Token
from pycardano import Asset, AssetName, MultiAsset, Network, ScriptHash, Value

GOV_STATE_NFT_TK_NAME = (
    "d2df764c3d88ae56503c9053b3bb60917116c88daa9643fe1e0d0a2e6473ad07"
)

OLD_GOV_STATE_NFT_TK_NAME = (
    "77813d879ac66733ef75d28d8e312d0d0defddc6d356fd43475b6093f7fa86f1"
)


TREASURER_STATE_NFT_TK_NAME = (
    # "84a34461aa95932ece5bd2a08cdc685ccd4d84a9b76a9f434b651a18a5b81b5d" # standard config, working
    "fbd683dbbdec3fb8faa77170dcb86b19111fe8aaee187291863156937701a73e"  # easy tallies
)
TALLY_METADATA_KEY = 2000
PROPOSAL_CONSTRUCTORS_TO_TYPES = {
    -1: "Opinion",
    6: "Reject",
    100: "GovStateUpdate",
    101: "LicenseRelease",
    106: "PoolUpgrade",
    102: "FundPayout",
}


def token_from_string(token: str) -> Token:
    if token == "lovelace":
        return Token(b"", b"")
    policy_id, token_name = token.split(".")
    return Token(
        policy_id=bytes.fromhex(policy_id),
        token_name=bytes.fromhex(token_name),
    )


def value_from_token(token: Token, amount: int) -> Value:
    if token.policy_id == b"" and token.token_name == b"":
        return pycardano.Value(coin=amount)
    return pycardano.Value(multi_asset=asset_from_token(token, amount))


def asset_from_token(token: Token, amount: int) -> MultiAsset:
    return MultiAsset(
        {ScriptHash(token.policy_id): Asset({AssetName(token.token_name): amount})}
    )


def with_min_lovelace(
    output: pycardano.TransactionOutput, context: pycardano.ChainContext
):
    min_lvl = pycardano.min_lovelace(context, output)
    output.amount.coin = max(output.amount.coin, min_lvl + 500000)
    return output


def sorted_utxos(txs: List[pycardano.UTxO]):
    return sorted(
        txs,
        key=lambda u: (u.input.transaction_id.payload, u.input.index),
    )


def amount_of_token_in_value(
    token: Token,
    value: Value,
) -> int:
    return value.multi_asset.get(ScriptHash(token.policy_id), {}).get(
        AssetName(token.token_name), 0
    )


def time_of_slot(slot: int, network=Network.TESTNET) -> datetime:
    if network == Network.MAINNET:
        return datetime.fromtimestamp(1596491091 + (slot - 4924800))
    else:
        return datetime.fromtimestamp(slot + 1655683200)


def slot_of_time(time: datetime, network=Network.TESTNET):
    if network == Network.MAINNET:
        return 4924800 + (round(time.timestamp()) - 1596491091)
    else:
        return round(time.timestamp()) - 1660000000


# NOTE: ChatGPT generated function
def remove_zero_values(v: Value) -> Value:
    """
    Removes keys from the inner dictionaries where the value is 0.
    Also removes keys from 'multi_asset' where the inner dict is empty.

    :param v: Value object containing the multi_asset dictionary
    :return: Processed Value object with keys removed where values are 0
    """
    # Collect keys from multi_asset whose inner dictionaries are empty after processing
    multi_asset_keys_to_delete = []

    # Iterate over the multi_asset dictionary
    for asset_key, tk in v.multi_asset.items():
        # Remove keys from the inner dictionary where the value is 0
        tk_keys_to_delete = [k for k, val in tk.items() if val == 0]
        for k in tk_keys_to_delete:
            del tk[k]
        # If the inner dictionary is empty after deletion, mark the outer key for deletion
        if not tk:
            multi_asset_keys_to_delete.append(asset_key)

    # Remove keys from multi_asset whose inner dictionaries are empty
    for asset_key in multi_asset_keys_to_delete:
        del v.multi_asset[asset_key]

    return v
