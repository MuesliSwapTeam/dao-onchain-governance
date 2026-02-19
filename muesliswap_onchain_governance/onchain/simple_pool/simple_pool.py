"""
A simple AMM pool contract that allows users to add and remove liquidity and swap tokens.
DISCLAIMER: This is a simple example to demonstrate onchain based contract upgradeability and should not be used in production.
"""

from muesliswap_onchain_governance.onchain.simple_pool.classes import *


@dataclass
class SwapAsset(PlutusData):
    CONSTR_ID = 1
    license_input_index: int
    pool_input_index: int
    pool_output_index: int
    swap_token: Token
    swap_token_amount: int


@dataclass
class AddLiquidity(PlutusData):
    CONSTR_ID = 2
    license_input_index: int
    pool_input_index: int
    pool_output_index: int
    deposit_token_a: int


@dataclass
class RemoveLiquidity(PlutusData):
    CONSTR_ID = 3
    license_input_index: int
    pool_input_index: int
    pool_output_index: int
    burn_liquidity_token: int


@dataclass
class PoolUpgrade(PlutusData):
    CONSTR_ID = 4
    pool_input_index: int
    pool_output_index: int
    tally_ref_index: int


PoolAction = Union[AddLiquidity, RemoveLiquidity, SwapAsset, PoolUpgrade]


def license_validity_from_name(license_name: TokenName) -> POSIXTime:
    """
    Extracts the validity time from a license name
    """
    return unsigned_int_from_bytes_big(license_name[16:32])


def check_valid_license_present(
    license_input_index: int, tx_info: TxInfo, license_policy_id: PolicyId
):
    """
    Checks that a valid license is present in the transaction
    """
    license_input = tx_info.inputs[license_input_index].resolved
    # note: no other licenses should be present in the input to ensure that this passes
    license_nft_name = license_input.value[license_policy_id].keys()[0]
    license_expiry_date = license_validity_from_name(license_nft_name)
    assert before_ext(tx_info.valid_range, FinitePOSIXTime(license_expiry_date)), (
        "License is expired"
    )


def check_change_liquidity(
    datum: PoolState,
    redeemer: Union[AddLiquidity, RemoveLiquidity],
    context: ScriptContext,
    own_input_info: TxInInfo,
    own_output: TxOut,
) -> None:
    """
    Validates that the deposit of liquidity is done correctly
    """
    own_input = own_input_info.resolved

    # compute expected added liquidity
    if isinstance(redeemer, AddLiquidity):
        # Follows theorem 2 in https://github.com/runtimeverification/verified-smart-contracts/blob/uniswap/uniswap/x-y-k.pdf
        delta_token_a = redeemer.deposit_token_a
        assert delta_token_a > 0, "Liquidity change must be positive"

        pool_value_token_a = amount_of_token_in_value(
            datum.im_pool_params.token_a, own_input.value
        )
        pool_value_token_b = amount_of_token_in_value(
            datum.im_pool_params.token_b, own_input.value
        )
        alpha = Fraction(delta_token_a, pool_value_token_a)
        expected_deposit_token_a = delta_token_a
        expected_deposit_token_b = (
            floor_fraction(mul_fraction(alpha, Fraction(pool_value_token_b, 1))) + 1
        )
        expected_minted_lp_tokens = floor_fraction(
            mul_fraction(Fraction(datum.global_liquidity_tokens, 1), alpha)
        )
    else:
        # Follows definition 3 in https://github.com/runtimeverification/verified-smart-contracts/blob/uniswap/uniswap/x-y-k.pdf
        delta_liquidity_token = redeemer.burn_liquidity_token
        assert delta_liquidity_token < 0, "Liquidity change must be negative"

        pool_value_token_a = amount_of_token_in_value(
            datum.im_pool_params.token_a, own_input.value
        )
        pool_value_token_b = amount_of_token_in_value(
            datum.im_pool_params.token_b, own_input.value
        )
        alpha = Fraction(delta_liquidity_token, datum.global_liquidity_tokens)
        expected_deposit_token_a = ceil_fraction(
            mul_fraction(alpha, Fraction(pool_value_token_a, 1))
        )
        expected_deposit_token_b = ceil_fraction(
            mul_fraction(alpha, Fraction(pool_value_token_b, 1))
        )
        expected_minted_lp_tokens = delta_liquidity_token

    # check addition of exactly the right amount of liquidity
    expected_new_global_liquidity_tokens = (
        datum.global_liquidity_tokens + expected_minted_lp_tokens
    )
    check_mint_exactly_n_with_name(
        context.tx_info.mint,
        expected_minted_lp_tokens,
        datum.im_pool_params.pool_lp_token.policy_id,
        datum.im_pool_params.pool_lp_token.token_name,
    )

    previous_value = own_input.value
    new_value = own_output.value
    expected_new_value = add_value(
        previous_value,
        {
            datum.im_pool_params.token_a.policy_id: {
                datum.im_pool_params.token_a.token_name: expected_deposit_token_a
            },
            datum.im_pool_params.token_b.policy_id: {
                datum.im_pool_params.token_b.token_name: expected_deposit_token_b
            },
        },
    )
    check_greater_or_equal_value(new_value, expected_new_value)

    # check that the new pool state is correct
    assert own_output.address == own_input.address, (
        "Liquidity change must not change address"
    )
    assert own_output.datum == SomeOutputDatum(
        PoolState(
            datum.im_pool_params,
            datum.up_pool_params,
            expected_new_global_liquidity_tokens,
            own_input_info.out_ref,
        )
    ), "Pool state must reflect new liquidity"


