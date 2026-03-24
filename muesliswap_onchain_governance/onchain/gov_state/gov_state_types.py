"""
Shared PlutusData type definitions for the governance state contracts.

Both gov_state.py (spending) and gov_state_nft.py (minting) import from
here so that gov_state_nft.py can use the datum types without importing
all of gov_state.py's validator logic (which would make it too large).
"""

from muesliswap_onchain_governance.onchain.util import *


@dataclass
class GovStateParams(PlutusData):
    """
    Parameters of a governance thread.
    """

    CONSTR_ID = 0
    tally_address: Address
    staking_address: Address
    governance_token: Token
    vault_ft_policy: PolicyId
    delegation_policy: PolicyId
    min_quorum: int
    min_winning_threshold: Fraction
    min_proposal_duration: POSIXTime
    gov_state_nft: Token
    tally_auth_nft_policy: PolicyId
    staking_vote_nft_policy: PolicyId
    # security parameter: the last proposal that was applied to update
    # the governance state - nothing can be applied twice
    latest_applied_proposal_id: ProposalId
    # hierarchical DAO: parent reference (set to sentinel values for root DAOs)
    # root DAOs use Token(b"", b"") as parent_gov_nft and b"" as parent_tally_auth_nft_policy
    parent_gov_nft: Token
    parent_tally_auth_nft_policy: PolicyId
    # security parameter: the last parent proposal applied to this sub-DAO
    # root DAOs use ALWAYS_EARLY_PROPOSAL_ID (never updated)
    latest_applied_parent_proposal_id: ProposalId


@dataclass
class GovStateUpdateParams(PlutusData):
    """
    VOTE OUTCOME
    A possible vote outcome specifying what the new governance state will be.
    """

    CONSTR_ID = 100
    params: GovStateParams
    address: Address


@dataclass
class CreateSubDaoParams(PlutusData):
    """
    VOTE OUTCOME
    A possible vote outcome specifying the creation of a new sub-DAO governance thread.
    """

    CONSTR_ID = 101
    params: GovStateParams
    address: Address


@dataclass
class ParentSubDaoUpdateParams(PlutusData):
    """
    VOTE OUTCOME (placed in a PARENT DAO tally)
    Authorises the parent DAO to update the parameters of one of its sub-DAOs.
    """

    CONSTR_ID = 102
    sub_dao_gov_nft: Token
    params: GovStateParams
    address: Address


@dataclass
class GovStateDatum(PlutusData):
    """
    Datum for the governance state.
    """

    CONSTR_ID = 0
    params: GovStateParams
    last_proposal_id: ProposalId


@dataclass
class CreateNewTally(PlutusData):
    """
    Redeemer: create a new tally.
    """

    CONSTR_ID = 1
    gov_state_input_index: int
    gov_state_output_index: int
    tally_output_index: int


@dataclass
class UpgradeGovState(PlutusData):
    """
    Redeemer: upgrade governance parameters or contract address.
    """

    CONSTR_ID = 2
    gov_state_input_index: int
    gov_state_output_index: int
    tally_input_index: int


@dataclass
class CreateSubDao(PlutusData):
    """
    Redeemer (on PARENT): execute a winning CreateSubDaoParams tally.
    """

    CONSTR_ID = 3
    gov_state_input_index: int
    gov_state_output_index: int
    tally_input_index: int
    sub_dao_output_index: int


@dataclass
class ParentUpgradeSubDao(PlutusData):
    """
    Redeemer (on SUB-DAO): apply a winning ParentSubDaoUpdateParams tally from the parent.
    """

    CONSTR_ID = 4
    gov_state_input_index: int
    gov_state_output_index: int
    parent_tally_input_index: int


GovStateRedeemer = Union[CreateNewTally, UpgradeGovState, CreateSubDao]
