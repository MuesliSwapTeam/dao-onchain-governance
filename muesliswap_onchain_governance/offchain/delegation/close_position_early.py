"""
This transaction demonstrates how to retrieve staked tokens before the end
of the delegation period
"""

import fire
from opshin.prelude import Token
from pycardano import (
    AlonzoMetadata,
    AssetName,
    AuxiliaryData,
    Metadata,
    Redeemer,
    ScriptHash,
    TransactionBuilder,
    UTxO,
)

from muesliswap_onchain_governance.offchain.util import (
    asset_from_token,
    token_from_string,
)
from muesliswap_onchain_governance.onchain.delegation import delegated_staking
from muesliswap_onchain_governance.utils import get_signing_info, network
from muesliswap_onchain_governance.utils.contracts import (
    get_contract,
    get_ref_utxo,
    module_name,
)
from muesliswap_onchain_governance.utils.network import context, show_tx


def main(
    delegator_wallet: str = "creator",
    gov_token: str = "bd976e131cfc3956b806967b06530e48c20ed5498b46a5eb836b61c2.744d494c4b7632",
):
    delegated_staking_script, delegated_staking_policy_id, delegated_staking_address = (
        get_contract(module_name(delegated_staking), True)
    )

    delegated_staking_ref_utxo = get_ref_utxo(delegated_staking_script, context)

    delegator_vkey, delegator_skey, delegator_address = get_signing_info(
        delegator_wallet, network=network
    )

    user_utxos = context.utxos(delegator_address)
    utxos_containing_delegation_token = [
        utxo
        for utxo in user_utxos
        if delegated_staking_policy_id in utxo.output.amount.multi_asset
    ]

    if not utxos_containing_delegation_token:
        raise Exception(
            "No delegation tokens owned by the delegator, so early unstaking is not possible"
        )

    _contract_utxos = context.utxos(delegated_staking_address)

    contract_utxos: list[UTxO] = []
    for utxo in _contract_utxos:
        try:
            datum = delegated_staking.DelegationDatum.from_cbor(utxo.output.datum.cbor)
            if datum.owner == delegator_address.payment_part.payload:
                contract_utxos.append(utxo)
        except Exception:
            continue

    if not contract_utxos:
        raise Exception("No delegation UTxOs found at the contract for this delegator")

    utxo_to_close = None
    utxo_with_delegation_tokens = None
    delegation_token_name = None

    for utxo in contract_utxos:
        delegation_datum = delegated_staking.DelegationDatum.from_cbor(
            utxo.output.datum.cbor
        )
        expected_tokenname = AssetName(
            delegated_staking.bytes_big_from_unsigned_int(
                delegation_datum.delegation_expiry
            )
        )

        for user_utxo in utxos_containing_delegation_token:
            if (
                delegated_staking_policy_id in user_utxo.output.amount.multi_asset
                and expected_tokenname
                in user_utxo.output.amount.multi_asset[delegated_staking_policy_id]
            ):
                utxo_to_close = utxo
                utxo_with_delegation_tokens = user_utxo
                delegation_token_name = expected_tokenname
                break
        if utxo_to_close is not None:
            break

    if utxo_to_close is None or utxo_with_delegation_tokens is None:
        raise Exception(
            "No matching delegation UTxO and delegation token UTxO found for early unstaking"
        )

    delegation_token = Token(
        policy_id=delegated_staking_policy_id.payload,
        token_name=delegation_token_name.payload,
    )

    governance_token = token_from_string(gov_token)

    staked_amount = utxo_to_close.output.amount.multi_asset[
        ScriptHash(governance_token.policy_id)
    ][AssetName(governance_token.token_name)]

    assert (
        utxo_with_delegation_tokens.output.amount.multi_asset[
            delegated_staking_policy_id
        ][delegation_token_name]
        >= staked_amount
    ), "Not enough delegation tokens in the user's UTxO"

    builder = TransactionBuilder(context)
    builder.auxiliary_data = AuxiliaryData(
        data=AlonzoMetadata(
            metadata=Metadata(
                {674: {"msg": ["Close Delegated Staking Position Early"]}}
            )
        )
    )
    builder.add_input_address(delegator_address)
    builder.add_input(utxo_with_delegation_tokens)

    builder.add_script_input(
        utxo_to_close,
        delegated_staking_ref_utxo or delegated_staking_script,
        redeemer=Redeemer(delegated_staking.RevokeDelegationBeforeExpiry()),
    )

    builder.mint = asset_from_token(delegation_token, -staked_amount)
    builder.add_minting_script(
        delegated_staking_ref_utxo or delegated_staking_script,
        Redeemer(delegated_staking.RevokeDelegationBeforeExpiry()),
    )

    builder.validity_start = context.last_block_slot
    builder.ttl = context.last_block_slot + 200

    signed_tx = builder.build_and_sign(
        [delegator_skey], change_address=delegator_address
    )

    context.submit_tx(signed_tx)
    show_tx(signed_tx)
    return signed_tx


if __name__ == "__main__":
    fire.Fire(main)
