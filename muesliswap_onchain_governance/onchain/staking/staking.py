"""
The staking contract.

This contract holds governance tokens (i.e. MILK) and vault FT tokens that represent
locked governance tokens. It tracks participation in tallies and releases these tokens
only when they are not participating in a tally anymore.

This contract is intended to be have inputs from these contracts:
- staking/staking (1 at most, maintaining the state of participations)
- tally/tally: For tracking the retraction of participation in a tally

This contract is intended to have mints with these contracts:
- staking/staking_vote_nft: For tracking the addition of participation in a tally

Outputs of this contract may go to:
- staking/staking (1 at most, continuation of the above)
- the owner of the staking position (for withdrawing funds)
- tally/tally (1 at most, maintaining the tally state, no value transfer should happen to this address)

NFTs present at outputs of this contract:
- staking/staking_vote_nft (authenticates a valid participation in the tally towards the tally contract)
- staking/vault_ft (represents locked governance tokens)
- staking/vote_permission_nft (permits a third party to execute an addition or retraction of tally participation, i.e. votes)
- tally/tally_auth_nft (1 at the output that goes to the tally and has previously been at the tally)

It is not allowed to spend several staking states in a single transaction.
"""

from muesliswap_onchain_governance.onchain.staking.staking_util import *


def resolve_linear_input_state(datum: StakingState) -> StakingState:
    """
    Resolve the datum of the input that is referenced by the redeemer.
    """
    # TODO could compare datum with previous_state_input.datum, but maybe not necessary
    return datum


def resolve_linear_output_state(
    next_state_output: TxOut, tx_info: TxInfo
) -> StakingState:
    """
    Resolve the continuing datum of the output that is referenced by the redeemer.
    """
    next_state: StakingState = resolve_datum_unsafe(next_state_output, tx_info)
    return next_state


def check_next_state_correct(
    next_state: StakingState, desired_next_state: StakingState
) -> None:
    assert desired_next_state == next_state, "New staking state is incorrect"


def transform_redeemer_to_delegated_redeemer(
    redeemer: Union[AddVote, RetractVote],
    previous_state: StakingState,
) -> DelegatableStakingRedeemer:
    if isinstance(redeemer, AddVote):
        return DelegatedAddVote(
            redeemer.participation,
        )
    elif isinstance(redeemer, RetractVote):
        return DelegatedRetractVote(
            previous_state.participations[redeemer.participation_index],
        )
    else:
        assert False, "Invalid redeemer type"
        return DelegatedAddVote(
            previous_state.participations[0],
        )


def check_owner_authorized_operation(
    previous_state: StakingState,
    redeemer: StakingRedeemer,
    previous_state_input: TxOut,
    vote_permission_nft_policy: PolicyId,
    tx_info: TxInfo,
) -> Value:
    # The has to have authorized performing the operation by adding the correct NFT

    print("Owner did not sign tx, checking for permission NFT")
    assert isinstance(redeemer, AddVote) or isinstance(redeemer, RetractVote), (
        "Only adding or retracting votes is allowed without owner signature"
    )
    spent_vote_permission_token = Token(
        vote_permission_nft_policy,
        vote_permission_nft_token_name(
            VotePermissionNFTParams(
                previous_state.params.owner,
                transform_redeemer_to_delegated_redeemer(redeemer, previous_state),
            )
        ),
    )
    assert token_present_in_output(
        spent_vote_permission_token,
        previous_state_input,
    ), "Permission NFT was not spent in specified tally index input"
    # check that the permission nft is burned upon execution
    assert (
        tx_info.mint[spent_vote_permission_token.policy_id][
            spent_vote_permission_token.token_name
        ]
        == -1
    ), "Permission NFT was not burned"

    # check that the corresponding vote nft is being added in case of addvote,
    # to prevent malicious execution of addvote
    if isinstance(redeemer, AddVote):
        participation = redeemer.participation
        participation_token_mint_amount = 1
    elif isinstance(redeemer, RetractVote):
        participation = previous_state.participations[redeemer.participation_index]
        participation_token_mint_amount = -1
    else:
        assert False, "Invalid redeemer type"
    desired_nft_name = staking_vote_nft_name(
        participation.proposal_index, participation.weight, participation.tally_params
    )
    participation_token = Token(
        participation.tally_params.staking_vote_nft_policy, desired_nft_name
    )
    assert (
        tx_info.mint[participation_token.policy_id][participation_token.token_name]
        == participation_token_mint_amount
    ), "Vote NFT was not minted/burned correctly"

    # Return permissible extracted value from staking position
    # By adding the vote permission token, we allow that it is removed from the staking position
    # Moreover we enforce that the vote permission token is added/removed to the staking position depending on whether
    # the vote is added or retracted / the token was minted or burned
    return {
        b"": {b"": -2_000_000},
        spent_vote_permission_token.policy_id: {
            spent_vote_permission_token.token_name: -1
        },
        participation_token.policy_id: {
            participation_token.token_name: participation_token_mint_amount
        },
    }


