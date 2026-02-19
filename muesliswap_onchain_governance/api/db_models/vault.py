from .db import *


class VaultPosition(OutputStateModel):
    owner = TextField()  # pkh in datum
    release_timestamp = IntegerField()  # unix timetamp in datum
    minted_ft = (
        BooleanField()
    )  # Whether VaultFTs have been minted for this position yet
    vault_address = ForeignKeyField(
        Address
    )  # In case we wish to support multiple vaults in the future


class MintVaultFTExistingPosition(TransActionModel):
    open_position = ForeignKeyField(VaultPosition, backref="mint_tx")
