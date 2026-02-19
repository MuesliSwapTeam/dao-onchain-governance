"""
The pool NFT contract.
This contract creates a single one-shot NFT with a unique token name.
Its presence uniquely identifies a liquidity pool.

Outputs of this contract may go to:
- Any address (but the intended target is a pool (1 at most for the creation of a new pool))

It is not allowed to mint several pool NFTs in a single transaction.
"""
from muesliswap_onchain_governance.onchain.one_shot_nft import *

pool_nft_name = one_shot_nft_name
