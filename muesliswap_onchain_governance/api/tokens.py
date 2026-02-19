from .config import TOKENS_BACKEND_URL, TOKENS_CACHE_TTL
import requests
from functools import lru_cache
import time


DESIRED_TOKEN_FIELDS = [
    "address",
    "symbol",
    "image",
    "decimalPlaces",
]


def get_ttl_hash(seconds=TOKENS_CACHE_TTL):
    return round(time.time() / seconds)


@lru_cache()
def _get_all_raw_tokens(ttl_hash=None):
    del ttl_hash
    try:
        res = requests.get(TOKENS_BACKEND_URL + "/tokens/*")
        res.raise_for_status()
        all_tokens = res.json()

        missing_new_milk = True
        new_milk = {
            "address": {
                "policyId": "bd976e131cfc3956b806967b06530e48c20ed5498b46a5eb836b61c2",
                "name": "744d494c4b7632",
            },
            "symbol": "tMILK",
            "decimalPlaces": 6,
            "image": "https://tokens.muesliswap.com/static/img/tokens/afbe91c0b44b3040e360057bf8354ead8c49c4979ae6ab7c4fbdc9eb.4d494c4b7632_scaled_100.webp",
        }
        for a in all_tokens:
            if "address" in a and a["address"]["policyId"] == "bd976e131cfc3956b806967b06530e48c20ed5498b46a5eb836b61c2" and a["address"]["name"] == "744d494c4b7632":
                missing_new_milk = False
                a["decimalPlaces"] = new_milk["decimalPlaces"]
                a["image"] = new_milk["image"]
        
        if missing_new_milk:
            all_tokens.append(new_milk)
        
        return all_tokens
    except requests.exceptions.RequestException as e:
        print(f"Error fetching data from {TOKENS_BACKEND_URL}: {e}")
        return []


def _cleanup_token_details(t):
    keys_to_delete = [k for k in t.keys() if k not in DESIRED_TOKEN_FIELDS]
    for k in keys_to_delete:
        if k not in DESIRED_TOKEN_FIELDS:
            del t[k]
    if "address" not in t and t["symbol"] == "ADA":
        t["address"] = {"policyId": "", "name": ""}
    if "symbol" not in t:
        t["symbol"] = ""
    if "decimalPlaces" not in t:
        t["decimalPlaces"] = 0
    if "image" not in t:
        t["image"] = "https://static.muesliswap.com/images/tokens/empty.png"
    elif t["image"] == "/images/tokens/MILK.png":
        t["image"] = (
            "https://tokens.muesliswap.com/static/img/tokens/afbe91c0b44b3040e360057bf8354ead8c49c4979ae6ab7c4fbdc9eb.4d494c4b7632.png"
        )
    elif t["image"] == "https://ada.muesliswap.com/images/tokens/ada.png":
        t["image"] = "https://static.muesliswap.com/images/tokens/ada.png"

    return t


@lru_cache()
def get_all_token_details(pred_fn=None, ttl_hash=None):
    del ttl_hash
    all_token_data = []
    for t in _get_all_raw_tokens(ttl_hash=get_ttl_hash()):
        res = _cleanup_token_details(t)
        if pred_fn and not pred_fn(res):
            continue
        all_token_data.append(res)

    return all_token_data


@lru_cache()
def get_token_details(policy_id: str, tokenname: str, ttl_hash=None):
    del ttl_hash
    all_token_data = _get_all_raw_tokens(ttl_hash=get_ttl_hash())
    for t in all_token_data:
        if (
            "address" in t
            and t["address"]["policyId"] == policy_id
            and t["address"]["name"] == tokenname
        ):
            _cleanup_token_details(t)
            return t

    symbol_placeholder = ""
    try:
        symbol_placeholder = bytes.fromhex(tokenname).decode("utf-8")
    except UnicodeDecodeError:
        symbol_placeholder = "AUTH"

    return {
        "address": {
            "policyId": policy_id,
            "name": tokenname,
        },
        "symbol": symbol_placeholder,
        "decimalPlaces": 0,
        "image": "https://static.muesliswap.com/images/tokens/empty.png",
    }
