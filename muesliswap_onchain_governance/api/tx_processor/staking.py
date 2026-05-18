import logging

import pycardano
from opshin.ledger.api_v2 import FinitePOSIXTime

from ...onchain.staking import staking as onchain_staking
from ...utils.from_script_context import from_address
from ..config import vote_permission_nft_policy_id
from ..db_models import (
    Block,
    StakingParams,
    StakingParticipation,
    StakingState,
    TrackedGovStates,
    TransactionOutput,
)
from ..db_models.staking import (
    StakingDeposit,
    StakingDepositDelta,
    StakingDepositParticipationAdded,
    StakingDepositParticipationRemoved,
    StakingParticipationInStaking,
    VotePermission,
    VotePermissionMint,
)
from . import from_db
from .to_db import (
    add_address,
    add_datum,
    add_output,
    add_token,
    add_token_token,
    add_transaction,
)

_LOGGER = logging.getLogger(__name__)


def process_tx(
    tx: pycardano.Transaction,
    block: Block,
    block_index: int,
    tracked_gov_states: TrackedGovStates,
):
    """
    Process a transaction and update the database accordingly.
    """
    # obtain all staking addresses from the tracked gov states
    staking_addresses = set(
        from_db.from_address(gs.gov_params.staking_address).to_primitive()
        for gs in tracked_gov_states
    )

    created_states = []
    for i, output in enumerate(tx.transaction_body.outputs):
        if output.address.to_primitive() in staking_addresses:
            _LOGGER.debug(f"Staking transaction: {tx.id.payload.hex()}")
            staking_output = add_output(
                output, i, tx.id.payload.hex(), block, block_index
            )
            try:
                onchain_staking_state: onchain_staking.StakingState = (
                    onchain_staking.StakingState.from_primitive(output.datum.data)
                )
            except Exception:
                _LOGGER.info(f"Invalid staking parameters at {tx.id.payload.hex()}")
                continue
            onchain_staking_params = onchain_staking_state.params
            db_staking_params = StakingParams.get_or_create(
                owner=add_address(from_address(onchain_staking_params.owner)),
                governance_token=add_token_token(
                    onchain_staking_params.governance_token
                ),
                vault_ft_policy=onchain_staking_params.vault_ft_policy.hex(),
                delegation_policy=onchain_staking_params.delegation_policy.hex(),
                reputation_policy=onchain_staking_params.reputation_policy.hex(),
                tally_auth_nft=add_token_token(onchain_staking_params.tally_auth_nft),
            )[0]
            db_staking_state = StakingState.create(
                transaction_output=staking_output,
                staking_params=db_staking_params,
            )
            created_states.append(db_staking_state)
            for i, participation in enumerate(onchain_staking_state.participations):
                db_staking_participation = StakingParticipation.get_or_create(
                    tally_auth_nft=add_token_token(
                        participation.tally_params.tally_auth_nft
                    ),
                    proposal_id=participation.tally_params.proposal_id,
                    weight=participation.weight,
                    proposal_index=participation.proposal_index,
                    end_time=(
                        participation.tally_params.end_time.time
                        if isinstance(
                            participation.tally_params.end_time, FinitePOSIXTime
                        )
                        else None
                    ),
                )[0]
                StakingParticipationInStaking.create(
                    staking_state=db_staking_state,
                    participation=db_staking_participation,
                    index=i,
                )
    spent_states = []
    # we don't need to bother checking the inputs if no output stake is created
    # there is no way to spend a stake without creating one
    if created_states:
        for input in tx.transaction_body.inputs:
            staking_state = (
                StakingState.select()
                .join(TransactionOutput)
                .where(
                    TransactionOutput.transaction_hash
                    == input.transaction_id.payload.hex(),
                    TransactionOutput.output_index == input.index,
                )
                .first()
            )
            if staking_state is None:
                continue
            spent_states.append(staking_state)
    for created_state in created_states:
        spent_state = spent_states[0] if spent_states else None
        staking_deposit = StakingDeposit.create(
            transaction=add_transaction(tx.id.payload.hex(), block, block_index),
            prev_staking_state=spent_state,
            next_staking_state=created_state,
        )
        delta_value = pycardano.Value()
        delta_value += from_db.from_output_values(
            created_state.transaction_output.assets
        )
        if spent_state is not None:
            delta_value -= from_db.from_output_values(
                spent_state.transaction_output.assets
            )

        lovelace = delta_value.coin
        if lovelace != 0:
            StakingDepositDelta.create(
                staking_deposit=staking_deposit,
                token=add_token(b"", b""),
                amount=lovelace,
            )
        for policy_id, d in delta_value.multi_asset.items():
            for asset_name, amount in d.items():
                if amount == 0:
                    continue
                token = add_token(policy_id, asset_name)
                StakingDepositDelta.create(
                    staking_deposit=staking_deposit, token=token, amount=amount
                )
        if spent_state is not None:
            previous_participations = [
                p.participation for p in spent_state.staking_participations
            ]
        else:
            previous_participations = []
        next_participations = [
            p.participation for p in created_state.staking_participations
        ]
        for participation in previous_participations:
            if participation not in next_participations:
                StakingDepositParticipationRemoved.create(
                    staking_deposit=staking_deposit, participation=participation
                )
        for participation in next_participations:
            if participation not in previous_participations:
                StakingDepositParticipationAdded.create(
                    staking_deposit=staking_deposit, participation=participation
                )
    vote_permission_nft_policy_mint = (
        tx.transaction_body.mint.get(vote_permission_nft_policy_id)
        if tx.transaction_body.mint
        else None
    )
    if vote_permission_nft_policy_mint:
        minted_vote_permissions = []
        for asset_name, amount in vote_permission_nft_policy_mint.items():
            add_token(vote_permission_nft_policy_id, asset_name)
            minted_vote_permissions.append(asset_name.to_primitive())
        # resolve the granted permission from the redeemer
        if isinstance(tx.transaction_witness_set.redeemer, pycardano.RedeemerMap):
            redeemers = tx.transaction_witness_set.redeemer.items()
        else:
            redeemers = [
                (redeemer, redeemer) for redeemer in tx.transaction_witness_set.redeemer
            ]
        for redeemer_key, redeemer_value in redeemers:
            if redeemer_key.tag != pycardano.RedeemerTag.MINT:
                continue
            redeemer_datum = redeemer_value.data
            datum_hash = pycardano.datum_hash(redeemer_datum)
            if datum_hash.payload not in minted_vote_permissions:
                continue
            output_indices = [
                i
                for i, out in enumerate(tx.transaction_body.outputs)
                if out.amount.multi_asset.get(vote_permission_nft_policy_id, {}).get(
                    pycardano.AssetName(datum_hash.payload), 0
                )
                > 0
            ]
            for output_index in output_indices:
                VotePermissionMint.create(
                    transaction=add_transaction(
                        tx.id.payload.hex(), block, block_index
                    ),
                    vote_permission=VotePermission.get_or_create(
                        token=add_token(
                            vote_permission_nft_policy_id, datum_hash.payload
                        ),
                        delegated_action=add_datum(redeemer_datum),
                    )[0],
                    output=add_output(
                        tx.transaction_body.outputs[output_index],
                        output_index,
                        tx.id.payload.hex(),
                        block,
                        block_index,
                    ),
                )

    pass
