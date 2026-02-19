import warnings
from datetime import datetime, timedelta, timezone
from time import sleep

from muesliswap_onchain_governance.offchain.delegation import (
    close_position_early,
    consolidate_delegation_tokens,
    deconsolidate_delegation_tokens,
    extend_delegation,
    open_position,
    retrieve_tokens_after_expiry,
)
from muesliswap_onchain_governance.offchain.utility_transactions import (
    send_all_with_pid,
)
from muesliswap_onchain_governance.onchain.delegation import delegated_staking
from muesliswap_onchain_governance.utils.contracts import get_contract, module_name

SLEEP_INTERVAL_SECONDS = 120

warnings.filterwarnings("ignore")


def main(
    delegator_wallet: str = "creator",
    delegatee_wallet: str = "delegatee",
    governance_token: str = "bd976e131cfc3956b806967b06530e48c20ed5498b46a5eb836b61c2.744d494c4b7632",
):
    delegation_time_1 = (
        int((datetime.now(timezone.utc) + timedelta(days=1)).timestamp()) * 1000
    )

    delegation_time_2 = (
        int((datetime.now(timezone.utc) + timedelta(days=2)).timestamp()) * 1000
    )

    delegation_time_expired = (
        int((datetime.now(timezone.utc) - timedelta(days=1)).timestamp()) * 1000
    )

    delegated_staking_script, delegated_staking_policy_id, delegated_staking_address = (
        get_contract(module_name(delegated_staking), True)
    )

    delegation_amount_1 = 3
    delegation_amount_2 = 5

    open_position.main(
        delegator_wallet=delegator_wallet,
        delegatee_wallet=delegatee_wallet,
        gov_token=governance_token,
        stake_amount=delegation_amount_1,
        delegate_until=delegation_time_1,
    )

    print("Opened first delegation position")
    sleep(SLEEP_INTERVAL_SECONDS)

    open_position.main(
        delegator_wallet=delegator_wallet,
        delegatee_wallet=delegatee_wallet,
        gov_token=governance_token,
        stake_amount=delegation_amount_2,
        delegate_until=delegation_time_2,
    )
    print("Opened second delegation position")
    sleep(SLEEP_INTERVAL_SECONDS)

    consolidate_delegation_tokens.main(
        delegatee_wallet=delegatee_wallet,
        lower_bound=delegation_time_1,
    )
    print("Consolidated delegation tokens for the delegatee")
    sleep(SLEEP_INTERVAL_SECONDS)

    deconsolidate_delegation_tokens.main(
        delegatee_wallet=delegatee_wallet,
    )
    print("Deconsolidated delegation tokens for the delegatee")
    sleep(SLEEP_INTERVAL_SECONDS)

    send_all_with_pid.main(
        sender=delegatee_wallet,
        recipient=delegator_wallet,
        pid=delegated_staking_policy_id,
    )
    print("Returned delegation tokens to the delegator")
    sleep(SLEEP_INTERVAL_SECONDS)

    # NOTE: This function should normally be called with a new delegation time
    # that is beyond the current expiry time
    extend_delegation.main(
        delegator_wallet=delegator_wallet,
        delegatee_wallet=delegatee_wallet,
        gov_token=governance_token,
        delegate_until=delegation_time_expired,
    )

    print("Extended delegation")
    sleep(SLEEP_INTERVAL_SECONDS)

    retrieve_tokens_after_expiry.main(
        delegator_wallet=delegator_wallet,
        gov_token=governance_token,
    )
    print("Retrieved staked tokens after delegation expiry")
    sleep(SLEEP_INTERVAL_SECONDS)

    close_position_early.main(
        delegator_wallet=delegator_wallet,
        gov_token=governance_token,
    )
    print("Closed delegation position early")


if __name__ == "__main__":
    import ipdb
    from fire import Fire

    try:
        Fire(main)
    except Exception as e:
        print(e)
        ipdb.post_mortem()
