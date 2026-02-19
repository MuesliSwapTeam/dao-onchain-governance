"""
This script demonstrates how to extend an existing delegation position
before expiry of the old position.
Extending a delegation position after it expires can be done in almost the same way -
the only difference is that the existing delegation tokens do not need to be burned

The functionality achieved in this transaction is also possible by first closing the old
position and then restaking the newly unlocked governance tokens. Doing it in a single transaction as shown here
saves on transaction fees and is more convenient for the user.
"""

from datetime import datetime, timedelta, timezone

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
    TransactionOutput,
    UTxO,
)

from muesliswap_onchain_governance.offchain.util import (
    asset_from_token,
    token_from_string,
    value_from_token,
    with_min_lovelace,
)
from muesliswap_onchain_governance.onchain.delegation import delegated_staking
from muesliswap_onchain_governance.utils import get_signing_info, network
from muesliswap_onchain_governance.utils.contracts import (
    get_contract,
    get_ref_utxo,
    module_name,
)
from muesliswap_onchain_governance.utils.network import context, show_tx
from muesliswap_onchain_governance.utils.to_script_context import to_address


def main(
    delegator_wallet: str = "creator",
    delegatee_wallet: str = "delegatee",
    delegate_until: int = int(
        (datetime.now(timezone.utc) + timedelta(days=180)).timestamp()
    )
    * 1000,
    gov_token: str = "bd976e131cfc3956b806967b06530e48c20ed5498b46a5eb836b61c2.744d494c4b7632",
):
    delegated_staking_script, delegated_staking_policy_id, delegated_staking_address = (
        get_contract(module_name(delegated_staking), True)
    )

    delegated_staking_ref_utxo = get_ref_utxo(delegated_staking_script, context)

    delegator_vkey, delegator_skey, delegator_address = get_signing_info(
        delegator_wallet, network=network
    )
    delegatee_vkey, delegatee_skey, delegatee_address = get_signing_info(
        delegatee_wallet, network=network
    )

    governance_token = token_from_string(gov_token)

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

    user_utxos = context.utxos(delegator_address)
    utxos_containing_delegation_token = [
        utxo
        for utxo in user_utxos
        if delegated_staking_policy_id in utxo.output.amount.multi_asset
    ]

    if not utxos_containing_delegation_token:
        raise Exception(
            "No delegation tokens owned by the delegator, so early extension is not possible"
        )

    utxo_to_extend = None
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
                utxo_to_extend = utxo
                utxo_with_delegation_tokens = user_utxo
                delegation_token_name = expected_tokenname
                break
        if utxo_to_extend is not None:
            break

    if utxo_to_extend is None or utxo_with_delegation_tokens is None:
        raise Exception(
            "No matching delegation UTxO and delegation token UTxO found for early unstaking"
        )

    old_delegation_token = Token(
        policy_id=delegated_staking_policy_id.payload,
        token_name=delegation_token_name.payload,
    )

    new_delegation_token = Token(
        policy_id=delegated_staking_policy_id.payload,
        token_name=delegated_staking.bytes_big_from_unsigned_int(delegate_until),
    )

    staked_amount = utxo_to_extend.output.amount.multi_asset[
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
        data=AlonzoMetadata(metadata=Metadata({674: {"msg": ["Renew Delegation"]}}))
    )
    builder.add_input_address(delegator_address)
    builder.add_input(utxo_with_delegation_tokens)

    redeemer_datum = delegated_staking.RenewDelegationBeforeExpiry(
        delegatee_address=to_address(delegatee_address), delegatee_output_index=1
    )

    builder.add_script_input(
        utxo_to_extend,
        delegated_staking_ref_utxo or delegated_staking_script,
        redeemer=Redeemer(redeemer_datum),
    )

    builder.mint = asset_from_token(
        old_delegation_token, -staked_amount
    ) + asset_from_token(new_delegation_token, staked_amount)

    builder.add_minting_script(
        delegated_staking_ref_utxo or delegated_staking_script, Redeemer(redeemer_datum)
    )

    builder.add_output(
        with_min_lovelace(
            TransactionOutput(
                address=delegated_staking_address,
                amount=value_from_token(governance_token, staked_amount),
                datum=delegated_staking.DelegationDatum(
                    delegation_expiry=delegate_until,
                    owner=delegator_address.payment_part.payload,
                ),
            ),
            context,
        )
    )

    builder.add_output(
        with_min_lovelace(
            TransactionOutput(
                address=delegatee_address,
                amount=value_from_token(new_delegation_token, staked_amount),
            ),
            context,
        )
    )

    builder.validity_start = context.last_block_slot
    builder.ttl = context.last_block_slot + 200

    signed_tx = builder.build_and_sign(
        signing_keys=[delegator_skey],
        change_address=delegator_address,
        merge_change=True,
    )

    context.submit_tx(signed_tx)
    show_tx(signed_tx)
    return signed_tx


if __name__ == "__main__":
    fire.Fire(main)
