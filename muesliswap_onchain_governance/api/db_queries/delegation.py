import pycardano

from muesliswap_onchain_governance.offchain.util import time_of_slot

from ..db_models import sqlite_db
from .util import parse_merged_assets


def query_delegation_positions_per_wallet(pkh: str):
    cursor = sqlite_db.execute_sql(
        """
        with merged_transaction_output_value as (
            select
            group_concat(tk.policy_id, ';') as policy_ids,
            group_concat(tk.asset_name, ';') as asset_names,
            group_concat(tov.amount, ';') as amounts,
            tov.transaction_output_id
            from transactionoutputvalue tov
            join token tk on tov.token_id = tk.id
            group by tov.transaction_output_id
        )
        
        SELECT
        txo.transaction_hash,
        txo.output_index,
        tov.policy_ids,
        tov.asset_names,
        tov.amounts,
        dp.expiry,
        dp.owner,
        delegatee.address_raw
        FROM delegationposition dp
        JOIN address delegatee on dp.delegatee_id = delegatee.id
        JOIN transactionoutput txo on dp.transaction_output_id = txo.id
        JOIN merged_transaction_output_value tov on tov.transaction_output_id = txo.id
        WHERE dp.owner = ? -- only for the given wallet
        and txo.spent_in_block_id is null -- only unspent outputs
        order by dp.id desc
        """,
        (pkh,),
    )

    results = []
    for row in cursor.fetchall():
        results.append(
            {
                "transaction_hash": row[0],
                "output_index": row[1],
                "attached_assets": parse_merged_assets(row[2], row[3], row[4]),
                "expiry": row[5],
                "owner": row[6],
                "delegated_to": pycardano.Address.from_primitive(
                    bytes.fromhex(row[7])
                ).encode(),
            }
        )

    return results


def query_delegation_history_per_wallet(pkh: str):
    cursor = sqlite_db.execute_sql(
        """
        with merged_transaction_output_value as (
            select
            group_concat(tk.policy_id, ';') as policy_ids,
            group_concat(tk.asset_name, ';') as asset_names,
            group_concat(tov.amount, ';') as amounts,
            tov.transaction_output_id
            from transactionoutputvalue tov
            join token tk on tov.token_id = tk.id
            group by tov.transaction_output_id
        )
        SELECT
        b.slot,
        tx.transaction_hash,
        prev_dp.id,
        next_dp.id,
        next_dp.owner,
        next_dp.expiry,
        next_delegatee.address_raw,
        spent_block.slot,
        tov.policy_ids,
        tov.asset_names,
        tov.amounts
        FROM delegationaction da
        JOIN "transaction" tx on da.transaction_id = tx.id
        JOIN block b on tx.block_id = b.id
        LEFT OUTER JOIN delegationposition prev_dp on da.prev_delegation_position_id = prev_dp.id
        JOIN delegationposition next_dp on da.next_delegation_position_id = next_dp.id
        JOIN transactionoutput next_txo on next_dp.transaction_output_id = next_txo.id
        JOIN merged_transaction_output_value tov on tov.transaction_output_id = next_txo.id
        LEFT OUTER JOIN block spent_block on next_txo.spent_in_block_id = spent_block.id
        LEFT OUTER JOIN delegationaction da_update on next_dp.id = da_update.prev_delegation_position_id
        JOIN address next_delegatee on next_dp.delegatee_id = next_delegatee.id
        WHERE next_dp.owner = ? -- only for the given wallet
        order by da.id desc
        """,
        (pkh,),
    )

    results = []
    for row in cursor.fetchall():
        if row[2] is not None:
            action = "update"
        else:
            action = "create"

        results.append(
            {
                "transaction_hash": row[1],
                "timestamp": time_of_slot(row[0]).strftime("%Y-%m-%d %H:%M:%S"),
                "action": action,
                "expiry": row[5],
                "owner": row[4],
                "delegated_to": pycardano.Address.from_primitive(
                    bytes.fromhex(row[6])
                ).encode(),
                "utxo_spent_at": time_of_slot(row[7]).strftime("%Y-%m-%d %H:%M:%S")
                if row[7]
                else None,
                "attached_assets": parse_merged_assets(row[8], row[9], row[10]),
                "_slot": row[0],
            }
        )

    # Query revokes from DelegationRevoke table (only records revokes from deployment onward)
    revoke_cursor = sqlite_db.execute_sql(
        """
        with merged_transaction_output_value as (
            select
            group_concat(tk.policy_id, ';') as policy_ids,
            group_concat(tk.asset_name, ';') as asset_names,
            group_concat(tov.amount, ';') as amounts,
            tov.transaction_output_id
            from transactionoutputvalue tov
            join token tk on tov.token_id = tk.id
            group by tov.transaction_output_id
        )
        SELECT
        b.slot,
        tx.transaction_hash,
        prev_dp.owner,
        prev_dp.expiry,
        prev_delegatee.address_raw,
        b.slot,
        tov.policy_ids,
        tov.asset_names,
        tov.amounts
        FROM delegationrevoke dr
        JOIN "transaction" tx on dr.transaction_id = tx.id
        JOIN block b on tx.block_id = b.id
        JOIN delegationposition prev_dp on dr.prev_delegation_position_id = prev_dp.id
        JOIN address prev_delegatee on prev_dp.delegatee_id = prev_delegatee.id
        JOIN transactionoutput prev_txo on prev_dp.transaction_output_id = prev_txo.id
        JOIN merged_transaction_output_value tov on tov.transaction_output_id = prev_txo.id
        WHERE prev_dp.owner = ?
        order by dr.id desc
        """,
        (pkh,),
    )

    for row in revoke_cursor.fetchall():
        results.append(
            {
                "transaction_hash": row[1],
                "timestamp": time_of_slot(row[0]).strftime("%Y-%m-%d %H:%M:%S"),
                "action": "revoke",
                "expiry": row[3],
                "owner": row[2],
                "delegated_to": pycardano.Address.from_primitive(
                    bytes.fromhex(row[4])
                ).encode(),
                "utxo_spent_at": time_of_slot(row[5]).strftime("%Y-%m-%d %H:%M:%S"),
                "attached_assets": parse_merged_assets(row[6], row[7], row[8]),
                "_slot": row[0],
            }
        )

    # Sort by slot descending (most recent first), remove internal _slot key
    results.sort(key=lambda x: x["_slot"], reverse=True)
    for r in results:
        del r["_slot"]

    return results
