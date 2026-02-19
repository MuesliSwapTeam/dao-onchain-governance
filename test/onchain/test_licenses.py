import datetime

from muesliswap_onchain_governance.offchain.licenses.util import create_license_name
from muesliswap_onchain_governance.onchain.licenses.licenses import (
    check_valid_license_name,
)
from opshin.ledger.api_v2 import FinitePOSIXTime
from opshin.std.math import unsigned_int_from_bytes_big


def test_max_license_datetime():
    # Ensures that 32 - (len of proposal ids) bytes of 0xff will result in a datetime that is far enough in the future
    max_license_len_bytes = 32 - 3
    max_license = b"\xff" * max_license_len_bytes
    max_license_posix = unsigned_int_from_bytes_big(max_license) / 1000
    # 8000 years in the future
    assert max_license_posix > datetime.datetime(9999, 12, 31).timestamp()


def test_max_proposal_id():
    # Ensures that 3 bytes of 0xff will result in large enough proposal ids to never cause issues
    max_license_len_bytes = 3
    max_license = b"\xff" * max_license_len_bytes
    max_license_pid = int.from_bytes(max_license, "big")
    # 10 million proposals
    assert max_license_pid >= 10_000_000


def test_valid_license_names():
    transaction_validity_lower_bound = int(
        datetime.datetime(2024, 1, 1).timestamp() * 1000
    )
    maximum_future_validity = int(datetime.timedelta(days=3).total_seconds() * 1000)
    proposal_id = 20
    license_name = create_license_name(
        proposal_id, transaction_validity_lower_bound + maximum_future_validity
    )
    check_valid_license_name(
        license_name,
        proposal_id,
        FinitePOSIXTime(transaction_validity_lower_bound),
        maximum_future_validity,
    )
    try:
        check_valid_license_name(
            license_name,
            proposal_id + 1,
            FinitePOSIXTime(transaction_validity_lower_bound),
            maximum_future_validity,
        )
        assert False
    except AssertionError:
        pass
    try:
        check_valid_license_name(
            license_name,
            proposal_id,
            FinitePOSIXTime(transaction_validity_lower_bound - 1),
            maximum_future_validity,
        )
        assert False
    except AssertionError:
        pass
    try:
        check_valid_license_name(
            license_name,
            proposal_id,
            FinitePOSIXTime(transaction_validity_lower_bound),
            maximum_future_validity - 1,
        )
        assert False
    except AssertionError:
        pass
    license_name_padded = proposal_id.to_bytes(16, "big") + (
        transaction_validity_lower_bound + maximum_future_validity
    ).to_bytes(32 - 16, "big")
    check_valid_license_name(
        license_name_padded,
        proposal_id,
        FinitePOSIXTime(transaction_validity_lower_bound),
        maximum_future_validity,
    )
