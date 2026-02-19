import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import ORJSONResponse
from fastapi_cache import Coder, FastAPICache
from fastapi_cache.backends.inmemory import InMemoryBackend
from starlette.responses import Response

from muesliswap_onchain_governance.api.db_models import db
from muesliswap_onchain_governance.api.db_queries import (
    delegation,
    gov_state,
    staking,
    tally,
    treasury,
    vault,
)
from muesliswap_onchain_governance.api.tokens import (
    get_all_token_details,
    get_token_details,
    get_ttl_hash,
)
from muesliswap_onchain_governance.offchain.util import time_of_slot

from .cardano import delegation_txs
from .cardano.constants import fetch_constants, store_reference_inputs
from .cardano.datums import construct_treasury_payout_datum
from .cardano.misc import append_signature
from .cardano.vault_txs import (
    construct_close_vault_position_tx,
    construct_mint_vault_ft_tx,
    construct_open_vault_position_tx,
)
from .db_models import TransactionOutput, VaultPosition
from .schema import *
from .util import (
    OpenDelegationPositionInfo,
    fetch_delegation_position_info,
    parse_address,
)

# logger setup
_LOGGER = logging.getLogger(__name__)
logging.basicConfig(
    format="%(asctime)s %(levelname)-8s %(message)s", level=logging.INFO, force=True
)


def DashingQuery(convert_underscores=True, **kwargs) -> Query:
    """
    This class enables "convert underscores" by default, allowing parameter names
    with underscores to be accessed via hypehenated versions
    """
    query = Query(**kwargs)
    query.convert_underscores = convert_underscores
    return query


@asynccontextmanager
async def lifespan(app: FastAPI):
    await store_reference_inputs()
    FastAPICache.init(
        InMemoryBackend(),
        expire=20,
        coder=NoCoder,
    )
    yield


app = FastAPI(
    default_response_class=ORJSONResponse,
    title="MuesliSwap Governance API.",
    description="The MuesliSwap Governance API provides access to on-chain data for the MuesliSwap Onchain Governance System.",
    version="0.0.1",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,  # Must be False when using allow_origins=["*"] per CORS spec
    allow_methods=["*"],
    allow_headers=["*"],
)


class NoCoder(Coder):
    @classmethod
    def encode(cls, value: Any) -> str:
        return value

    @classmethod
    def decode(cls, value: str) -> Any:
        return value


def add_cachecontrol(response: Response, max_age: int, directive: str = "public"):
    # see https://developer.mozilla.org/en-US/docs/Web/HTTP/Headers/Cache-Control
    # and https://fastapi.tiangolo.com/advanced/response-headers/
    response.headers["Cache-Control"] = f"{directive}, max-age={max_age}"


def add_jsoncontenttype(response: Response):
    # see https://developer.mozilla.org/en-US/docs/Web/HTTP/Headers/Cache-Control
    # and https://fastapi.tiangolo.com/advanced/response-headers/
    response.headers["Content-Type"] = "application/json"


#################################################################################################
#                                            Endpoints                                          #
#################################################################################################