def check_enough_governance_tokens_in_output(
    desired_next_state: StakingState,
    next_state_output: TxOut,
    tx_validity_range: POSIXTimeRange,
    no_output: bool,
) -> None:
    fixed_gov_token_in_output = (
        amount_of_token_in_output(
            desired_next_state.params.governance_token, next_state_output
        )
        if not no_output
        else 0
    )
    empty_variable_gov_weight_list: List[Weight] = []
    variable_gov_weight_list = (
        variable_governance_weight_in_output_list(
            next_state_output,
            desired_next_state.params.vault_ft_policy,
            desired_next_state.params.delegation_policy,
        )
        if not no_output
        else empty_variable_gov_weight_list
    )
    for p in desired_next_state.participations:
        if not vote_has_ended(p.tally_params.end_time, tx_validity_range):
            next_locked_valid_governance_tokens = fixed_gov_token_in_output
            tally_end_time = p.tally_params.end_time
            if isinstance(tally_end_time, FinitePOSIXTime):
                for w in variable_gov_weight_list:
                    if w.valid_until >= tally_end_time.time:
                        next_locked_valid_governance_tokens += w.weight
            required_governance_tokens = p.weight
            assert required_governance_tokens <= next_locked_valid_governance_tokens, (
                "Removed too many gov tokens"
            )


def check_preserve_staking_position_value(
    previous_state_input: TxOut,
    next_state_output: TxOut,
    expected_value_change: Value,
    no_output: bool,
) -> None:
    prev_value = previous_state_input.value
    prev_value_plus_changed_value = add_value(
        prev_value,
        expected_value_change,
    )
    if no_output:
        check_greater_or_equal_value(EMPTY_VALUE_DICT, prev_value_plus_changed_value)
    else:
        next_value = next_state_output.value
        # note that it is fine to add in particular ada so that minutxo is preserved
        # however no unrelated tokens are to be added which would increase the output size
        check_equal_except_ada_increase(next_value, prev_value_plus_changed_value)


def validator(
    vote_permission_nft_policy: PolicyId,
    state: StakingState,
    redeemer: StakingRedeemer,
    context: ScriptContext,
) -> None:
    """
    Staking Contract
    Locks user funds and tracks participation in the governance.
    Funds can only be withdrawn after the proposals that the fund participate in have ended.
    Until the end of participating proposals, the user can only withdraw so many tokens that all proposals are still backed (max of participating funds).
    The user may add or retract votes at any time, with weight up to the locked tokens or participating tokens respectively.

    Note that the staking contract is not aware of the existance of the governance state.
    This is why a vote participation is only valid when accompanied by the the correct stake authentication NFT.
    """
    purpose = get_spending_purpose(context)
    tx_info = context.tx_info

    previous_state_input = resolve_linear_input(
        tx_info, redeemer.state_input_index, purpose
    )
    previous_state = resolve_linear_input_state(state)
    desired_next_state = construct_desired_output_staking_state(
        previous_state, redeemer, tx_info
    )
    owner_controls_tx = user_signed_tx(previous_state.params.owner, tx_info)

    no_staking_output = no_output_to_address(
        previous_state_input.address, tx_info.outputs
    )
    if not no_staking_output:
        next_state_output = resolve_linear_output(
            previous_state_input, tx_info, redeemer.state_output_index
        )
        next_state = resolve_linear_output_state(next_state_output, tx_info)

        # check that the new state is correct
        check_next_state_correct(next_state, desired_next_state)
        # check that the staking state is not made too large accidentally
        check_staking_output_reasonably_sized(next_state_output, next_state)
    else:
        next_state_output = previous_state_input

    # check that the amount of governance tokens in the output is correct
    check_enough_governance_tokens_in_output(
        desired_next_state, next_state_output, tx_info.valid_range, no_staking_output
    )
    if not owner_controls_tx:
        # check that only the owner can perform operations
        expected_value_change = check_owner_authorized_operation(
            previous_state,
            redeemer,
            previous_state_input,
            vote_permission_nft_policy,
            tx_info,
        )
        # check that the executor may take a maximum of 2 ada from the output
        # and adds/removes the correct NFTs
        check_preserve_staking_position_value(
            previous_state_input,
            next_state_output,
            expected_value_change,
            no_staking_output,
        )
