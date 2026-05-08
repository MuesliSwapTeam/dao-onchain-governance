"""
Reputation minting policy.

Reputation is represented as fungible tokens whose token name is derived from the
staking position owner. A user can mint reputation by consuming a staking position
that contains an ended vote participation and removing that participation from the
continuing staking datum. This makes the participation a one-time proof.
"""

from muesliswap_onchain_governance.onchain.util import *


@dataclass
class MintReputation(PlutusData):
    """
    Mint reputation for one ended participation in a staking position.
    """

    CONSTR_ID = 0
    staking_input_index: int
    staking_output_index: int
    participation_index: int
    amount: int


def validator(redeemer: MintReputation, context: ScriptContext) -> None:
    purpose = get_minting_purpose(context)
    tx_info = context.tx_info

    staking_input = tx_info.inputs[redeemer.staking_input_index].resolved
    previous_state: StakingState = resolve_datum_unsafe(staking_input, tx_info)
    assert user_signed_tx(
        previous_state.params.owner, tx_info
    ), "Staking owner must sign"
    assert (
        previous_state.params.reputation_policy == purpose.policy_id
    ), "Wrong reputation policy"

    participation = previous_state.participations[redeemer.participation_index]
    assert vote_has_ended(
        participation.tally_params.end_time, tx_info.valid_range
    ), "Participation is not from an ended vote"
    assert redeemer.amount == 1, "One reputation is minted per vote participation"

    desired_next_state = StakingState(
        remove_participation_at_index(
            previous_state.participations, redeemer.participation_index
        ),
        previous_state.params,
    )
    staking_output = tx_info.outputs[redeemer.staking_output_index]
    assert (
        staking_output.address == staking_input.address
    ), "Staking output must stay at staking address"
    next_state: StakingState = resolve_datum_unsafe(staking_output, tx_info)
    assert next_state == desired_next_state, "Unexpected staking output datum"

    reputation_token = Token(
        purpose.policy_id, reputation_token_name(previous_state.params.owner)
    )
    check_mint_exactly_n_with_name(
        tx_info.mint,
        redeemer.amount,
        reputation_token.policy_id,
        reputation_token.token_name,
    )
    expected_output_value = add_value(
        staking_input.value,
        {reputation_token.policy_id: {reputation_token.token_name: redeemer.amount}},
    )
    check_equal_except_ada_increase(staking_output.value, expected_output_value)
