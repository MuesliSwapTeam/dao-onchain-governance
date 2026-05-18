import datetime
from typing import Tuple

import fire
import pycardano

from muesliswap_onchain_governance.onchain.licenses import licenses
from muesliswap_onchain_governance.onchain.simple_pool import (
    classes as simple_pool_classes,
)
from muesliswap_onchain_governance.onchain.staking import vault_ft
from muesliswap_onchain_governance.onchain.treasury import treasurer
from muesliswap_onchain_governance.utils.network import show_tx, context
from muesliswap_onchain_governance.utils.to_script_context import to_address
from opshin.ledger.api_v2 import TxOut, NoOutputDatum, NoScriptHash
from opshin.prelude import Token
from pycardano import (
    TransactionBuilder,
    Redeemer,
    AuxiliaryData,
    AlonzoMetadata,
    Metadata,
    TransactionOutput,
    Value,
)

from muesliswap_onchain_governance.offchain.util import (
    asset_from_token,
    with_min_lovelace,
    sorted_utxos,
    GOV_STATE_NFT_TK_NAME,
    TALLY_METADATA_KEY,
)
from muesliswap_onchain_governance.onchain.tally import tally_auth_nft, tally
from muesliswap_onchain_governance.onchain.gov_state import gov_state, gov_state_nft
from muesliswap_onchain_governance.utils import (
    get_signing_info,
    ogmios_url,
    network,
    kupo_url,
    get_address,
)
from muesliswap_onchain_governance.utils.contracts import (
    get_contract,
    module_name,
    get_ref_utxo,
)


