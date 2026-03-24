"""
The governance state contract.
This contract maintains the state of a governance thread and allows for the creation of new tally proposals.
A governance thread is authenticated by the presence of a governance nft along the UTxO holding the state as datum.

This contract is intended to have mints with these contracts:
- tally/tally_auth_nft: Mints 1 matching the attached Governance State NFT during Tally Creation
- gov_state/gov_state_nft: Mints 1 for the new sub-DAO governance thread during sub-DAO creation

Outputs of this contract may go to:
- tally/tally (1 at most for the creation of new tally states)
- gov_state/gov_state (1 at most for the creation of new tally states)
- Any upgraded governance state contract (1 at most for the upgrade of the governance state contract)
- A new sub-DAO governance state contract (1 at most for sub-DAO creation)

NFTs present at outputs of this contract:
- tally/tally_auth_nft (1 at most for the created tally)
- gov_state/gov_state_nft (1 at most for the continuing output)

Reference inputs:
- tally/tally (any number for referencing a winning proposal that indicates a governance upgrade or sub-DAO creation)

It is not allowed to spend several governance states in a single transaction.
"""

from muesliswap_onchain_governance.onchain.util import *
from muesliswap_onchain_governance.onchain.gov_state.gov_state_types import *


def resolve_linear_output_state(
    next_state_output: TxOut, tx_info: TxInfo
) -> GovStateDatum:
    """
    Resolve the continuing datum of the output that is referenced by the redeemer.
    """
    next_state: GovStateDatum = resolve_datum_unsafe(next_state_output, tx_info)
    return next_state


def resolve_linear_tally_output(
    tx_info: TxInfo, tally_output_index: int, gov_state: GovStateParams
) -> TxOut:
    """
    Resolve the tally output and ensure there is only one output to the tally address
    """
    tally_output = tx_info.outputs[tally_output_index]
    tally_address = tally_output.address
    assert tally_address == gov_state.tally_address, (
        "Tally output is not at the tally address"
    )
    assert (
        len([o for o in tx_info.outputs if o.address == gov_state.tally_address]) == 1
    ), "More than one output to the tally address"
    return tally_output


def add_milliseconds_to_posix_time(
    posix_time: POSIXTime, milliseconds: int
) -> POSIXTime:
    """
    Add milliseconds to a POSIXTime
    """
    return POSIXTime(milliseconds + posix_time)


def add_milliseconds_to_extended_posix_time(
    posix_time: ExtendedPOSIXTime, milliseconds: int
) -> ExtendedPOSIXTime:
    """
    Add milliseconds to an ExtendedPOSIXTime
    """
    if isinstance(posix_time, FinitePOSIXTime):
        return FinitePOSIXTime(
            add_milliseconds_to_posix_time(posix_time.time, milliseconds)
        )
    elif isinstance(posix_time, NegInfPOSIXTime):
        return NegInfPOSIXTime()
    elif isinstance(posix_time, PosInfPOSIXTime):
        return PosInfPOSIXTime()
    else:
        assert False, "Invalid ExtendedPOSIXTime"
        return NegInfPOSIXTime()


def ext_after_ext(a: ExtendedPOSIXTime, b: ExtendedPOSIXTime) -> bool:
    """
    Check if a is after b, i.e b -------------- a
    """
    return compare_extended(a, b) == -1


