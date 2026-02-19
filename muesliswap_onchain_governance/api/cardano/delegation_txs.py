from datetime import datetime, timezone

import pycardano
from opshin.prelude import Token
from pycardano import (
    AlonzoMetadata,
    AuxiliaryData,
    Metadata,
    Redeemer,
    TransactionBuilder,
    TransactionOutput,
)

from muesliswap_onchain_governance.offchain.util import (
    asset_from_token,
    value_from_token,
    with_min_lovelace,
)
from muesliswap_onchain_governance.onchain.delegation import delegated_staking
from muesliswap_onchain_governance.utils.network import context
from muesliswap_onchain_governance.utils.to_script_context import to_address

from ...utils import network
from ...utils.contracts import get_contract, get_ref_utxo, module_name
from ..schema import SignedTxResponse
from .util import get_collateral_signing_info, get_collateral_utxo, get_goverance_token


async def construct_open_delegation_position_tx(
    delegator: pycardano.Address,
    representative: pycardano.Address,
    amount: int,
    delegate_until: int,
):
    delegated_staking_script, delegated_staking_policy_id, delegated_staking_address = (
        get_contract(module_name(delegated_staking), True)
    )

    delegated_staking_ref_utxo = get_ref_utxo(delegated_staking_script, context)

    governance_token = get_goverance_token()

    datum = delegated_staking.DelegationDatum(
        delegation_expiry=delegate_until,
        owner=delegator.payment_part.payload,
    )

    builder = TransactionBuilder(context)
    builder.auxiliary_data = AuxiliaryData(
        data=AlonzoMetadata(
            metadata=Metadata({674: {"msg": ["Open Delegated Staking Position"]}})
        )
    )
    builder.add_input_address(delegator)
    builder.add_output(
        with_min_lovelace(
            TransactionOutput(
                address=delegated_staking_address,
                amount=value_from_token(governance_token, amount),
                datum=datum,
            ),
            context,
        )
    )

    delegation_token = Token(
        policy_id=delegated_staking_policy_id.payload,
        token_name=delegated_staking.bytes_big_from_unsigned_int(
            datum.delegation_expiry
        ),
    )
    builder.mint = asset_from_token(delegation_token, amount)

    builder.add_output(
        with_min_lovelace(
            TransactionOutput(
                address=representative,
                amount=value_from_token(delegation_token, amount),
            ),
            context,
        )
    )

    builder.add_minting_script(
        delegated_staking_ref_utxo or delegated_staking_script,
        Redeemer(
            delegated_staking.OpenDelegationPositionRedeemer(
                delegatee_address=to_address(representative),
                delegatee_output_index=1,
            )
        ),
    )

    builder.fee_buffer = 100
    builder.collaterals = [get_collateral_utxo(network)]

    _, collateral_skey, collateral_address = get_collateral_signing_info(network)
    signed_tx = builder.build_and_sign(
        signing_keys=[collateral_skey],
        change_address=delegator,
        merge_change=True,
        collateral_change_address=collateral_address,
    )

    return SignedTxResponse(
        signed_tx=signed_tx.to_cbor_hex(),
        tx_body=signed_tx.transaction_body.to_cbor_hex(),
    ).model_dump()


