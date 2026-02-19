from muesliswap_onchain_governance.onchain.util import *


@dataclass
class ValueStoreState(PlutusData):
    CONSTR_ID = 1
    # Unique NFT of the only valid treasurer (one shot NFT)
    treasurer_nft: Token


@dataclass
class TreasurerParams(PlutusData):
    CONSTR_ID = 1
    auth_nft: Token
    value_store: Address
    treasurer_nft: Token


@dataclass
class TreasurerState(PlutusData):
    CONSTR_ID = 1
    params: TreasurerParams
    last_applied_proposal_id: ProposalId
