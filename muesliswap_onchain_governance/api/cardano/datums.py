from opshin.ledger import api_v2
from muesliswap_onchain_governance.onchain.treasury.treasurer import FundPayoutParams
from pycardano import (
    Address,
    VerificationKeyHash,
    ScriptHash,
    MultiAsset,
    AssetName,
    Asset,
)
from ..util import KnownException


def _convert_value(
    assets: list[dict],
) -> api_v2.Value:
    """
    [
        {'lovelace': 1},
        {'bd976e131cfc3956b806967b06530e48c20ed5498b46a5eb836b61c2744d494c4b7632': 100000}
    ]
    """

    multi_asset = MultiAsset()

    coin = 0
    for asset in assets:
        for token, quantity in asset.items():
            if token in ["lovelace", ".", ""]:
                coin = quantity
                continue
            pid = ScriptHash(bytes.fromhex(token[:56]))
            if pid not in multi_asset:
                multi_asset[pid] = Asset()
            multi_asset[pid][AssetName(bytes.fromhex(token[56:]))] = quantity

    ret = {}
    if coin > 0:
        ret.update({b"": {b"": coin}})

    if multi_asset is not None:
        ret.update(
            {
                bytes(policy_id): {
                    bytes(asset_name): amount for asset_name, amount in assets.items()
                }
                for policy_id, assets in multi_asset.items()
            }
        )

    return ret


def _convert_address(address: Address) -> api_v2.Address:
    if address.payment_part is None:
        raise ValueError("Address must have a payment part")
    if isinstance(address.payment_part, VerificationKeyHash):
        payment_credential = api_v2.PubKeyCredential(bytes(address.payment_part))
    elif isinstance(address.payment_part, ScriptHash):
        payment_credential = api_v2.ScriptCredential(bytes(address.payment_part))

    if address.staking_part is None:
        staking_credential = api_v2.NoStakingCredential()
    elif isinstance(address.staking_part, VerificationKeyHash):
        staking_credential = api_v2.SomeStakingCredential(
            api_v2.StakingHash(api_v2.PubKeyCredential(bytes(address.staking_part)))
        )
    elif isinstance(address.staking_part, ScriptHash):
        staking_credential = api_v2.SomeStakingCredential(
            api_v2.StakingHash(api_v2.ScriptCredential(bytes(address.staking_part)))
        )
    else:
        staking_credential = api_v2.SomeStakingCredential(
            api_v2.StakingPtr(
                slot_no=address.staking_part.slot,
                tx_index=address.staking_part.tx_index,
                cert_index=address.staking_part.cert_index,
            )
        )
    return api_v2.Address(
        payment_credential=payment_credential,
        staking_credential=staking_credential,
    )


# TODO/NOTE the smart contract checks that the datum of the payout output is equal
# to what is specified in the winning tally. However, this is difficult to construct here
# because the type of the datum can be so broad. For simplicity, this function enforces
# no output datum.
def construct_treasury_payout_datum(
    address: str, value: list[dict], reference_script_hash: str = None
) -> str:
    """
    Constructs a CBOR representation of the treasury payout datum.

    Args:
        address (str): Bech32 encoded address
        value (List[dict]): The value to be sent
        reference_script_hash (str, optional): The reference script hash (hex string). Defaults to None.

    Returns:
        str: CBOR of the datum
    """

    try:
        address = Address.decode(address)
    except Exception as e:
        raise KnownException("Invalid address could not be decoded")

    datum = FundPayoutParams(
        output=api_v2.TxOut(
            _convert_address(address),
            _convert_value(value),
            api_v2.NoOutputDatum(),
            reference_script=(
                api_v2.SomeScriptHash(bytes.fromhex(reference_script_hash))
                if reference_script_hash
                else api_v2.NoScriptHash()
            ),
        )
    )

    return datum.to_cbor_hex()


if __name__ == "__main__":
    import ipdb

    try:
        datum = construct_treasury_payout_datum(
            address="addr_test1qpqchd994g4cgv67uv346zvmhqu290ah7wwyqqty4at2akf84q8sdhrug5rnwx7p7rgvtqhx6wzkxfcx5tcwkcsy4akqcee0wx",
            value=[
                {"lovelace": 1000000},
                {
                    "bd976e131cfc3956b806967b06530e48c20ed5498b46a5eb836b61c2744d494c4b7632": 100000
                },
            ],
        )
        print(datum)
    except Exception as e:
        print(e)
        ipdb.post_mortem()
