import datetime

import fire
import pycardano

from muesliswap_onchain_governance.onchain.tally.tally import BoxedInt
from muesliswap_onchain_governance.onchain.util import reduced_proposal_params
from muesliswap_onchain_governance.utils.network import show_tx, context
from muesliswap_onchain_governance.utils.to_script_context import to_address
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
    sorted_utxos,
    amount_of_token_in_value,
)
from muesliswap_onchain_governance.onchain.tally import tally, tally_auth_nft
from muesliswap_onchain_governance.onchain.staking import staking_vote_nft, staking
from ...utils import get_signing_info, ogmios_url, network, kupo_url
from ...utils.contracts import get_contract, module_name


def main(
    wallet: str = "creator",
    participation_index: int = 0,
    governance_token: str = "bd976e131cfc3956b806967b06530e48c20ed5498b46a5eb836b61c2.744d494c4b",
):
    # Load chain context
    governance_token = token_from_string(governance_token)

    # Load script info
    (
        tally_script,
        _,
        tally_address,
    ) = get_contract(module_name(tally), True)
    (
        staking_script,
        _,
        staking_address,
    ) = get_contract(module_name(staking), True)
    (
        staking_vote_nft_script,
        staking_vote_nft_policy_id,
        _,
    ) = get_contract(module_name(staking_vote_nft), True)
    (
        _,
        tally_auth_nft_policy_id,
        _,
    ) = get_contract(module_name(tally_auth_nft), True)

    # Get payment address
    payment_vkey, payment_skey, payment_address = get_signing_info(
        wallet, network=network
    )

    # select staking position
    staking_utxos = context.utxos(staking_address)
    staking_utxo = None
    for u in staking_utxos:
        try:
            prev_staking_datum = staking.StakingState.from_cbor(u.output.datum.cbor)
        except Exception as e:
            continue
        if prev_staking_datum.params.owner != to_address(payment_address):
            continue
        if prev_staking_datum.params.governance_token != governance_token:
            continue
        if not amount_of_token_in_value(governance_token, u.output.amount):
            continue
        if not prev_staking_datum.participations:
            continue
        staking_utxo = u
        break
    assert staking_utxo, "Staking position not found"
    tally_auth_nft_tk = prev_staking_datum.params.tally_auth_nft
    participation = prev_staking_datum.participations[participation_index]

    # Select tally
    tally_utxos = context.utxos(tally_address)
    tally_utxo = None
    for u in tally_utxos:
        if not amount_of_token_in_value(tally_auth_nft_tk, u.output.amount):
            continue
        prev_tally_datum = tally.TallyState.from_cbor(u.output.datum.cbor)
        if (
            prev_tally_datum.params.proposal_id
            == participation.tally_params.proposal_id
        ):
            tally_utxo = u
            break
    assert tally_utxo, "Tally with given proposal id not found"

    voting_power = participation.weight

    payment_utxos = context.utxos(payment_address)
    all_inputs = sorted_utxos(
        [tally_utxo] + [staking_utxo] + payment_utxos,
    )
    tally_input_index = all_inputs.index(tally_utxo)
    staking_input_index = all_inputs.index(staking_utxo)

    # generate redeemer for the tally
    tally_redeemer = Redeemer(
        tally.RetractTallyVote(
            proposal_index=participation.tally_params.proposal_id,
            weight=voting_power,
            voter_address=to_address(payment_address),
            tally_input_index=tally_input_index,
            tally_output_index=0,
            staking_output_index=1,
            staking_participation_index=participation_index,
        )
    )

    # Make the new datum of the Tally
    new_tally_votes = prev_tally_datum.votes.copy()
    new_tally_votes[participation.proposal_index] -= voting_power
    new_tally_datum = tally.TallyState(
        params=prev_tally_datum.params,
        votes=new_tally_votes,
    )

    # generate redeemer for the staking
    participation = staking.Participation(
        tally_params=reduced_proposal_params(prev_tally_datum.params),
        weight=voting_power,
        proposal_index=participation.proposal_index,
    )
    staking_redeemer = Redeemer(
        staking.RetractVote(
            state_input_index=staking_input_index,
            state_output_index=1,
            participation_index=participation_index,
            tally_input_index=tally_input_index,
        )
    )
    # generate the new datum for the staking
    new_staking_participations = prev_staking_datum.participations.copy()
    new_staking_participations.pop(participation_index)
    new_staking_datum = staking.StakingState(
        params=prev_staking_datum.params,
        participations=new_staking_participations,
    )

    # generate the redeemer for the staking vote nft
    staking_vote_nft_redeemer = Redeemer(staking_vote_nft.BurnRedeemer())
    staking_vote_nft_name = staking_vote_nft.staking_vote_nft_name(
        participation.proposal_index,
        voting_power,
        reduced_proposal_params(prev_tally_datum.params),
    )
    staking_vote_nft_tk = Token(
        staking_vote_nft_policy_id.payload, staking_vote_nft_name
    )

    # Build the transaction
    builder = TransactionBuilder(context)
    builder.auxiliary_data = AuxiliaryData(
        data=AlonzoMetadata(
            metadata=Metadata({674: {"msg": ["Retract Vote in Tally"]}})
        )
    )
    for u in payment_utxos:
        builder.add_input(u)
    builder.add_script_input(tally_utxo, tally_script, None, tally_redeemer)
    builder.add_script_input(staking_utxo, staking_script, None, staking_redeemer)

    builder.add_minting_script(
        staking_vote_nft_script,
        staking_vote_nft_redeemer,
    )
    builder.mint = asset_from_token(staking_vote_nft_tk, -1)
    tally_output = TransactionOutput(
        address=tally_address,
        amount=tally_utxo.output.amount,
        datum=new_tally_datum,
    )
    builder.add_output(tally_output)
    builder.add_output(
        with_min_lovelace(
            pycardano.TransactionOutput(
                address=staking_address,
                amount=staking_utxo.output.amount
                - Value(multi_asset=asset_from_token(staking_vote_nft_tk, 1)),
                datum=new_staking_datum,
            ),
            context,
        )
    )

    # Sign the transaction
    signed_tx = builder.build_and_sign(
        signing_keys=[payment_skey],
        change_address=payment_address,
    )

    # Submit the transaction
    context.submit_tx(signed_tx)

    show_tx(signed_tx)
    return signed_tx


if __name__ == "__main__":
    fire.Fire(main)
