from datetime import datetime, timezone
from time import sleep
import random
from collections import defaultdict

import fire
import pycardano

from muesliswap_onchain_governance.onchain.tally.tally import BoxedInt
from muesliswap_onchain_governance.onchain.util import reduced_proposal_params
from muesliswap_onchain_governance.utils.network import (
    show_tx,
    blockfrost_client,
    context,
)
from muesliswap_onchain_governance.utils.to_script_context import to_address
from opshin.prelude import Token, Nothing, FinitePOSIXTime, PosInfPOSIXTime
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
    asset_from_token,
    with_min_lovelace,
    sorted_utxos,
    amount_of_token_in_value,
    remove_zero_values,
)
from muesliswap_onchain_governance.onchain.tally import tally, tally_auth_nft
from muesliswap_onchain_governance.onchain.staking import (
    staking_vote_nft,
    staking,
    vote_permission_nft,
)
from muesliswap_onchain_governance.utils import (
    get_signing_info,
    network,
)
from muesliswap_onchain_governance.utils.contracts import (
    get_contract,
    module_name,
    get_ref_utxo,
)

# "txid:[redeemer_hash]"
BAD_REQUESTS = defaultdict(list)


def main(
    wallet: str = "creator",
    retry_interval: int = 5,
):
    while True:
        try:
            execute_permissioned_vote_requests(
                wallet=wallet,
            )
        except KeyboardInterrupt:
            break
        except Exception as e:
            print(e)
        print(
            f"Press Ctrl+C to stop. Trying again in {retry_interval} seconds...",
            flush=True,
        )
        sleep(retry_interval)


def get_vote_permissions_from_staking_utxo(
    staking_utxo: pycardano.UTxO,
    vote_permission_nft_policy_id: pycardano.ScriptHash,
) -> list[tuple[pycardano.CBORSerializable, Token]]:
    vote_permission_nft_names = [
        tk.payload
        for tk in staking_utxo.output.amount.multi_asset.get(
            pycardano.ScriptHash(vote_permission_nft_policy_id.payload), {}
        ).keys()
    ]
    vote_permission_nft_tks = [
        Token(vote_permission_nft_policy_id.payload, name)
        for name in vote_permission_nft_names
    ]
    # We can simply look this up because the token name is the same as the datum hash of the redeemer during minting - it is hence known to most indexers
    vote_permission_raw_cbors = [
        blockfrost_client.script_datum_cbor(tk.token_name.hex()).cbor
        for tk in vote_permission_nft_tks
    ]

    vote_permissions = [
        vote_permission_nft.VotePermissionNFTParams.from_cbor(raw_cbor)
        for raw_cbor in vote_permission_raw_cbors
    ]

    filtered = [
        (tk, vp)
        for tk, vp in zip(vote_permission_nft_tks, vote_permissions)
        if (
            isinstance(vp.redeemer, vote_permission_nft.DelegatedAddVote)
            and vp.redeemer.hash().payload.hex()
            not in BAD_REQUESTS[staking_utxo.input.transaction_id.payload.hex()]
        )
    ]
    if not filtered:
        return [], []
    vote_permission_nft_tks, vote_permissions = zip(*filtered)
    return vote_permissions, vote_permission_nft_tks


