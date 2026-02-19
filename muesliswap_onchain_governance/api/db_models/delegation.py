from .db import *


class DelegationPosition(OutputStateModel):
    owner = TextField()  # pkh in datum
    expiry = IntegerField()  # POSIX time in ms
    delegatee = ForeignKeyField(Address)


class ConsolidationPosition(OutputStateModel):
    lower_bound = IntegerField()  # POSIX time in ms
    owner = TextField()  # pkh in datum
    amount = IntegerField()  # Total amount of delegation tokens consolidated here


class DelegationAction(TransActionModel):
    prev_delegation_position = ForeignKeyField(
        DelegationPosition,
        backref="delegation_action_prev",
        null=True,
        on_delete="CASCADE",
    )

    next_delegation_position = ForeignKeyField(
        DelegationPosition, backref="delegation_action_next", on_delete="CASCADE"
    )


class DelegationRevoke(TransActionModel):
    prev_delegation_position = ForeignKeyField(
        DelegationPosition, backref="delegation_revoke", on_delete="CASCADE"
    )


class Consolidation(TransActionModel):
    consolidation_position = ForeignKeyField(
        ConsolidationPosition, backref="consolidation", on_delete="CASCADE"
    )
