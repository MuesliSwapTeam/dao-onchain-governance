import datetime
import logging
from typing import List, Optional

import opshin.prelude as opshin
import pycardano
from opshin.prelude import Token

from muesliswap_onchain_governance.api.db_models import sqlite_db
from muesliswap_onchain_governance.offchain.util import (
    GOV_STATE_NFT_TK_NAME,
    OLD_GOV_STATE_NFT_TK_NAME,
    PROPOSAL_CONSTRUCTORS_TO_TYPES,
)
from muesliswap_onchain_governance.onchain.gov_state.gov_state import (
    GovStateUpdateParams,
)
from muesliswap_onchain_governance.onchain.gov_state.gov_state_types import (
    CreateSubDaoParams,
)
from muesliswap_onchain_governance.onchain.licenses.licenses import LicenseReleaseParams
from muesliswap_onchain_governance.onchain.simple_pool.classes import (
    PoolUpgradeParams,
    UpgradeablePoolParams,
)
from muesliswap_onchain_governance.onchain.treasury.treasurer import FundPayoutParams
from muesliswap_onchain_governance.utils.from_script_context import from_address

LOGGER = logging.getLogger(__name__)


def parse_important_proposal_info(proposal_cbor: str):
    proposal_dict = pycardano.RawPlutusData.from_cbor(proposal_cbor).to_dict()

    if not proposal_dict.get("constructor"):
        if proposal_dict.get("bytes"):  # Opinion
            return {
                "opinion": bytes.fromhex(proposal_dict["bytes"]).decode(
                    "utf-8", errors="ignore"
                )
            }
        else:
            return {}

    if proposal_dict["constructor"] == 100:  # Gov state update
        try:
            proposal = GovStateUpdateParams.from_cbor(proposal_cbor)
        except Exception as e:
            LOGGER.warning(f"Failed to parse GovStateUpdateParams from cbor: {e}")
            return {}
        return {
            "address": from_address(proposal.address).encode(),
            "params": {
                "tally_address": from_address(proposal.params.tally_address).encode(),
                "staking_address": from_address(
                    proposal.params.staking_address
                ).encode(),
                "governance_token": {
                    "policy_id": proposal.params.governance_token.policy_id.hex(),
                    "asset_name": proposal.params.governance_token.token_name.hex(),
                },
                "vault_ft_policy_id": proposal.params.vault_ft_policy.hex(),
                "delegation_policy": proposal.params.delegation_policy.hex(),
                "min_quorum": proposal.params.min_quorum,
                "min_winning_threshold": f"{proposal.params.min_winning_threshold.numerator}/{proposal.params.min_winning_threshold.denominator}",
                "min_proposal_duration": proposal.params.min_proposal_duration // 1000,
                "gov_state_nft": {
                    "policy_id": proposal.params.gov_state_nft.policy_id.hex(),
                    "asset_name": proposal.params.gov_state_nft.token_name.hex(),
                },
                "tally_auth_nft_policy": proposal.params.tally_auth_nft_policy.hex(),
                "staking_vote_nft_policy": proposal.params.staking_vote_nft_policy.hex(),
            },
        }
    elif proposal_dict["constructor"] == 101:  # CreateSubDaoParams or Batcher License (same CONSTR_ID)
        # Try CreateSubDaoParams first — its first field is a nested GovStateParams
        try:
            proposal = CreateSubDaoParams.from_cbor(proposal_cbor)
            _ = proposal.params.gov_state_nft  # probe nested field to confirm correct parse
            return {
                "sub_dao_params": {
                    "gov_state_nft": {
                        "policy_id": proposal.params.gov_state_nft.policy_id.hex(),
                        "asset_name": proposal.params.gov_state_nft.token_name.hex(),
                    },
                    "tally_address": from_address(proposal.params.tally_address).encode(),
                    "governance_token": {
                        "policy_id": proposal.params.governance_token.policy_id.hex(),
                        "asset_name": proposal.params.governance_token.token_name.hex(),
                    },
                    "tally_auth_nft_policy": proposal.params.tally_auth_nft_policy.hex(),
                    "parent_gov_nft": {
                        "policy_id": proposal.params.parent_gov_nft.policy_id.hex(),
                        "asset_name": proposal.params.parent_gov_nft.token_name.hex(),
                    },
                    "min_quorum": proposal.params.min_quorum,
                    "min_winning_threshold": f"{proposal.params.min_winning_threshold.numerator}/{proposal.params.min_winning_threshold.denominator}",
                    "min_proposal_duration": proposal.params.min_proposal_duration // 1000,
                },
                "address": from_address(proposal.address).encode(),
            }
        except Exception:
            pass  # Not a CreateSubDaoParams, fall through to LicenseReleaseParams
        try:
            proposal = LicenseReleaseParams.from_cbor(proposal_cbor)
        except Exception as e:
            LOGGER.warning(f"Failed to parse constructor 101 from cbor: {e}")
            return {}
        return {
            "recipient": from_address(proposal.address).encode(),
            "license_validity": proposal.maximum_future_validity // 1000,
        }

    elif proposal_dict["constructor"] == 102:  # Treasury Payout
        try:
            proposal = FundPayoutParams.from_cbor(proposal_cbor)
        except Exception as e:
            LOGGER.warning(f"Failed to parse FundPayoutParams from cbor: {e}")
            return {}

        payout_value = []
        for pid in proposal.output.value:
            for tname in proposal.output.value[pid]:
                amount = proposal.output.value[pid][tname]
                if amount > 0:
                    payout_value.append(
                        {
                            "policy_id": pid.hex(),
                            "asset_name": tname.decode("utf-8", errors="ignore"),
                            "amount": amount,
                        }
                    )
        return {
            "recipient": from_address(proposal.output.address).encode(),
            "value": payout_value,
        }
    elif proposal_dict["constructor"] == 106:  # Pool upgrade
        try:
            proposal = PoolUpgradeParams.from_cbor(proposal_cbor)
        except Exception as e:
            LOGGER.warning(f"Failed to parse PoolUpgradeParams from cbor: {e}")
            return {}
        return {
            "affects_pool": (
                proposal.old_pool_nft.token_name.hex()
                if isinstance(proposal.old_pool_nft, opshin.Token)
                else "all"
            ),
            "new_pool_address": (
                from_address(proposal.new_pool_address).encode()
                if isinstance(proposal.new_pool_address, opshin.Address)
                else None
            ),
            "new_pool_params": (
                {
                    "fee": f"{proposal.new_pool_params.fee.numerator}/{proposal.new_pool_params.fee.denominator}",
                    "auth_nft": {
                        "policy_id": proposal.new_pool_params.auth_nft.policy_id.hex(),
                        "asset_name": proposal.new_pool_params.auth_nft.token_name.hex(),
                    },
                    "license_policy_id": proposal.new_pool_params.license_policy_id.hex(),
                }
                if isinstance(proposal.new_pool_params, UpgradeablePoolParams)
                else None
            ),
        }
    else:
        return {}


