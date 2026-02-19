"""
Simple LP Tokens for the simple pool
Ensures that the name of the lp is exactly the name of the pool nft
and can be only minted when said pool nft is minted.
DISCLAIMER: This is a simple example to demonstrate onchain based contract upgradeability and should not be used in production.
"""

from muesliswap_onchain_governance.onchain.simple_pool.classes import *


def validator(
    pool_nft_policy_id: PolicyId, pool_input_index: int, context: ScriptContext
) -> None:
    """
    Validates that the LP tokens are minted correctly
    """
    # try to obtain the spent pool
    pool_input = context.tx_info.inputs[pool_input_index].resolved
    # ensure that the LP tokens are minted correctly
    pool_nft_name = pool_input.value[pool_nft_policy_id].keys()[0]
    purpose = get_minting_purpose(context)
    policy_id = purpose.policy_id
    assert len(context.tx_info.mint[policy_id]) == 1, "Only one token can be minted"
    token_name = context.tx_info.mint[policy_id].keys()[0]
    assert token_name == pool_nft_name, "LP token name must match pool NFT name"
