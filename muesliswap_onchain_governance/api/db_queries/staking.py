import cbor2
from opshin.ledger.api_v2 import FinitePOSIXTime

from muesliswap_onchain_governance.offchain.util import GOV_STATE_NFT_TK_NAME
from muesliswap_onchain_governance.onchain.util import Participation

from ..db_models import sqlite_db
from .util import parse_merged_assets


def parse_merged_participations(
    end_times: str,
    weights: str,
    proposal_indices: str,
    proposal_ids: str,
    tally_transaction_hashes: str,
    tally_output_indices: str,
    tally_titles: str,
    tally_descriptions: str,
    tally_short_descriptions: str,
    tally_creator_names: str,
    tally_forum_links: str,
    proposal_titles: str,
    proposal_descriptions: str,
):
    """
    Parse the merged participations
    :param end_times: The end times
    :param weights: The weights
    :param proposal_indices: The proposal indices
    :param tally_transaction_hashes: The tally transaction hashes
    :param tally_output_indices: The tally output indices
    :return: A list of participations
    """
    end_times = [] if end_times is None else end_times.split(";")
    weights = [] if weights is None else weights.split(";")
    proposal_indices = [] if proposal_indices is None else proposal_indices.split(";")
    proposal_ids = [] if proposal_ids is None else proposal_ids.split(";")
    tally_transaction_hashes = (
        [] if tally_transaction_hashes is None else tally_transaction_hashes.split(";")
    )
    tally_output_indices = (
        [] if tally_output_indices is None else tally_output_indices.split(";")
    )
    tally_titles = [] if tally_titles is None else tally_titles.split(";")
    tally_descriptions = (
        [] if tally_descriptions is None else tally_descriptions.split(";")
    )
    tally_short_descriptions = (
        [] if tally_short_descriptions is None else tally_short_descriptions.split(";")
    )
    tally_creator_names = (
        [] if tally_creator_names is None else tally_creator_names.split(";")
    )
    tally_forum_links = (
        [] if tally_forum_links is None else tally_forum_links.split(";")
    )
    proposal_titles = [] if proposal_titles is None else proposal_titles.split(";")
    proposal_descriptions = (
        [] if proposal_descriptions is None else proposal_descriptions.split(";")
    )
    participations = [
        {
            "end_time": end_time if end_time != "" else None,
            "weight": weight,
            "proposal_index": proposal_index,
            "proposal_id": proposal_id,
            "tally": {
                "transaction_hash": tally_transaction_hash,
                "output_index": tally_output_index,
            },
            "tally_metadata": {
                "title": tally_title,
                "description": tally_description,
                "short_description": tally_short_description,
                "creator_name": tally_creator_name,
                "forum_link": tally_forum_link,
            },
            "proposal_metadata": {
                "title": proposal_title,
                "description": proposal_description,
            },
        }
        for end_time, weight, proposal_index, proposal_id, tally_transaction_hash, tally_output_index, tally_title, tally_description, tally_short_description, tally_creator_name, tally_forum_link, proposal_title, proposal_description in zip(
            end_times,
            weights,
            proposal_indices,
            proposal_ids,
            tally_transaction_hashes,
            tally_output_indices,
            tally_titles,
            tally_descriptions,
            tally_short_descriptions,
            tally_creator_names,
            tally_forum_links,
            proposal_titles,
            proposal_descriptions,
        )
    ]
    return participations


def parse_delegated_actions(
    delegated_actions: str,
):
    """
    Parse the delegated actions
    :param delegated_actions: The delegated actions
    :return: A list of delegated actions
    """
    delegated_actions = (
        [x for x in delegated_actions.split(";") if x] if delegated_actions else []
    )
    parsed_actions = []
    for delegated_action in delegated_actions:
        parsed = cbor2.loads(bytes.fromhex(delegated_action)).value[1]
        if not isinstance(parsed, cbor2.CBORTag):
            continue
        tag = "add_vote" if parsed.tag == 122 else "retract_vote"
        try:
            participation = Participation.from_primitive(parsed.value[0])
        except Exception:
            continue
        parsed_actions.append(
            {
                "tag": tag,
                "participation": {
                    "end_time": (
                        str(participation.tally_params.end_time.time)
                        if isinstance(
                            participation.tally_params.end_time, FinitePOSIXTime
                        )
                        else None
                    ),
                    "weight": str(participation.weight),
                    "proposal_index": participation.proposal_index,
                    "proposal_id": participation.tally_params.proposal_id,
                    "tally_auth_nft": {
                        "policy_id": participation.tally_params.tally_auth_nft.policy_id.hex(),
                        "asset_name": participation.tally_params.tally_auth_nft.token_name.hex(),
                    },
                },
            }
        )

    return parsed_actions


