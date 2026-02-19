"""
The tally contract.

This contract holds the current state of a tally. It interacts with the staking contract in order to add and retract
its participation in the tally.

This contract is intended to be have inputs from these contracts:
- tally/tally: Maintaining the state of the tally votes
- staking/staking: For tracking the addition or retraction of votes

This contract is intended to have mints with these contracts:
- staking/staking_vote_nft: For tracking the addition (resp. retraction) of participation in a tally by mint (resp. burn)

Outputs of this contract may go to:
- tally/tally (1 at most, continuation of the above)
- staking/staking (1 at most, maintaining the state of participations, no value transfer should happen here)

Relevant NFTs present at outputs of this contract:
- staking/staking_vote_nft (authenticates a valid participation in the tally towards the tally contract)
- staking/vault_ft (represents locked governance tokens)
- tally/tally_auth_nft (1 at the output that goes to the tally and has previously been at the tally)

It is not allowed to spend several tally states in a single transaction.
"""

from muesliswap_onchain_governance.onchain.staking.staking_util import *


@dataclass
class BoxedInt(PlutusData):
    """
    Boxed Int
    """

    CONSTR_ID = 0
    value: int


OptionalInt = Union[BoxedInt, Nothing]


@dataclass
class AddTallyVote(PlutusData):
    """
    Redeemer for the Tally contract to add a vote to the tally.

    Add a vote to the tally
    """

    CONSTR_ID = 1
    proposal_index: int
    weight: int
    voter_address: Address
    tally_input_index: int
    tally_output_index: int
    staking_output_index: int
    staking_input_index: OptionalInt


@dataclass
class RetractTallyVote(PlutusData):
    """
    Redeemer for the Tally contract to retract a vote from the tally.

    Retracts a vote to the tally
    """

    CONSTR_ID = 2
    proposal_index: int
    weight: int
    voter_address: Address
    tally_input_index: int
    tally_output_index: int
    staking_output_index: int
    staking_participation_index: int


TallyAction = Union[AddTallyVote, RetractTallyVote]


def resolve_linear_output_state(
    next_state_output: TxOut, tx_info: TxInfo
) -> TallyState:
    """
    Resolve the continuing datum of the output that is referenced by the redeemer.
    """
    next_state: TallyState = resolve_datum_unsafe(next_state_output, tx_info)
    return next_state


def add_votes_to_index(list: List[int], index: int, weight: int) -> List[int]:
    assert 0 <= index < len(list), "Invalid index"
    assert weight >= 0, "Weight must be positive"
    return list[:index] + [list[index] + weight] + list[index + 1 :]


def remove_votes_from_index(list: List[int], index: int, weight: int) -> List[int]:
    assert 0 <= index < len(list), "Invalid index"
    return list[:index] + [list[index] - weight] + list[index + 1 :]


def construct_new_tally_state(
    previous_tally_state: TallyState, redeemer: TallyAction
) -> TallyState:
    """
    Construct the new tally state based on the previous tally state and the redeemer
    """
    if isinstance(redeemer, AddTallyVote):
        desired_votes = add_votes_to_index(
            previous_tally_state.votes, redeemer.proposal_index, redeemer.weight
        )
    elif isinstance(redeemer, RetractTallyVote):
        desired_votes = remove_votes_from_index(
            previous_tally_state.votes, redeemer.proposal_index, redeemer.weight
        )
    else:
        assert False, "Invalid redeemer"
    return TallyState(
        desired_votes,
        previous_tally_state.params,
    )


def translate_to_participation(
    redeemer: TallyAction, tally_state: TallyState
) -> Participation:
    return Participation(
        reduced_proposal_params(tally_state.params),
        redeemer.weight,
        redeemer.proposal_index,
    )