def parse_merged_tally_votes(
    weights: str,
    indices: str,
    proposals: str,
    proposal_indices: str,
    proposal_titles: str = "",
    proposal_descriptions: str = "",
):
    weights = weights.split(";")
    indices = indices.split(";")
    proposals = proposals.split(";")
    proposal_titles = (
        proposal_titles.split(";") if proposal_titles else [""] * len(proposals)
    )
    proposal_descriptions = (
        proposal_descriptions.split(";")
        if proposal_descriptions
        else [""] * len(proposals)
    )
    proposal_indices = proposal_indices.split(";")
    votes = [{} for _ in range(len(weights))]
    for weight, index in zip(weights, indices):
        votes[int(index)]["weight"] = int(weight)
    for proposal, title, description, proposal_index in zip(
        proposals, proposal_titles, proposal_descriptions, proposal_indices
    ):
        votes[int(proposal_index)]["proposal"] = pycardano.RawPlutusData.from_cbor(
            proposal
        ).to_dict()
        votes[int(proposal_index)]["details"] = parse_important_proposal_info(proposal)
        votes[int(proposal_index)]["proposal_cbor"] = proposal.lower()
        votes[int(proposal_index)]["title"] = title
        votes[int(proposal_index)]["description"] = description
    return votes


def parse_datetime(date_str: Optional[str]) -> Optional[datetime.datetime]:
    if date_str is None:
        return None
    try:
        return datetime.datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S.%f")
    except ValueError:
        return datetime.datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S")