PolicyIdQuery = DashingQuery(
    description="Policy ID of a token",
    examples=["", "afbe91c0b44b3040e360057bf8354ead8c49c4979ae6ab7c4fbdc9eb"],
    # TODO add validation
)
TokenNameQuery = DashingQuery(
    description="Hex encoded name of a token",
    examples=["", "4d494c4b7632"],
    # TODO add validation
)
AsBaseQuery = DashingQuery(
    description="Token that should be used as base",
    examples=["from", "to"],
    # TODO add validation
)
IncludeTradesQuery = DashingQuery(
    description="Whether or not to include the last trades data",
    examples=["true", "false"],
    # TODO add validation
)
IncludeAdaPricesQuery = DashingQuery(
    description="Whether or not to include the ada price data",
    examples=["true", "false"],
    # TODO add validation
)
VerifiedQuery = DashingQuery(
    description="Filter for only verified tokens",
    examples=["true", "false", "1", "0"],
    # TODO add validation
)
PubkeyHashQuery = DashingQuery(
    description="Pubkeyhash of a wallet",
    examples=["dcbc64ce3cc4aeac225a45dd67dfc3717f732f6303556efb6dd8024f"],
    # TODO add validation
)
StakekeyHashQuery = DashingQuery(
    description="Stake key hash of a wallet",
    examples=["dcbc64ce3cc4aeac225a45dd67dfc3717f732f6303556efb6dd8024f"],
    # TODO add validation
)
PubkeyHashesQuery = DashingQuery(
    description="Stake key hash of a wallet",
    examples=[
        "",
        "dcbc64ce3cc4aeac225a45dd67dfc3717f732f6303556efb6dd8024f,dcbc64ce3cc4aeac225a45dd67dfc3717f732f6303556efb6dd8024f",
    ],
    # TODO add validation
)
OptWalletQuery = DashingQuery(
    default=None,
    description="Wallet address in hex",
    examples=[
        "01dcbc64ce3cc4aeac225a45dd67dfc3717f732f6303556efb6dd8024f0420b0d045f11e8a66319f9d19ffcba35aa9fee0164014776a1f7c95"
    ],
    # TODO add validation
)
WalletQuery = DashingQuery(
    description="Wallet address in hex",
    examples=[
        "01dcbc64ce3cc4aeac225a45dd67dfc3717f732f6303556efb6dd8024f0420b0d045f11e8a66319f9d19ffcba35aa9fee0164014776a1f7c95"
    ],
    # TODO add validation
)
AddressQuery = DashingQuery(
    description="Wallet address in bech32",
    examples=[
        "addr1q8wtcexw8nz2atpztfza6e7lcdch7ue0vvp42mhmdhvqyncyyzcdq303r69xvvvln5vlljart25lacqkgq28w6sl0j2skvlxf4"
    ],
    # TODO add validation
)
ProviderQuery = DashingQuery(
    description="Provider name",
    examples=["muesliswap", "minswap", "vyfi"],
    # TODO add validation
)
TokenQuery = DashingQuery(
    description="Toke name in hex",
    examples=[
        ".",
        "afbe91c0b44b3040e360057bf8354ead8c49c4979ae6ab7c4fbdc9eb.4d494c4b7632",
    ],
    # TODO add validation
)
AssetIdentifierQuery = DashingQuery(
    description="Asset identifier in hex: Concatenation of the policy_id and hex-encoded asset_name",
    examples=[
        "",
        "afbe91c0b44b3040e360057bf8354ead8c49c4979ae6ab7c4fbdc9eb4d494c4b7632",
    ],
    # TODO add validation
)
TransactionHashQuery = DashingQuery(
    description="Transaction hash",
    examples=["6804edf9712d2b619edb6ac86861fe93a730693183a262b165fcc1ba1bc99cad"],
    # TODO add validation
)
TransactionIdQuery = DashingQuery(
    description="Transaction id",
    examples=[0, 1, 2],
    # TODO add validation
)
ProposalTypeQuery = DashingQuery(
    description="Proposal types (e.g. Opinion, Reject, GovStateUpdate, FundPayout, LicenseRelease, PoolUpgrade) that must be contained, separated through ','",
    examples=[["any"], ["FundPayout"], ["LicenseRelease", "PoolUpgrade"]],
    default="any",
    # TODO add validation
)


def add_token_details_and_timestamps(data):
    if isinstance(data, dict):
        if "policy_id" in data and "asset_name" in data:
            details = get_token_details(
                data["policy_id"], data["asset_name"], ttl_hash=get_ttl_hash()
            )
            if details is not None and "address" in details:
                del details["address"]
            data.update(details)

        if "slot" in data:
            data["timestamp"] = time_of_slot(data["slot"]).strftime("%Y-%m-%d %H:%M:%S")

        # recursively call this function for each value in the dict
        for _, value in data.items():
            add_token_details_and_timestamps(value)

    elif isinstance(data, list):
        # recursively call this function for each item in the list
        for item in data:
            add_token_details_and_timestamps(item)

    # if data is neither a dict nor a list, do nothing
    return data