def execute_permissioned_vote_requests(
    wallet: str = "creator",
):
    # Load script info
    (
        tally_script,
        _,
        tally_address,
    ) = get_contract(module_name(tally), True)
    tally_script_ref_utxo = get_ref_utxo(tally_script, context)
    (
        staking_script,
        _,
        staking_address,
    ) = get_contract(module_name(staking), True)
    staking_script_ref_utxo = get_ref_utxo(staking_script, context)
    (
        staking_vote_nft_script,
        staking_vote_nft_policy_id,
        _,
    ) = get_contract(module_name(staking_vote_nft), True)
    staking_vote_nft_ref_utxo = get_ref_utxo(staking_vote_nft_script, context)
    (
        vote_permission_nft_script,
        vote_permission_nft_policy_id,
        _,
    ) = get_contract(module_name(vote_permission_nft), True)
    vote_permission_nft_ref_utxo = get_ref_utxo(vote_permission_nft_script, context)

    # Get payment address
    _, payment_skey, payment_address = get_signing_info(wallet, network=network)

    # find staking position with vote permission
    staking_utxos = context.utxos(staking_address)
    random.shuffle(staking_utxos)
    staking_utxo = None
    for u in staking_utxos:
        try:
            prev_staking_datum = staking.StakingState.from_cbor(u.output.datum.cbor)
        except Exception:
            continue
        if prev_staking_datum.params.owner == to_address(payment_address):
            continue
        if not u.output.amount.multi_asset.get(
            pycardano.ScriptHash(vote_permission_nft_policy_id.payload), {}
        ):
            continue
        vote_permissions, vote_permission_nft_tks = (
            get_vote_permissions_from_staking_utxo(u, vote_permission_nft_policy_id)
        )
        if not vote_permissions:
            continue

        # pick vote permission with latest end time
        if any(
            isinstance(vp.redeemer.participation.tally_params.end_time, PosInfPOSIXTime)
            for vp in vote_permissions
        ):
            vote_permission, vote_permission_nft_tk = [
                (vp, tk)
                for vp, tk in zip(vote_permissions, vote_permission_nft_tks)
                if isinstance(
                    vp.redeemer.participation.tally_params.end_time, PosInfPOSIXTime
                )
            ][0]
        else:
            vote_permission, vote_permission_nft_tk = [
                (vp, tk)
                for vp, tk in zip(vote_permissions, vote_permission_nft_tks)
                if vp.redeemer.participation.tally_params.end_time.time
                >= max(
                    [
                        vp.redeemer.participation.tally_params.end_time.time
                        for vp in vote_permissions
                    ]
                )
            ][0]
        # skip tallies that have already ended
        end_time = vote_permission.redeemer.participation.tally_params.end_time

        if isinstance(end_time, FinitePOSIXTime) and end_time.time < int(
            datetime.now(timezone.utc).timestamp() * 1000
        ):
            continue
        staking_utxo = u
        break
    assert staking_utxo, "Staking position with vote permission not found"

    proposal_id = vote_permission.redeemer.participation.tally_params.proposal_id

    tally_auth_nft_tk = (
        vote_permission.redeemer.participation.tally_params.tally_auth_nft
    )
    # Select tally
    tally_utxos = context.utxos(tally_address)
    random.shuffle(tally_utxos)
    tally_utxo = None
    for u in tally_utxos:
        if not amount_of_token_in_value(tally_auth_nft_tk, u.output.amount):
            continue
        prev_tally_datum = tally.TallyState.from_cbor(u.output.datum.cbor)
        if prev_tally_datum.params.proposal_id == proposal_id:
            tally_utxo = u
            break
    assert tally_utxo, "Tally with given proposal id not found"

    voting_power = vote_permission.redeemer.participation.weight
    proposal_index = vote_permission.redeemer.participation.proposal_index

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
            voter_address=vote_permission.owner,
            tally_input_index=tally_input_index,
            tally_output_index=0,
            staking_output_index=1,
            staking_input_index=BoxedInt(staking_input_index),
        ),
    )

    # Make the new datum of the Tally
    new_tally_votes = prev_tally_datum.votes.copy()
    new_tally_votes[proposal_index] += voting_power
    new_tally_datum = tally.TallyState(
        params=prev_tally_datum.params,
        votes=new_tally_votes,
    )

    # generate redeemer for the staking
    participation = vote_permission.redeemer.participation
    staking_redeemer = Redeemer(
        staking.AddVote(
            state_input_index=staking_input_index,
            state_output_index=1,
            participation=participation,
        ),
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
        ),
    )
    staking_vote_nft_name = staking_vote_nft.staking_vote_nft_name(
        proposal_index,
        voting_power,
        reduced_proposal_params(prev_tally_datum.params),
    )
    staking_vote_nft_tk = Token(
        staking_vote_nft_policy_id.payload, staking_vote_nft_name
    )
    vote_permission_nft_redeemer = Redeemer(Nothing())

    # Build the transaction
    builder = TransactionBuilder(context)
    builder.auxiliary_data = AuxiliaryData(
        data=AlonzoMetadata(
            metadata=Metadata({674: {"msg": ["Vote in Tally (delegated)"]}})
        )
    )
    for u in payment_utxos:
        builder.add_input(u)
    builder.add_script_input(
        tally_utxo, tally_script_ref_utxo or tally_script, None, tally_redeemer
    )
    builder.add_script_input(
        staking_utxo, staking_script_ref_utxo or staking_script, None, staking_redeemer
    )

    builder.add_minting_script(
        staking_vote_nft_ref_utxo or staking_vote_nft_script,
        staking_vote_nft_redeemer,
    )
    builder.add_minting_script(
        vote_permission_nft_ref_utxo or vote_permission_nft_script,
        vote_permission_nft_redeemer,
    )
    builder.mint = asset_from_token(staking_vote_nft_tk, 1) + asset_from_token(
        vote_permission_nft_tk, -1
    )
    tally_output = TransactionOutput(
        address=tally_address,
        amount=tally_utxo.output.amount,
        datum=new_tally_datum,
    )
    builder.add_output(tally_output)
    out_amount = remove_zero_values(
        staking_utxo.output.amount
        + Value(multi_asset=asset_from_token(staking_vote_nft_tk, 1))
        - Value(multi_asset=asset_from_token(vote_permission_nft_tk, 1))
    )
    builder.add_output(
        with_min_lovelace(
            pycardano.TransactionOutput(
                address=staking_address,
                amount=out_amount,
                datum=new_staking_datum,
            ),
            context,
        )
    )

    try:
        # Sign the transaction
        signed_tx = builder.build_and_sign(
            signing_keys=[payment_skey],
            change_address=payment_address,
        )

        # Submit the transaction
        context.submit_tx(signed_tx)

        show_tx(signed_tx)
        return signed_tx
    except Exception as e:
        print(f"Error submitting tx: {e}")
        BAD_REQUESTS[staking_utxo.input.transaction_id.payload.hex()].append(
            vote_permission.redeemer.hash().payload.hex()
        )


if __name__ == "__main__":
    fire.Fire(main)