def is_batcher_license_tally(tally_votes: List[dict]) -> bool:
    """
    Checks if the tally votes correspond to a canonical batcher license tally.
    Such a tally should include only the default reject option and the license proposal.

    Note: A canonical batcher license tally should also have no finite end time. If
    relevant, this should be checked by the calling function
    """
    return len(tally_votes) == 2 and tally_votes[1].get("details", {}).get("recipient")


def query_tallies(
    closed: bool = True,
    open: bool = True,
    contains_proposal_type: List[str] = ["any"],
    gov_nft_asset_name: Optional[str] = None,
):
    """
    Query tallies from the database.
    :param closed: Show closed tallies.
    :param open: Show open tallies.
    :return:
    """
    if open and closed:
        dateconstraint = ""
    elif open:
        dateconstraint = (
            "and (tp.end_time is NULL or DATETIME(tp.end_time) > DATETIME('now'))"
        )
    elif closed:
        dateconstraint = "and DATETIME(tp.end_time) <= DATETIME('now')"
    else:
        return []
    cursor = sqlite_db.execute_sql(
        """
        with merged_tally_votes as (
          select
          sum(tw.weight) as total_weight,
          group_concat(tw.weight, ';') as weights,
          group_concat(tw."index", ';') as indices,
          tw.tally_state_id
          from tallyweights tw
          group by tw.tally_state_id
        ),
        merged_tally_proposals as (
            select
            tp.tally_params_id,
            group_concat(hex(d.data), ';') as proposals,
            group_concat(tp."index", ';') as indices,
            group_concat(tpm."title", ';') as titles,
            group_concat(tpm."description", ';') as descriptions
            from tallyproposals tp
            join datum d on tp.proposal_id = d.id
            join tallyproposalmetadata tpm on tp.metadata_id = tpm.id
            group by tp.tally_params_id
        )
        
        SELECT 
        tp.quorum,
        tp.end_time,
        tp.proposal_id,
        tally_auth_nft.policy_id,
        tally_auth_nft.asset_name,
        tp.staking_vote_nft_policy,
        staking_address.address_raw,
        gov_token.policy_id,
        gov_token.asset_name,
        tp.vault_ft_policy,
        tp.delegation_policy,
        mtv.total_weight,
        mtv.weights,
        mtv.indices,
        mtp.proposals,
        mtp.indices,
        tx_out.transaction_hash,
        tx_out.output_index,
        tmd.title,
        tmd.description,
        tmd.short_description,
        tmd.creator_name,
        tmd.forum_link,
        mtp.titles,
        mtp.descriptions,
        (tp.end_time is NULL or DATETIME(tp.end_time) > DATETIME('now')),
        tp.winning_threshold_numerator,
        tp.winning_threshold_denominator
        FROM tallystate ts
        join tallyparams tp on ts.tally_params_id = tp.id
        join tallymetadata tmd on tp.metadata_id = tmd.id
        join merged_tally_votes mtv on ts.id = mtv.tally_state_id
        join merged_tally_proposals mtp on tp.id = mtp.tally_params_id
        join transactionoutput tx_out on ts.transaction_output_id = tx_out.id
        join token tally_auth_nft on tp.tally_auth_nft_id = tally_auth_nft.id
        join address staking_address on tp.staking_address_id = staking_address.id
        join token gov_token on tp.governance_token_id = gov_token.id
        where tx_out.spent_in_block_id is NULL
        """
        + dateconstraint
        + """
        order by tp.end_time asc nulls first
        """
    )
    allowed_nft_names = (
        [gov_nft_asset_name]
        if gov_nft_asset_name is not None
        else [GOV_STATE_NFT_TK_NAME, OLD_GOV_STATE_NFT_TK_NAME]
    )
    results = []
    for row in cursor.fetchall():
        # filter to the requested DAO thread
        if row[4] not in allowed_nft_names:
            continue

        tally_votes = parse_merged_tally_votes(
            row[12], row[13], row[14], row[15], row[23], row[24]
        )
        for v in tally_votes:
            v["proposal_type"] = PROPOSAL_CONSTRUCTORS_TO_TYPES.get(
                v["proposal"].get("constructor", -1), None
            )
            # Constructor 101 is shared by LicenseRelease and CreateSubDao.
            # Override the type when the parsed details indicate a sub-DAO proposal.
            if v.get("details", {}).get("sub_dao_params"):
                v["proposal_type"] = "CreateSubDao"
        if "any" not in contains_proposal_type:
            # filter out tallies that do not contain any of the proposal types
            if not any(
                v["proposal_type"] in contains_proposal_type for v in tally_votes
            ):
                continue
        if is_batcher_license_tally(tally_votes):
            # filter out batcher license tallies
            continue
        # filter out earlier test tallies
        # if parse_datetime(row[1]) < datetime.datetime(2024, 10, 22):
        #     continue
        results.append(
            {
                "quorum": row[0],
                "end_time": row[1],
                "end_time_posix": (
                    parse_datetime(row[1]).timestamp() * 1000 if row[1] else None
                ),
                "winning_threshold": f"{row[26]}/{row[27]}",
                "is_open": bool(row[25]),
                "proposal_id": row[2],
                "tally_auth_nft": {
                    "policy_id": row[3],
                    "asset_name": row[4],
                },
                "staking_vote_nft_policy_id": row[5],
                "staking_address": row[6],
                "gov_token": {
                    "policy_id": row[7],
                    "asset_name": row[8],
                },
                "vault_ft_policy_id": row[9],
                "delegation_policy": row[10],
                "total_weight": row[11],
                "votes": tally_votes,
                "transaction_output": {
                    "transaction_hash": row[16],
                    "output_index": row[17],
                },
                "title": row[18],
                "description": row[19],
                "summary": row[20],
                "creator_name": row[21],
                "forum_link": row[22],
            }
        )
    return results


