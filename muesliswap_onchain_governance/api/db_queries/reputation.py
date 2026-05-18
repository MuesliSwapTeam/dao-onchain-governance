from muesliswap_onchain_governance.offchain.util import GOV_STATE_NFT_TK_NAME

from ..db_models import sqlite_db
from .staking import parse_merged_participations
from .util import parse_merged_assets


def query_reputation_holders():
    """
    Return all staking positions that hold reputation tokens, ranked by count descending.
    Filters to the primary governance thread via GOV_STATE_NFT_TK_NAME.
    """
    cursor = sqlite_db.execute_sql(
        """
        SELECT
            owner_a.address_raw,
            sp.reputation_policy,
            SUM(tov.amount) AS reputation_count
        FROM stakingstate ss
        JOIN stakingparams sp ON ss.staking_params_id = sp.id
        JOIN address owner_a ON sp.owner_id = owner_a.id
        JOIN transactionoutput txo ON ss.transaction_output_id = txo.id
        JOIN transactionoutputvalue tov ON tov.transaction_output_id = txo.id
        JOIN token tk ON tov.token_id = tk.id
        JOIN token tally_auth_tk ON sp.tally_auth_nft_id = tally_auth_tk.id
        WHERE txo.spent_in_block_id IS NULL
          AND tk.policy_id = sp.reputation_policy
          AND sp.reputation_policy != ''
          AND tally_auth_tk.asset_name = ?
        GROUP BY owner_a.address_raw, sp.reputation_policy
        ORDER BY reputation_count DESC
        """,
        (GOV_STATE_NFT_TK_NAME,),
    )
    results = []
    for row in cursor.fetchall():
        results.append(
            {
                "owner": row[0],
                "reputation_policy": row[1],
                "reputation_count": row[2],
            }
        )
    return results


def query_reputation_per_wallet(wallet: str):
    """
    Return reputation token count and claimable participations for one wallet.
    Claimable participations are those whose end_time is in the past — reputation
    can be minted for each of these via POST /api/v1/reputation/mint.
    """
    cursor = sqlite_db.execute_sql(
        """
        WITH merged_transaction_output_value AS (
            SELECT
                GROUP_CONCAT(tk.policy_id, ';') AS policy_ids,
                GROUP_CONCAT(tk.asset_name, ';') AS asset_names,
                GROUP_CONCAT(tov.amount, ';') AS amounts,
                tov.transaction_output_id
            FROM transactionoutputvalue tov
            JOIN token tk ON tov.token_id = tk.id
            GROUP BY tov.transaction_output_id
        )
        SELECT
            owner_a.address_raw,
            txo.transaction_hash,
            txo.output_index,
            sp.reputation_policy,
            COALESCE(rep_tov.reputation_count, 0) AS reputation_count,
            mtov.policy_ids,
            mtov.asset_names,
            mtov.amounts,
            GROUP_CONCAT(COALESCE(spt.end_time, ''), ';') AS end_times,
            GROUP_CONCAT(spt.weight, ';') AS weights,
            GROUP_CONCAT(spt.proposal_index, ';') AS proposal_indices,
            GROUP_CONCAT(spt.proposal_id, ';') AS proposal_ids,
            GROUP_CONCAT(spis."index", ';') AS participation_indices
        FROM stakingstate ss
        JOIN stakingparams sp ON ss.staking_params_id = sp.id
        JOIN address owner_a ON sp.owner_id = owner_a.id
        JOIN transactionoutput txo ON ss.transaction_output_id = txo.id
        JOIN merged_transaction_output_value mtov ON mtov.transaction_output_id = txo.id
        JOIN token tally_auth_tk ON sp.tally_auth_nft_id = tally_auth_tk.id
        LEFT JOIN stakingparticipationinstaking spis ON ss.id = spis.staking_state_id
        LEFT JOIN stakingparticipation spt ON spis.participation_id = spt.id
        LEFT JOIN (
            SELECT
                tov2.transaction_output_id,
                SUM(tov2.amount) AS reputation_count
            FROM transactionoutputvalue tov2
            JOIN token tk2 ON tov2.token_id = tk2.id
            JOIN stakingstate ss2 ON ss2.transaction_output_id = tov2.transaction_output_id
            JOIN stakingparams sp2 ON ss2.staking_params_id = sp2.id
            WHERE tk2.policy_id = sp2.reputation_policy
              AND sp2.reputation_policy != ''
            GROUP BY tov2.transaction_output_id
        ) rep_tov ON rep_tov.transaction_output_id = txo.id
        WHERE owner_a.address_raw = ?
          AND txo.spent_in_block_id IS NULL
          AND tally_auth_tk.asset_name = ?
        GROUP BY owner_a.address_raw, txo.transaction_hash, txo.output_index,
                 sp.reputation_policy, rep_tov.reputation_count,
                 mtov.policy_ids, mtov.asset_names, mtov.amounts
        """,
        (wallet, GOV_STATE_NFT_TK_NAME),
    )
    results = []
    for row in cursor.fetchall():
        end_times = row[8].split(";") if row[8] else []
        weights = row[9].split(";") if row[9] else []
        proposal_indices = row[10].split(";") if row[10] else []
        proposal_ids = row[11].split(";") if row[11] else []
        participation_indices = row[12].split(";") if row[12] else []

        claimable = []
        for i, (et, w, pi, pid, idx) in enumerate(
            zip(end_times, weights, proposal_indices, proposal_ids, participation_indices)
        ):
            if et and et != "":
                claimable.append(
                    {
                        "participation_index": int(idx) if idx else i,
                        "end_time": et,
                        "weight": w,
                        "proposal_index": pi,
                        "proposal_id": pid,
                    }
                )

        results.append(
            {
                "owner": row[0],
                "transaction_hash": row[1],
                "output_index": row[2],
                "reputation_policy": row[3],
                "reputation_count": row[4],
                "funds": parse_merged_assets(row[5], row[6], row[7]),
                "claimable_participations": claimable,
            }
        )
    return results
