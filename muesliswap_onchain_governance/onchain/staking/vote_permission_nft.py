"""
The vote permission NFT contract.
This NFT allows a third party to perform the addition or retraction of a participation in a vally
for a staking position with a (potentially contended) tally UTxO

This contract is intended to have inputs from these contracts:
- Any (intended: staking/staking)

Outputs of this contract may go to:
- Any (intended: staking/staking (continuation of the above, this output will hold the minted NFT))

NFTs that the outputs may hold:
- staking/vote_permission_nft (previously minted plus the own minted one)

It is not allowed to mint several vote permission NFTs in a single transaction.
"""
from muesliswap_onchain_governance.onchain.staking.staking_util import *


def validator(
    redeemer: Union[VotePermissionNFTParams, Nothing], context: ScriptContext
) -> None:
    """
    Permission NFT

    The presence of this NFT in a staking position indicates that a third party may execute the given redeemer.
    """
    purpose = get_minting_purpose(context)
    tx_info = context.tx_info

    own_mint = tx_info.mint[purpose.policy_id]
    if all([amount < 0 for amount in own_mint.values()]):
        # Burning NFTs is always allowed
        # but we need to make sure that all mints with this policy are burning
        pass
    elif isinstance(redeemer, VotePermissionNFTParams):
        token_name = vote_permission_nft_token_name(redeemer)
        assert user_signed_tx(
            redeemer.owner, tx_info
        ), "Only the owner may mint this NFT"

        check_mint_exactly_one_with_name(tx_info.mint, purpose.policy_id, token_name)
    else:
        assert False, "Invalid redeemer"