def query_batcher_license_tallies():
    # def is_batcher_license_tally(tally_votes: List[dict]) -> bool:
    #     """
    #     Checks if the tally votes correspond to a canonical batcher license tally.
    #     Such a tally should include only the default reject option and the license proposal.
    #     """
    #     return len(tally_votes) == 2 and tally_votes[1].get("details", {}).get(
    #         "recipient"
    #     )

    cursor = sqlite_db.execute_sql(
        """
        with merged_tally_votes as (
          select
          sum(tw.weight) as total_weight,
          group_concat(tw.weight, ';') as weights,
          group_concat(tw."index", ';') as indices,
          tw.tally_state_id
          from tallyweights tw
          group by tw.tally_state_id
        ),
        merged_tally_proposals as (
            select
            tp.tally_params_id,
            group_concat(hex(d.data), ';') as proposals,
            group_concat(tp."index", ';') as indices,
            group_concat(tpm."title", ';') as titles,
            group_concat(tpm."description", ';') as descriptions
            from tallyproposals tp
            join datum d on tp.proposal_id = d.id
            join tallyproposalmetadata tpm on tp.metadata_id = tpm.id
            group by tp.tally_params_id
        )
        
        SELECT 
        tp.quorum,
        tp.end_time,
        tp.proposal_id,
        tally_auth_nft.policy_id,
        tally_auth_nft.asset_name,
        tp.staking_vote_nft_policy,
        staking_address.address_raw,
        gov_token.policy_id,
        gov_token.asset_name,
        tp.vault_ft_policy,
        tp.delegation_policy,
        mtv.total_weight,
        mtv.weights,
        mtv.indices,
        mtp.proposals,
        mtp.indices,
        tx_out.transaction_hash,
        tx_out.output_index,
        tmd.title,
        tmd.description,
        tmd.short_description,
        tmd.creator_name,
        tmd.forum_link,
        mtp.titles,
        mtp.descriptions,
        (tp.end_time is NULL or DATETIME(tp.end_time) > DATETIME('now')),
        tp.winning_threshold_numerator,
        tp.winning_threshold_denominator
        FROM tallystate ts
        join tallyparams tp on ts.tally_params_id = tp.id
        join tallymetadata tmd on tp.metadata_id = tmd.id
        join merged_tally_votes mtv on ts.id = mtv.tally_state_id
        join merged_tally_proposals mtp on tp.id = mtp.tally_params_id
        join transactionoutput tx_out on ts.transaction_output_id = tx_out.id
        join token tally_auth_nft on tp.tally_auth_nft_id = tally_auth_nft.id
        join address staking_address on tp.staking_address_id = staking_address.id
        join token gov_token on tp.governance_token_id = gov_token.id
        where tx_out.spent_in_block_id is NULL
        and tp.end_time is NULL
        """
    )

    results = []
    for row in cursor.fetchall():
        # filter out other threads
        if row[4] not in [GOV_STATE_NFT_TK_NAME, OLD_GOV_STATE_NFT_TK_NAME]:
            continue

        tally_votes = parse_merged_tally_votes(
            row[12], row[13], row[14], row[15], row[23], row[24]
        )

        if not is_batcher_license_tally(tally_votes):
            continue

        results.append(
            {
                "quorum": row[0],
                "winning_threshold": f"{row[26]}/{row[27]}",
                "proposal_id": row[2],
                "tally_auth_nft": {
                    "policy_id": row[3],
                    "asset_name": row[4],
                },
                "staking_vote_nft_policy_id": row[5],
                "staking_address": row[6],
                "gov_token": {
                    "policy_id": row[7],
                    "asset_name": row[8],
                },
                "vault_ft_policy_id": row[9],
                "delegation_policy": row[10],
                "total_weight": row[11],
                "votes": tally_votes,
                "transaction_output": {
                    "transaction_hash": row[16],
                    "output_index": row[17],
                },
                "title": row[18],
                "description": row[19],
                "summary": row[20],
                "creator_name": row[21],
                "forum_link": row[22],
            }
        )
    return results