def main(
    wallet: str = "creator",
    gov_state_nft_tk_name: str = GOV_STATE_NFT_TK_NAME,
    treasury_benefactor: str = "voter",
    tally_state_cbor: str = None,
    duration_open: int = 300,  # minutes
) -> Tuple[pycardano.Transaction, tally.TallyState]:
    # Load script info
    (
        gov_state_script,
        _,
        gov_state_address,
    ) = get_contract(module_name(gov_state), True)
    gov_state_script_ref_utxo = get_ref_utxo(gov_state_script, context)
    (
        tally_script,
        _,
        tally_address,
    ) = get_contract(module_name(tally), True)
    tally_script_ref_utxo = get_ref_utxo(tally_script, context)
    (
        tally_auth_nft_script,
        tally_auth_nft_policy_id,
        _,
    ) = get_contract(module_name(tally_auth_nft), True)
    tally_auth_nft_script_ref_utxo = get_ref_utxo(tally_auth_nft_script, context)
    (_, gov_state_nft_policy_id, _) = get_contract(module_name(gov_state_nft), True)
    (_, vault_ft_policy_id, _) = get_contract(module_name(vault_ft), True)

    gov_state_nft_tk = Token(
        gov_state_nft_policy_id.payload, bytes.fromhex(gov_state_nft_tk_name)
    )
    # Get payment address
    payment_vkey, payment_skey, payment_address = get_signing_info(
        wallet, network=network
    )

    try:
        treasury_benefactor = pycardano.Address.decode(treasury_benefactor)
    except Exception:
        pass
    if isinstance(treasury_benefactor, str):
        treasury_benefactor = get_address(treasury_benefactor, network=network)

    assert isinstance(
        treasury_benefactor, pycardano.Address
    ), "Could not resolve treasury benefactor address"

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

    payment_utxos = context.utxos(payment_address)
    all_inputs = sorted_utxos(
        [gov_state_utxo] + payment_utxos,
    )

    auth_nft_tk = Token(tally_auth_nft_policy_id.payload, gov_state_nft_tk.token_name)
    gov_state_input_index = all_inputs.index(gov_state_utxo)

    # generate redeemer
    gov_state_redeemer = Redeemer(
        gov_state.CreateNewTally(
            gov_state_input_index=gov_state_input_index,
            gov_state_output_index=1,
            tally_output_index=0,
        )
    )

    # Make the new datum of the GovState
    prev_gov_state_datum = gov_state.GovStateDatum.from_cbor(
        gov_state_utxo.output.datum.cbor
    )
    new_gov_state_datum = gov_state.GovStateDatum(
        params=prev_gov_state_datum.params,
        last_proposal_id=gov_state.increment_proposal_id(
            prev_gov_state_datum.last_proposal_id
        ),
    )
    assert (
        tally_auth_nft_policy_id.payload
        == prev_gov_state_datum.params.tally_auth_nft_policy
    ), "Auth NFT policy mismatch"

    # Build the transaction
    builder = TransactionBuilder(context)

    tally_mock_metadata = {
        "title": "Example Tally",
        "description": ["This is an example tally description."],
        "short_description": ["This is an example tally short description."],
        "creator_name": "Example creator name",
        "forum_link": "https://muesliswap.com",
        "proposals": [
            {
                "title": "Nothing",
                "description": ["This is an example of a proposal that does nothing."],
            },
            {
                "title": "Fund Payout",
                "description": [
                    "This is an example of a proposal that initiates ",
                    "a payout of funds from the treasury.",
                ],
            },
            {
                "title": "Release License",
                "description": [
                    "This is an example of a proposal that releases a license."
                ],
            },
            {
                "title": "Pool Upgrade",
                "description": [
                    "This is an example of a proposal that upgrades ",
                    "a pool contract's parameters.",
                ],
            },
        ],
    }

    builder.auxiliary_data = AuxiliaryData(
        data=AlonzoMetadata(
            metadata=Metadata(
                {
                    674: {"msg": ["MuesliSwap DAO Tally Creation"]},
                    TALLY_METADATA_KEY: tally_mock_metadata,
                }
            )
        )
    )
    for u in payment_utxos:
        builder.add_input(u)
    builder.add_script_input(
        gov_state_utxo,
        gov_state_script_ref_utxo or gov_state_script,
        None,
        gov_state_redeemer,
    )

    builder.add_minting_script(
        tally_auth_nft_script_ref_utxo or tally_auth_nft_script,
        Redeemer(
            tally_auth_nft.AuthRedeemer(
                spent_utxo_index=gov_state_input_index,
                governance_nft_name=gov_state_nft_tk.token_name,
            )
        ),
    )
    builder.mint = asset_from_token(auth_nft_tk, 1)
    if tally_state_cbor:
        tally_state = tally.TallyState.from_cbor(tally_state_cbor)
    else:
        tally_state = tally.TallyState(
            votes=[0, 0, 0, 0],
            params=tally.ProposalParams(
                quorum=prev_gov_state_datum.params.min_quorum,
                proposals=[
                    tally.Nothing(),
                    treasurer.FundPayoutParams(
                        output=TxOut(
                            address=to_address(treasury_benefactor),
                            value={b"": {b"": 5000000}},
                            datum=NoOutputDatum(),
                            reference_script=NoScriptHash(),
                        ),
                    ),
                    licenses.LicenseReleaseParams(
                        address=to_address(treasury_benefactor),
                        datum=NoOutputDatum(),
                        maximum_future_validity=1000000000,
                    ),
                    simple_pool_classes.PoolUpgradeParams(
                        old_pool_nft=tally.Nothing(),
                        new_pool_params=tally.Nothing(),
                        new_pool_address=to_address(payment_address),
                    ),
                ],
                end_time=tally.FinitePOSIXTime(
                    int(
                        (
                            datetime.datetime.now()
                            + datetime.timedelta(minutes=duration_open)
                        ).timestamp()
                    )
                    * 1000
                ),
                proposal_id=new_gov_state_datum.last_proposal_id,
                vault_ft_policy=vault_ft_policy_id.payload,
                tally_auth_nft=auth_nft_tk,
                staking_vote_nft_policy=new_gov_state_datum.params.staking_vote_nft_policy,
                staking_address=new_gov_state_datum.params.staking_address,
                governance_token=new_gov_state_datum.params.governance_token,
                winning_threshold=new_gov_state_datum.params.min_winning_threshold,
            ),
        )
    tally_output = TransactionOutput(
        address=tally_address,
        amount=Value(
            coin=2000000,
            multi_asset=asset_from_token(auth_nft_tk, 1),
        ),
        datum=tally_state,
    )

    builder.add_output(with_min_lovelace(tally_output, context))
    builder.add_output(
        pycardano.TransactionOutput(
            address=gov_state_address,
            amount=gov_state_utxo.output.amount,
            datum=new_gov_state_datum,
        )
    )
    builder.ttl = context.last_block_slot + 100
    builder.fee_buffer = 1000

    # Sign the transaction
    signed_tx = builder.build_and_sign(
        signing_keys=[payment_skey],
        change_address=payment_address,
    )

    # print(signed_tx.to_cbor_hex())

    # Submit the transaction
    context.submit_tx(signed_tx)

    show_tx(signed_tx)

    return signed_tx, tally_state


if __name__ == "__main__":
    fire.Fire(main)
