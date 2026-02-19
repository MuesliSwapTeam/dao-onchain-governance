import cbor2
import pycardano
from ..db_models import Address, TransactionOutput, TransactionOutputValue, Datum


def from_address(address: Address) -> pycardano.Address:
    """
    Convert an address from the database to a pycardano address.
    """
    return pycardano.Address.from_primitive(bytes.fromhex(address.address_raw))


def from_output_value(output_value: TransactionOutputValue) -> pycardano.Value:
    """
    Convert an output from the database to a pycardano value.
    """
    token = output_value.token
    if token.policy_id == "":
        return pycardano.Value(output_value.amount)
    return pycardano.Value(
        multi_asset=pycardano.MultiAsset(
            {
                pycardano.ScriptHash(bytes.fromhex(token.policy_id)): pycardano.Asset(
                    {
                        pycardano.AssetName(
                            bytes.fromhex(token.asset_name)
                        ): output_value.amount,
                    }
                )
            }
        )
    )


def from_output_values(output_values: [TransactionOutputValue]) -> pycardano.Value:
    """
    Convert a list of output values from the database to a pycardano value.
    """
    value = pycardano.Value()
    for output_value in output_values:
        value += from_output_value(output_value)
    return value


def from_datum(datum: Datum) -> pycardano.Datum:
    """
    Convert a datum from the database to a pycardano datum.
    """
    return pycardano.RawCBOR(datum.data)


def from_output(output: TransactionOutput) -> pycardano.TransactionOutput:
    """
    Convert an output from the database to a pycardano output.
    """
    datum = from_datum(output.datum_hash) if output.datum_hash else None
    return pycardano.TransactionOutput(
        address=from_address(output.address),
        amount=from_output_values(output.assets),
        datum=datum,
        datum_hash=pycardano.datum_hash(datum) if datum else None,
    )
