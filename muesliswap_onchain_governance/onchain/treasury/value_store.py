"""
The value store contract.

This contract maintains funds of the treasury.
The funds are controlled by a state at treasury/treasurer.

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

It is allowed to spend as many value_store inputs as one can fit into a single transaction.
"""


from muesliswap_onchain_governance.onchain.treasury.util import *


@dataclass
class FundPayoutParams(PlutusData):
    """
    Redeemer for the value store contract to issue a payout of funds.
    """

    CONSTR_ID = 3
    treasurer_index: int


ValueStoreRedeemer = FundPayoutParams


def validator(
    value_store_state: ValueStoreState,
    redeemer: ValueStoreRedeemer,
    context: ScriptContext,
) -> None:
    """
    Value store validator. Ensures to only release funds if the treasurer approves the transaction, i.e. is spent in it.
    """
    treasurer_input = context.tx_info.inputs[redeemer.treasurer_index].resolved
    assert token_present_in_output(
        value_store_state.treasurer_nft, treasurer_input
    ), "Unique treasurer NFT is not present in the treasurer input"