def query_staking_positions_per_wallet(
    wallet: str,
    filter_empty_positions: bool = True,
):
    """
    Query the staking positions per wallet
    :param wallet: Hex encoded wallet address
    :return:
    """
    cursor = sqlite_db.execute_sql(
        """
        with merged_transaction_output_value as (
            select
            group_concat(tk.policy_id, ';') as policy_ids,
            group_concat(tk.asset_name, ';') as asset_names,
            group_concat(tov.amount, ';') as amounts,
            group_concat(hex(d.data), ';') as delegated_actions,
            tov.transaction_output_id
            from transactionoutputvalue tov
            join token tk on tov.token_id = tk.id
            left outer join votepermission vp on tov.token_id = vp.token_id
            left outer join datum d on vp.delegated_action_id = d.id
            group by tov.transaction_output_id
        )
        
        SELECT
        owner_a.address_raw,
        txo.transaction_hash,
        txo.output_index,
        tov.policy_ids,
        tov.asset_names,
        tov.amounts,
        -- group_concat(spt.end_time, ';'),
        GROUP_CONCAT(COALESCE(spt.end_time, ''), ';') AS end_times,
        group_concat(spt.weight, ';'),
        group_concat(spt.proposal_index, ';'),
        group_concat(spt.proposal_id, ';'),
        group_concat(tally_txo.transaction_hash, ';'),
        group_concat(tally_txo.output_index, ';'),
        sp.vault_ft_policy,
        sp.delegation_policy,
        gov_tk.policy_id,
        gov_tk.asset_name,
        tov.delegated_actions,
        tally_auth_tk.policy_id,
        tally_auth_tk.asset_name,
        group_concat(tmd.title, ';'),
        group_concat(tmd.description, ';'),
        group_concat(tmd.short_description, ';'),
        group_concat(tmd.creator_name, ';'),
        group_concat(tmd.forum_link, ';'),
        group_concat(tpm."title", ';'),
        group_concat(tpm."description", ';'),
        datum.data
        FROM stakingstate ss
        JOIN stakingparams sp on ss.staking_params_id = sp.id
        JOIN address owner_a on sp.owner_id = owner_a.id
        JOIN transactionoutput txo on ss.transaction_output_id = txo.id
        JOIN merged_transaction_output_value tov on tov.transaction_output_id = txo.id
        JOIN token gov_tk on sp.governance_token_id = gov_tk.id
        JOIN token tally_auth_tk on sp.tally_auth_nft_id = tally_auth_tk.id
        left outer JOIN stakingparticipationinstaking spis on ss.id = spis.staking_state_id
        left outer JOIN stakingparticipation spt on spis.participation_id = spt.id
        left outer join tallyparams tp on (spt.tally_auth_nft_id = tp.tally_auth_nft_id and spt.proposal_id = tp.proposal_id)
        left outer join tallyproposals tpr on (tp.id = tpr.tally_params_id and spt.proposal_index = tpr."index")
        left outer join tallyproposalmetadata tpm on tpr.metadata_id = tpm.id
        left outer join tallymetadata tmd on tp.metadata_id = tmd.id
        left outer join tallystate ts on tp.id = ts.tally_params_id
        left outer join transactionoutput tally_txo on ts.transaction_output_id = tally_txo.id
        left outer join datum on txo.datum_hash_id = datum.hash
        WHERE owner_a.address_raw = ? -- only for the given wallet
        and txo.spent_in_block_id is null -- only unspent outputs
        and tally_txo.spent_in_block_id is null -- only unspent tally outputs
        group by owner_a.address_raw, txo.transaction_hash, txo.output_index, tov.policy_ids, tov.asset_names, tov.amounts, sp.vault_ft_policy, sp.delegation_policy, gov_tk.policy_id, gov_tk.asset_name
        order by sp.id
        """,
        (wallet,),
    )
    results = []
    for row in cursor.fetchall():
        # filter out other threads
        if row[17] != GOV_STATE_NFT_TK_NAME:
            continue

        assets = parse_merged_assets(row[3], row[4], row[5])
        if len(assets) == 0:
            continue
        if filter_empty_positions:
            if (
                len(assets) == 1
                and assets[0]["policy_id"] == ""
                and assets[0]["asset_name"] == ""
            ):
                continue
        results.append(
            {
                "owner": row[0],
                "transaction_hash": row[1],
                "output_index": row[2],
                "datum": row[25].hex(),
                "funds": assets,
                "participations": parse_merged_participations(
                    row[6],
                    row[7],
                    row[8],
                    row[9],
                    row[10],
                    row[11],
                    row[18],
                    row[19],
                    row[20],
                    row[21],
                    row[22],
                    row[23],
                    row[24],
                ),
                "vault_ft_policy": row[12],
                "delegation_policy": row[13],
                "gov_token": {"policy_id": row[14], "asset_name": row[15]},
                "delegated_actions": parse_delegated_actions(row[16]),
                "tally_auth_nft": {"policy_id": row[17], "asset_name": row[18]},
            }
        )
    return results


