"""
The tally auth NFT contract.
This NFT authenticates that a tally was minted from a specific governance thread.

This contract is intended to have inputs from these contracts:
- gov_state/gov_state (1, for indicating the governance thread that created this tally)

Outputs of this contract may go to:
- tally/tally (1, the created tally, note this is checked by the gov thread and not here)
- gov_state/gov_state (1, continuation of the above)

NFTs that the outputs may hold:
- tally/tally_auth_nft (the minted one)

It is not allowed to mint several tally auth NFTs in a single transaction.
"""
from opshin.prelude import *

from muesliswap_onchain_governance.onchain.util import *


@dataclass
class AuthRedeemer(PlutusData):
    """
    Redeemer for the auth NFT policy
    """

    CONSTR_ID = 0
    spent_utxo_index: int
    governance_nft_name: TokenName


def validator(
    governance_nft_policy: PolicyId, redeemer: AuthRedeemer, context: ScriptContext
) -> None:
    """
    Authentication NFT policy.
    Ensures that the name of the resulting NFT matches the governance NFT
    that is being spent in the given transaction.
    The policy is parameterized by the policy id of the governance NFT.
    """
    auth_policy_id = get_minting_purpose(context).policy_id

    # Check that
    # 1. the governance NFT is being spent
    # 2. the tokenname is the name of the spent governance NFT

    spent_input = context.tx_info.inputs[redeemer.spent_utxo_index].resolved
    required_token_name = redeemer.governance_nft_name
    assert (
        spent_input.value[governance_nft_policy][required_token_name] == 1
    ), "Governance NFT is not being spent"

    check_mint_exactly_one_with_name(
        context.tx_info.mint, auth_policy_id, required_token_name
    )
