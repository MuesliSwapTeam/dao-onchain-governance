import time
from dataclasses import dataclass
from fractions import Fraction

import pycardano

from muesliswap_onchain_governance.onchain import free_mint
from muesliswap_onchain_governance.onchain.delegation import delegated_staking
from muesliswap_onchain_governance.onchain.staking import (
    staking,
    staking_vote_nft,
    vault_ft,
)
from muesliswap_onchain_governance.onchain.tally import tally_auth_nft
from muesliswap_onchain_governance.utils.contracts import get_contract, module_name
from muesliswap_onchain_governance.utils.network import context

(_, vault_ft_policy_id, _) = get_contract(module_name(vault_ft), True)
(_, delegated_staking_policy_id, _) = get_contract(module_name(delegated_staking), True)
(_, free_mint_policy_id, _) = get_contract(module_name(free_mint), True)
(
    _,
    tally_auth_nft_policy_id,
    _,
) = get_contract(module_name(tally_auth_nft), True)
(
    _,
    staking_vote_nft_policy_id,
    _,
) = get_contract(module_name(staking_vote_nft), True)
(
    _,
    _,
    staking_address,
) = get_contract(module_name(staking), True)


@dataclass
class TestConfig:
    voter_wallet_name: str
    creator_wallet_name: str
    batcher_wallet_name: str
    treasury_benefactor_wallet_name: str
    governance_token: str
    min_quorum: int = 1000
    min_winning_threshold: Fraction = Fraction(1, 4)
    min_proposal_duration: int = 1000
    vault_ft_policy_id: str = vault_ft_policy_id.payload
    delegation_policy_id: str = delegated_staking_policy_id.payload


DEFAULT_TEST_CONFIG = TestConfig(
    voter_wallet_name="voter",
    creator_wallet_name="creator",
    batcher_wallet_name="batcher",
    treasury_benefactor_wallet_name="voter",
    governance_token=f"{free_mint_policy_id.payload.hex()}.{b'tMILK'.hex()}",
)


def wait_for_tx(
    tx: pycardano.Transaction, context: pycardano.OgmiosChainContext = context
):
    while not context.utxo_by_tx_id(tx.id.payload.hex(), 0):
        time.sleep(1)
        print("Waiting for transaction to be included in the blockchain")
