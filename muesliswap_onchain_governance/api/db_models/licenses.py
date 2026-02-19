from .db import *
from .tally_state import TallyState


class LicenseMint(TransActionModel):
    """
    Mirrors the current status of the on-chain license
    """

    license_nft = ForeignKeyField(Token, backref="licenses")
    amount = IntegerField()
    receiver = ForeignKeyField(Address, backref="received_licenses")
    tally_proposal_id = IntegerField()
    expiration_date = DateTimeField()
    used_tally_state = ForeignKeyField(
        TallyState, backref="minted_licenses", on_delete="CASCADE"
    )


class LicenseOutput(OutputStateModel):
    """
    Mirrors the presence of a license in an output
    """

    license_nft = ForeignKeyField(Token, backref="licenses")
