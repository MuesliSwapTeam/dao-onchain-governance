import cbor2
import pycardano

from muesliswap_onchain_governance.onchain.util import Participation
from muesliswap_onchain_governance.offchain.util import GOV_STATE_NFT_TK_NAME
from opshin.ledger.api_v2 import FinitePOSIXTime
from .util import parse_merged_assets
from ..db_models import sqlite_db
from ..tx_processor.vault import VAULT_ADDRESS_TO_NAME
from ..tx_processor.from_db import from_address


def query_vault_positions_per_wallet(
    pkh: str,
):
    """
    Query the vault positions per pkh
    :param pkh: Hex encoded pkh
    :return:
    """
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
        vaultposition.owner,
        vaultposition.release_timestamp,
        vaultposition.minted_ft,
        vaultaddress.address_raw,        
        txo.transaction_hash,
        txo.output_index,
        tov.policy_ids,
        tov.asset_names,
        tov.amounts
        
        FROM vaultposition
        JOIN address vaultaddress on vaultposition.vault_address_id = vaultaddress.id
        JOIN transactionoutput txo on vaultposition.transaction_output_id = txo.id
        JOIN merged_transaction_output_value tov on tov.transaction_output_id = txo.id

        WHERE vaultposition.owner = ? -- only for the given pkh
        and txo.spent_in_block_id is null -- only unspent outputs
        
        group by vaultposition.owner, txo.transaction_hash, txo.output_index, tov.policy_ids, tov.asset_names, tov.amounts
        """,
        (pkh,),
    )
    results = []
    for row in cursor.fetchall():
        assets = parse_merged_assets(row[6], row[7], row[8])

        # Assume only ADA and one native token are locked
        if len(assets) != 2:
            continue

        for asset in assets:
            if asset["policy_id"] == "":
                continue
            locked_amount = asset["amount"]

        bech32_vault_address = pycardano.Address.from_primitive(
            bytes.fromhex(row[3])
        ).encode()

        results.append(
            {
                "owner": row[0],
                "release_timestamp": row[1],
                "vault_ft_already_minted": row[2],
                "vault_address": bech32_vault_address,
                "vault_name": VAULT_ADDRESS_TO_NAME.get(bech32_vault_address, ""),
                "locked_amount": locked_amount,
                "transaction_hash": row[4],
                "output_index": row[5],
            }
        )
    return results


if __name__ == "__main__":
    print(
        query_vault_positions_per_wallet(
            "607195078bd15707f7a74581a317c41c14be16ffe7ce7dc0f22b039713"
        )
    )
