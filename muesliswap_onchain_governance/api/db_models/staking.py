from .db import *


class StakingParams(BaseModel):
    owner = ForeignKeyField(Address, backref="staking_params")
    governance_token = ForeignKeyField(Token, backref="staking_params")
    vault_ft_policy = PolicyId()
    delegation_policy = PolicyId()
    reputation_policy = PolicyId()
    tally_auth_nft = ForeignKeyField(Token, backref="staking_params")


class StakingState(OutputStateModel):
    """
    Mirrors the current status of the on-chain staking state
    """

    staking_params = ForeignKeyField(StakingParams, backref="staking_states")


class StakingParticipation(BaseModel):
    """
    Tracks the participation of a staking state in proposals
    """

    tally_auth_nft = ForeignKeyField(Token, backref="staking_participations")
    proposal_id = IntegerField()
    weight = IntegerField()
    proposal_index = IntegerField()
    end_time = DateTimeField(null=True)


class StakingParticipationInStaking(BaseModel):
    """
    Tracks at which index a staking participation is stored in which staking state
    This design allows also to reconstruct past participations of a user and naturally avoids duplication
    of Participations in the DB
    """

    staking_state = ForeignKeyField(
        StakingState, backref="staking_participations", on_delete="CASCADE"
    )
    participation = ForeignKeyField(
        StakingParticipation, backref="staking_participations"
    )
    index = IntegerField()


class VotePermission(BaseModel):
    """
    Models tokens that express the right to perform a vote
    Find the vote permissions of a staking state by following the token backref
    """

    token = ForeignKeyField(Token, backref="vote_permissions")
    delegated_action = ForeignKeyField(Datum, backref="vote_permissions")

    class Meta:
        constraints = [SQL("UNIQUE (token_id, delegated_action_id)")]


class StakingDeposit(TransActionModel):
    """
    Models the deposit or withdrawal of funds into/from a staking state
    """

    prev_staking_state = ForeignKeyField(
        StakingState, backref="staking_deposits_prev", null=True, on_delete="CASCADE"
    )
    next_staking_state = ForeignKeyField(
        StakingState, backref="staking_deposits_next", on_delete="CASCADE"
    )


class StakingDepositDelta(BaseModel):
    """
    Models added or removed funds from a staking state
    """

    staking_deposit = ForeignKeyField(
        StakingDeposit, backref="staking_deposit_deltas", on_delete="CASCADE"
    )
    token = ForeignKeyField(Token, backref="staking_deposit_deltas")
    amount = IntegerField()

    class Meta:
        constraints = [SQL("UNIQUE (staking_deposit_id, token_id)")]


class StakingDepositParticipationAdded(BaseModel):
    """
    Models added participation to a staking state
    """

    staking_deposit = ForeignKeyField(
        StakingDeposit, backref="staking_deposit_additions", on_delete="CASCADE"
    )
    participation = ForeignKeyField(
        StakingParticipation, backref="staking_deposit_additions"
    )

    class Meta:
        constraints = [SQL("UNIQUE (staking_deposit_id, participation_id)")]


class StakingDepositParticipationRemoved(BaseModel):
    """
    Models removed participation from a staking state
    """

    staking_deposit = ForeignKeyField(
        StakingDeposit, backref="staking_deposit_removals", on_delete="CASCADE"
    )
    participation = ForeignKeyField(
        StakingParticipation, backref="staking_deposit_removals"
    )

    class Meta:
        constraints = [SQL("UNIQUE (staking_deposit_id, participation_id)")]


class VotePermissionMint(TransActionModel):
    """
    Models the minting of vote permissions
    Note these might not go to the staking state directly but to the owner of the staking state or someone else
    """

    vote_permission = ForeignKeyField(VotePermission, backref="vote_permission_mints")
    output = ForeignKeyField(
        TransactionOutput, backref="vote_permission_mints", on_delete="CASCADE"
    )
