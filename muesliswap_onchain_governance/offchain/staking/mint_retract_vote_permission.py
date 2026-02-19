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
    GOV_STATE_NFT_TK_NAME,
)
from muesliswap_onchain_governance.onchain.tally import tally, tally_auth_nft
from muesliswap_onchain_governance.onchain.staking import (
    staking_vote_nft,
    staking,
    vote_permission_nft,
)
from ...utils import get_signing_info, ogmios_url, network, kupo_url
from ...utils.contracts import get_contract, module_name


def main(
    wallet: str = "creator",
    participation_index: int = 0,
    tally_auth_nft_tk_name: str = GOV_STATE_NFT_TK_NAME,
):
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
    (
        vote_permission_nft_script,
        vote_permission_nft_policy_id,
        _,
    ) = get_contract(module_name(vote_permission_nft), True)

    tally_auth_nft_tk = Token(
        tally_auth_nft_policy_id.payload, bytes.fromhex(tally_auth_nft_tk_name)
    )

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
        if prev_staking_datum.params.tally_auth_nft != tally_auth_nft_tk:
            continue
        if not amount_of_token_in_value(
            prev_staking_datum.params.governance_token, u.output.amount
        ):
            continue
        staking_utxo = u
        break
    assert staking_utxo, "Staking position not found"

    payment_utxos = context.utxos(payment_address)
    all_inputs = sorted_utxos(
        [staking_utxo] + payment_utxos,
    )
    staking_input_index = all_inputs.index(staking_utxo)

    # generate redeemer for the vote permission
    participation = prev_staking_datum.participations[participation_index]
    vote_permission_nft_redeemer = Redeemer(
        vote_permission_nft.VotePermissionNFTParams(
            owner=prev_staking_datum.params.owner,
            redeemer=staking.DelegatedRetractVote(
                participation=participation,
            ),
        )
    )
    vote_permission_nft_tk = Token(
        vote_permission_nft_policy_id.payload,
        vote_permission_nft.vote_permission_nft_token_name(
            vote_permission_nft_redeemer.data
        ),
    )
    # generate redeemer for the staking
    staking_redeemer = Redeemer(
        staking.AddFunds(
            state_input_index=staking_input_index,
            state_output_index=0,
        )
    )

    # generate the new datum for the staking
    new_staking_datum = prev_staking_datum

    # Build the transaction
    builder = TransactionBuilder(context)
    builder.auxiliary_data = AuxiliaryData(
        data=AlonzoMetadata(
            metadata=Metadata({674: {"msg": ["Add permission to retract vote"]}})
        )
    )
    for u in payment_utxos:
        builder.add_input(u)
    builder.add_script_input(staking_utxo, staking_script, None, staking_redeemer)

    builder.add_minting_script(
        vote_permission_nft_script,
        vote_permission_nft_redeemer,
    )
    builder.mint = asset_from_token(vote_permission_nft_tk, 1)
    builder.add_output(
        with_min_lovelace(
            pycardano.TransactionOutput(
                address=staking_address,
                amount=staking_utxo.output.amount
                + Value(multi_asset=asset_from_token(vote_permission_nft_tk, 1)),
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

    return signed_tx, vote_permission_nft_redeemer.data.to_cbor()


if __name__ == "__main__":
    fire.Fire(main)