def query_staking_history_per_wallet(wallet: str):
    """
    Query the staking history per wallet
    :param wallet: Hex encoded wallet address
    :return:
    """
    cursor = sqlite_db.execute_sql(
        """
        with merged_staking_deposit_delta as (
            select
            group_concat(tk.policy_id, ';') as policy_ids,
            group_concat(tk.asset_name, ';') as asset_names,
            group_concat(sdd.amount, ';') as amounts,
            group_concat(hex(d.data), ';') as delegated_actions,
            sdd.staking_deposit_id
            from stakingdepositdelta sdd
            join token tk on sdd.token_id = tk.id
            left outer join votepermission vp on sdd.token_id = vp.token_id
            left outer join datum d on vp.delegated_action_id = d.id
            group by sdd.staking_deposit_id
        ),
        merged_participation_additions as (
            select
            group_concat(spt.end_time, ';') as end_times,
            group_concat(spt.weight, ';') as weights,
            group_concat(spt.proposal_index, ';') as proposal_indices,
            group_concat(spt.proposal_id, ';') as proposal_ids,
            group_concat(tally_txo.transaction_hash, ';') as tally_transaction_hashes,
            group_concat(tally_txo.output_index, ';') as tally_output_indices,
            spa.staking_deposit_id
            from stakingdepositparticipationadded spa
            join stakingparticipationinstaking spis on spa.staking_deposit_id = spis.staking_state_id
            join stakingparticipation spt on spis.participation_id = spt.id
            left outer join tallyparams tp on (spt.tally_auth_nft_id = tp.tally_auth_nft_id and spt.proposal_id = tp.proposal_id)
            left outer join tallystate ts on tp.id = ts.tally_params_id
            left outer join transactionoutput tally_txo on ts.transaction_output_id = tally_txo.id
            where tally_txo.spent_in_block_id is null
            group by spa.staking_deposit_id
        ),
        merged_participation_retractions as (
            select
            group_concat(spt.end_time, ';') as end_times,
            group_concat(spt.weight, ';') as weights,
            group_concat(spt.proposal_index, ';') as proposal_indices,
            group_concat(spt.proposal_id, ';') as proposal_ids,
            group_concat(tally_txo.transaction_hash, ';') as tally_transaction_hashes,
            group_concat(tally_txo.output_index, ';') as tally_output_indices,
            spa.staking_deposit_id
            from stakingdepositparticipationremoved spa
            join stakingparticipationinstaking spis on spa.staking_deposit_id = spis.staking_state_id
            join stakingparticipation spt on spis.participation_id = spt.id
            left outer join tallyparams tp on (spt.tally_auth_nft_id = tp.tally_auth_nft_id and spt.proposal_id = tp.proposal_id)
            left outer join tallystate ts on tp.id = ts.tally_params_id
            left outer join transactionoutput tally_txo on ts.transaction_output_id = tally_txo.id
            where tally_txo.spent_in_block_id is null
            -- todo: join with block and mark as retraction only if the block is before the end time of the participation
            group by spa.staking_deposit_id
        )
        
        SELECT
        b.slot,
        tx.transaction_hash,
        tx.block_index,
        sdd.policy_ids,
        sdd.asset_names,
        sdd.amounts,
        sdd.delegated_actions,
        spa.end_times,
        spa.weights,
        spa.proposal_indices,
        spa.proposal_ids,
        spa.tally_transaction_hashes,
        spa.tally_output_indices,
        spr.end_times,
        spr.weights,
        spr.proposal_indices,
        spr.proposal_ids,
        spr.tally_transaction_hashes,
        spr.tally_output_indices,
        owner_a.address_raw,
        gov_tk.policy_id,
        gov_tk.asset_name
        from stakingdeposit sd
        join "transaction" tx on sd.transaction_id = tx.id
        join main.block b on tx.block_id = b.id
        join stakingstate ss on sd.next_staking_state_id = ss.id
        join stakingparams sps on sps.id = ss.staking_params_id
        join token gov_tk on sps.governance_token_id = gov_tk.id
        join address owner_a on sps.owner_id = owner_a.id
        left outer join merged_staking_deposit_delta sdd on sdd.staking_deposit_id = sd.id
        left outer join merged_participation_additions spa on spa.staking_deposit_id = sd.id
        left outer join merged_participation_retractions spr on spr.staking_deposit_id = sd.id
        where owner_a.address_raw = ?
        order by b.slot, tx.block_index, tx.transaction_hash
        """,
        (wallet,),
    )
    results = []
    for row in cursor.fetchall():
        # filter out other threads
        if row[21] != GOV_STATE_NFT_TK_NAME:
            continue
        results.append(
            {
                "slot": row[0],
                "transaction_hash": row[1],
                "block_index": row[2],
                "funds": parse_merged_assets(row[3], row[4], row[5]),
                "delegated_actions": parse_delegated_actions(row[6]),
                "participations_added": parse_merged_participations(
                    row[7], row[8], row[9], row[10], row[11], row[12]
                ),
                "participations_retracted": parse_merged_participations(
                    row[13], row[14], row[15], row[16], row[17], row[18]
                ),
                "owner": row[19],
            }
        )
    return results


