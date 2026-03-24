import json
from ..db_models import sqlite_db


def get_gov_state_utxo_info(gov_nft_asset_name: str):
    """
    Return (transaction_hash, output_index, address_raw) for the current
    unspent governance state UTxO identified by its NFT asset name, or None.

    address_raw is the hex-encoded address primitive (as stored by add_address).
    """
    cursor = sqlite_db.execute_sql(
        """
        SELECT txo.transaction_hash, txo.output_index, addr.address_raw
        FROM govstate gs
        JOIN transactionoutput txo ON gs.transaction_output_id = txo.id
        JOIN address addr ON txo.address_id = addr.id
        JOIN govparams gp ON gs.gov_params_id = gp.id
        JOIN token gov_nft ON gp.gov_state_nft_id = gov_nft.id
        WHERE gov_nft.asset_name = ? AND txo.spent_in_block_id IS NULL
        """,
        (gov_nft_asset_name,),
    )
    return cursor.fetchone()


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
