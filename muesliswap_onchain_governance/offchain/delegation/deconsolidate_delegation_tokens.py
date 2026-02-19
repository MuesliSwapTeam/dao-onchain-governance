"""
This transaction demonstrates how to deconsolidate delegation tokens
"""

import fire
from opshin.prelude import Token
from pycardano import (
    AlonzoMetadata,
    AssetName,
    AuxiliaryData,
    Metadata,
    Redeemer,
    TransactionBuilder,
)

from muesliswap_onchain_governance.offchain.util import asset_from_token
from muesliswap_onchain_governance.onchain.delegation import delegated_staking
from muesliswap_onchain_governance.utils import get_signing_info, network
from muesliswap_onchain_governance.utils.contracts import (
    get_contract,
    get_ref_utxo,
    module_name,
)
from muesliswap_onchain_governance.utils.network import context, show_tx


def main(
    delegatee_wallet: str = "creator",
):
    delegated_staking_script, delegated_staking_policy_id, delegated_staking_address = (
        get_contract(module_name(delegated_staking), True)
    )

    delegated_staking_ref_utxo = get_ref_utxo(delegated_staking_script, context)

    delegatee_vkey, delegatee_skey, delegatee_address = get_signing_info(
        delegatee_wallet, network=network
    )

    _contract_utxos = context.utxos(delegated_staking_address)
    contract_utxos = []
    for utxo in _contract_utxos:
        try:
            datum = delegated_staking.ConsolidationDatum.from_cbor(
                utxo.output.datum.cbor
            )
            if datum.owner == delegatee_address.payment_part.payload:
                contract_utxos.append(utxo)
        except Exception:
            continue

    if not contract_utxos:
        raise Exception(
            "No consolidation UTxOs found at the contract for this delegatee"
        )

    delegatee_utxos = context.utxos(delegatee_address)
    utxos_containing_delegation_tokens = [
        utxo
        for utxo in delegatee_utxos
        if delegated_staking_policy_id in utxo.output.amount.multi_asset
    ]

    if not utxos_containing_delegation_tokens:
        raise Exception(
            "No delegation tokens owned by the delegatee, so deconsolidation is not possible"
        )

    utxo_to_deconsolidate = None
    deconsolidation_token_name = None
    for utxo in contract_utxos:
        consolidation_datum = delegated_staking.ConsolidationDatum.from_cbor(
            utxo.output.datum.cbor
        )
        expected_tokenname = AssetName(
            delegated_staking.bytes_big_from_unsigned_int(
                consolidation_datum.lower_bound
            )
        )

        for user_utxo in utxos_containing_delegation_tokens:
            if (
                delegated_staking_policy_id in user_utxo.output.amount.multi_asset
                and expected_tokenname
                in user_utxo.output.amount.multi_asset[delegated_staking_policy_id]
                and user_utxo.output.amount.multi_asset[delegated_staking_policy_id][
                    expected_tokenname
                ]
                >= consolidation_datum.amount
            ):
                utxo_to_deconsolidate = utxo
                deconsolidation_token_name = expected_tokenname
                break
        if utxo_to_deconsolidate is not None:
            break

    if utxo_to_deconsolidate is None:
        raise Exception(
            "No matching consolidation UTxO and delegation token UTxO found for deconsolidation"
        )

    builder = TransactionBuilder(context)
    builder.auxiliary_data = AuxiliaryData(
        data=AlonzoMetadata(
            metadata=Metadata({674: {"msg": ["Deconsolidate Delegation Tokens"]}})
        )
    )
    builder.add_input_address(delegatee_address)
    for utxo in delegatee_utxos:
        builder.add_input(utxo)

    datum = delegated_staking.ConsolidationDatum.from_cbor(
        utxo_to_deconsolidate.output.datum.cbor
    )

    builder.add_script_input(
        utxo_to_deconsolidate,
        delegated_staking_ref_utxo or delegated_staking_script,
        redeemer=Redeemer(delegated_staking.DeconsolidateDelegation()),
    )

    builder.mint = asset_from_token(
        Token(
            policy_id=delegated_staking_policy_id.payload,
            token_name=deconsolidation_token_name.payload,
        ),
        -datum.amount,
    )

    builder.add_minting_script(
        delegated_staking_ref_utxo or delegated_staking_script,
        Redeemer(delegated_staking.DeconsolidateDelegation()),
    )

    signed_tx = builder.build_and_sign(
        [delegatee_skey], change_address=delegatee_address, merge_change=True
    )

    context.submit_tx(signed_tx)
    show_tx(signed_tx)
    return signed_tx


if __name__ == "__main__":
    fire.Fire(main)