def query_tally_details_by_auth_nft_proposal_id(auth_nft: str, proposal_id: int):
    cursor = sqlite_db.execute_sql(
        """
        with merged_tally_votes as (
          select
          sum(tw.weight) as total_weight,
          group_concat(tw.weight, ';') as weights,
          group_concat(tw."index", ';') as indices,
          tw.tally_state_id
          from tallyweights tw
          group by tw.tally_state_id
        ),
        merged_tally_proposals as (
            select
            tp.tally_params_id,
            group_concat(hex(d.data), ';') as proposals,
            group_concat(tp."index", ';') as indices,
            group_concat(tpm."title", ';') as titles,
            group_concat(tpm."description", ';') as descriptions
            from tallyproposals tp
            join datum d on tp.proposal_id = d.id
            join tallyproposalmetadata tpm on tp.metadata_id = tpm.id
            group by tp.tally_params_id
        )
        
        SELECT 
        tp.quorum,
        tp.end_time,
        tp.proposal_id,
        tally_auth_nft.policy_id,
        tally_auth_nft.asset_name,
        tp.staking_vote_nft_policy,
        staking_address.address_raw,
        gov_token.policy_id,
        gov_token.asset_name,
        tp.vault_ft_policy,
        tp.delegation_policy,
        mtv.total_weight,
        mtv.weights,
        mtv.indices,
        mtp.proposals,
        mtp.indices,
        tx_out.transaction_hash,
        tx_out.output_index,
        tmd.title,
        tmd.description,
        tmd.short_description,
        tmd.creator_name,
        tmd.forum_link,
        mtp.titles,
        mtp.descriptions,
        (tp.end_time is NULL or DATETIME(tp.end_time) > DATETIME('now')),
        tp.winning_threshold_numerator,
        tp.winning_threshold_denominator
        FROM tallystate ts
        join tallyparams tp on ts.tally_params_id = tp.id
        join tallymetadata tmd on tp.metadata_id = tmd.id
        join merged_tally_votes mtv on ts.id = mtv.tally_state_id
        join merged_tally_proposals mtp on tp.id = mtp.tally_params_id
        join transactionoutput tx_out on ts.transaction_output_id = tx_out.id
        join token tally_auth_nft on tp.tally_auth_nft_id = tally_auth_nft.id
        join address staking_address on tp.staking_address_id = staking_address.id
        join token gov_token on tp.governance_token_id = gov_token.id
        where tx_out.spent_in_block_id is NULL
        and tally_auth_nft.policy_id = ?
        and tally_auth_nft.asset_name = ?
        and tp.proposal_id = ?
    """,
        (*auth_nft.split("."), proposal_id),
    )
    results = []
    for row in cursor.fetchall():
        tally_votes = parse_merged_tally_votes(
            row[12], row[13], row[14], row[15], row[23], row[24]
        )
        for v in tally_votes:
            v["proposal_type"] = PROPOSAL_CONSTRUCTORS_TO_TYPES.get(
                v["proposal"].get("constructor", -1), None
            )
            if v.get("details", {}).get("sub_dao_params"):
                v["proposal_type"] = "CreateSubDao"
        results.append(
            {
                "quorum": row[0],
                "end_time": row[1],
                "end_time_posix": (
                    parse_datetime(row[1]).timestamp() * 1000 if row[1] else None
                ),
                "winning_threshold": f"{row[26]}/{row[27]}",
                "is_open": bool(row[25]),
                "proposal_id": row[2],
                "tally_auth_nft": {
                    "policy_id": row[3],
                    "asset_name": row[4],
                },
                "staking_vote_nft_policy_id": row[5],
                "staking_address": row[6],
                "gov_token": {
                    "policy_id": row[7],
                    "asset_name": row[8],
                },
                "vault_ft_policy_id": row[9],
                "delegation_policy": row[10],
                "total_weight": row[11],
                "votes": tally_votes,
                # TODO: removed for quick fix, need to add it back (fix query above)
                # "creation_slot": row[15],
                # "creators": row[16].split(";"),
                "transaction_output": {
                    "transaction_hash": row[16],
                    "output_index": row[17],
                },
                "title": row[18],
                "summary": row[20],
                "description": row[19],
                "creator_name": row[21],
                "forum_link": row[22],
            }
        )
    return results


