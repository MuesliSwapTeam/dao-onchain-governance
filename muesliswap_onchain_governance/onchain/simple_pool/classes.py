from muesliswap_onchain_governance.onchain.util import *


@dataclass
class ImmutablePoolParams(PlutusData):
    CONSTR_ID = 0
    token_a: Token
    token_b: Token
    pool_nft: Token
    pool_lp_token: Token


@dataclass
class UpgradeablePoolParams(PlutusData):
    CONSTR_ID = 0
    fee: Fraction
    auth_nft: Token
    license_policy_id: PolicyId
    last_applied_proposal_id: ProposalId


@dataclass
class PoolState(PlutusData):
    CONSTR_ID = 0
    im_pool_params: ImmutablePoolParams
    up_pool_params: UpgradeablePoolParams
    global_liquidity_tokens: int
    spent_for: Union[TxOutRef, Nothing]


@dataclass
class PoolUpgradeParams(PlutusData):
    """VOTE OUTCOME"""

    CONSTR_ID = 106
    # Set to specific token to upgrade only one, or Nothing to upgrade all
    old_pool_nft: Union[Token, Nothing]
    # Set to desired new parameters and address of pool
    # Set to Nothing to preserve old parameters
    new_pool_params: Union[UpgradeablePoolParams, Nothing]
    new_pool_address: Union[Address, Nothing]
