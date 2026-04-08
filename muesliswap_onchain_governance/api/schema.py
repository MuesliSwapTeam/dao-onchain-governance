from typing import Optional

from pydantic import BaseModel, Field


class FundPayoutDatumRequest(BaseModel):
    address: str
    value: list[dict[str, int]]
    reference_script_hash: Optional[str] = None


class OpenVaultPositionRequest(BaseModel):
    address: str
    amount: int
    locked_weeks: int


class CloseVaultPositionRequest(BaseModel):
    address: str
    tx_hash: str
    output_index: int


class ExistingVaultPositionMintRequest(BaseModel):
    address: str
    tx_hash: str
    output_index: int


class OpenDelegationPositionRequest(BaseModel):
    delegator_address: str = Field(
        ...,
        description="The address of the delegator opening the staking position",
    )
    representative_address: str = Field(
        ...,
        description="The address of the representative to whom the staking rights are delegated",
    )
    stake_amount: int = Field(
        ...,
        description="Amount of governance tokens to stake, represented in onchain units (ie. no decimals)",
    )
    delegate_until: int = Field(..., description="Unix timestamp in milliseconds")


class UpdateDelegationRequest(BaseModel):
    open_position_tx_hash: str = Field(
        ...,
        description="The transaction hash of the open delegation position UTxO",
    )
    delegator_address: str = Field(
        ...,
        description="The address of the delegator updating the staking position",
    )
    new_delegate_until: int = Field(
        ..., description="New unix timestamp in milliseconds"
    )
    representative_address: Optional[str] = Field(
        None,
        description="The address of the new representative to whom the staking rights are delegated. If not provided, the representative remains unchanged.",
    )
    new_stake_amount: Optional[int] = Field(
        None,
        description="New amount of governance tokens to stake, represented in onchain units (ie. no decimals). If not provided, the stake amount remains unchanged.",
    )


class RevokeDelegationRequest(BaseModel):
    open_position_tx_hash: str = Field(
        ...,
        description="The transaction hash of the open delegation position UTxO",
    )
    delegator_address: str = Field(
        ...,
        description="The address of the delegator revoking the staking position",
    )


class AppendSignatureRequest(BaseModel):
    tx: str
    tx_body: str
    witness_set: str


class CreateSubDaoTallyRequest(BaseModel):
    proposer_address: str = Field(
        ...,
        description="Hex-encoded address of the proposer (pays fees). Use pycardano Address.to_primitive().hex().",
    )
    parent_gov_nft_name: str = Field(
        ...,
        description="Hex token name of the parent DAO's gov state NFT (from GET /api/v1/gov/state → gov_nft.asset_name).",
    )
    nft_utxo_tx_hash: str = Field(
        ...,
        description="Transaction hash of a UTxO the proposer controls. This UTxO is NOT spent here — it is reserved and must be spent later when executing the sub-DAO creation.",
    )
    nft_utxo_index: int = Field(
        ...,
        description="Output index of the pre-committed UTxO.",
    )
    sub_dao_address: str = Field(
        ...,
        description="Bech32 address where the sub-DAO governance state will live. Must differ from the parent's gov_state address.",
    )
    duration_minutes: int = Field(
        default=1500,
        description="Voting period in minutes (default 25 hours).",
    )
    sub_dao_min_quorum: Optional[int] = Field(
        default=None,
        description="Minimum quorum for the sub-DAO. Inherits from parent if omitted.",
    )
    sub_dao_min_winning_threshold_num: int = Field(
        default=1,
        description="Numerator of minimum winning threshold fraction.",
    )
    sub_dao_min_winning_threshold_den: int = Field(
        default=4,
        description="Denominator of minimum winning threshold fraction.",
    )
    sub_dao_min_proposal_duration: Optional[int] = Field(
        default=None,
        description="Minimum proposal duration in milliseconds. Inherits from parent if omitted.",
    )
    title: str = Field(default="Create Sub-DAO", description="Tally title.")
    description: str = Field(
        default="This proposal creates a new sub-DAO governance thread.",
        description="Tally description.",
    )


class CreateSubDaoTallyResponse(BaseModel):
    signed_tx: str = Field(
        ...,
        description="CBOR hex of TX partially signed by the server collateral key. Pass to POST /api/v1/append_signature to add the proposer's signature.",
    )
    tx_body: str = Field(
        ...,
        description="CBOR hex of the unsigned TX body.",
    )
    sub_dao_nft_name: str = Field(
        ...,
        description="Hex token name of the sub-DAO NFT that will be minted when the tally is executed. Record this — it is needed for POST /api/v1/gov/execute-sub-dao.",
    )


class ExecuteSubDaoRequest(BaseModel):
    proposer_address: str = Field(
        ...,
        description="Hex-encoded address of the executor (pays fees).",
    )
    parent_gov_nft_name: str = Field(
        ...,
        description="Hex token name of the parent DAO's gov state NFT.",
    )
    nft_utxo_tx_hash: str = Field(
        ...,
        description="Transaction hash of the pre-committed UTxO from the tally creation step. This UTxO IS spent in this transaction.",
    )
    nft_utxo_index: int = Field(
        ...,
        description="Output index of the pre-committed UTxO.",
    )


class SignedTxResponse(BaseModel):
    signed_tx: str
    tx_body: str
