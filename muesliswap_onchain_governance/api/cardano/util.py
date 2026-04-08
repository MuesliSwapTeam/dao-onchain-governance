from opshin.prelude import Token
from pycardano import Network, TransactionInput, TransactionOutput, UTxO

from muesliswap_onchain_governance.api.util import GOVERNANCE_TOKEN
from muesliswap_onchain_governance.offchain.util import token_from_string

from ...utils import get_signing_info


def get_collateral_signing_info(network: Network):
    return get_signing_info("collateral", network=network)


def get_collateral_utxo(network: Network):
    if network == Network.TESTNET:
        tx_id = "3d5a1b514c4407a8639d919e58a3eb420792a453b05e634907b5fac12a994d09"
        ref_address = "addr_test1vqnerlxfyaa87uuf8cx9genw0549gkpfl2twwr98le83sjgkvsxhd"
    else:
        raise NotImplementedError("Collateral UTxO not set for this network")
    return UTxO(
        TransactionInput.from_primitive([tx_id, 0]),
        TransactionOutput.from_primitive([ref_address, 10_000_000]),
    )


def get_goverance_token() -> Token:
    return token_from_string(GOVERNANCE_TOKEN)
