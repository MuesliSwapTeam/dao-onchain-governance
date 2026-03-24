"""
The governance state NFT contract.
This contract creates a single one-shot NFT with a unique token name.
Its presence uniquely identifies a governance thread.

Two minting modes are supported via the redeemer:

  int  (plain UTxO index)
      Original one-shot NFT minting used when initialising a root DAO
      (offchain: init.py).  The NFT name is the SHA-256 hash of the
      spending input at the given index.

  SubDaoMintRedeemer
      Used during sub-DAO creation (offchain: create_sub_dao.py).
      In addition to the one-shot NFT logic this mode validates all
      sub-DAO-specific invariants that would otherwise have to live in
      gov_state.py (and inflate its size):
        - Sub-DAO params correctly reference the parent DAO.
        - Sub-DAO initial datum matches the winning CreateSubDaoParams proposal.
        - Sub-DAO address differs from the parent.
"""

from muesliswap_onchain_governance.onchain.util import *
from muesliswap_onchain_governance.onchain.gov_state.gov_state_types import *


@dataclass
class OneShotMintRedeemer(PlutusData):
    """
    Redeemer for root-DAO initialisation: plain one-shot NFT minting.
    unique_utxo_index is the position of the spending input whose hash
    becomes the NFT token name.
    """

    CONSTR_ID = 0
    unique_utxo_index: int


@dataclass
class SubDaoMintRedeemer(PlutusData):
    """
    Extended redeemer for sub-DAO creation.

    Carries the transaction indices needed to locate:
      - the UTxO being spent for the one-shot NFT name derivation,
      - the parent gov-state input (to read current params),
      - the winning tally reference input,
      - the sub-DAO output being created.
    """

    CONSTR_ID = 1
    unique_utxo_index: int            # spending input providing the one-shot UTxO
    parent_gov_state_input_index: int  # spending input of the parent gov state
    tally_ref_index: int              # reference input of the winning parent tally
    sub_dao_output_index: int         # output index for the new sub-DAO


GovStateNFTRedeemer = Union[OneShotMintRedeemer, SubDaoMintRedeemer]

gov_state_nft_name = one_shot_nft_name


def validator(
    redeemer: GovStateNFTRedeemer, context: ScriptContext
) -> None:
    """
    Gov-state NFT minting policy.

    Accepts either an OneShotMintRedeemer (root-DAO init) or a SubDaoMintRedeemer
    (sub-DAO creation with full sub-DAO invariant validation).
    """
    policy_id = get_minting_purpose(context).policy_id
    tx_info = context.tx_info

    if isinstance(redeemer, OneShotMintRedeemer):
        # ----------------------------------------------------------------
        # Root DAO init: plain one-shot NFT minting.
        # ----------------------------------------------------------------
        spent_input = tx_info.inputs[redeemer.unique_utxo_index].out_ref
        check_mint_exactly_one_with_name(
            tx_info.mint, policy_id, one_shot_nft_name(spent_input)
        )

    elif isinstance(redeemer, SubDaoMintRedeemer):
        # ----------------------------------------------------------------
        # Sub-DAO creation: one-shot NFT + sub-DAO invariant validation.
        # ----------------------------------------------------------------

        # One-shot NFT: name = hash of the committed UTxO.
        spent_input = tx_info.inputs[redeemer.unique_utxo_index].out_ref
        check_mint_exactly_one_with_name(
            tx_info.mint, policy_id, one_shot_nft_name(spent_input)
        )

        # Read parent gov state from the spending inputs.
        parent_input = tx_info.inputs[redeemer.parent_gov_state_input_index].resolved
        parent_state: GovStateDatum = resolve_datum_unsafe(parent_input, tx_info)
        parent_params: GovStateParams = parent_state.params

        # Validate the winning tally.
        tally_auth_nft = Token(
            parent_params.tally_auth_nft_policy,
            parent_params.gov_state_nft.token_name,
        )
        tally_result = winning_tally_result(
            redeemer.tally_ref_index,
            tally_auth_nft,
            tx_info,
            parent_params.latest_applied_proposal_id,
            True,
        )
        winning_proposal: CreateSubDaoParams = tally_result.winning_proposal
        check_integrity(winning_proposal)

        sub_dao_params: GovStateParams = winning_proposal.params

        # Sub-DAO must correctly reference the parent DAO.
        assert sub_dao_params.parent_gov_nft == parent_params.gov_state_nft, (
            "Sub-DAO parent_gov_nft must match parent's gov_state_nft"
        )
        assert (
            sub_dao_params.parent_tally_auth_nft_policy
            == parent_params.tally_auth_nft_policy
        ), "Sub-DAO parent_tally_auth_nft_policy must match parent's tally_auth_nft_policy"
        assert sub_dao_params.latest_applied_proposal_id == ALWAYS_EARLY_PROPOSAL_ID, (
            "Sub-DAO latest_applied_proposal_id must be ALWAYS_EARLY_PROPOSAL_ID"
        )
        assert (
            sub_dao_params.latest_applied_parent_proposal_id == ALWAYS_EARLY_PROPOSAL_ID
        ), "Sub-DAO latest_applied_parent_proposal_id must be ALWAYS_EARLY_PROPOSAL_ID"

        # Sub-DAO must live at a different address than the parent.
        assert winning_proposal.address != parent_input.address, (
            "Sub-DAO must be deployed at a different address than the parent DAO"
        )

        # Sub-DAO initial datum must exactly match the winning proposal.
        sub_dao_output = tx_info.outputs[redeemer.sub_dao_output_index]
        expected_sub_dao_state = GovStateDatum(sub_dao_params, INITIAL_PROPOSAL_ID)
        actual_sub_dao_state: GovStateDatum = resolve_datum_unsafe(
            sub_dao_output, tx_info
        )
        assert expected_sub_dao_state == actual_sub_dao_state, (
            "Sub-DAO initial state does not match the winning proposal"
        )

    else:
        assert False, "Invalid redeemer"