def validate_new_tally(
    state: GovStateDatum, input: TxOut, redeemer: CreateNewTally, tx_info: TxInfo
):
    """
    Validate a new tally proposal
    This ensures that the created proposal has the correct parameters and is created at the right address
    Further it ensures that the creator of the proposal locks/pays the correct amount of fee for creation
    """

    params = state.params
    new_proposal_id = increment_proposal_id(state.last_proposal_id)
    tally_auth_nft = Token(
        params.tally_auth_nft_policy, params.gov_state_nft.token_name
    )

    next_gov_state_output = resolve_linear_output(
        input, tx_info, redeemer.gov_state_output_index
    )
    next_gov_state = resolve_linear_output_state(next_gov_state_output, tx_info)
    # ensure that the gov state is not changed except for the last_proposal_id
    desired_new_gov_state = GovStateDatum(
        params,
        new_proposal_id,
    )
    assert desired_new_gov_state == next_gov_state, (
        "Gov state must not change except for the last_proposal_id"
    )
    # ensure that no tokens are being removed from the gov state
    # and no tokens are added except for the existing ones (only ada increase is ok)
    check_preserves_value(input, next_gov_state_output)
    # ensure that the new tally is created at the correct address
    # and no other tally is created
    tally_output = resolve_linear_tally_output(
        tx_info, redeemer.tally_output_index, params
    )
    # ensure that the new tally has an auth nft (and only one)
    # and that no further token is minted (this duplicates some tally auth nft logic just to be safe)
    check_mint_exactly_one_to_address(tx_info.mint, tally_auth_nft, tally_output)
    # ensure that the tally state is correct
    tally_state: TallyState = resolve_datum_unsafe(tally_output, tx_info)

    tally_state_params = tally_state.params
    assert tally_state_params.quorum >= params.min_quorum, "Quorum too low"
    assert ge_fraction(
        tally_state_params.winning_threshold, params.min_winning_threshold
    ), "Winning threshold too low"

    tx_validity_end = tx_info.valid_range.upper_bound.limit
    assert ext_after_ext(
        tally_state_params.end_time,
        add_milliseconds_to_extended_posix_time(
            tx_validity_end, params.min_proposal_duration
        ),
    ), "Proposal duration too short or validity end too late"
    assert tally_state_params.proposal_id == new_proposal_id, "Proposal ID incorrect"
    assert tally_state_params.tally_auth_nft == tally_auth_nft, (
        "AuthNFT must be the same as in the gov state"
    )
    assert (
        tally_state_params.staking_vote_nft_policy == params.staking_vote_nft_policy
    ), "VoteNFT policy must be the same as in the gov state"
    assert tally_state_params.staking_address == params.staking_address, (
        "Staking address must be the same as in the gov state"
    )
    assert tally_state_params.governance_token == params.governance_token, (
        "Governance token must be the same as in the gov state"
    )
    assert tally_state_params.vault_ft_policy == params.vault_ft_policy, (
        "Vault FT policy must be the same as in the gov state"
    )

    assert tally_state_params.delegation_policy == params.delegation_policy, (
        "Delegation policy must be the same as in the gov state"
    )

    assert tally_state_params.proposals[0] == Nothing(), (
        "Tally must offer a No-Op proposal as the first proposal"
    )
    assert all([v == 0 for v in tally_state.votes]), (
        "Tally state must not have any votes"
    )
    assert len(tally_state.votes) == len(tally_state.params.proposals), (
        "Length of votes must match length of proposals"
    )


def validate_update_gov_state(
    state: GovStateDatum,
    gov_state_input: TxOut,
    redeemer: UpgradeGovState,
    tx_info: TxInfo,
):
    """
    Validate an update to the governance state
    This ensures that the update is backed by a valid tally result at the governance address.
    """
    params = state.params
    tally_result = winning_tally_result(
        redeemer.tally_input_index,
        Token(params.tally_auth_nft_policy, params.gov_state_nft.token_name),
        tx_info,
        state.params.latest_applied_proposal_id,
        True,
    )
    winning_proposal: GovStateUpdateParams = tally_result.winning_proposal
    # check that the winning proposal is actually a gov state update
    check_integrity(winning_proposal)
    # the winning proposal is the params and address for the new gov state
    # check that the new gov state is correct
    desired_new_gov_state = GovStateDatum(
        winning_proposal.params,
        state.last_proposal_id,
    )
    new_gov_state_output = tx_info.outputs[redeemer.gov_state_output_index]
    assert new_gov_state_output.address == winning_proposal.address, (
        "Gov state output is not at the correct address"
    )
    new_gov_state: GovStateDatum = resolve_datum_unsafe(new_gov_state_output, tx_info)
    assert desired_new_gov_state == new_gov_state, (
        "Gov state must be updated to the winning proposal"
    )

    # check that the value is preserved and no additional tokens are attached
    # the only possible addition is ada
    check_preserves_value(gov_state_input, new_gov_state_output)

    # check that no tally auth nft is minted during this transaction
    assert (
        len(tx_info.mint.get(state.params.tally_auth_nft_policy, EMTPY_TOKENNAME_DICT))
        == 0
    ), "No AuthNFTs must be minted during this transaction"


