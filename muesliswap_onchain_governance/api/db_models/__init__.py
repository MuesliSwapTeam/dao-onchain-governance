from .db import (
    Address,
    Block,
    Datum,
    Token,
    Transaction,
    TransactionOutput,
    TransactionOutputValue,
    sqlite_db,
)
from .delegation import (
    Consolidation,
    ConsolidationPosition,
    DelegationAction,
    DelegationPosition,
    DelegationRevoke,
)
from .gov_state import GovParams, GovState, GovUpgrade, TrackedGovStates
from .licenses import LicenseMint, LicenseOutput
from .staking import (
    StakingDeposit,
    StakingDepositDelta,
    StakingDepositParticipationAdded,
    StakingDepositParticipationRemoved,
    StakingParams,
    StakingParticipation,
    StakingParticipationInStaking,
    StakingState,
    VotePermission,
    VotePermissionMint,
)
from .tally_state import (
    TallyCreation,
    TallyCreationParticipants,
    TallyMetadata,
    TallyParams,
    TallyProposalMetadata,
    TallyProposals,
    TallyState,
    TallyVote,
    TallyWeights,
)
from .treasury import (
    TrackedTreasuryStates,
    TreasurerParams,
    TreasurerState,
    TreasuryDelta,
    TreasuryDeltaValue,
    TreasuryPayout,
    ValueStoreState,
)
from .vault import MintVaultFTExistingPosition, VaultPosition

sqlite_db.connect()
sqlite_db.create_tables(
    [
        Block,
        Address,
        Datum,
        Token,
        Transaction,
        TransactionOutput,
        TransactionOutputValue,
        GovParams,
        GovState,
        GovUpgrade,
        TallyState,
        TallyParams,
        TallyMetadata,
        TallyProposals,
        TallyProposalMetadata,
        TallyWeights,
        TallyCreation,
        TallyCreationParticipants,
        TallyVote,
        TreasurerParams,
        TreasurerState,
        TreasuryDelta,
        TreasuryDeltaValue,
        TreasuryPayout,
        ValueStoreState,
        StakingParams,
        StakingState,
        StakingParticipation,
        StakingDeposit,
        StakingDepositDelta,
        StakingDepositParticipationAdded,
        StakingDepositParticipationRemoved,
        StakingParticipationInStaking,
        VotePermission,
        VotePermissionMint,
        VaultPosition,
        MintVaultFTExistingPosition,
        LicenseMint,
        LicenseOutput,
        DelegationPosition,
        DelegationAction,
        DelegationRevoke,
        ConsolidationPosition,
        Consolidation,
    ]
)
# Migrate existing DB: add sub-DAO hierarchy columns to govparams if not present
_existing_staking_cols = {
    row[1]
    for row in sqlite_db.execute_sql("PRAGMA table_info(stakingparams)").fetchall()
}
if "reputation_policy" not in _existing_staking_cols:
    sqlite_db.execute_sql(
        "ALTER TABLE stakingparams ADD COLUMN reputation_policy TEXT DEFAULT ''"
    )

_existing_cols = {
    row[1]
    for row in sqlite_db.execute_sql("PRAGMA table_info(govparams)").fetchall()
}
for _col_name, _col_type, _col_sql in [
    ("parent_gov_nft_policy", "TEXT", "ALTER TABLE govparams ADD COLUMN parent_gov_nft_policy TEXT"),
    ("parent_gov_nft_name", "TEXT", "ALTER TABLE govparams ADD COLUMN parent_gov_nft_name TEXT"),
    ("parent_tally_auth_nft_policy", "TEXT", "ALTER TABLE govparams ADD COLUMN parent_tally_auth_nft_policy TEXT"),
    ("latest_applied_parent_proposal_id", "INTEGER", "ALTER TABLE govparams ADD COLUMN latest_applied_parent_proposal_id INTEGER"),
]:
    if _col_name not in _existing_cols:
        sqlite_db.execute_sql(_col_sql)
