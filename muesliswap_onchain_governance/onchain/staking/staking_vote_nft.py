"""
The staking vote NFT contract.
This NFT authenticates that a staking position has participated in a tally.
The purpose is to prevent removing votes from a tally without participating in the first place.

This contract is intended to have inputs from these contracts:
- staking/staking (1, indicating the stake participating in some tally)
- tally/tally (1, indicating the tally in which the stake participates)

Outputs of this contract may go to:
- staking/staking (continuation of the above, this output will hold the minted NFT)
- tally/tally (continuation of the above)

NFTs that the outputs may hold:
- staking/staking_vote_nft (previously minted plus the own minted one)
- tally/tally_auth_nft (at the tally address)

It is not allowed to mint several staking vote NFTs in a single transaction.
"""
from opshin.prelude import *
from opshin.std.builtins import *

from muesliswap_onchain_governance.onchain.util import *


@dataclass
class VoteAuthRedeemer(PlutusData):
    """
    Redeemer for the stake authentication NFT to mint a vote NFT
    """

    CONSTR_ID = 0
    tally_input_index: int
    tally_output_index: int
    vote_index: int
    staking_output_index: int


@dataclass
class BurnRedeemer(PlutusData):
    """
    Redeemer for the stake authentication NFT to burn a vote NFT
    """

    CONSTR_ID = 1


VoteNFTRedeemer = Union[VoteAuthRedeemer, BurnRedeemer]


def validator(
    tally_address: Address, redeemer: VoteNFTRedeemer, context: ScriptContext
) -> None:
    """
    Stake Authentication NFT
    This NFT authenticates that the user participated correctly in a governance proposal,
    i.e. a Staking Participation is only valid if accompanied by the matching NFT.
    The minting contract validates that the user can only mint an NFT with the name that matches the tally state and participation.
    """
    purpose = get_minting_purpose(context)
    tx_info = context.tx_info

    if isinstance(redeemer, BurnRedeemer):
        # Burning NFTs is always allowed
        # but we need to make sure that all mints with this policy are burning
        own_mint = tx_info.mint[purpose.policy_id]
        assert all(
            [amount < 0 for amount in own_mint.values()]
        ), "NFTs can only be burned with the burn redeemer"
    else:
        tally_input = tx_info.inputs[redeemer.tally_input_index].resolved
        assert (
            tally_input.address == tally_address
        ), "Tally input is not at the tally address"
        tally_input_state: TallyState = resolve_datum_unsafe(tally_input, tx_info)
        assert token_present_in_output(
            tally_input_state.params.tally_auth_nft, tally_input
        ), f"AuthNFT missing from given input"

        tally_output = tx_info.outputs[redeemer.tally_output_index]
        assert (
            tally_output.address == tally_address
        ), "Tally output is not at the tally address"
        tally_output_state: TallyState = resolve_datum_unsafe(tally_output, tx_info)
        assert token_present_in_output(
            tally_input_state.params.tally_auth_nft, tally_output
        ), f"AuthNFT missing from given output"

        vote_index = redeemer.vote_index
        weight = (
            tally_output_state.votes[vote_index]
            - tally_input_state.votes[redeemer.vote_index]
        )

        staking_output = tx_info.outputs[redeemer.staking_output_index]
        assert (
            staking_output.address == tally_input_state.params.staking_address
        ), "Staking output is not at the staking address"

        check_correct_staking_vote_nft_mint(
            vote_index,
            weight,
            tally_input_state.params,
            tx_info,
            staking_output,
        )