@app.get("/api/v1/health")
def health():
    last_block = db.Block.select().order_by(db.Block.slot.desc()).first()
    return ORJSONResponse(
        {
            "status": "ok" if last_block else "nok",
            "last_block": (
                {
                    "slot": last_block.slot,
                    "height": last_block.height,
                    "hash": last_block.hash,
                }
                if last_block
                else None
            ),
        }
    )


@app.get("/api/v1/tokens/all")
def all_tokens():
    """
    Provide a curated list of tokens
    """

    all_tokens = get_all_token_details(ttl_hash=get_ttl_hash())
    return ORJSONResponse(all_tokens)


@app.get("/api/v1/tokens/curated")
def curated_tokens():
    """
    Provide a curated list of tokens
    """

    def filter_fn(t):
        if "address" not in t:
            return False
        return (t["address"]["policyId"], t["address"]["name"]) in [
            ("", ""),  # ADA
            (
                "afbe91c0b44b3040e360057bf8354ead8c49c4979ae6ab7c4fbdc9eb",
                "4d494c4b7632",
            ),  # Mainnet MILK
            (
                "bd976e131cfc3956b806967b06530e48c20ed5498b46a5eb836b61c2",
                "744d494c4b7632",
            ),  # Preprod tMilk
        ]

    all_tokens = get_all_token_details(pred_fn=filter_fn, ttl_hash=get_ttl_hash())
    return ORJSONResponse(all_tokens)


@app.get("/api/v1/staking/positions")
def staking_positions(
    wallet: str = WalletQuery,
):
    """
    Get the currently open staking positions for a wallet.
    """
    return ORJSONResponse(
        add_token_details_and_timestamps(
            staking.query_staking_positions_per_wallet(wallet)
        )
    )


@app.get("/api/v1/staking/history")
def staking_history(
    wallet: str = OptWalletQuery,
):
    """
    Get the staking history for a wallet.
    """
    return ORJSONResponse(
        add_token_details_and_timestamps(
            staking.query_staking_history_per_wallet(wallet)
            if wallet
            else staking.query_staking_history()
        )
    )


@app.get("/api/v1/tallies")
def tallies(
    open: bool = DashingQuery(
        description="Show open tallies",
        examples=["true", "false", "1", "0"],
    ),
    closed: bool = DashingQuery(
        description="Show closed tallies",
        examples=["true", "false", "1", "0"],
    ),
    contains_proposal_type: str = ProposalTypeQuery,
):
    """
    Get all open tallies
    """
    return ORJSONResponse(
        add_token_details_and_timestamps(
            tally.query_tallies(closed, open, contains_proposal_type.split(","))
        )
    )


@app.get("/api/v1/tallies/batcher-licenses")
def tally_batcher_licenses():
    """
    Get all batcher licenses
    """
    return ORJSONResponse(
        add_token_details_and_timestamps(tally.query_batcher_license_tallies())
    )


@app.get("/api/v1/tallies/tally_detail")
def tally_detail(
    tally_auth_nft: str = DashingQuery(
        description="Tally Auth NFT",
        examples=[
            "471b0b6f3fab69f9c6e8c1c1389782a410a8689d97e22a22ac24b30f.bc0a47f8459162152c33913f9d4e50d2340459ce4b6197761967d64368e0e50c"
        ],
    ),
    tally_proposal_id: int = DashingQuery(
        description="Tally Proposal ID",
        examples=[0, 1, 2],
    ),
):
    """
    Get details for a specific tally
    """
    return ORJSONResponse(
        add_token_details_and_timestamps(
            tally.query_tally_details_by_auth_nft_proposal_id(
                tally_auth_nft, tally_proposal_id
            )
        )
    )


