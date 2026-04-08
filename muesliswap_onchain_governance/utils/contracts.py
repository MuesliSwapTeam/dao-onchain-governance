from pathlib import Path

from pycardano import (
    PaymentVerificationKey,
    PaymentSigningKey,
    Address,
    Network,
    PlutusV2Script,
    plutus_script_hash,
)

from .keys import get_address
from .network import network

build_dir = Path(__file__).parent.parent.parent.joinpath("build")


def module_name(module):
    return Path(module.__file__).stem


def get_contract(name, compressed=True):
    with open(
        build_dir.joinpath(f"{name}{'_compressed' if compressed else ''}/script.cbor")
    ) as f:
        contract_cbor_hex = f.read().strip()
    contract_cbor = bytes.fromhex(contract_cbor_hex)

    contract_plutus_script = PlutusV2Script(contract_cbor)
    contract_script_hash = plutus_script_hash(contract_plutus_script)
    contract_script_address = Address(contract_script_hash, network=network)
    return contract_plutus_script, contract_script_hash, contract_script_address


_ref_utxo_cache: dict[bytes, "pycardano.UTxO | None"] = {}


def get_ref_utxo(contract: PlutusV2Script, context):
    cache_key = plutus_script_hash(contract).payload
    if cache_key in _ref_utxo_cache:
        return _ref_utxo_cache[cache_key]
    script_address = Address(payment_part=plutus_script_hash(contract), network=network)
    for utxo in context.utxos(script_address):
        if utxo.output.script == contract:
            _ref_utxo_cache[cache_key] = utxo
            return utxo
    _ref_utxo_cache[cache_key] = None
    return None
