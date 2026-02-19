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


class SignedTxResponse(BaseModel):
    signed_tx: str
    tx_body: str
