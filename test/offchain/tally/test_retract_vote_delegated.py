from datetime import datetime
from muesliswap_onchain_governance.offchain.init_gov_tokens import (
    main as init_gov_tokens,
)

import pytest

from muesliswap_onchain_governance.offchain.gov_state.init import main as init_gov_state
from muesliswap_onchain_governance.offchain.gov_state.create_tally import (
    main as create_tally,
)
from muesliswap_onchain_governance.offchain.staking.init import main as init_staking
from muesliswap_onchain_governance.offchain.tally.add_vote_tally import (
    main as add_vote_tally,
)
from muesliswap_onchain_governance.offchain.tally.execute_retract_vote_permission import (
    main as execute_retract_vote_permission,
)
from muesliswap_onchain_governance.offchain.staking.mint_retract_vote_permission import (
    main as mint_retract_vote_permission,
)
from test.offchain.util import DEFAULT_TEST_CONFIG, wait_for_tx


def test_retract_vote():
    init_tk_tx = init_gov_tokens(
        wallet=DEFAULT_TEST_CONFIG.voter_wallet_name,
        token_name=DEFAULT_TEST_CONFIG.governance_token.split(".")[1],
        amount=1000000,
    )
    wait_for_tx(init_tk_tx)
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
    tally_tx, tally_state = create_tally(
        **main_create_tally_params,
    )
    wait_for_tx(tally_tx)
    staking_tx = init_staking(
        wallet=DEFAULT_TEST_CONFIG.voter_wallet_name,
        governance_token=DEFAULT_TEST_CONFIG.governance_token,
        locked_amount=1000,
        tally_auth_nft_tk_name=gov_nft_name,
    )
    wait_for_tx(staking_tx)
    added_tally_tx, tally_state = add_vote_tally(
        wallet=DEFAULT_TEST_CONFIG.voter_wallet_name,
        proposal_id=tally_state.params.proposal_id,
        proposal_index=0,
        tally_auth_nft_tk_name=gov_nft_name,
    )
    wait_for_tx(added_tally_tx)
    mint_tx, vote_permission_nft_cbor = mint_retract_vote_permission(
        wallet=DEFAULT_TEST_CONFIG.voter_wallet_name,
        participation_index=0,
        tally_auth_nft_tk_name=gov_nft_name,
    )
    wait_for_tx(mint_tx)
    wait_for_tx(
        execute_retract_vote_permission(
            wallet=DEFAULT_TEST_CONFIG.batcher_wallet_name,
            vote_permission_nft_cbor_hex=vote_permission_nft_cbor.hex(),
        )
    )
