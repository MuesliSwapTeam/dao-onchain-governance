"""
The license NFT contract.

Consumer of the tally states.
Releases license with limited validity to the specified address if the tally is successful.
Tallys are expected to have infinite validity and do not need to be finished for releasing licenses.
However the quorum must be reached.

The license name is structured as follows:
- The first 3 bytes are the id of the winning tally in big-endian, left-padded with 0s
- The remaining bytes are the expiry date of the license in POSIX time, milliseconds, big-endian.
  They may be left-padded with 0s but do not have to be.

Outputs of this contract may go to:
- The winning address of the referenced address in the winning tally

Reference inputs:
- tally/tally (1, referencing a winning proposal that indicates a governance upgrade)

NFTs that the outputs may hold:
- licenses/licenses (previously minted plus the own minted one)

It is not allowed to mint several license NFTs with distinct names in a single transaction but well allowed to mint
several licenses of the same name (i.e. expiry date).
"""

from opshin.std.math import *
from muesliswap_onchain_governance.onchain.util import *


@dataclass
class ReleaseLicenses(PlutusData):
    CONSTR_ID = 2
    license_name: TokenName
    release_index: int
    # the index of the reference input with the tally
    tally_input_index: int


@dataclass
class BurnLicenses(PlutusData):
    CONSTR_ID = 3


@dataclass
class LicenseReleaseParams(PlutusData):
    """
    VOTE OUTCOME
    A possible vote outcome specifying what batcher will receive liceneses.
    """

    CONSTR_ID = 101
    address: Address
    datum: OutputDatum
    # how long into the future the license is valid from a mint in milliseconds
    maximum_future_validity: POSIXTime


def check_valid_license_name(
    license_name: TokenName,
    proposal_id: ProposalId,
    transaction_validity_lower_bound: ExtendedPOSIXTime,
    maximum_future_validity: int,
) -> None:
    # check that the license has a valid name
    # - first 16 bytes are the id of the winning tally in big-endian
    # - remaining bytes are the expiry date of the license in POSIX time, milliseconds, big-endian
    license_tally_id = unsigned_int_from_bytes_big(license_name[:16])
    assert license_tally_id == proposal_id

    license_posix = unsigned_int_from_bytes_big(license_name[16:32])
    assert isinstance(
        transaction_validity_lower_bound, FinitePOSIXTime
    ), "Transaction validity lower bound must be finite"
    latest_allowed_license_posix = (
        transaction_validity_lower_bound.time + maximum_future_validity
    )
    assert license_posix <= latest_allowed_license_posix, "License minted too late"


def winning_license_tally_result(
    tally_input_index: int,
    auth_nft: Token,
    tx_info: TxInfo,
) -> TallyResult:
    """
    This ensures that the index points to a winning proposal
    """
    tally_input = tx_info.reference_inputs[tally_input_index].resolved
    tally_state: TallyState = resolve_datum_unsafe(tally_input, tx_info)
    assert token_present_in_output(auth_nft, tally_input), "AuthNFT missing from input"
    tally_end_time = tally_state.params.end_time
    assert isinstance(
        tally_end_time, PosInfPOSIXTime
    ), "Tally must have infinite end time"
    total_votes = sum(tally_state.votes)
    assert total_votes >= tally_state.params.quorum, "Quorum not reached"
    winning_proposal_votes = max(tally_state.votes)
    assert ge_fraction(
        Fraction(winning_proposal_votes, total_votes),
        tally_state.params.winning_threshold,
    ), "Winning threshold not reached"
    winning_proposal_index = list_index(tally_state.votes, winning_proposal_votes)
    return TallyResult(
        tally_state.params.proposals[winning_proposal_index],
        tally_state.params.proposal_id,
    )


def validator(
    auth_nft: Token,
    redeemer: Union[ReleaseLicenses, BurnLicenses],
    context: ScriptContext,
) -> None:
    """
    Check that liceneses are released to the specified address with limited validity.
    """
    tx_info = context.tx_info
    purpose = get_minting_purpose(context)

    if isinstance(redeemer, ReleaseLicenses):
        winning_tally = winning_license_tally_result(
            redeemer.tally_input_index,
            auth_nft,
            tx_info,
        )
        license_release_params: LicenseReleaseParams = winning_tally.winning_proposal
        # check that the winning proposal is actually a license release proposal
        check_integrity(license_release_params)

        # check that the correct license is minted
        minted_amount = 0
        for tkname, tkamount in tx_info.mint[purpose.policy_id].items():
            assert tkname == redeemer.license_name, "License minted with wrong name"
            minted_amount += tkamount

        # check that the license is released to the specified address
        license = Token(purpose.policy_id, redeemer.license_name)
        total_amount_sent_out = all_tokens_locked_at_address_with_datum(
            tx_info.outputs,
            license_release_params.address,
            license,
            license_release_params.datum,
        )
        assert (
            total_amount_sent_out == minted_amount
        ), "License not released to the specified address with specified datum"

        # check that the license has a valid name
        check_valid_license_name(
            redeemer.license_name,
            winning_tally.proposal_id,
            tx_info.valid_range.lower_bound.limit,
            license_release_params.maximum_future_validity,
        ), "Invalid license name (either too long validity or wrong proposal id)"
    else:
        # BurnLicenses and other redeemers
        assert all(
            [tkamount < 0 for tkamount in tx_info.mint[purpose.policy_id].values()]
        ), "Minted some licenses instead of burning"