def validate_create_sub_dao(
    state: GovStateDatum,
    gov_state_input: TxOut,
    redeemer: CreateSubDao,
    tx_info: TxInfo,
):
    """
    Validate the creation of a new sub-DAO governance thread (parent side).

    This function validates only what gov_state.py uniquely needs to check:
      - The winning tally is valid (to obtain proposal_id for advancing latest_applied_proposal_id).
      - The parent state output is correct (datum, value).
      - The sub-DAO NFT is minted to the sub-DAO output (proving gov_state_nft.py ran its
        full sub-DAO validation: parent references, initial datum, address-differs check).

    Sub-DAO-specific invariants (parent_gov_nft correctness, initial datum, address check)
    are validated by gov_state_nft.py to keep this contract small.
    """
    params = state.params

    tally_result = winning_tally_result(
        redeemer.tally_input_index,
        Token(params.tally_auth_nft_policy, params.gov_state_nft.token_name),
        tx_info,
        params.latest_applied_proposal_id,
        True,
    )
    winning_proposal: CreateSubDaoParams = tally_result.winning_proposal
    check_integrity(winning_proposal)

    # parent state continues with only latest_applied_proposal_id updated
    updated_parent_params = GovStateParams(
        params.tally_address,
        params.staking_address,
        params.governance_token,
        params.vault_ft_policy,
        params.delegation_policy,
        params.min_quorum,
        params.min_winning_threshold,
        params.min_proposal_duration,
        params.gov_state_nft,
        params.tally_auth_nft_policy,
        params.staking_vote_nft_policy,
        tally_result.proposal_id,
        params.parent_gov_nft,
        params.parent_tally_auth_nft_policy,
        params.latest_applied_parent_proposal_id,
    )
    desired_parent_state = GovStateDatum(updated_parent_params, state.last_proposal_id)
    parent_output = resolve_linear_output(
        gov_state_input, tx_info, redeemer.gov_state_output_index
    )
    actual_parent_state: GovStateDatum = resolve_linear_output_state(
        parent_output, tx_info
    )
    assert desired_parent_state == actual_parent_state, (
        "Parent state must be preserved except for latest_applied_proposal_id"
    )
    check_preserves_value(gov_state_input, parent_output)

    # The sub-DAO NFT being minted proves gov_state_nft.py ran and validated
    # all sub-DAO-specific invariants (correct parent refs, initial datum, address).
    sub_dao_output = tx_info.outputs[redeemer.sub_dao_output_index]
    check_mint_exactly_one_to_address(
        tx_info.mint, winning_proposal.params.gov_state_nft, sub_dao_output
    )

    # no parent tally auth NFT may be minted in this transaction
    assert (
        len(tx_info.mint.get(params.tally_auth_nft_policy, EMTPY_TOKENNAME_DICT)) == 0
    ), "No parent AuthNFTs must be minted during sub-DAO creation"



def resolve_linear_input_state(datum: GovStateDatum) -> GovStateDatum:
    """
    Resolve the datum of the input that is referenced by the redeemer.
    """
    return datum


def validator(
    state: GovStateDatum, redeemer: GovStateRedeemer, context: ScriptContext
) -> None:
    """
    GovState Contract.

    Ensures that new tally proposals are only submitted with the correct parameters
    defined in the governance state.
    The only other operation allowed is to update the governance state.
    """
    purpose = get_spending_purpose(context)
    tx_info = context.tx_info

    gov_state_input = resolve_linear_input(
        tx_info, redeemer.gov_state_input_index, purpose
    )
    gov_state = resolve_linear_input_state(state)

    if isinstance(redeemer, CreateNewTally):
        validate_new_tally(gov_state, gov_state_input, redeemer, tx_info)
    elif isinstance(redeemer, UpgradeGovState):
        validate_update_gov_state(state, gov_state_input, redeemer, tx_info)
    elif isinstance(redeemer, CreateSubDao):
        validate_create_sub_dao(state, gov_state_input, redeemer, tx_info)
    else:
        assert False, "Invalid redeemer"