def resolve_sublinear_staking_input(
    tx_info: TxInfo, staking_input_index: OptionalInt, tally_state: TallyState
) -> Union[TxOut, Nothing]:
    """
    Resolve the staking input that is referenced by the redeemer. Ensure that at most one staking input is present.
    """
    staking_address = tally_state.params.staking_address
    if isinstance(staking_input_index, BoxedInt):
        previous_staking_state_input = tx_info.inputs[
            staking_input_index.value
        ].resolved
        assert previous_staking_state_input.address == staking_address, (
            "Staking input is not at the staking address"
        )
        assert (
            len([i for i in tx_info.inputs if i.resolved.address == staking_address])
            == 1
        ), "More than one staking input"
        return previous_staking_state_input
    else:
        assert (
            len([i for i in tx_info.inputs if i.resolved.address == staking_address])
            == 0
        ), "A staking input is consumed, but none declared in the redeemer"
        return Nothing()


def resolve_staking_input_state(
    previous_staking_state_input: Union[TxOut, Nothing],
    tx_info: TxInfo,
    redeemer: AddTallyVote,
    tally_state: TallyState,
) -> StakingState:
    if isinstance(previous_staking_state_input, TxOut):
        res: StakingState = resolve_datum_unsafe(previous_staking_state_input, tx_info)
        return res
    else:
        participations: List[Participation] = []
        return StakingState(
            participations,
            StakingParams(
                redeemer.voter_address,
                tally_state.params.governance_token,
                tally_state.params.vault_ft_policy,
                tally_state.params.delegation_policy,
                tally_state.params.tally_auth_nft,
            ),
        )


def check_valid_staking_update(
    previous_tally_state: TallyState,
    redeemer: TallyAction,
    next_staking_state: StakingState,
    tx_info: TxInfo,
    next_staking_state_output: TxOut,
) -> None:
    """
    Check that the staking state is correctly updated (from the view of the tally contract)
    This means that it is checked whether the voting participation is correctly added or removed.
    It also checks whether the correct amount of governance tokens is locked in the staking contract,
    and that the correct vote nft is minted or burned.
    """
    participation = translate_to_participation(redeemer, previous_tally_state)
    if isinstance(redeemer, AddTallyVote):
        previous_staking_state_input = resolve_sublinear_staking_input(
            tx_info, redeemer.staking_input_index, previous_tally_state
        )
        previous_staking_state = resolve_staking_input_state(
            previous_staking_state_input,
            tx_info,
            redeemer,
            previous_tally_state,
        )
        # Ensure that the stake does not already participate in the vote
        own_reduced_params = reduced_proposal_params(previous_tally_state.params)
        assert (
            len(
                [
                    p
                    for p in previous_staking_state.participations
                    if p.tally_params == own_reduced_params
                ]
            )
            == 0
        ), "Stake already participates in vote"
        # Ensure that the vote is added to the list of votes in the staking state
        desired_next_staking_state = StakingState(
            [participation] + previous_staking_state.participations,
            previous_staking_state.params,
        )
        assert next_staking_state == desired_next_staking_state, (
            "New staking state is incorrect"
        )
        # vote nft is correctly minted
        check_correct_staking_vote_nft_mint(
            redeemer.proposal_index,
            redeemer.weight,
            previous_tally_state.params,
            tx_info,
            next_staking_state_output,
        )
        # staking contract owns enough governance tokens
        assert (
            governance_weight_in_output(
                next_staking_state_output,
                previous_tally_state.params.governance_token,
                previous_tally_state.params.vault_ft_policy,
                previous_tally_state.params.delegation_policy,
                previous_tally_state.params.end_time,
            )
            >= redeemer.weight
        ), "Not enough gov tokens in output"
    elif isinstance(redeemer, RetractTallyVote):
        # Ensure that the corresponding vote nft is burned
        # This is enough because a vote nft can only be obtained by adding a vote
        # A participation in the participation list without a vote nft is not useful
        check_correct_vote_nft_burn(
            redeemer.proposal_index,
            redeemer.weight,
            previous_tally_state,
            tx_info,
        )
    else:
        assert False, "Invalid redeemer"