@app.get("/api/v1/tallies/tally_votes")
def tally_votes(
    tally_auth_nft: str = DashingQuery(
        description="Tally Auth NFT",
        examples=[
            "471b0b6f3fab69f9c6e8c1c1389782a410a8689d97e22a22ac24b30f.bc0a47f8459162152c33913f9d4e50d2340459ce4b6197761967d64368e0e50c"
        ],
    ),
    tally_proposal_id: int = DashingQuery(
        description="Tally Proposal ID",
        examples=[0, 1, 2],
    ),
):
    """
    Get votes for a specific tally
    """
    return ORJSONResponse(
        add_token_details_and_timestamps(
            tally.query_all_user_votes_for_tally(tally_auth_nft, tally_proposal_id)
        )
    )


@app.get("/api/v1/treasury/funds")
def treasury_funds():
    """
    Get the funds in the current treasury
    """
    return ORJSONResponse(
        add_token_details_and_timestamps(treasury.query_current_treasury_funds())
    )


@app.get("/api/v1/treasury/history")
def treasury_history():
    """
    Get the deposits, payouts and other operations on the treasury
    """
    return ORJSONResponse(
        add_token_details_and_timestamps(treasury.query_treasury_history())
    )


@app.get("/api/v1/treasury/daily_chart")
def treasury_funds_daily_chart():
    """
    Get the accumulated funds in treasury over time (one entry per day)
    """
    sparse_balances = add_token_details_and_timestamps(
        treasury.query_treasury_history()
    )
    return ORJSONResponse(treasury.fill_daily_balances(sparse_balances))


@app.get("/api/v1/gov/state")
def current_gov_state():
    """
    Get the current state of the governance system
    """
    return ORJSONResponse(gov_state.query_current_gov_state())


@app.get("/api/v1/vault/positions")
def vault_positions(
    pkh: str = PubkeyHashQuery,
):
    """
    Get the currently open vault positions for a wallet.
    """
    return ORJSONResponse(
        add_token_details_and_timestamps(vault.query_vault_positions_per_wallet(pkh))
    )


@app.get("/api/v1/delegation/positions")
def delegation_positions(
    pkh: str = PubkeyHashQuery,
):
    """
    Get the currently open delegation positions for a wallet.
    """
    return ORJSONResponse(
        add_token_details_and_timestamps(
            delegation.query_delegation_positions_per_wallet(pkh)
        )
    )


@app.get("/api/v1/delegation/history")
def delegation_history(
    pkh: str = PubkeyHashQuery,
):
    """
    Get the currently open delegation positions for a wallet.
    """
    return ORJSONResponse(
        add_token_details_and_timestamps(
            delegation.query_delegation_history_per_wallet(pkh)
        )
    )


################# VAULT TXS ####################


@app.post("/api/v1/vault/open_position")
async def _construct_open_vault_position(
    request: OpenVaultPositionRequest,
) -> SignedTxResponse:
    """
    Constructs an open vault position transaction.
    """
    response = await construct_open_vault_position_tx(
        request.address,
        request.locked_weeks,
        request.amount,
    )
    return ORJSONResponse(response)


@app.post("/api/v1/vault/mint_ft")
async def _construct_mint_vault_ft(
    request: ExistingVaultPositionMintRequest,
) -> SignedTxResponse:
    """
    Constructs a mint vault FT transaction.
    """
    vault_position = (
        VaultPosition.select()
        .join(TransactionOutput)
        .where(
            TransactionOutput.transaction_hash == request.tx_hash,
            TransactionOutput.output_index == request.output_index,
        )
        .first()
    )

    if vault_position is None:
        raise HTTPException(status_code=404, detail="Vault position not found")

    if vault_position.minted_ft:
        raise HTTPException(status_code=400, detail="Vault FT already minted")

    response = await construct_mint_vault_ft_tx(
        request.address,
        request.tx_hash,
        request.output_index,
    )
    return ORJSONResponse(response)


