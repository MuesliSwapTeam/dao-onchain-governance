from .db import *
from .gov_state import GovState
from .staking import StakingState


class TallyMetadata(BaseModel):
    title = CharField(max_length=64)
    description = TextField()
    short_description = TextField()
    creator_name = CharField(max_length=64)
    forum_link = CharField(max_length=64)


class TallyParams(BaseModel):
    quorum = IntegerField()
    end_time = DateTimeField(null=True)
    winning_threshold_numerator = IntegerField()
    winning_threshold_denominator = IntegerField()
    proposal_id = IntegerField()
    tally_auth_nft = ForeignKeyField(Token, backref="tally_params")
    staking_vote_nft_policy = PolicyId()
    staking_address = ForeignKeyField(Address, backref="tally_params")
    governance_token = ForeignKeyField(Token, backref="tally_params")
    vault_ft_policy = PolicyId()
    delegation_policy = PolicyId()
    metadata = ForeignKeyField(TallyMetadata, backref="tally_params")


class TallyProposalMetadata(BaseModel):
    title = CharField(max_length=64)
    description = TextField()


class TallyProposals(BaseModel):
    tally_params = ForeignKeyField(TallyParams, backref="tally_proposals")
    index = IntegerField()
    proposal = ForeignKeyField(Datum, backref="tally_proposals")
    metadata = ForeignKeyField(TallyProposalMetadata, backref="tally_proposals")


class TallyState(OutputStateModel):
    """
    Mirrors the current status of the on-chain tally state
    """

    tally_params = ForeignKeyField(TallyParams, backref="tally_states")


class TallyWeights(BaseModel):
    """
    Mirrors the current status of the on-chain governance state
    """

    tally_state = ForeignKeyField(
        TallyState, backref="tally_votes", on_delete="CASCADE"
    )
    index = IntegerField()
    weight = IntegerField()


class TallyVote(TransActionModel):
    """
    Model the vote of a staking state
    """

    staking_state = ForeignKeyField(
        StakingState, backref="tally_voters", on_delete="CASCADE"
    )
    index = IntegerField()
    weight_delta = IntegerField()
    prev_tally_state = ForeignKeyField(
        TallyState, backref="tally_votes_prev", on_delete="CASCADE"
    )
    next_tally_state = ForeignKeyField(
        TallyState, backref="tally_votes_next", on_delete="CASCADE"
    )


class TallyCreation(TransActionModel):
    """
    Model the creation of a tally state
    """

    gov_state = ForeignKeyField(
        GovState, backref="tally_creations", on_delete="CASCADE"
    )
    next_tally_state = ForeignKeyField(
        TallyState, backref="tally_creations_next", on_delete="CASCADE"
    )


class TallyCreationParticipants(BaseModel):
    """
    Model the participation of an address in the creation of a tally state
    """

    tally_creation = ForeignKeyField(
        TallyCreation, backref="tally_creation_participants", on_delete="CASCADE"
    )
    address = ForeignKeyField(Address, backref="tally_creation_participations")

    class Meta:
        constaints = [SQL("UNIQUE (tally_creation, address)")]
