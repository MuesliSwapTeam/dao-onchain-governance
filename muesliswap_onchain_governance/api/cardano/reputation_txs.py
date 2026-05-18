import pycardano
from opshin.prelude import Token
from pycardano import (
    Address,
    AlonzoMetadata,
    AuxiliaryData,
    Metadata,
    Redeemer,
    TransactionBuilder,
    TransactionOutput,
    Value,
)

from muesliswap_onchain_governance.offchain.util import (
    asset_from_token,
    sorted_utxos,
    with_min_lovelace,
)
from muesliswap_onchain_governance.onchain.reputation import reputation as reputation_contract
from muesliswap_onchain_governance.onchain.staking import staking as staking_contract
from muesliswap_onchain_governance.onchain.util import reputation_token_name
from muesliswap_onchain_governance.utils.network import context, evaluation_context

from ...utils import network
from ...utils.contracts import get_contract, get_ref_utxo, module_name
from ..schema import SignedTxResponse
from .util import get_collateral_signing_info, get_collateral_utxo

# Prefer the Ogmios context for on-chain queries when Blockfrost is unavailable.
_chain_context = context if context is not None else evaluation_context


async def construct_mint_reputation_tx(
    address: str,
    staking_tx_hash: str,
    staking_output_index: int,
    participation_index: int,
) -> dict:
    """
    Build a transaction that mints 1 reputation token by consuming one ended
    vote participation from a staking UTxO.

    The server signs with its collateral key; the user must additionally sign
    (their payment key is listed as a required signer). Use POST /api/v1/append_signature
    to attach the user's witness before submission.
    """
    staking_script, _, staking_address = get_contract(
        module_name(staking_contract), True
    )
    staking_ref_utxo = get_ref_utxo(staking_script, _chain_context)

    reputation_script, reputation_policy_id, _ = get_contract(
        module_name(reputation_contract), True
    )
    reputation_ref_utxo = get_ref_utxo(reputation_script, _chain_context)

    user_address = Address.from_primitive(bytes.fromhex(address))

    # Locate the specific staking UTxO on chain
    staking_utxo = None
    for utxo in _chain_context.utxos(staking_address):
        if (
            utxo.input.transaction_id.payload.hex() == staking_tx_hash
            and utxo.input.index == staking_output_index
        ):
            staking_utxo = utxo
            break

    if staking_utxo is None:
        raise ValueError(
            f"Staking UTxO {staking_tx_hash}#{staking_output_index} not found"
        )

    prev_datum = staking_contract.StakingState.from_cbor(
        staking_utxo.output.datum.cbor
    )

    if participation_index >= len(prev_datum.participations):
        raise ValueError(
            f"participation_index {participation_index} out of range "
            f"({len(prev_datum.participations)} participations)"
        )

    # Compute deterministic input ordering (redeemer embeds the staking input index)
    payment_utxos = _chain_context.utxos(user_address)
    all_inputs = sorted_utxos([staking_utxo] + list(payment_utxos))
    staking_input_index = all_inputs.index(staking_utxo)

    # Build updated staking datum with the participation removed
    new_participations = list(prev_datum.participations)
    new_participations.pop(participation_index)
    new_datum = staking_contract.StakingState(
        participations=new_participations,
        params=prev_datum.params,
    )

    reputation_token = Token(
        policy_id=reputation_policy_id.payload,
        token_name=reputation_token_name(prev_datum.params.owner),
    )

    builder = TransactionBuilder(_chain_context)
    builder.auxiliary_data = AuxiliaryData(
        data=AlonzoMetadata(metadata=Metadata({674: {"msg": ["Mint Reputation"]}}))
    )

    for utxo in payment_utxos:
        builder.add_input(utxo)

    builder.add_script_input(
        staking_utxo,
        staking_ref_utxo or staking_script,
        None,
        Redeemer(
            staking_contract.ClaimReputation(
                state_input_index=staking_input_index,
                state_output_index=0,
                participation_index=participation_index,
            )
        ),
    )

    builder.add_minting_script(
        reputation_ref_utxo or reputation_script,
        Redeemer(
            reputation_contract.MintReputation(
                staking_input_index=staking_input_index,
                staking_output_index=0,
                participation_index=participation_index,
                amount=1,
            )
        ),
    )
    builder.mint = asset_from_token(reputation_token, 1)

    builder.add_output(
        with_min_lovelace(
            TransactionOutput(
                address=staking_address,
                amount=staking_utxo.output.amount
                + Value(multi_asset=asset_from_token(reputation_token, 1)),
                datum=new_datum,
            ),
            context,
        )
    )

    # User must sign — server only contributes the collateral witness
    builder.required_signers = [user_address.payment_part]

    builder.validity_start = context.last_block_slot
    builder.ttl = context.last_block_slot + 200
    builder.fee_buffer = 100
    builder.collaterals = [get_collateral_utxo(network)]

    _, collateral_skey, collateral_address = get_collateral_signing_info(network)
    signed_tx = builder.build_and_sign(
        signing_keys=[collateral_skey],
        change_address=user_address,
        merge_change=True,
        collateral_change_address=collateral_address,
    )

    return SignedTxResponse(
        signed_tx=signed_tx.to_cbor_hex(),
        tx_body=signed_tx.transaction_body.to_cbor_hex(),
    ).model_dump()