@app.post("/api/v1/vault/close_position")
async def _construct_close_vault_position(
    request: CloseVaultPositionRequest,
) -> SignedTxResponse:
    """
    Constructs a close vault position transaction.
    """
    response = await construct_close_vault_position_tx(
        request.address,
        request.tx_hash,
        request.output_index,
    )
    return ORJSONResponse(response)


############## DELEGATION TXS #################


@app.post("/api/v1/delegation/delegate")
async def _construct_open_delegation_position(
    request: OpenDelegationPositionRequest,
) -> SignedTxResponse:
    """
    Constructs an open delegation position transaction.
    """

    delegator = parse_address(request.delegator_address)
    representative = parse_address(request.representative_address)

    response = await delegation_txs.construct_open_delegation_position_tx(
        delegator,
        representative,
        request.stake_amount,
        request.delegate_until,
    )
    return ORJSONResponse(response)


@app.post("/api/v1/delegation/update_delegation")
async def _construct_delegation_update(
    request: UpdateDelegationRequest,
    open_position_info: OpenDelegationPositionInfo = Depends(
        fetch_delegation_position_info
    ),
) -> SignedTxResponse:
    """
    Constructs a delegation update transaction.
    """
    delegator = parse_address(request.delegator_address)

    response = await delegation_txs.construct_update_delegation_tx(
        tx_hash=open_position_info.tx_hash,
        output_idx=open_position_info.output_idx,
        delegator_address=delegator,
        position_owner_pkh=bytes.fromhex(open_position_info.owner),
        current_expiry=open_position_info.expiry_timestamp,
        new_expiry=request.new_delegate_until,
        attached_lvl=open_position_info.attached_lvl,
        current_staked_amount=open_position_info.staked_amount,
        new_staked_amount=(
            request.new_stake_amount
            if request.new_stake_amount is not None
            else open_position_info.staked_amount
        ),
        representative_address=(
            parse_address(request.representative_address)
            if request.representative_address is not None
            else open_position_info.representative
        ),
    )

    return ORJSONResponse(response)


@app.post("/api/v1/delegation/revoke_delegation")
async def _construct_revoke_delegation(
    request: RevokeDelegationRequest,
    open_position_info: OpenDelegationPositionInfo = Depends(
        fetch_delegation_position_info
    ),
) -> SignedTxResponse:
    """
    Constructs a revoke delegation transaction.
    """

    response = await delegation_txs.construct_revoke_delegation_tx(
        tx_hash=open_position_info.tx_hash,
        output_idx=open_position_info.output_idx,
        expiry=open_position_info.expiry_timestamp,
        staked_amount=open_position_info.staked_amount,
        attached_lvl=open_position_info.attached_lvl,
        delegator_address=parse_address(request.delegator_address),
    )

    return ORJSONResponse(response)


######### MISCELLANEOUS SMART CONTRACT UTILITIES ################


@app.post("/api/v1/append_signature")
def _append_signature(request: AppendSignatureRequest) -> str:
    """
    Appends a signature to a transaction.
    """
    return ORJSONResponse(
        append_signature(
            request.tx,
            request.tx_body,
            request.witness_set,
        )
    )


@app.post("/api/v1/treasury/build_payout_datum")
def _construct_fund_payout_datum(request: FundPayoutDatumRequest):
    """
    Constructs a fund payout datum.
    """
    return ORJSONResponse(
        construct_treasury_payout_datum(
            request.address, request.value, request.reference_script_hash
        )
    )


@app.get("/api/v1/constants")
def get_constants():
    """
    Get the current constants of the governance system
    """

    return ORJSONResponse(fetch_constants())


# for debugging
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "server:app", host="localhost", port=8001, log_level="info", reload=True
    )
