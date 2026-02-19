from datetime import datetime, timedelta, timezone

import fire
from opshin.prelude import Token
from pycardano import (AlonzoMetadata, Asset, AssetName, AuxiliaryData,
                       Metadata, MultiAsset, Redeemer, TransactionBuilder,
                       TransactionOutput, Value)

from muesliswap_onchain_governance.offchain.util import (asset_from_token,
                                                         value_from_token,
                                                         with_min_lovelace)
from muesliswap_onchain_governance.onchain.delegation import delegated_staking
from muesliswap_onchain_governance.utils import get_signing_info, network
from muesliswap_onchain_governance.utils.contracts import (get_contract,
                                                           get_ref_utxo,
                                                           module_name)
from muesliswap_onchain_governance.utils.network import context, show_tx

from .config import DEBUG, DEFAULT_EXECUTION_UNITS


def main(
    delegatee_wallet: str = "delegatee",
    lower_bound=int((datetime.now(timezone.utc) + timedelta(days=90)).timestamp())
    * 1000,
):
    delegated_staking_script, delegated_staking_policy_id, delegated_staking_address = (
        get_contract(module_name(delegated_staking), True)
    )

    delegated_staking_ref_utxo = get_ref_utxo(delegated_staking_script, context)

    delegatee_vkey, delegatee_skey, delegatee_address = get_signing_info(
        delegatee_wallet, network=network
    )

    delegatee_utxos = context.utxos(delegatee_address)

    tokens_to_consolidate: list[tuple[bytes, int]] = []

    for utxo in delegatee_utxos:
        if delegated_staking_policy_id in utxo.output.amount.multi_asset:
            for token_name, amount in utxo.output.amount.multi_asset[
                delegated_staking_policy_id
            ].items():
                token_expiry = delegated_staking.unsigned_int_from_bytes_big(
                    token_name.payload
                )

                if token_expiry >= lower_bound:
                    tokens_to_consolidate.append((token_name.payload, amount))

    if len(tokens_to_consolidate) < 2:
        raise Exception("Not enough delegation tokens found to consolidate")

    builder = TransactionBuilder(context)
    builder.auxiliary_data = AuxiliaryData(
        data=AlonzoMetadata(
            metadata=Metadata({674: {"msg": ["Consolidate Delegation Tokens"]}})
        )
    )
    builder.add_input_address(delegatee_address)
    for utxo in delegatee_utxos:
        builder.add_input(utxo)

    staking_multiasset = MultiAsset()
    staking_multiasset[delegated_staking_policy_id] = Asset()
    for token_name, amount in tokens_to_consolidate:
        staking_multiasset[delegated_staking_policy_id][AssetName(token_name)] = amount

    consolidation_token = Token(
        policy_id=delegated_staking_policy_id.payload,
        token_name=delegated_staking.bytes_big_from_unsigned_int(lower_bound),
    )

    amount_of_consolidation_token = sum(amount for _, amount in tokens_to_consolidate)
    builder.mint = asset_from_token(consolidation_token, amount_of_consolidation_token)

    builder.add_output(
        with_min_lovelace(
            TransactionOutput(
                address=delegated_staking_address,
                amount=Value(multi_asset=staking_multiasset),
                datum=delegated_staking.ConsolidationDatum(
                    lower_bound=lower_bound,
                    owner=delegatee_address.payment_part.payload,
                    amount=amount_of_consolidation_token,
                ),
            ),
            context,
        )
    )

    builder.add_minting_script(
        delegated_staking_ref_utxo or delegated_staking_script,
        Redeemer(
            delegated_staking.ConsolidateDelegation(lower_bound=lower_bound),
            ex_units=DEFAULT_EXECUTION_UNITS if DEBUG else None,
        ),
    )

    builder.add_output(
        with_min_lovelace(
            TransactionOutput(
                address=delegatee_address,
                amount=value_from_token(
                    consolidation_token, amount_of_consolidation_token
                ),
            ),
            context,
        )
    )

    signed_tx = builder.build_and_sign(
        [delegatee_skey], change_address=delegatee_address, merge_change=True
    )
    try:
        context.submit_tx(signed_tx)
    except Exception:
        print(f"Transaction CBOR: {signed_tx.to_cbor_hex()}")
        raise
    show_tx(signed_tx)

    return signed_tx


if __name__ == "__main__":
    fire.Fire(main)