async def construct_update_delegation_tx(
    tx_hash: bytes,
    output_idx: int,
    delegator_address: pycardano.Address,
    position_owner_pkh: bytes,
    current_expiry: int,
    new_expiry: int,
    attached_lvl: int,
    current_staked_amount: int,
    new_staked_amount: int,
    representative_address: pycardano.Address,
):
    delegated_staking_script, delegated_staking_policy_id, delegated_staking_address = (
        get_contract(module_name(delegated_staking), True)
    )

    delegated_staking_ref_utxo = get_ref_utxo(delegated_staking_script, context)

    governance_token = get_goverance_token()

    # This UTxO also has a datum, but we don't need it here since this is just
    # an input. Datum will be fetched onchain
    current_position_utxo = pycardano.UTxO(
        pycardano.TransactionInput(pycardano.TransactionId(tx_hash), output_idx),
        pycardano.TransactionOutput(
            address=delegated_staking_address,
            amount=value_from_token(governance_token, current_staked_amount)
            + pycardano.Value(attached_lvl),
        ),
    )

    old_delegation_token = Token(
        policy_id=delegated_staking_policy_id.payload,
        token_name=delegated_staking.bytes_big_from_unsigned_int(current_expiry),
    )

    new_delegation_token = Token(
        policy_id=delegated_staking_policy_id.payload,
        token_name=delegated_staking.bytes_big_from_unsigned_int(new_expiry),
    )

    builder = TransactionBuilder(context)
    builder.auxiliary_data = AuxiliaryData(
        data=AlonzoMetadata(metadata=Metadata({674: {"msg": ["Update Delegation"]}}))
    )
    builder.add_input_address(delegator_address)

    builder.mint = asset_from_token(new_delegation_token, new_staked_amount)

    if datetime.now(timezone.utc).timestamp() * 1000 < current_expiry:
        # Renewing before expiry
        redeemer_datum = delegated_staking.RenewDelegationBeforeExpiry(
            delegatee_address=to_address(representative_address),
            delegatee_output_index=1,
        )
        builder.mint += asset_from_token(old_delegation_token, -current_staked_amount)
    else:
        # Renewing after expiry
        redeemer_datum = delegated_staking.RenewDelegationAfterExpiry(
            delegatee_address=to_address(representative_address),
            delegatee_output_index=1,
        )

    builder.add_script_input(
        current_position_utxo,
        delegated_staking_ref_utxo or delegated_staking_script,
        redeemer=Redeemer(redeemer_datum),
    )

    builder.add_minting_script(
        delegated_staking_ref_utxo or delegated_staking_script, Redeemer(redeemer_datum)
    )

    builder.add_output(
        with_min_lovelace(
            TransactionOutput(
                address=delegated_staking_address,
                amount=value_from_token(governance_token, new_staked_amount),
                datum=delegated_staking.DelegationDatum(
                    delegation_expiry=new_expiry,
                    owner=position_owner_pkh,
                ),
            ),
            context,
        )
    )

    builder.add_output(
        with_min_lovelace(
            TransactionOutput(
                address=representative_address,
                amount=value_from_token(new_delegation_token, new_staked_amount),
            ),
            context,
        )
    )

    builder.validity_start = context.last_block_slot
    builder.ttl = context.last_block_slot + 200

    builder.collaterals = [get_collateral_utxo(network)]

    _, collateral_skey, collateral_address = get_collateral_signing_info(network)
    signed_tx = builder.build_and_sign(
        signing_keys=[collateral_skey],
        change_address=delegator_address,
        merge_change=True,
        collateral_change_address=collateral_address,
    )

    return SignedTxResponse(
        signed_tx=signed_tx.to_cbor_hex(),
        tx_body=signed_tx.transaction_body.to_cbor_hex(),
    ).model_dump()


async def construct_revoke_delegation_tx(
    tx_hash: bytes,
    output_idx: int,
    expiry: int,
    staked_amount: int,
    attached_lvl: int,
    delegator_address: pycardano.Address,
):
    delegated_staking_script, delegated_staking_policy_id, delegated_staking_address = (
        get_contract(module_name(delegated_staking), True)
    )

    delegated_staking_ref_utxo = get_ref_utxo(delegated_staking_script, context)

    governance_token = get_goverance_token()

    # This UTxO also has a datum, but we don't need it here since this is just
    # an input. Datum will be fetched onchain
    delegation_utxo = pycardano.UTxO(
        pycardano.TransactionInput(pycardano.TransactionId(tx_hash), output_idx),
        pycardano.TransactionOutput(
            address=delegated_staking_address,
            amount=value_from_token(governance_token, staked_amount)
            + pycardano.Value(attached_lvl),
        ),
    )

    delegation_token = Token(
        policy_id=delegated_staking_policy_id.payload,
        token_name=delegated_staking.bytes_big_from_unsigned_int(expiry),
    )

    builder = TransactionBuilder(context)
    builder.auxiliary_data = AuxiliaryData(
        data=AlonzoMetadata(
            metadata=Metadata({674: {"msg": ["Close Delegated Staking Position"]}})
        )
    )
    builder.add_input_address(delegator_address)

    # Script requires datum.owner in signatories; add delegator so evaluation passes.
    # User adds their signature via append_signature before submitting.
    if isinstance(delegator_address.payment_part, pycardano.VerificationKeyHash):
        builder.required_signers = [delegator_address.payment_part]

    if datetime.now(timezone.utc).timestamp() * 1000 < expiry:
        redeemer_datum = delegated_staking.RevokeDelegationBeforeExpiry()
        builder.mint = asset_from_token(delegation_token, -staked_amount)
        builder.add_minting_script(
            delegated_staking_ref_utxo or delegated_staking_script,
            Redeemer(delegated_staking.RevokeDelegationBeforeExpiry()),
        )
    else:
        redeemer_datum = delegated_staking.ReclaimExpiredDelegation()

    builder.add_script_input(
        delegation_utxo,
        delegated_staking_ref_utxo or delegated_staking_script,
        redeemer=Redeemer(redeemer_datum),
    )

    builder.validity_start = context.last_block_slot
    builder.ttl = context.last_block_slot + 200

    builder.collaterals = [get_collateral_utxo(network)]

    _, collateral_skey, collateral_address = get_collateral_signing_info(network)
    signed_tx = builder.build_and_sign(
        signing_keys=[collateral_skey],
        change_address=delegator_address,
        merge_change=True,
        collateral_change_address=collateral_address,
    )

    return SignedTxResponse(
        signed_tx=signed_tx.to_cbor_hex(),
        tx_body=signed_tx.transaction_body.to_cbor_hex(),
    ).model_dump()
