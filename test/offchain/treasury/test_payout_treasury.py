import datetime
from time import sleep

from opshin.ledger.api_v2 import NoOutputDatum, NoScriptHash, TxOut
from opshin.prelude import Token

from muesliswap_onchain_governance.offchain.gov_state.create_tally import (
    main as create_tally,
)
from muesliswap_onchain_governance.offchain.gov_state.init import main as init_gov
from muesliswap_onchain_governance.offchain.init_gov_tokens import (
    main as init_gov_tokens,
)
from muesliswap_onchain_governance.offchain.staking.init import main as init_staking
from muesliswap_onchain_governance.offchain.tally.add_vote_tally import (
    main as add_vote_tally,
)
from muesliswap_onchain_governance.offchain.treasury.deposit import main as deposit
from muesliswap_onchain_governance.offchain.treasury.init import main as init_treasury
from muesliswap_onchain_governance.offchain.treasury.payout import main as payout
from muesliswap_onchain_governance.offchain.util import token_from_string
from muesliswap_onchain_governance.onchain.tally import tally
from muesliswap_onchain_governance.onchain.treasury import treasurer
from muesliswap_onchain_governance.utils import get_address
from muesliswap_onchain_governance.utils.to_script_context import (
    to_address,
    to_fraction,
)
from test.offchain.util import (
    DEFAULT_TEST_CONFIG,
    staking_address,
    staking_vote_nft_policy_id,
    tally_auth_nft_policy_id,
    wait_for_tx,
)


def test_payout_treasury():
    wait_for_tx(
        init_gov_tokens(
            wallet=DEFAULT_TEST_CONFIG.creator_wallet_name,
            token_name=DEFAULT_TEST_CONFIG.governance_token.split(".")[1],
            amount=1000000000,
        )
    )
    wait_for_tx(
        init_gov_tokens(
            wallet=DEFAULT_TEST_CONFIG.voter_wallet_name,
            token_name=DEFAULT_TEST_CONFIG.governance_token.split(".")[1],
            amount=1000000000,
        )
    )
    creation_tx, gov_nft_name = init_gov(
        wallet=DEFAULT_TEST_CONFIG.creator_wallet_name,
        governance_token=DEFAULT_TEST_CONFIG.governance_token,
        min_quorum=DEFAULT_TEST_CONFIG.min_quorum,
        min_proposal_duration=DEFAULT_TEST_CONFIG.min_proposal_duration,
        vault_ft_policy_id=DEFAULT_TEST_CONFIG.vault_ft_policy_id,
        delegation_policy_id=DEFAULT_TEST_CONFIG.delegation_policy_id,
    )
    wait_for_tx(creation_tx)
    init_treasury_tx, treasury_nft_name = init_treasury(
        wallet=DEFAULT_TEST_CONFIG.creator_wallet_name,
        auth_nft_token_name=gov_nft_name,
    )
    wait_for_tx(init_treasury_tx)
    deposit_tx = deposit(
        wallet=DEFAULT_TEST_CONFIG.creator_wallet_name,
        treasurer_nft_token_name=treasury_nft_name,
        deposit_token=DEFAULT_TEST_CONFIG.governance_token,
        deposit_amount=200,
        number_of_outputs=20,
    )
    wait_for_tx(deposit_tx)
    staking_tx = init_staking(
        wallet=DEFAULT_TEST_CONFIG.voter_wallet_name,
        governance_token=DEFAULT_TEST_CONFIG.governance_token,
        locked_amount=1000,
        tally_auth_nft_tk_name=gov_nft_name,
    )
    wait_for_tx(staking_tx)
    gov_token = token_from_string(DEFAULT_TEST_CONFIG.governance_token)
    auth_nft_tk = Token(tally_auth_nft_policy_id.payload, bytes.fromhex(gov_nft_name))
    tally_state = tally.TallyState(
        votes=[0, 0],
        params=tally.ProposalParams(
            quorum=DEFAULT_TEST_CONFIG.min_quorum,
            proposals=[
                tally.Nothing(),
                treasurer.FundPayoutParams(
                    output=TxOut(
                        address=to_address(
                            get_address(DEFAULT_TEST_CONFIG.voter_wallet_name)
                        ),
                        value={gov_token.policy_id: {gov_token.token_name: 200 * 15}},
                        datum=NoOutputDatum(),
                        reference_script=NoScriptHash(),
                    ),
                ),
            ],
            end_time=tally.FinitePOSIXTime(
                int(
                    (
                        datetime.datetime.now() + datetime.timedelta(minutes=1)
                    ).timestamp()
                )
                * 1000
            ),
            proposal_id=1,
            vault_ft_policy=DEFAULT_TEST_CONFIG.vault_ft_policy_id,
            delegation_policy=DEFAULT_TEST_CONFIG.delegation_policy_id,
            reputation_policy=b"",
            tally_auth_nft=auth_nft_tk,
            staking_vote_nft_policy=staking_vote_nft_policy_id.payload,
            staking_address=to_address(staking_address),
            governance_token=gov_token,
            winning_threshold=to_fraction(DEFAULT_TEST_CONFIG.min_winning_threshold),
        ),
    )
    main_create_tally_params = {
        "wallet": DEFAULT_TEST_CONFIG.creator_wallet_name,
        "gov_state_nft_tk_name": gov_nft_name,
        "treasury_benefactor": DEFAULT_TEST_CONFIG.treasury_benefactor_wallet_name,
        "tally_state_cbor": tally_state.to_cbor(),
    }
    tally_tx, proposals = create_tally(
        **main_create_tally_params,
    )
    wait_for_tx(tally_tx)
    added_tally_tx, tally_state = add_vote_tally(
        wallet=DEFAULT_TEST_CONFIG.voter_wallet_name,
        proposal_id=tally_state.params.proposal_id,
        proposal_index=1,
        tally_auth_nft_tk_name=gov_nft_name,
    )
    wait_for_tx(added_tally_tx)
    sleep(60)
    payout_tx = payout(
        wallet=DEFAULT_TEST_CONFIG.batcher_wallet_name,
        treasurer_nft_token_name=treasury_nft_name,
        max_inputs=20,
    )
    wait_for_tx(payout_tx)
