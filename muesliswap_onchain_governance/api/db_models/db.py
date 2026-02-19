from peewee import *

sqlite_db = SqliteDatabase(
    "muesliswap_onchain_governance.db",
    # "new.db",
    # "test.db",
    pragmas={
        "journal_mode": "wal",
        "foreign_keys": 1,
        "ignore_check_constraints": 0,
    },
)


class BaseModel(Model):
    class Meta:
        database = sqlite_db


PolicyId = lambda: CharField(max_length=64)
AssetName = lambda: CharField(max_length=64)
CBORField = BlobField


class Block(BaseModel):
    hash = CharField(max_length=64, unique=True)
    slot = IntegerField(index=True)
    height = IntegerField()


class Token(BaseModel):
    policy_id = PolicyId()
    asset_name = AssetName()

    class Meta:
        indexes = ((("policy_id", "asset_name"), True),)
        constraints = [SQL("UNIQUE (policy_id, asset_name)")]


class Address(BaseModel):
    address_raw = CharField(max_length=128, unique=True, index=True)


class Datum(BaseModel):
    hash = CharField(max_length=64, unique=True, index=True)
    data = CBORField()


class Transaction(BaseModel):
    transaction_hash = CharField(max_length=64, unique=True, index=True)
    block = ForeignKeyField(Block, backref="transactions", on_delete="CASCADE")
    block_index = IntegerField()


class TransactionOutput(BaseModel):
    transaction = ForeignKeyField(Transaction, backref="outputs", on_delete="CASCADE")
    transaction_hash = CharField(max_length=64)
    output_index = IntegerField()
    address = ForeignKeyField(Address, backref="outputs", index=True)
    datum_hash = ForeignKeyField(Datum, field="hash", backref="outputs", null=True)
    spent_in_block = ForeignKeyField(
        Block, backref="transaction_inputs", on_delete="SET NULL", null=True
    )

    class Meta:
        indexes = ((("transaction_hash", "output_index"), True),)
        constraints = [SQL("UNIQUE (transaction_hash, output_index)")]


class OutputStateModel(BaseModel):
    transaction_output = ForeignKeyField(
        TransactionOutput, backref="created_states", on_delete="CASCADE"
    )


class TransActionModel(BaseModel):
    transaction = ForeignKeyField(
        Transaction, backref="transactions", on_delete="CASCADE"
    )


class TransactionOutputValue(BaseModel):
    transaction_output = ForeignKeyField(
        TransactionOutput, backref="assets", on_delete="CASCADE"
    )
    token = ForeignKeyField(Token, backref="outputs")
    amount = IntegerField()
