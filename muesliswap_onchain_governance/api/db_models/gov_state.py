from typing import List

from .db import *


class GovParams(BaseModel):
    tally_address = ForeignKeyField(Address, backref="gov_states")
    staking_address = ForeignKeyField(Address, backref="gov_states")
    delegation_address = ForeignKeyField(Address, backref="gov_states")
    governance_token = ForeignKeyField(Token, backref="gov_states")
    vault_ft_policy = PolicyId()
    delegation_policy = PolicyId()
    min_quorum = IntegerField()
    min_winning_threshold_numerator = IntegerField()
    min_winning_threshold_denominator = IntegerField()
    min_proposal_duration = IntegerField()
    gov_state_nft = ForeignKeyField(Token, backref="gov_states")
    tally_auth_nft_policy = PolicyId()
    staking_vote_nft_policy = PolicyId()
    latest_applied_proposal_id = IntegerField()
    # sub-DAO hierarchy fields (null for legacy rows; "" for root DAOs; non-empty for sub-DAOs)
    parent_gov_nft_policy = CharField(max_length=64, null=True)
    parent_gov_nft_name = CharField(max_length=64, null=True)
    parent_tally_auth_nft_policy = CharField(max_length=64, null=True)
    latest_applied_parent_proposal_id = IntegerField(null=True)


class GovState(OutputStateModel):
    """
    Mirrors the current status of the on-chain governance state
    """

    last_proposal_id = IntegerField()
    utxo_assets = TextField()
    gov_params = ForeignKeyField(GovParams, backref="gov_states")


class GovUpgrade(TransActionModel):
    """
    Model the upgrade of the governance state
    If prev_gov_state is None, the upgrade is the creation of the governance state
    """

    prev_gov_state = ForeignKeyField(
        GovState, backref="gov_upgrades_prev", null=True, on_delete="CASCADE"
    )
    next_gov_state = ForeignKeyField(
        GovState, backref="gov_upgrades_next", on_delete="CASCADE"
    )


TrackedGovStates = List[GovState]
