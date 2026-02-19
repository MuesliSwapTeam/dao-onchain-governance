"""
NOTE: This is only a sample contract, designed to allow demonstration of
Vault FT minting, staking and voting on the Testnet

It is not otherwise linked to any DAO ecosystem so locking tokens at this
contract will not accrue rewards.
"""

from muesliswap_onchain_governance.onchain.util import *


@dataclass
class UnlockRedeemer(PlutusData):
    CONSTR_ID = 0


def validator(
    datum: VaultDatum, redeemer: UnlockRedeemer, context: ScriptContext
) -> None:
    purpose = get_spending_purpose(context)
    tx_info = context.tx_info
    assert datum.owner in context.tx_info.signatories, "Not signed by owner"
    lower_bound_limit = tx_info.valid_range.lower_bound.limit
    assert isinstance(lower_bound_limit, FinitePOSIXTime), "Must set tx start time"
    assert ext_after_ext(
        lower_bound_limit, FinitePOSIXTime(datum.release_time)
    ), "Too early"