def check_swap(
    datum: PoolState,
    redeemer: SwapAsset,
    context: ScriptContext,
    own_input_info: TxInInfo,
    own_output: TxOut,
) -> None:
    """
    Validates that the swapping of tokens is done correctly
    """
    own_input = own_input_info.resolved

    # compute expected added liquidity
    delta_token = redeemer.swap_token_amount
    assert delta_token > 0, "Swap amount must be positive"

    pool_value_token_a = amount_of_token_in_value(
        datum.im_pool_params.token_a, own_input.value
    )
    pool_value_token_b = amount_of_token_in_value(
        datum.im_pool_params.token_b, own_input.value
    )
    if redeemer.swap_token == datum.im_pool_params.token_a:
        # need to deposit token a plus pool fee
        expected_change_token_a = delta_token + ceil_fraction(
            mul_fraction(datum.up_pool_params.fee, Fraction(delta_token, 1))
        )
        expected_change_token_b = -floor_fraction(
            sub_fraction(
                Fraction(pool_value_token_b, 1),
                Fraction(
                    pool_value_token_a * pool_value_token_b,
                    pool_value_token_a + delta_token,
                ),
            )
        )
    else:
        # need to deposit token b plus pool fee
        expected_change_token_b = delta_token + ceil_fraction(
            mul_fraction(datum.up_pool_params.fee, Fraction(delta_token, 1))
        )
        expected_change_token_a = -floor_fraction(
            sub_fraction(
                Fraction(pool_value_token_a, 1),
                Fraction(
                    pool_value_token_a * pool_value_token_b,
                    pool_value_token_b + delta_token,
                ),
            )
        )

    # no liquidity tokens must be minted
    check_mint_exactly_nothing(
        context.tx_info.mint,
        datum.im_pool_params.pool_lp_token.policy_id,
        datum.im_pool_params.pool_lp_token.token_name,
    )

    previous_value = own_input.value
    new_value = own_output.value
    expected_new_value = add_value(
        previous_value,
        {
            datum.im_pool_params.token_a.policy_id: {
                datum.im_pool_params.token_a.token_name: expected_change_token_a
            },
            datum.im_pool_params.token_b.policy_id: {
                datum.im_pool_params.token_b.token_name: expected_change_token_b
            },
        },
    )
    check_greater_or_equal_value(new_value, expected_new_value)

    # check that the new pool state is correct
    assert own_output.address == own_input.address, (
        "Liquidity change must not change address"
    )
    assert own_output.datum == SomeOutputDatum(
        PoolState(
            datum.im_pool_params,
            datum.up_pool_params,
            datum.global_liquidity_tokens,
            own_input_info.out_ref,
        )
    ), "Pool state must not change except for output reference"


