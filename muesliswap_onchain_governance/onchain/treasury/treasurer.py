"""
The treasurer contract.

This contract maintains state over past payouts of the treasury.
Funds of the treasury remain at treasury/value_store
Consumer of the tally states.
Releases specified funds to the specified address if the tally is successful.

This contract is intended to be have inputs from these contracts:
- treasury/treasurer (1, the previous state)
- treasury/value_store (n, storing funds handled by the treasurer)

This contract is intended to have mints with these contracts:
- None

Outputs of this contract may go to:
- treasury/treasurer (1, continuation of above)
- treasury/value_store (<= n, storing remaining funds not paid out in this transaction)

Relevant NFTs present at outputs of this contract:
- treasury/treasurer_nft (1, authenticates the treasurer thread akin to the governance thread)

Reference inputs:
- tally/tally (1, referencing a winning proposal that indicates a governance upgrade)

It is not allowed to spend several treasurer states in a single transaction.
"""

from muesliswap_onchain_governance.onchain.treasury.util import *


@dataclass
class PayoutFunds(PlutusData):
    """
    Redeemer for the treasurer contract to issue a payout of funds.
    """

    CONSTR_ID = 2
    treasurer_input_index: int
    treasurer_output_index: int
    next_proposal_id: ProposalId
    payout_index: int
    # the index of the reference input with the tally
    tally_input_index: int


@dataclass
class FundPayoutParams(PlutusData):
    """
    VOTE OUTCOME
    A possible vote outcome specifying who will receive funds from the treasury
    """

    CONSTR_ID = 102
    output: TxOut


@dataclass
class ConsolidateFunds(PlutusData):
    """
    Consolidate multiple UTxOs into fewer ones.
    This may be necessary when the treasury funds are split over too many UTxOs for a payout to be possible.
    The person who executes this may not obtain any funds for doing a consolidation.
    """

    CONSTR_ID = 3
    treasurer_input_index: int
    treasurer_output_index: int
    # the last_applied_proposal_id of the treasurer state, which must be preserved
    next_proposal_id: ProposalId


TreasurerRedeemer = Union[PayoutFunds, ConsolidateFunds]


def resolve_input_state(treasurer_state: TreasurerState) -> TreasurerState:
    return treasurer_state


def resolve_linear_output_state(
    next_state_output: TxOut, tx_info: TxInfo
) -> TreasurerState:
    """
    Resolve the continuing datum of the output that is referenced by the redeemer.
    """
    next_state: TreasurerState = resolve_datum_unsafe(next_state_output, tx_info)
    return next_state


def check_payout_executed_correctly(
    redeemer: TreasurerRedeemer,
    previous_treasurer_state: TreasurerState,
    tx_info: TxInfo,
) -> Value:
    """
    Check that the payout was performed correctly (if any)
    Returns the intended payout amount (i.e. the maximum that may be withdrawn from the treasury)
    """
    if isinstance(redeemer, ConsolidateFunds):
        assert (
            redeemer.next_proposal_id
            == previous_treasurer_state.last_applied_proposal_id
        ), "Changed the proposal id for consolidation"
        return EMPTY_VALUE_DICT
    elif isinstance(redeemer, PayoutFunds):
        # obtain the tally result that justifies the payout
        tally_result = winning_tally_result(
            redeemer.tally_input_index,
            previous_treasurer_state.params.auth_nft,
            tx_info,
            previous_treasurer_state.last_applied_proposal_id,
            True,
        )
        assert (
            tally_result.proposal_id == redeemer.next_proposal_id
        ), "Incorrect update of the proposal id"
        fund_payout_params: FundPayoutParams = tally_result.winning_proposal
        # check that the winning proposal is actually a fund payout
        check_integrity(fund_payout_params)

        fund_payout_params_output = fund_payout_params.output
        payout_output = tx_info.outputs[redeemer.payout_index]

        ## Checking that the correct funds are sent to the correct person
        # check that the receiver of the funds is correct
        assert (
            payout_output.address == fund_payout_params_output.address
        ), "Payout address is incorrect"
        # check that the amount of the payout is correct
        check_greater_or_equal_value(
            payout_output.value, fund_payout_params_output.value
        )
        # check that the datum of the payout is adhered to
        assert (
            payout_output.datum == fund_payout_params_output.datum
        ), "Payout datum is incorrect"
        # check that the reference script is correct
        assert (
            payout_output.reference_script == fund_payout_params_output.reference_script
        ), "Payout reference script is incorrect"
        # check that the output is not too big
        check_output_reasonably_sized(
            payout_output, resolve_datum(payout_output, tx_info)
        )
        # important: return the intended output amount, not the actual one (which may be larger and hence drain the treasury)
        return fund_payout_params_output.value
    else:
        assert False, "Invalid redeemer"
        return EMPTY_VALUE_DICT


