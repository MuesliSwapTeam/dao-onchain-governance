import fire
import pycardano
from pycardano import (
    AlonzoMetadata,
    AuxiliaryData,
    Metadata,
    Redeemer,
    TransactionBuilder,
    Value,
)

from muesliswap_onchain_governance.onchain.reputation import reputation
from muesliswap_onchain_governance.onchain.staking import staking
from muesliswap_onchain_governance.onchain.util import reputation_token_name
from muesliswap_onchain_governance.utils.network import context, show_tx

from ...utils import get_signing_info, network
from ...utils.contracts import get_contract, get_ref_utxo, module_name
from ...utils.to_script_context import to_address
from ..util import asset_from_token, sorted_utxos, with_min_lovelace
from opshin.prelude import Token


def main(
    wallet: str = "voter",
    participation_index: int = 0,
    reputation_amount: int = 1,
):
    (
        staking_script,
        _,
        staking_address,
    ) = get_contract(module_name(staking), True)
    staking_script_ref_utxo = get_ref_utxo(staking_script, context)
    (
        reputation_script,
        reputation_policy_id,
        _,
    ) = get_contract(module_name(reputation), True)
    reputation_script_ref_utxo = get_ref_utxo(reputation_script, context)

    _, payment_skey, payment_address = get_signing_info(wallet, network=network)

    staking_utxo = None
    prev_staking_datum = None
    for utxo in context.utxos(staking_address):
        if utxo.output.datum is None:
            continue
        try:
            candidate = staking.StakingState.from_cbor(utxo.output.datum.cbor)
        except Exception:
            continue
        if candidate.params.owner != to_address(payment_address):
            continue
        if len(candidate.participations) <= participation_index:
            continue
        if candidate.params.reputation_policy != reputation_policy_id.payload:
            continue
        staking_utxo = utxo
        prev_staking_datum = candidate
        break
    assert staking_utxo is not None, "Staking position with participation not found"

    payment_utxos = context.utxos(payment_address)
    all_inputs = sorted_utxos([staking_utxo] + payment_utxos)
    staking_input_index = all_inputs.index(staking_utxo)

    new_participations = prev_staking_datum.participations.copy()
    new_participations.pop(participation_index)
    new_staking_datum = staking.StakingState(
        participations=new_participations,
        params=prev_staking_datum.params,
    )
    reputation_token = Token(
        reputation_policy_id.payload,
        reputation_token_name(prev_staking_datum.params.owner),
    )

    builder = TransactionBuilder(context)
    builder.auxiliary_data = AuxiliaryData(
        data=AlonzoMetadata(metadata=Metadata({674: {"msg": ["Mint reputation"]}}))
    )
    for utxo in payment_utxos:
        builder.add_input(utxo)
    builder.add_script_input(
        staking_utxo,
        staking_script_ref_utxo or staking_script,
        None,
        Redeemer(
            staking.ClaimReputation(
                state_input_index=staking_input_index,
                state_output_index=0,
                participation_index=participation_index,
            )
        ),
    )
    builder.add_minting_script(
        reputation_script_ref_utxo or reputation_script,
        Redeemer(
            reputation.MintReputation(
                staking_input_index=staking_input_index,
                staking_output_index=0,
                participation_index=participation_index,
                amount=reputation_amount,
            )
        ),
    )
    builder.mint = asset_from_token(reputation_token, reputation_amount)
    builder.add_output(
        with_min_lovelace(
            pycardano.TransactionOutput(
                address=staking_address,
                amount=staking_utxo.output.amount
                + Value(
                    multi_asset=asset_from_token(reputation_token, reputation_amount)
                ),
                datum=new_staking_datum,
            ),
            context,
        )
    )
    builder.validity_start = context.last_block_slot
    builder.ttl = context.last_block_slot + 200

    signed_tx = builder.build_and_sign(
        signing_keys=[payment_skey],
        change_address=payment_address,
    )
    context.submit_tx(signed_tx)
    show_tx(signed_tx)
    return signed_tx, reputation_token.token_name.hex()


if __name__ == "__main__":
    fire.Fire(main)
