import datetime

import fire
import pycardano
from opshin.ledger.api_v2 import NoOutputDatum, PosInfPOSIXTime, POSIXTime
from opshin.prelude import Nothing, Token

from muesliswap_onchain_governance.offchain.gov_state.create_tally import (
    main as create_tally,
)
from muesliswap_onchain_governance.onchain.gov_state import gov_state, gov_state_nft
from muesliswap_onchain_governance.onchain.licenses.licenses import LicenseReleaseParams
from muesliswap_onchain_governance.onchain.reputation import reputation
from muesliswap_onchain_governance.onchain.util import ProposalParams, TallyState
from muesliswap_onchain_governance.utils.network import context, show_tx
from muesliswap_onchain_governance.utils.to_script_context import to_address

from ...utils.contracts import get_contract, module_name
from ..util import GOV_STATE_NFT_TK_NAME


def main(
    wallet: str = "creator",
    gov_state_nft_tk_name: str = GOV_STATE_NFT_TK_NAME,
    target_address: str = None,
    maximum_future_validity: POSIXTime = datetime.timedelta(days=7).total_seconds()
    * 1000,
) -> pycardano.Transaction:
    assert target_address, "target_address is required"

    # Load script info
    (
        gov_state_script,
        _,
        gov_state_address,
    ) = get_contract(module_name(gov_state), True)
    (_, gov_state_nft_policy_id, _) = get_contract(module_name(gov_state_nft), True)
    (_, reputation_policy_id, _) = get_contract(module_name(reputation), True)
    gov_state_nft_tk = Token(
        gov_state_nft_policy_id.payload, bytes.fromhex(gov_state_nft_tk_name)
    )

    # Select governance thread
    gov_utxos = context.utxos(gov_state_address)
    gov_state_utxo = None
    for u in gov_utxos:
        if u.output.amount.multi_asset.get(
            pycardano.ScriptHash(gov_state_nft_tk.policy_id), {}
        ).get(pycardano.AssetName(gov_state_nft_tk.token_name)):
            gov_state_utxo = u
            break
    assert gov_state_utxo, "No governance thread found"
    gov_state_datum = gov_state.GovStateDatum.from_cbor(
        gov_state_utxo.output.datum.cbor
    )

    matchmaker_address = to_address(pycardano.Address.from_primitive(target_address))
    tally_state = TallyState(
        votes=[0, 0],
        params=ProposalParams(
            quorum=gov_state_datum.params.min_quorum,
            winning_threshold=gov_state_datum.params.min_winning_threshold,
            proposals=[
                Nothing(),
                LicenseReleaseParams(
                    address=matchmaker_address,
                    datum=NoOutputDatum(),
                    maximum_future_validity=maximum_future_validity,
                ),
            ],
            end_time=PosInfPOSIXTime(),
            proposal_id=gov_state_datum.last_proposal_id + 1,
            tally_auth_nft=Token(
                gov_state_datum.params.tally_auth_nft_policy,
                gov_state_nft_tk.token_name,
            ),
            staking_vote_nft_policy=gov_state_datum.params.staking_vote_nft_policy,
            staking_address=gov_state_datum.params.staking_address,
            governance_token=gov_state_datum.params.governance_token,
            vault_ft_policy=gov_state_datum.params.vault_ft_policy,
            delegation_policy=gov_state_datum.params.delegation_policy,
            reputation_policy=gov_state_datum.params.reputation_policy,
        ),
    )
    (tx, tally_state) = create_tally(
        wallet,
        gov_state_nft_tk_name,
        tally_state_cbor=tally_state.to_cbor().hex(),
    )
    show_tx(tx)
    return tx


if __name__ == "__main__":
    fire.Fire(main)