def query_staking_history():
    """
    Query the staking history per wallet
    :param wallet: Hex encoded wallet address
    :return:
    """
    cursor = sqlite_db.execute_sql(
        """
        with merged_staking_deposit_delta as (
            select
            group_concat(tk.policy_id, ';') as policy_ids,
            group_concat(tk.asset_name, ';') as asset_names,
            group_concat(sdd.amount, ';') as amounts,
            group_concat(hex(d.data), ';') as delegated_actions,
            sdd.staking_deposit_id
            from stakingdepositdelta sdd
            join token tk on sdd.token_id = tk.id
            left outer join votepermission vp on sdd.token_id = vp.token_id
            left outer join datum d on vp.delegated_action_id = d.id
            group by sdd.staking_deposit_id
        ),
        merged_participation_additions as (
            select
            group_concat(spt.end_time, ';') as end_times,
            group_concat(spt.weight, ';') as weights,
            group_concat(spt.proposal_index, ';') as proposal_indices,
            group_concat(spt.proposal_id, ';') as proposal_ids,
            group_concat(tally_txo.transaction_hash, ';') as tally_transaction_hashes,
            group_concat(tally_txo.output_index, ';') as tally_output_indices,
            spa.staking_deposit_id
            from stakingdepositparticipationadded spa
            join stakingparticipationinstaking spis on spa.staking_deposit_id = spis.staking_state_id
            join stakingparticipation spt on spis.participation_id = spt.id
            left outer join tallyparams tp on (spt.tally_auth_nft_id = tp.tally_auth_nft_id and spt.proposal_id = tp.proposal_id)
            left outer join tallystate ts on tp.id = ts.tally_params_id
            left outer join transactionoutput tally_txo on ts.transaction_output_id = tally_txo.id
            where tally_txo.spent_in_block_id is null
            group by spa.staking_deposit_id
        ),
        merged_participation_retractions as (
            select
            group_concat(spt.end_time, ';') as end_times,
            group_concat(spt.weight, ';') as weights,
            group_concat(spt.proposal_index, ';') as proposal_indices,
            group_concat(spt.proposal_id, ';') as proposal_ids,
            group_concat(tally_txo.transaction_hash, ';') as tally_transaction_hashes,
            group_concat(tally_txo.output_index, ';') as tally_output_indices,
            spa.staking_deposit_id
            from stakingdepositparticipationremoved spa
            join stakingparticipationinstaking spis on spa.staking_deposit_id = spis.staking_state_id
            join stakingparticipation spt on spis.participation_id = spt.id
            left outer join tallyparams tp on (spt.tally_auth_nft_id = tp.tally_auth_nft_id and spt.proposal_id = tp.proposal_id)
            left outer join tallystate ts on tp.id = ts.tally_params_id
            left outer join transactionoutput tally_txo on ts.transaction_output_id = tally_txo.id
            where tally_txo.spent_in_block_id is null
            -- todo: join with block and mark as retraction only if the block is before the end time of the participation
            group by spa.staking_deposit_id
        )
        
        SELECT
        b.slot,
        tx.transaction_hash,
        tx.block_index,
        sdd.policy_ids,
        sdd.asset_names,
        sdd.amounts,
        sdd.delegated_actions,
        spa.end_times,
        spa.weights,
        spa.proposal_indices,
        spa.proposal_ids,
        spa.tally_transaction_hashes,
        spa.tally_output_indices,
        spr.end_times,
        spr.weights,
        spr.proposal_indices,
        spr.proposal_ids,
        spr.tally_transaction_hashes,
        spr.tally_output_indices,
        owner_a.address_raw,
        gov_tk.policy_id,
        gov_tk.asset_name
        from stakingdeposit sd
        join "transaction" tx on sd.transaction_id = tx.id
        join main.block b on tx.block_id = b.id
        join stakingstate ss on sd.next_staking_state_id = ss.id
        join stakingparams sps on sps.id = ss.staking_params_id
        join address owner_a on sps.owner_id = owner_a.id
        join token gov_tk on sps.governance_token_id = gov_tk.id
        left outer join merged_staking_deposit_delta sdd on sdd.staking_deposit_id = sd.id
        left outer join merged_participation_additions spa on spa.staking_deposit_id = sd.id
        left outer join merged_participation_retractions spr on spr.staking_deposit_id = sd.id
        order by b.slot, tx.block_index, tx.transaction_hash
        """,
    )
    results = []
    for row in cursor.fetchall():
        # filter out other threads
        if row[21] != GOV_STATE_NFT_TK_NAME:
            continue
        results.append(
            {
                "slot": row[0],
                "transaction_hash": row[1],
                "block_index": row[2],
                "funds": parse_merged_assets(row[3], row[4], row[5]),
                "delegated_actions": parse_delegated_actions(row[6]),
                "participations_added": parse_merged_participations(
                    row[7], row[8], row[9], row[10], row[11], row[12]
                ),
                "participations_retracted": parse_merged_participations(
                    row[13], row[14], row[15], row[16], row[17], row[18]
                ),
                "owner": row[19],
            }
        )
    return results


if __name__ == "__main__":
    print(
        query_staking_positions_per_wallet(
            "00418bb4a5aa2b84335ee3235d099bb838a2bfb7f39c400164af56aed927a80f06dc7c4507371bc1f0d0c582e6d385632706a2f0eb6204af6c"
        )
    )
    print(
        query_staking_history_per_wallet(
            "00418bb4a5aa2b84335ee3235d099bb838a2bfb7f39c400164af56aed927a80f06dc7c4507371bc1f0d0c582e6d385632706a2f0eb6204af6c"
        )
    )