def query_tally_auth_nft_proposal_id(transaction_hash: str, transaction_index: int):
    """
    Obtain the auth nft and proposal id for a tally that once had a given transaction output
    :param transaction_hash:
    :param transaction_index:
    :return: (auth_nft, proposal_id) or None if the transaction output is not part of a tally
    """
    cursor = sqlite_db.execute_sql(
        """
    SELECT
    tk.policy_id,
    tk.asset_name,
    tp.proposal_id
    FROM tallystate ts
    join tallyparams tp on ts.tally_params_id = tp.id
    join transactionoutput tx_out on ts.transaction_output_id = tx_out.id
    join token tk on tp.tally_auth_nft_id = tk.id
    where tx_out.transaction_hash = ?
    and tx_out.output_index = ?
    """,
        (transaction_hash, transaction_index),
    )
    for row in cursor.fetchall():
        return (Token(bytes.fromhex(row[0]), bytes.fromhex(row[1])), row[2])
    return None


def query_tally_details_by_tx_out(transaction_hash: str, transaction_index: int):
    """
    Returns the latest tally details for a tally that has at some point had a transaction output with the given hash and index.
    :param transaction_hash:
    :param transaction_index:
    :return:
    """
    auth_nft_proposal_id = query_tally_auth_nft_proposal_id(
        transaction_hash, transaction_index
    )
    if auth_nft_proposal_id is None:
        return []
    return query_tally_details_by_auth_nft_proposal_id(*auth_nft_proposal_id)


