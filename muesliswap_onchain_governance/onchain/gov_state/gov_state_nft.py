"""
The governance state NFT contract.
This contract creates a single one-shot NFT with a unique token name.
Its presence uniquely identifies a governance thread.

Outputs of this contract may go to:
- Any address (but the intended target is gov_state/gov_state (1 at most for the creation of a new governance state))

It is not allowed to mint several governance state NFTs in a single transaction.
"""

from muesliswap_onchain_governance.onchain.one_shot_nft import *

gov_state_nft_name = one_shot_nft_name
