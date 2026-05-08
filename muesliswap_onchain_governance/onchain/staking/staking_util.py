"""
Utils for the staking contracts. This is not a contract.
"""

from opshin.std.math import *

from muesliswap_onchain_governance.onchain.util import *


@dataclass
class AddVote(PlutusData):
    """
    Redeemer for the staking contract to add a vote to the tally.

    Adds a vote to the tally and tracks
    the participation in the staking state
    """

    CONSTR_ID = 1
    state_input_index: int
    state_output_index: int
    participation: Participation


@dataclass
class RetractVote(PlutusData):
    """
    Redeemer for the staking contract to retract a vote from the tally.

    Removes the vote from the tally and
    removes the participation from the staking state
    """

    CONSTR_ID = 2
    state_input_index: int
    state_output_index: int
    participation_index: int
    tally_input_index: int


@dataclass
class WithdrawFunds(PlutusData):
    """
    Redeemer for the staking contract to withdraw funds from the staking state.

    Removes funds from the staking state
    """

    CONSTR_ID = 3
    state_input_index: int
    # TODO allow Optional[BoxedInteger] to allow removing the state
    state_output_index: int


@dataclass
class AddFunds(PlutusData):
    """
    Adds funds to the staking state
    """

    CONSTR_ID = 4
    state_input_index: int
    state_output_index: int


@dataclass
class FilterOutdatedVotes(PlutusData):
    """
    Removes outdated participations
    """

    CONSTR_ID = 5
    state_input_index: int
    state_output_index: int


@dataclass
class ClaimReputation(PlutusData):
    """
    Removes one ended participation after reputation was minted for it.
    """

    CONSTR_ID = 6
    state_input_index: int
    state_output_index: int
    participation_index: int


StakingRedeemer = Union[
    AddVote, RetractVote, WithdrawFunds, AddFunds, FilterOutdatedVotes, ClaimReputation
]


def construct_desired_output_staking_state(
    previous_state: StakingState, redeemer: StakingRedeemer, tx_info: TxInfo
) -> StakingState:
    if isinstance(redeemer, AddVote):
        # Ensure that list is only extended
        desired_next_state_participation = [
            redeemer.participation
        ] + previous_state.participations
    elif isinstance(redeemer, RetractVote):
        # Ensure that only one element is removed
        # And that the auth nft is unlocked == the tally contract approves the transaction
        desired_next_state_participation = remove_participation_at_index(
            previous_state.participations, redeemer.participation_index
        )
        assert token_present_in_output(
            previous_state.params.tally_auth_nft,
            tx_info.inputs[redeemer.tally_input_index].resolved,
        ), "Auth NFT was not spent in specified tally index input"
    elif isinstance(redeemer, FilterOutdatedVotes):
        desired_next_state_participation = [
            p
            for p in previous_state.participations
            if not vote_has_ended(p.tally_params.end_time, tx_info.valid_range)
        ]
    elif isinstance(redeemer, ClaimReputation):
        participation = previous_state.participations[redeemer.participation_index]
        assert vote_has_ended(
            participation.tally_params.end_time, tx_info.valid_range
        ), "Participation has not ended"
        desired_next_state_participation = remove_participation_at_index(
            previous_state.participations, redeemer.participation_index
        )
    elif isinstance(redeemer, WithdrawFunds) or isinstance(redeemer, AddFunds):
        desired_next_state_participation = previous_state.participations
    else:
        assert False, "Invalid redeemer"

    next_state = StakingState(
        desired_next_state_participation,
        previous_state.params,
    )

    return next_state


#### Permission NFT


@dataclass
class DelegatedAddVote(PlutusData):
    """
    Allows a third party to add a vote to the tally specified by the participation
    """

    CONSTR_ID = 1
    participation: Participation


@dataclass
class DelegatedRetractVote(PlutusData):
    """
    Allows a third party to retract a vote from the tally specified by the participation

    Note: One must not use the index here because the index might change when the staking state is updated
    """

    CONSTR_ID = 2
    participation: Participation


