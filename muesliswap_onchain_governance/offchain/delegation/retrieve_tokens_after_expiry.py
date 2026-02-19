"""
This transaction demonstrates how to retrieve staked tokens before the end
of the delegation period
"""

from datetime import datetime, timezone

import fire
from pycardano import (
    AlonzoMetadata,
    AuxiliaryData,
    Metadata,
    Redeemer,
    TransactionBuilder,
    UTxO,
)

from muesliswap_onchain_governance.onchain.delegation import delegated_staking
from muesliswap_onchain_governance.utils import get_signing_info, network
from muesliswap_onchain_governance.utils.contracts import (
    get_contract,
    get_ref_utxo,
    module_name,
)
from muesliswap_onchain_governance.utils.network import context, show_tx

from .config import DEBUG, DEFAULT_EXECUTION_UNITS


def main(
    delegator_wallet: str = "creator",
    gov_token: str = "bd976e131cfc3956b806967b06530e48c20ed5498b46a5eb836b61c2.744d494c4b7632",
):
    delegated_staking_script, delegated_staking_policy_id, delegated_staking_address = (
        get_contract(module_name(delegated_staking), True)
    )

    delegated_staking_ref_utxo = get_ref_utxo(delegated_staking_script, context)

    delegator_vkey, delegator_skey, delegator_address = get_signing_info(
        delegator_wallet, network=network
    )

    _contract_utxos = context.utxos(delegated_staking_address)

    contract_utxos: list[UTxO] = []

    for utxo in _contract_utxos:
        try:
            datum = delegated_staking.DelegationDatum.from_cbor(utxo.output.datum.cbor)
            if (
                datum.owner == delegator_address.payment_part.payload
                and datum.delegation_expiry
                < int(datetime.now(timezone.utc).timestamp() * 1000)
            ):
                contract_utxos.append(utxo)
        except Exception:
            continue

    if not contract_utxos:
        raise Exception(
            "No expired delegation UTxOs found at the contract for this delegator"
        )

    utxo_to_close = contract_utxos[0]

    builder = TransactionBuilder(context)
    builder.auxiliary_data = AuxiliaryData(
        data=AlonzoMetadata(
            metadata=Metadata(
                {674: {"msg": ["Close Expired Delegated Staking Position"]}}
            )
        )
    )
    builder.add_input_address(delegator_address)

    builder.add_script_input(
        utxo_to_close,
        delegated_staking_ref_utxo or delegated_staking_script,
        redeemer=Redeemer(
            delegated_staking.ReclaimExpiredDelegation(),
            ex_units=DEFAULT_EXECUTION_UNITS if DEBUG else None,
        ),
    )

    signed_tx = builder.build_and_sign(
        [delegator_skey], change_address=delegator_address
    )

    try:
        context.submit_tx(signed_tx)
    except Exception:
        print(f"Transaction CBOR: {signed_tx.to_cbor_hex()}")
        raise
    show_tx(signed_tx)
    return signed_tx


if __name__ == "__main__":
    fire.Fire(main)