def check_upgrade(
    datum: PoolState,
    redeemer: PoolUpgrade,
    context: ScriptContext,
    own_input_info: TxInInfo,
    own_output: TxOut,
) -> None:
    """
    Validates that a tally justifies the upgrade and that the upgrade is done correctly
    """
    # no liquidity tokens must be minted
    check_mint_exactly_nothing(
        context.tx_info.mint,
        datum.im_pool_params.pool_lp_token.policy_id,
        datum.im_pool_params.pool_lp_token.token_name,
    )
    # obtain the tally result that justifies the payout
    tally_result = winning_tally_result(
        redeemer.tally_ref_index,
        datum.up_pool_params.auth_nft,
        context.tx_info,
        datum.up_pool_params.last_applied_proposal_id,
        True,
    )
    pool_upgrade_params: PoolUpgradeParams = tally_result.winning_proposal
    # check that the winning proposal is actually a pool upgrade
    check_integrity(pool_upgrade_params)

    # check that this specific pool is being upgraded
    raw_old_pool_nft = pool_upgrade_params.old_pool_nft
    if isinstance(raw_old_pool_nft, Token):
        assert raw_old_pool_nft == datum.im_pool_params.pool_nft, (
            "Old pool nft does not match"
        )
    else:
        pass  # upgrade all pools

    # check that the new pool state is correct
    raw_new_pool_params = pool_upgrade_params.new_pool_params
    if isinstance(raw_new_pool_params, UpgradeablePoolParams):
        new_pool_params = raw_new_pool_params
        assert new_pool_params.last_applied_proposal_id == tally_result.proposal_id, (
            "Last applied proposal id must match the proposal id of the tally"
        )
    else:
        # preserve old parameters except for the proposal id
        new_pool_params = UpgradeablePoolParams(
            datum.up_pool_params.fee,
            datum.up_pool_params.auth_nft,
            datum.up_pool_params.license_policy_id,
            tally_result.proposal_id,
        )
    raw_new_pool_address = pool_upgrade_params.new_pool_address
    if isinstance(raw_new_pool_address, Address):
        new_pool_address = raw_new_pool_address
    else:
        new_pool_address = own_output.address
    assert own_output.address == new_pool_address, "New pool address is incorrect"
    assert own_output.datum == SomeOutputDatum(
        PoolState(
            datum.im_pool_params,
            new_pool_params,
            datum.global_liquidity_tokens,
            own_input_info.out_ref,
        )
    ), "Pool params must match new pool params"
    (
        check_greater_or_equal_value(own_output.value, own_input_info.resolved.value),
        "Value must not decrease in upgrade",
    )


def validator(datum: PoolState, redeemer: PoolAction, context: ScriptContext) -> None:
    """
    Validates that the pool is spent correctly
    DISCLAIMER: This is a simple example to demonstrate onchain based contract upgradeability and should not be used in production.
    """
    purpose = get_spending_purpose(context)
    own_input_info = context.tx_info.inputs[redeemer.pool_input_index]
    assert own_input_info.out_ref == purpose.tx_out_ref, (
        "Index of own input does not match purpose"
    )

    own_output = context.tx_info.outputs[redeemer.pool_output_index]
    if isinstance(redeemer, AddLiquidity) or isinstance(redeemer, RemoveLiquidity):
        check_valid_license_present(
            redeemer.license_input_index,
            context.tx_info,
            datum.up_pool_params.license_policy_id,
        )
        check_change_liquidity(datum, redeemer, context, own_input_info, own_output)
    elif isinstance(redeemer, SwapAsset):
        check_valid_license_present(
            redeemer.license_input_index,
            context.tx_info,
            datum.up_pool_params.license_policy_id,
        )
        check_swap(datum, redeemer, context, own_input_info, own_output)
    elif isinstance(redeemer, PoolUpgrade):
        check_upgrade(datum, redeemer, context, own_input_info, own_output)
    else:
        assert False, "Unknown redeemer"
        assert False, "Unknown redeemer"
