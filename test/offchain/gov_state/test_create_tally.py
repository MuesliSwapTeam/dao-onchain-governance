from datetime import datetime

import pytest

from muesliswap_onchain_governance.offchain.gov_state.init import main as init_gov_state
from muesliswap_onchain_governance.offchain.gov_state.create_tally import (
    main as create_tally,
)
from muesliswap_onchain_governance.onchain.tally import tally
from test.offchain.util import DEFAULT_TEST_CONFIG, wait_for_tx


def test_create_tally():
    creation_tx, gov_nft_name = init_gov_state(
        wallet=DEFAULT_TEST_CONFIG.creator_wallet_name,
        governance_token=DEFAULT_TEST_CONFIG.governance_token,
        min_quorum=DEFAULT_TEST_CONFIG.min_quorum,
        min_proposal_duration=DEFAULT_TEST_CONFIG.min_proposal_duration,
    )
    wait_for_tx(creation_tx)
    main_create_tally_params = {
        "wallet": DEFAULT_TEST_CONFIG.creator_wallet_name,
        "gov_state_nft_tk_name": gov_nft_name,
        "treasury_benefactor": DEFAULT_TEST_CONFIG.treasury_benefactor_wallet_name,
    }
    tally_tx, proposals = create_tally(
        **main_create_tally_params,
    )
    wait_for_tx(tally_tx)