# Staking redeemers for which the user can give a third party the right to perform the operation
DelegatableStakingRedeemer = Union[DelegatedAddVote, DelegatedRetractVote]


@dataclass
class VotePermissionNFTParams(PlutusData):
    """
    Parameters for the permission NFT
    """

    CONSTR_ID = 1
    owner: Address
    redeemer: DelegatableStakingRedeemer


def vote_permission_nft_token_name(
    params: VotePermissionNFTParams,
) -> TokenName:
    """
    This is the exact same as the datum hash of the redeemer to aid looking up the datum in common chain indexers.
    """
    return blake2b_256(params.to_cbor())


@dataclass
class Weight(PlutusData):
    valid_until: int
    weight: int


def variable_governance_weight_in_output_list(
    output: TxOut,
    vault_ft_policy: PolicyId,
    delegation_policy: PolicyId,
    reputation_policy: PolicyId,
    owner: Address,
) -> List[Weight]:
    """
    Returns a list of how much valid governance tokens are in the output and until when they are valid
    """
    vault_proxy_tokens: List[Weight] = []
    for tokenname, amount in output.value.get(
        vault_ft_policy, EMTPY_TOKENNAME_DICT
    ).items():
        vault_proxy_tokens = [
            Weight(unsigned_int_from_bytes_big(tokenname), amount)
        ] + vault_proxy_tokens

    for tokenname, amount in output.value.get(
        delegation_policy, EMTPY_TOKENNAME_DICT
    ).items():
        vault_proxy_tokens = [
            Weight(unsigned_int_from_bytes_big(tokenname), amount)
        ] + vault_proxy_tokens
    reputation_amount = output.value.get(reputation_policy, EMTPY_TOKENNAME_DICT).get(
        reputation_token_name(owner), 0
    )
    if reputation_amount > 0:
        vault_proxy_tokens = [
            Weight(9223372036854775807, reputation_amount)
        ] + vault_proxy_tokens
    return vault_proxy_tokens


def variable_governance_weight_in_output(
    output: TxOut,
    vault_ft_policy: PolicyId,
    delegation_policy: PolicyId,
    reputation_policy: PolicyId,
    owner: Address,
    tally_end: ExtendedPOSIXTime,
) -> int:
    """
    Returns the weight of variable governance tokens in the output (vault ft tokens)
    based on vault ft tokens that are valid at the tally end time
    """
    vault_proxy_tokens = 0
    if isinstance(tally_end, FinitePOSIXTime):
        tally_end_time = tally_end.time
        for tokenname, amount in output.value.get(
            vault_ft_policy, EMTPY_TOKENNAME_DICT
        ).items():
            if unsigned_int_from_bytes_big(tokenname) >= tally_end_time:
                vault_proxy_tokens += amount

        for tokenname, amount in output.value.get(
            delegation_policy, EMTPY_TOKENNAME_DICT
        ).items():
            if unsigned_int_from_bytes_big(tokenname) >= tally_end_time:
                vault_proxy_tokens += amount
    vault_proxy_tokens += output.value.get(reputation_policy, EMTPY_TOKENNAME_DICT).get(
        reputation_token_name(owner), 0
    )
    return vault_proxy_tokens


def governance_weight_in_output(
    output: TxOut,
    governance_token: Token,
    vault_ft_policy: PolicyId,
    delegation_policy: PolicyId,
    reputation_policy: PolicyId,
    owner: Address,
    tally_end: ExtendedPOSIXTime,
) -> int:
    """
    Returns the weight of governance tokens in the output
    and also adds the weight of the governance tokens that are locked in the vault and will be unlocked after the end of the tally
    """
    governance_token_amount = amount_of_token_in_output(governance_token, output)
    proxy_token_amount = variable_governance_weight_in_output(
        output, vault_ft_policy, delegation_policy, reputation_policy, owner, tally_end
    )
    return governance_token_amount + proxy_token_amount
