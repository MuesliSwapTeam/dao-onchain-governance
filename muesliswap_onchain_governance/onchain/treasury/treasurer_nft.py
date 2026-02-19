"""
The treasurer NFT contract.
This contract creates a single one-shot NFT with a unique token name.
Its presence uniquely identifies a treasurer thread.

Outputs of this contract may go to:
- Any address (but the intended target is treasurer/treasurer (1 at most for the creation of a new treasurer state))

It is not allowed to mint several treasurer NFTs in a single transaction.
"""
from muesliswap_onchain_governance.onchain.one_shot_nft import *

treasurer_nft_name = one_shot_nft_name
