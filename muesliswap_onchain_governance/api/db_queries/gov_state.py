import json
from ..db_models import sqlite_db


def query_current_gov_state():
    cursor = sqlite_db.execute_sql(
        """
        select
        txo.transaction_hash,
        txo.output_index,
        gs.last_proposal_id,
        tally_address.address_raw,
        staking_address.address_raw,
        gov_token.policy_id,
        gov_token.asset_name,
        gp.min_quorum,
        gp.min_proposal_duration,
        gov_nft.policy_id,
        gov_nft.asset_name,
        gp.tally_auth_nft_policy,
        gp.staking_vote_nft_policy,
        gp.latest_applied_proposal_id,
        gp.min_winning_threshold_numerator,
        gp.min_winning_threshold_denominator,
        gs.utxo_assets,
        gp.parent_gov_nft_policy,
        gp.parent_gov_nft_name,
        gp.parent_tally_auth_nft_policy,
        gp.latest_applied_parent_proposal_id
        from govstate gs
        join transactionoutput txo on gs.transaction_output_id = txo.id
        join govparams gp on gs.gov_params_id = gp.id
        join address tally_address on gp.staking_address_id = tally_address.id
        join address staking_address on gp.staking_address_id = staking_address.id
        join token gov_token on gp.governance_token_id = gov_token.id
        join token gov_nft on gp.gov_state_nft_id = gov_nft.id
        where txo.spent_in_block_id is null
        order by txo.transaction_hash, txo.output_index asc
        """
    )
    results = []
    for row in cursor.fetchall():
        parent_policy = row[17] or ""
        results.append(
            {
                "transaction_hash": row[0],
                "output_index": row[1],
                "last_proposal_id": row[2],
                "tally_address": row[3],
                "staking_address": row[4],
                "gov_token": {"policy_id": row[5], "asset_name": row[6]},
                "min_quorum": row[7],
                "min_proposal_duration": row[8],
                "min_winning_threshold": f"{row[14]}/{row[15]}",
                "gov_nft": {"policy_id": row[9], "asset_name": row[10]},
                "tally_auth_nft_policy": row[11],
                "staking_vote_nft_policy": row[12],
                "latest_applied_proposal_id": row[13],
                "utxo_assets": json.loads(row[16]),
                "parent_gov_nft": {
                    "policy_id": parent_policy,
                    "asset_name": row[18] or "",
                },
                "parent_tally_auth_nft_policy": row[19] or "",
                "latest_applied_parent_proposal_id": row[20],
                "is_root_dao": parent_policy == "",
            }
        )
    return results
