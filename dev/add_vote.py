import datetime

import fire
import pycardano

from muesliswap_onchain_governance.onchain.tally.tally import BoxedInt
from muesliswap_onchain_governance.onchain.util import reduced_proposal_params
from muesliswap_onchain_governance.utils.network import show_tx, context
from muesliswap_onchain_governance.utils.to_script_context import to_address
from opshin.ledger.api_v2 import PosInfPOSIXTime
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
    token_from_string,
    asset_from_token,
    with_min_lovelace,
    sorted_utxos,
    amount_of_token_in_value,
    GOV_STATE_NFT_TK_NAME,
)
from muesliswap_onchain_governance.onchain.tally import tally, tally_auth_nft
from muesliswap_onchain_governance.onchain.staking import staking_vote_nft, staking
from muesliswap_onchain_governance.utils import (
    get_signing_info,
    ogmios_url,
    network,
    kupo_url,
)
from muesliswap_onchain_governance.utils.contracts import (
    get_contract,
    module_name,
    get_ref_utxo,
)


def main(
    wallet: str = "voter",
    proposal_id: int = 1,
    proposal_index: int = 0,
    tally_auth_nft_tk_name: str = GOV_STATE_NFT_TK_NAME,
):
    # Load script info
    (
        tally_script,
        _,
        tally_address,
    ) = get_contract(module_name(tally), True)
    tally_script = get_ref_utxo(tally_script, context) or tally_script
    (
        staking_script,
        _,
        staking_address,
    ) = get_contract(module_name(staking), True)
    staking_script = get_ref_utxo(staking_script, context) or staking_script
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
    tally_auth_nft_tk = Token(
        tally_auth_nft_policy_id.payload, bytes.fromhex(tally_auth_nft_tk_name)
    )

    # Get payment address
    payment_vkey, payment_skey, payment_address = get_signing_info(
        wallet, network=network
    )

    # Select tally
    tally_utxos = context.utxos(tally_address)
    tally_utxo = None
    prev_tally_datum = None
    for u in tally_utxos:
        if not amount_of_token_in_value(tally_auth_nft_tk, u.output.amount):
            continue
        prev_tally_datum = tally.TallyState.from_cbor(u.output.datum.cbor)
        if prev_tally_datum.params.staking_address != to_address(staking_address):
            continue
        if (
            isinstance(prev_tally_datum.params.end_time, PosInfPOSIXTime)
            or prev_tally_datum.params.end_time.time
            < datetime.datetime.now().timestamp() * 1000
        ):
            continue
        if prev_tally_datum.params.proposal_id == proposal_id:
            tally_utxo = u
            break
    assert tally_utxo, "Tally with given proposal id not found"

    # select staking position
    staking_utxos = context.utxos(staking_address)
    staking_utxo = None
    for u in staking_utxos:
        try:
            prev_staking_datum = staking.StakingState.from_cbor(u.output.datum.cbor)
        except Exception:
            continue
        if prev_staking_datum.params.owner != to_address(payment_address):
            continue
        if (
            prev_staking_datum.params.governance_token
            != prev_tally_datum.params.governance_token
        ):
            continue
        if prev_staking_datum.params.tally_auth_nft != tally_auth_nft_tk:
            continue
        if not amount_of_token_in_value(
            prev_staking_datum.params.governance_token, u.output.amount
        ):
            continue
        staking_utxo = u
        break
    assert staking_utxo, "Staking position not found"
    voting_power = staking_utxo.output.amount.multi_asset.get(
        pycardano.ScriptHash(prev_staking_datum.params.governance_token.policy_id), {}
    ).get(pycardano.AssetName(prev_staking_datum.params.governance_token.token_name))

    payment_utxos = context.utxos(payment_address)
    all_inputs = sorted_utxos(
        [tally_utxo] + [staking_utxo] + payment_utxos,
    )
    tally_input_index = all_inputs.index(tally_utxo)
    staking_input_index = all_inputs.index(staking_utxo)

    # generate redeemer for the tally
    tally_redeemer = Redeemer(
        tally.AddTallyVote(
            proposal_index=proposal_index,
            weight=voting_power,
            voter_address=to_address(payment_address),
            tally_input_index=tally_input_index,
            tally_output_index=0,
            staking_output_index=1,
            staking_input_index=BoxedInt(staking_input_index),
        )
    )

    # Make the new datum of the Tally
    new_tally_votes = prev_tally_datum.votes.copy()
    new_tally_votes[proposal_index] += voting_power
    new_tally_datum = tally.TallyState(
        params=prev_tally_datum.params,
        votes=new_tally_votes,
    )

    # generate redeemer for the staking
    participation = staking.Participation(
        tally_params=reduced_proposal_params(prev_tally_datum.params),
        weight=voting_power,
        proposal_index=proposal_index,
    )
    staking_redeemer = Redeemer(
        staking.AddVote(
            state_input_index=staking_input_index,
            state_output_index=1,
            participation=participation,
        )
    )
    # generate the new datum for the staking
    new_staking_participations = prev_staking_datum.participations.copy()
    new_staking_participations.insert(0, participation)
    new_staking_datum = staking.StakingState(
        params=prev_staking_datum.params,
        participations=new_staking_participations,
    )

    # generate the redeemer for the staking vote nft
    staking_vote_nft_redeemer = Redeemer(
        staking_vote_nft.VoteAuthRedeemer(
            tally_input_index=tally_input_index,
            tally_output_index=0,
            vote_index=proposal_index,
            staking_output_index=1,
        )
    )
    staking_vote_nft_name = staking_vote_nft.staking_vote_nft_name(
        proposal_index,
        voting_power,
        reduced_proposal_params(prev_tally_datum.params),
    )
    staking_vote_nft_tk = Token(
        staking_vote_nft_policy_id.payload, staking_vote_nft_name
    )

    # Build the transaction
    builder = TransactionBuilder(context)
    builder.auxiliary_data = AuxiliaryData(
        data=AlonzoMetadata(metadata=Metadata({674: {"msg": ["Vote in Tally"]}}))
    )
    for u in payment_utxos:
        builder.add_input(u)
    builder.add_script_input(tally_utxo, tally_script, None, tally_redeemer)
    builder.add_script_input(staking_utxo, staking_script, None, staking_redeemer)

    builder.add_minting_script(
        get_ref_utxo(staking_vote_nft_script, context) or staking_vote_nft_script,
        staking_vote_nft_redeemer,
    )
    builder.mint = asset_from_token(staking_vote_nft_tk, 1)
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
                + Value(multi_asset=asset_from_token(staking_vote_nft_tk, 1)),
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
    return signed_tx, new_tally_datum


if __name__ == "__main__":
    fire.Fire(main)
