from test.offchain.util import DEFAULT_TEST_CONFIG, wait_for_tx

from muesliswap_onchain_governance.offchain.gov_state.init import main as init_gov
from muesliswap_onchain_governance.offchain.treasury.init import main as init_treasury


def test_init_treasury():
    creation_tx, gov_nft_name = init_gov(
        wallet=DEFAULT_TEST_CONFIG.creator_wallet_name,
        governance_token=DEFAULT_TEST_CONFIG.governance_token,
        min_quorum=DEFAULT_TEST_CONFIG.min_quorum,
        min_proposal_duration=DEFAULT_TEST_CONFIG.min_proposal_duration,
        vault_ft_policy_id=DEFAULT_TEST_CONFIG.vault_ft_policy_id,
        delegation_policy_id=DEFAULT_TEST_CONFIG.delegation_policy_id,
    )
    wait_for_tx(creation_tx)
    wait_for_tx(
        init_treasury(
            wallet=DEFAULT_TEST_CONFIG.creator_wallet_name,
            auth_nft_token_name=gov_nft_name,
        )
    )