def query_tally_details_by_auth_nft_proposal_id_with_user_vote(
    auth_nft: str, proposal_id: int, user_address: str
):
    cursor = sqlite_db.execute_sql(
        """
    with merged_tally_votes as (
        select
        sum(tw.weight) as total_weight,
        group_concat(tw.weight, ';') as weights,
        group_concat(tw."index", ';') as indices,
        tw.tally_state_id
        from tallyweights tw
        group by tw.tally_state_id
    ),
    merged_tally_proposals as (
        select
        tp.tally_params_id,
        group_concat(hex(d.data), ';') as proposals,
        group_concat(tp."index", ';') as indices
        from tallyproposals tp
        join datum d on tp.proposal_id = d.id
        group by tp.tally_params_id
    ),
    merged_tally_creation_participants as (
        select
        tc.next_tally_state_id,
        group_concat(address.address_raw, ';') as addresses
        from tallycreation tc
        join tallycreationparticipants tcp on tc.id = tcp.tally_creation_id
        join address on tcp.address_id = address.id
        group by tc.next_tally_state_id
    ),
    user_staking_participation as (
        select
        sp.tally_auth_nft_id,
        sp.proposal_id,
        sp.weight,
        sp.proposal_index,
        staking_blk.slot
        from stakingparticipation sp
        join stakingparticipationinstaking spis on sp.id = spis.participation_id
        join stakingstate ss on spis.staking_state_id = ss.id
        join stakingparams sparams on ss.staking_params_id = sparams.id
        join address sa on sa.id = sparams.owner_id
        join transactionoutput staking_tx_out on ss.transaction_output_id = staking_tx_out.id
        join "transaction" staking_tx on staking_tx.id = staking_tx_out.transaction_id
        join "block" staking_blk on staking_blk.id = staking_tx.block_id
        where sa.address_raw = ?
    )


    SELECT
    tp.quorum,
    tp.end_time,
    tp.proposal_id,
    tally_auth_nft.policy_id,
    tally_auth_nft.asset_name,
    tp.staking_vote_nft_policy,
    staking_address.address_raw,
    gov_token.policy_id,
    gov_token.asset_name,
    tp.vault_ft_policy,
    tp.delegation_policy,
    mtv.total_weight,
    mtv.weights,
    mtv.indices,
    mtp.proposals,
    mtp.indices,
    tcblk.slot,
    mtcps.addresses,
    tx_out.transaction_hash,
    tx_out.output_index,
    spart.weight,
    spart.proposal_index
    -- get the tally details
    FROM tallystate ts
    join tallyparams tp on ts.tally_params_id = tp.id
    join merged_tally_votes mtv on ts.id = mtv.tally_state_id
    join merged_tally_proposals mtp on tp.id = mtp.tally_params_id
    join transactionoutput tx_out on ts.transaction_output_id = tx_out.id
    join token tally_auth_nft on tp.tally_auth_nft_id = tally_auth_nft.id
    join address staking_address on tp.staking_address_id = staking_address.id
    join token gov_token on tp.governance_token_id = gov_token.id
    join tallystate tcts on tcts.tally_params_id = tp.id
    join tallycreation tc on tc.next_tally_state_id = tcts.id
    join "transaction" tctx on tc.transaction_id = tctx.id
    join "block" tcblk on tcblk.id = tctx.block_id
    join merged_tally_creation_participants mtcps on tc.next_tally_state_id = mtcps.next_tally_state_id
    left outer join user_staking_participation spart on tp.tally_auth_nft_id = spart.tally_auth_nft_id and tp.proposal_id = spart.proposal_id
    -- get last vote on this tally
    join tallyvote tv on tv.next_tally_state_id = ts.id
    join "transaction" last_vote_tx on tv.transaction_id = last_vote_tx.id
    join "block" last_vote_blk on last_vote_blk.id = last_vote_tx.block_id
    where tx_out.spent_in_block_id is NULL
    and tally_auth_nft.policy_id = ?
    and tally_auth_nft.asset_name = ?
    and tp.proposal_id = ?
    and spart.slot <= last_vote_blk.slot
    order by spart.slot desc
    limit 1
    """,
        (
            user_address,
            *auth_nft.split("."),
            proposal_id,
        ),
    )
    results = []
    for row in cursor.fetchall():
        results.append(
            {
                "quorum": row[0],
                "end_time": row[1],
                "proposal_id": row[2],
                "tally_auth_nft": {
                    "policy_id": row[3],
                    "asset_name": row[4],
                },
                "staking_vote_nft_policy_id": row[5],
                "staking_address": row[6],
                "gov_token": {
                    "policy_id": row[7],
                    "asset_name": row[8],
                },
                "vault_ft_policy_id": row[9],
                "delegation_policy": row[10],
                "total_weight": row[11],
                "votes": parse_merged_tally_votes(row[12], row[13], row[14], row[15]),
                "creation_slot": row[16],
                "creators": row[17].split(";"),
                "transaction_output": {
                    "transaction_hash": row[18],
                    "output_index": row[19],
                },
                "user_vote": {"weight": row[20], "proposal_index": row[21]},
            }
        )
    return results


def query_tally_details_by_tx_out_with_user_vote(
    transaction_hash: str, transaction_index: int, user_address: str
):
    """
    Returns the latest tally details for a tally that has at some point had a transaction output with the given hash and index.
    :param transaction_hash:
    :param transaction_index:
    :return:
    """
    auth_nft_proposal_id = query_tally_auth_nft_proposal_id(
        transaction_hash, transaction_index
    )
    if auth_nft_proposal_id is None:
        return []
    return query_tally_details_by_auth_nft_proposal_id_with_user_vote(
        *auth_nft_proposal_id, user_address
    )


