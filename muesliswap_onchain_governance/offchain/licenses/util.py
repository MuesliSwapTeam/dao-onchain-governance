def byte_length(i):
    return (i.bit_length() + 7) // 8


def create_license_name(proposal_id: int, license_validity: int) -> bytes:
    """
    Create a license name from a proposal id and a license validity.
    The first 3 bytes are the id of the winning tally in big-endian, left-padded with 0s
    The remaining bytes are the expiry date of the license in POSIX time, milliseconds, big-endian, with minimum length
    :param proposal_id:
    :param license_validity:
    :return:
    """
    return proposal_id.to_bytes(16, "big") + (license_validity).to_bytes(
        byte_length(license_validity), "big"
    )
