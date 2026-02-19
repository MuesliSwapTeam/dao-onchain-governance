from typing import List

from . import TallyState
from .db import *
from .gov_state import GovState


class TreasurerParams(BaseModel):
    auth_nft = ForeignKeyField(Token, backref="treasurer_params")
    value_store = ForeignKeyField(Address, backref="treasurer_params")
    treasurer_nft = ForeignKeyField(Token, backref="treasurer_params")


class TreasurerState(OutputStateModel):
    """
    Mirrors the current status of the on-chain treasurer
    """

    last_applied_proposal_id = IntegerField()
    treasurer_params = ForeignKeyField(TreasurerParams, backref="treasurer_states")


class ValueStoreState(OutputStateModel):
    """
    Mirrors the current status of funds in the value store
    """

    treasurer_nft = ForeignKeyField(Token, backref="value_store_states")


class TreasuryDelta(TransActionModel):
    """
    Model the movement of funds in the value store
    """

    treasurer_nft = ForeignKeyField(Token, backref="treasury_deltas")


class TreasuryPayout(BaseModel):
    treasury_delta = ForeignKeyField(
        TreasuryDelta, backref="treasury_payouts", on_delete="CASCADE"
    )
    treasurer_state = ForeignKeyField(
        TreasurerState, backref="treasury_payouts", on_delete="CASCADE"
    )
    tally_state = ForeignKeyField(
        TallyState, backref="treasury_payouts", on_delete="CASCADE"
    )
    payout_output = ForeignKeyField(
        TransactionOutput, backref="treasury_payouts", on_delete="CASCADE"
    )


class TreasuryDeltaValue(BaseModel):
    """
    Model the amount of funds moved
    """

    treasury_delta = ForeignKeyField(
        TreasuryDelta, backref="treasury_delta_values", on_delete="CASCADE"
    )
    token = ForeignKeyField(Token, backref="treasury_delta_values")
    amount = IntegerField()


TrackedTreasuryStates = List[TreasurerState]
