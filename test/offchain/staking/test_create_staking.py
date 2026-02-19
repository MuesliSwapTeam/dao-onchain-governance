from datetime import datetime

import pytest

from muesliswap_onchain_governance.offchain.gov_state.init import main as init_gov_state
from muesliswap_onchain_governance.offchain.staking.init import main as init_staking
from muesliswap_onchain_governance.offchain.init_gov_tokens import (
    main as init_gov_tokens,
)
from test.offchain.util import DEFAULT_TEST_CONFIG, wait_for_tx


def test_create_staking():
    init_tk_tx = init_gov_tokens(
        wallet=DEFAULT_TEST_CONFIG.voter_wallet_name,
        token_name=DEFAULT_TEST_CONFIG.governance_token.split(".")[1],
        amount=1000000,
    )
    creation_tx, gov_nft_name = init_gov_state(
        wallet=DEFAULT_TEST_CONFIG.creator_wallet_name,
        governance_token=DEFAULT_TEST_CONFIG.governance_token,
        min_quorum=DEFAULT_TEST_CONFIG.min_quorum,
        min_winning_threshold=DEFAULT_TEST_CONFIG.min_winning_threshold,
        min_proposal_duration=DEFAULT_TEST_CONFIG.min_proposal_duration,
    )
    wait_for_tx(init_tk_tx)
    wait_for_tx(creation_tx)
    tx = init_staking(
        wallet=DEFAULT_TEST_CONFIG.voter_wallet_name,
        governance_token=DEFAULT_TEST_CONFIG.governance_token,
        locked_amount=1000,
        tally_auth_nft_tk_name=gov_nft_name,
    )
    wait_for_tx(tx)