def check_treasurer_state_updated_correctly(
    previous_treasurer_state: TreasurerState,
    new_proposal_id: ProposalId,
    next_treasurer_state: TreasurerState,
    previous_treasurer_state_input: TxOut,
    next_treasurer_state_output: TxOut,
):
    desired_next_state = TreasurerState(
        previous_treasurer_state.params,
        new_proposal_id,
    )
    assert (
        desired_next_state == next_treasurer_state
    ), "New treasurer state is incorrect"
    check_preserves_value(previous_treasurer_state_input, next_treasurer_state_output)
    check_output_reasonably_sized(next_treasurer_state_output, next_treasurer_state)


def check_only_treasurer_and_value_store_contracts(
    tx_info: TxInfo, number_value_store_inputs: int
):
    """
    Check that the only involved contracts are the treasurer and the value store
    This covers inputs, withdrawals, and mints
    :param tx_info:
    :param params:
    :return:
    """
    assert len(tx_info.redeemers) == number_value_store_inputs + 1, "Too many redeemers"


def check_at_most_n_token(value: Value, n: int) -> None:
    total_tokens = sum([len(d.items()) for d in value.values()])
    assert total_tokens <= n, "value contains too many tokens"


def check_fund_distribution_correct(
    previous_treasurer_state_params: TreasurerParams, tx_info: TxInfo, payout: Value
):
    valid_value_store_state = ValueStoreState(
        previous_treasurer_state_params.treasurer_nft,
    )
    value_store_inputs = [
        txi.resolved
        for txi in tx_info.inputs
        if txi.resolved.address == previous_treasurer_state_params.value_store
    ]
    # make sure that no funds are spent that do not belong to this treasurer
    for txi in value_store_inputs:
        assert (
            resolve_datum_unsafe(txi, tx_info) == valid_value_store_state
        ), "Spending incorrect value store funds"
    value_store_outputs = [
        txo
        for txo in tx_info.outputs
        if txo.address == previous_treasurer_state_params.value_store
        # this ensures that the value store state is preserved
        and resolve_datum_unsafe(txo, tx_info) == valid_value_store_state
    ]
    # make sure that the value store utxos are not unncessarily split
    assert len(value_store_inputs) >= len(
        value_store_outputs
    ), "Creating additional value store outputs is not allowed"

    # check that only the amount of funds that are supposed to be released are released
    previous_value_store_value = total_value(value_store_inputs)
    next_value_store_value = total_value(value_store_outputs)
    desired_new_value_store_value = subtract_value(previous_value_store_value, payout)
    check_greater_or_equal_value(next_value_store_value, desired_new_value_store_value)
    for txo in value_store_outputs:
        # check that all outputs are reasonably sized
        check_output_reasonably_sized(txo, valid_value_store_state)
        # check that none of the outputs contains more than 5 tokens
        check_at_most_n_token(txo.value, 5)

    # check that no other contracts are satisfied by this transaction
    check_only_treasurer_and_value_store_contracts(tx_info, len(value_store_inputs))


def validator(
    treasurer_state: TreasurerState, redeemer: TreasurerRedeemer, context: ScriptContext
) -> None:
    tx_info = context.tx_info
    purpose = get_spending_purpose(context)

    previous_treasurer_state_input = resolve_linear_input(
        tx_info, redeemer.treasurer_input_index, purpose
    )
    previous_treasurer_state = resolve_input_state(treasurer_state)
    # check that the treasurer state is correct
    assert token_present_in_output(
        previous_treasurer_state.params.treasurer_nft, previous_treasurer_state_input
    ), "Unique treasurer NFT is not present in the treasurer input"

    next_treasurer_state_output = resolve_linear_output(
        previous_treasurer_state_input, tx_info, redeemer.treasurer_output_index
    )
    next_treasurer_state = resolve_linear_output_state(
        next_treasurer_state_output, tx_info
    )

    ## Checking that the correct funds are sent to the correct person
    # check that the receiver of the funds is correct
    payout_amount = check_payout_executed_correctly(
        redeemer, previous_treasurer_state, tx_info
    )

    ## Checking that the treasurer state is updated correctly
    check_treasurer_state_updated_correctly(
        previous_treasurer_state,
        redeemer.next_proposal_id,
        next_treasurer_state,
        previous_treasurer_state_input,
        next_treasurer_state_output,
    )

    ## Checking that the value store state is updated correctly
    check_fund_distribution_correct(
        previous_treasurer_state.params, tx_info, payout_amount
    )
