import datetime
import logging

import pycardano

from ...offchain.util import TALLY_METADATA_KEY
from ...onchain.tally import tally as onchain_tally
from ...utils.from_script_context import from_address
from ..db_models import Block, TrackedGovStates, TransactionOutput
from ..db_models import tally_state as db_tally
from . import from_db
from .to_db import (
    add_address,
    add_address_raw,
    add_datum,
    add_output,
    add_token_token,
    add_transaction,
)

_LOGGER = logging.getLogger(__name__)
_LOGGER.setLevel(logging.DEBUG)


def process_tx(
    tx: pycardano.Transaction,
    block: Block,
    block_index: int,
    tracked_gov_states: TrackedGovStates,
):
    """
    Process a transaction and update the database accordingly.
    """
    tally_auth_nft_policy_ids = set(
        pycardano.ScriptHash(bytes.fromhex(gs.gov_params.tally_auth_nft_policy))
        for gs in tracked_gov_states
    )
    tally_addresses = set(
        from_db.from_address(gs.gov_params.tally_address).to_primitive()
        for gs in tracked_gov_states
    )
    created_states = []
    participants = set()
    for i, output in enumerate(tx.transaction_body.outputs):
        if output.address.to_primitive() not in tally_addresses:
            participants.add(output.address.to_primitive())
            continue
        _LOGGER.info(f"Transaction contains tally {tx.id.payload.hex()}")
        tally_auth_nft_policy_id = tally_auth_nft_policy_ids.intersection(
            output.amount.multi_asset.keys()
        )
        if not tally_auth_nft_policy_id:
            _LOGGER.warning(
                f"Transaction output does not contain tally auth nft {tx.id.payload.hex()}"
            )
            continue
        tally_output = add_output(output, i, tx.id.payload.hex(), block, block_index)
        try:
            onchain_tally_state: onchain_tally = (
                onchain_tally.TallyState.from_primitive(output.datum.data)
            )
        except Exception:
            _LOGGER.info(f"Invalid gov state parameters at {tx.id.payload.hex()}")
            continue

        onchain_tally_params = onchain_tally_state.params
        db_tally_params_title = ""
        db_tally_params_description = ""
        db_tally_params_short_description = ""
        db_tally_params_creator_name = ""
        db_tally_params_forum_link = ""
        try:
            if isinstance(tx.auxiliary_data.data, pycardano.Metadata):
                metadata = tx.auxiliary_data.data
            else:
                metadata = tx.auxiliary_data.data.metadata
            onchain_metadata = metadata[TALLY_METADATA_KEY]
            expected_fields = {
                "title",
                "description",
                "creator_name",
                "forum_link",
                "proposals",
                "short_description",
            }
            for k in expected_fields:
                assert k in onchain_metadata, f"Missing metadata field {k}"
            assert len(onchain_metadata["proposals"]) == len(
                onchain_tally_params.proposals
            ), "Mismatch in number of proposals for metadata"

            db_tally_params_title = "".join(onchain_metadata["title"])
            db_tally_params_description = "".join(onchain_metadata["description"])
            db_tally_params_short_description = "".join(
                onchain_metadata["short_description"]
            )
            db_tally_params_creator_name = "".join(onchain_metadata["creator_name"])
            db_tally_params_forum_link = "".join(onchain_metadata["forum_link"])
        except Exception as e:
            _LOGGER.info(f"Invalid metadata at {tx.id.payload.hex()}: {e}")
        db_tally_metadata = db_tally.TallyMetadata.get_or_create(
            title=db_tally_params_title,
            description=db_tally_params_description,
            short_description=db_tally_params_short_description,
            creator_name=db_tally_params_creator_name,
            forum_link=db_tally_params_forum_link,
        )[0]
        db_tally_params = db_tally.TallyParams.get_or_create(
            quorum=onchain_tally_params.quorum,
            end_time=(
                datetime.datetime.fromtimestamp(
                    onchain_tally_params.end_time.time / 1000
                )
                if isinstance(
                    onchain_tally_params.end_time, onchain_tally.FinitePOSIXTime
                )
                else None
            ),
            winning_threshold_numerator=onchain_tally_params.winning_threshold.numerator,
            winning_threshold_denominator=onchain_tally_params.winning_threshold.denominator,
            proposal_id=onchain_tally_params.proposal_id,
            tally_auth_nft=add_token_token(onchain_tally_params.tally_auth_nft),
            staking_vote_nft_policy=onchain_tally_params.staking_vote_nft_policy.hex(),
            staking_address=add_address(
                from_address(onchain_tally_params.staking_address)
            ),
            governance_token=add_token_token(onchain_tally_params.governance_token),
            vault_ft_policy=onchain_tally_params.vault_ft_policy.hex(),
            delegation_policy=onchain_tally_params.delegation_policy.hex(),
            metadata=db_tally_metadata,
        )[0]

        for i, proposal in enumerate(onchain_tally_params.proposals):
            try:
                proposal_metadata = onchain_metadata["proposals"][i]
                db_tally_proposal_title = "".join(proposal_metadata["title"])
                db_tally_proposal_description = "".join(
                    proposal_metadata["description"]
                )
            except Exception as e:
                db_tally_proposal_title = ""
                db_tally_proposal_description = ""
                _LOGGER.info(f"Invalid proposal metadata at {tx.id.payload.hex()}: {e}")
            db_tally_proposal_metadata = db_tally.TallyProposalMetadata.get_or_create(
                title=db_tally_proposal_title,
                description=db_tally_proposal_description,
            )[0]
            db_tally.TallyProposals.get_or_create(
                index=i,
                tally_params=db_tally_params,
                proposal=add_datum(proposal),
                metadata=db_tally_proposal_metadata,
            )

        _db_tally = db_tally.TallyState.create(
            transaction_output=tally_output,
            tally_params=db_tally_params,
        )
        for i, weight in enumerate(onchain_tally_state.votes):
            db_tally.TallyWeights.get_or_create(
                index=i,
                tally_state=_db_tally,
                weight=weight,
            )
        created_states.append(_db_tally)

    spent_states = []
    spent_gov_states = []
    spent_staking_states = []
    # we don't need to bother checking the inputs if no output stake is created
    # there is no way to spend a tally without creating one
    if created_states:
        for input in tx.transaction_body.inputs:
            _db_tally = (
                db_tally.TallyState.select()
                .join(TransactionOutput)
                .where(
                    TransactionOutput.transaction_hash
                    == input.transaction_id.payload.hex(),
                    TransactionOutput.output_index == input.index,
                )
                .first()
            )
            _db_gov_state = (
                db_tally.GovState.select()
                .join(TransactionOutput)
                .where(
                    TransactionOutput.transaction_hash
                    == input.transaction_id.payload.hex(),
                    TransactionOutput.output_index == input.index,
                )
                .first()
            )
            _db_staking_state = (
                db_tally.StakingState.select()
                .join(TransactionOutput)
                .where(
                    TransactionOutput.transaction_hash
                    == input.transaction_id.payload.hex(),
                    TransactionOutput.output_index == input.index,
                )
                .first()
            )
            if _db_tally is not None:
                spent_states.append(_db_tally)
            if _db_gov_state is not None:
                spent_gov_states.append(_db_gov_state)
            if _db_staking_state is not None:
                spent_staking_states.append(_db_staking_state)

        # if no tally was spent, then this was the creation of a new tally
        if not spent_states and spent_gov_states:
            for created_state in created_states:
                tally_creation = db_tally.TallyCreation.create(
                    transaction=add_transaction(
                        tx.id.payload.hex(), block, block_index
                    ),
                    gov_state=spent_gov_states[0],
                    next_tally_state=created_state,
                )
                for participant in participants:
                    db_tally.TallyCreationParticipants.create(
                        tally_creation=tally_creation,
                        address=add_address_raw(participant),
                    )
        # if a tally and a stake was spent, then this was a vote
        if spent_states and spent_staking_states:
            for created_state in created_states:
                # because it is convenient, we just fetch the vote delta from the database
                previous_tally_state = spent_states[0]
                OldWeights = db_tally.TallyWeights.alias()
                NewWeights = db_tally.TallyWeights.alias()
                res = (
                    OldWeights.select(
                        NewWeights.weight - OldWeights.weight,
                        OldWeights.index,
                    )
                    .join(NewWeights, on=(OldWeights.index == NewWeights.index))
                    .where(
                        OldWeights.tally_state == previous_tally_state,
                        NewWeights.tally_state == created_state,
                        OldWeights.weight != NewWeights.weight,
                    )
                    .scalar(as_tuple=True)
                )
                delta, index = res
                db_tally.TallyVote.create(
                    transaction=add_transaction(
                        tx.id.payload.hex(), block, block_index
                    ),
                    staking_state=spent_staking_states[0],
                    index=index,
                    weight_delta=delta,
                    prev_tally_state=previous_tally_state,
                    next_tally_state=created_state,
                )
                # re-use metadata from previous state
                created_state.tally_params.metadata = (
                    previous_tally_state.tally_params.metadata
                )
                created_state.tally_params.save()
                for new_tp, old_tp in zip(
                    created_state.tally_params.tally_proposals,
                    previous_tally_state.tally_params.tally_proposals,
                ):
                    new_tp.metadata = old_tp.metadata
                    new_tp.save()
