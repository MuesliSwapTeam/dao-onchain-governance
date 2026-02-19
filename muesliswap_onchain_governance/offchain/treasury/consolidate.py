import fire
import pycardano

from muesliswap_onchain_governance.onchain.treasury import (
    treasurer_nft,
    treasurer,
    value_store,
)
from muesliswap_onchain_governance.utils.network import show_tx, context
from opshin.ledger.api_v2 import (
    POSIXTime,
)
from opshin.prelude import Token
from pycardano import (
    OgmiosChainContext,
    TransactionBuilder,
    Redeemer,
    AuxiliaryData,
    AlonzoMetadata,
    Metadata,
    TransactionOutput,
    Value,
)

from ..util import (
    token_from_string,
    asset_from_token,
    with_min_lovelace,
    TREASURER_STATE_NFT_TK_NAME,
    sorted_utxos,
)
from muesliswap_onchain_governance.onchain.staking import (
    staking_vote_nft,
    staking,
    vault_ft,
)
from muesliswap_onchain_governance.onchain.tally import tally_auth_nft, tally
from muesliswap_onchain_governance.onchain.gov_state import gov_state_nft, gov_state
from ...utils import get_signing_info, ogmios_url, network, kupo_url
from ...utils.contracts import get_contract, get_ref_utxo, module_name
from ...utils.to_script_context import to_address, to_tx_out_ref


def main(
    wallet: str = "creator",
    treasurer_nft_token_name: str = TREASURER_STATE_NFT_TK_NAME,
    max_inputs: int = 40,
):
    # Load script info
    (
        treasurer_nft_script,
        treasurer_nft_policy_id,
        _,
    ) = get_contract(module_name(treasurer_nft), True)
    (
        treasurer_script,
        _,
        treasurer_address,
    ) = get_contract(module_name(treasurer), True)
    treasurer_script_ref_utxo = get_ref_utxo(treasurer_script, context)
    (value_store_script, _, value_store_address) = get_contract(
        module_name(value_store), True
    )
    value_store_ref_utxo = get_ref_utxo(value_store_script, context)

    # Get payment address
    payment_vkey, payment_skey, payment_address = get_signing_info(
        wallet, network=network
    )

    # generate treasurer_state_nft
    treasurer_nft_token = Token(
        policy_id=treasurer_nft_policy_id.payload,
        token_name=bytes.fromhex(treasurer_nft_token_name),
    )

    # Make the datum of the ValueStore
    value_store_datum = value_store.ValueStoreState(
        treasurer_nft=treasurer_nft_token,
    )

    # Select treasurer thread
    treasurer_utxos = context.utxos(treasurer_address)
    treasurer_state_utxo = None
    for u in treasurer_utxos:
        if u.output.amount.multi_asset.get(
            pycardano.ScriptHash(treasurer_nft_token.policy_id), {}
        ).get(pycardano.AssetName(treasurer_nft_token.token_name)):
            treasurer_state_utxo = u
            break
    assert treasurer_state_utxo, "No treasurer thread found"
    treasurer_state = treasurer.TreasurerState.from_cbor(
        treasurer_state_utxo.output.datum.cbor
    )

    # Select value store deposits
    value_store_utxos = context.utxos(value_store_address)
    selected_utxos = []
    for u in value_store_utxos:
        if not u.output.amount.multi_asset:
            continue
        try:
            datum = value_store.ValueStoreState.from_cbor(u.output.datum.cbor)
        except Exception:
            continue
        if datum.treasurer_nft == treasurer_nft_token:
            selected_utxos.append(u)
    while True:
        selected_utxos = selected_utxos[:max_inputs]
        try:
            total_value = sum([u.output.amount for u in selected_utxos], start=Value())

            own_utxos = context.utxos(payment_address)
            all_utxos = sorted_utxos(
                [treasurer_state_utxo] + own_utxos + selected_utxos,
            )
            treasurer_input_index = all_utxos.index(treasurer_state_utxo)

            # Build the transaction
            builder = TransactionBuilder(context)
            builder.auxiliary_data = AuxiliaryData(
                data=AlonzoMetadata(
                    metadata=Metadata({674: {"msg": ["Consolidate Funds in Treasury"]}})
                )
            )
            builder.add_input_address(payment_address)
            for u in selected_utxos:
                builder.add_script_input(
                    u,
                    value_store_ref_utxo or value_store_script,
                    None,
                    Redeemer(
                        value_store.ValueStoreRedeemer(
                            treasurer_index=treasurer_input_index
                        )
                    ),
                )
            builder.add_script_input(
                treasurer_state_utxo,
                treasurer_script_ref_utxo or treasurer_script,
                None,
                Redeemer(
                    treasurer.ConsolidateFunds(
                        treasurer_input_index=treasurer_input_index,
                        treasurer_output_index=0,
                        next_proposal_id=treasurer_state.last_applied_proposal_id,
                    )
                ),
            )
            # Re-add the treasurer state without any changes
            builder.add_output(
                treasurer_state_utxo.output,
            )
            # Add the new value store output
            output = TransactionOutput(
                address=value_store_address,
                amount=total_value,
                datum=value_store_datum,
            )
            builder.add_output(output)

            # Sign the transaction
            signed_tx = builder.build_and_sign(
                signing_keys=[payment_skey],
                change_address=payment_address,
            )

            # Submit the transaction
            context.submit_tx(signed_tx)

            show_tx(signed_tx)
            break
        except Exception as e:
            print(max_inputs, "failed")
            max_inputs -= 1
            continue


if __name__ == "__main__":
    fire.Fire(main)