def query_all_user_votes_for_tally(auth_nft: str, proposal_id: int):
    res = sqlite_db.execute_sql(
        """
    SELECT
    last_vote_blk.slot,
    ts.id
    -- get the tally details
    FROM tallystate ts
    join tallyparams tp on ts.tally_params_id = tp.id
    join transactionoutput tx_out on ts.transaction_output_id = tx_out.id
    join token tally_auth_nft on tp.tally_auth_nft_id = tally_auth_nft.id
    join tallystate tcts on tcts.tally_params_id = tp.id
    -- get last vote on this tally
    join tallyvote tv on tv.next_tally_state_id = ts.id
    join "transaction" last_vote_tx on tv.transaction_id = last_vote_tx.id
    join "block" last_vote_blk on last_vote_blk.id = last_vote_tx.block_id
    where tx_out.spent_in_block_id is NULL
    and tally_auth_nft.policy_id = ?
    and tally_auth_nft.asset_name = ?
    and tp.proposal_id = ?
    """,
        (
            *auth_nft.split("."),
            proposal_id,
        ),
    ).fetchall()
    if len(res) == 0:
        return []
    last_vote_slot, tally_state_id = res[0]
    cursor = sqlite_db.execute_sql(
        """
    with latest_staking_state_before_vote_per_user as (
        select
        max(blk.slot) as slot,
        sp.owner_id
        from stakingstate ss
        join stakingparams sp on ss.staking_params_id = sp.id
        join transactionoutput tx_out on ss.transaction_output_id = tx_out.id
        join "transaction" tx on tx_out.transaction_id = tx.id
        join "block" blk on tx.block_id = blk.id
        where blk.slot <= ?
        group by sp.owner_id
    )


    SELECT
    sa.address_raw,
    sp.proposal_index,
    sp.weight,
    blk.slot
    FROM tallystate ts
    join tallyparams tp on ts.tally_params_id = tp.id
    join stakingparticipation sp on sp.tally_auth_nft_id = tp.tally_auth_nft_id and sp.proposal_id = tp.proposal_id
    join stakingparticipationinstaking spis on sp.id = spis.participation_id
    join stakingstate ss on spis.staking_state_id = ss.id
    join stakingparams sparams on ss.staking_params_id = sparams.id
    join address sa on sa.id = sparams.owner_id
    join transactionoutput tx_out on ss.transaction_output_id = tx_out.id
    join "transaction" tx on tx_out.transaction_id = tx.id
    join "block" blk on tx.block_id = blk.id
    join latest_staking_state_before_vote_per_user ls on ls.owner_id = sa.id
    where ts.id = ?
    and blk.slot = ls.slot
    """,
        (
            last_vote_slot,
            tally_state_id,
        ),
    )
    results = []
    for row in cursor.fetchall():
        results.append(
            {
                "address": row[0],
                "proposal_index": row[1],
                "weight": row[2],
                "slot": row[3],
            }
        )
    return results


if __name__ == "__main__":
    import ipdb

    try:
        print(query_tallies(True, False))
        print(query_tallies(False, True))
        print(query_tallies(True, True))
        print(query_tallies(False, False))
        print(
            query_tally_details_by_auth_nft_proposal_id(
                "471b0b6f3fab69f9c6e8c1c1389782a410a8689d97e22a22ac24b30f.bc0a47f8459162152c33913f9d4e50d2340459ce4b6197761967d64368e0e50c",
                3,
            )
        )
        print(
            query_tally_details_by_tx_out(
                "03b0238d4418cba3dde0f6d2f92495f16ee641fd154d1b93bdb4155a7afdd93d", 0
            )
        )
        print(
            query_tally_details_by_auth_nft_proposal_id_with_user_vote(
                "471b0b6f3fab69f9c6e8c1c1389782a410a8689d97e22a22ac24b30f.bc0a47f8459162152c33913f9d4e50d2340459ce4b6197761967d64368e0e50c",
                1,
                "607195078bd15707f7a74581a317c41c14be16ffe7ce7dc0f22b039713",
            )
        )
        print(
            query_all_user_votes_for_tally(
                "471b0b6f3fab69f9c6e8c1c1389782a410a8689d97e22a22ac24b30f.bc0a47f8459162152c33913f9d4e50d2340459ce4b6197761967d64368e0e50c",
                2,
            )
        )
        print(query_batcher_license_tallies())
    except Exception as e:
        print(e)
        ipdb.post_mortem()