def resolve_staking_output_state(
    next_staking_output: TxOut, tx_info: TxInfo, tally_state: TallyState
) -> StakingState:
    """
    Resolve the continuing datum of the output that is referenced by the redeemer.
    """
    next_staking_state: StakingState = resolve_datum_unsafe(
        next_staking_output, tx_info
    )
    assert (
        tally_state.params.governance_token
        == next_staking_state.params.governance_token
    ), "Wrong gov token"
    assert (
        tally_state.params.tally_auth_nft == next_staking_state.params.tally_auth_nft
    ), "Wrong auth nft"
    return next_staking_state


def check_valid_tally_update(
    tally: TallyState,
    redeemer: TallyAction,
    previous_tally_state: TallyState,
    next_tally_output: TxOut,
    next_tally_state: TallyState,
) -> None:
    """
    Check that the tally state is correctly updated and may be spent at all
    :param tally:
    :param redeemer:
    :param tx_info:
    :return:
    """
    # tally state is correct
    desired_next_tally_state = construct_new_tally_state(previous_tally_state, redeemer)
    assert next_tally_state == desired_next_tally_state, "New tally state is incorrect"
    # auth nft is not moved out of this tally
    assert token_present_in_output(tally.params.tally_auth_nft, next_tally_output), (
        "Auth NFT missing from given output"
    )
    check_output_reasonably_sized(next_tally_output, next_tally_state)
    # Note: tallies only check that the tally auth nft is attached and otherwise do not enforce any preservation of values.
    # This effectively means that spamming with additional tokens is not possible because the next transaction can freely
    # withdraw the tokens and remove them from the state


def resolve_linear_staking_output(
    tx_info: TxInfo, staking_output_index: int, tally: TallyState
) -> TxOut:
    """
    Resolve the staking output that is referenced by the redeemer.
    Ensures that the staking output is at the staking address.
    Ensures that no other staking outputs are present.
    """

    next_staking_state_output = tx_info.outputs[staking_output_index]
    assert next_staking_state_output.address == tally.params.staking_address, (
        "Staking output is not at the staking address"
    )
    assert (
        len([o for o in tx_info.outputs if o.address == tally.params.staking_address])
        == 1
    ), "More than one staking output"
    return next_staking_state_output


def resolve_linear_input_state(datum: TallyState) -> TallyState:
    """
    Resolve the datum of the input that is referenced by the redeemer.
    """
    # TODO could compare datum with previous_state_input.datum, but maybe not necessary
    return datum


def validator(tally: TallyState, redeemer: TallyAction, context: ScriptContext) -> None:
    """
    Tally State tracker
    Ensures that tallys are correctly updated based on staked funds.
    """
    tx_info = context.tx_info
    purpose = get_spending_purpose(context)
    previous_tally_state_input = resolve_linear_input(
        tx_info, redeemer.tally_input_index, purpose
    )
    previous_tally_state = resolve_linear_input_state(tally)
    next_tally_state_output = resolve_linear_output(
        previous_tally_state_input, tx_info, redeemer.tally_output_index
    )
    next_tally_state = resolve_linear_output_state(next_tally_state_output, tx_info)

    # Ensure that at most one staking input is present so that no additional staking positions
    # can improperly retract votes (0 inputs is ok, this is a staking creation upon vote)
    assert (
        len(
            [
                o
                for o in tx_info.inputs
                if o.resolved.address == tally.params.staking_address
            ]
        )
        <= 1
    ), "More than one staking input"
    # There should also not be more than one staking output for the same reason
    next_staking_state_output = resolve_linear_staking_output(
        tx_info, redeemer.staking_output_index, tally
    )
    next_staking_state = resolve_staking_output_state(
        next_staking_state_output, tx_info, previous_tally_state
    )

    # check that the vote is not over yet
    assert not vote_has_ended(tally.params.end_time, tx_info.valid_range), (
        "Vote has ended"
    )

    # ensure the tally state is correctly updated
    check_valid_tally_update(
        tally,
        redeemer,
        previous_tally_state,
        next_tally_state_output,
        next_tally_state,
    )

    # ensure that the staking state is correctly updated
    check_valid_staking_update(
        previous_tally_state,
        redeemer,
        next_staking_state,
        tx_info,
        next_staking_state_output,
    )
