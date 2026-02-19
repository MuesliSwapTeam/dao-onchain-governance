"""
This transaction demonstrates how to open a delegated staking position.
"""

from datetime import datetime, timedelta, timezone

import fire
from opshin.prelude import Token
from pycardano import (
    AlonzoMetadata,
    AuxiliaryData,
    Metadata,
    Redeemer,
    TransactionBuilder,
    TransactionOutput,
)

from muesliswap_onchain_governance.offchain.util import (
    asset_from_token,
    token_from_string,
    value_from_token,
    with_min_lovelace,
)
from muesliswap_onchain_governance.onchain.delegation import delegated_staking
from muesliswap_onchain_governance.utils import get_signing_info, network
from muesliswap_onchain_governance.utils.contracts import (
    get_contract,
    get_ref_utxo,
    module_name,
)
from muesliswap_onchain_governance.utils.network import context, show_tx
from muesliswap_onchain_governance.utils.to_script_context import to_address


def main(
    delegator_wallet: str = "creator",
    delegatee_wallet: str = "delegatee",
    stake_amount: int = 5,
    delegate_until: int = int(
        (datetime.now(timezone.utc) + timedelta(days=180)).timestamp()
    )
    * 1000,
    gov_token: str = "bd976e131cfc3956b806967b06530e48c20ed5498b46a5eb836b61c2.744d494c4b7632",
):
    delegated_staking_script, delegated_staking_policy_id, delegated_staking_address = (
        get_contract(module_name(delegated_staking), True)
    )

    delegated_staking_ref_utxo = get_ref_utxo(delegated_staking_script, context)

    delegator_vkey, delegator_skey, delegator_address = get_signing_info(
        delegator_wallet, network=network
    )
    delegatee_vkey, delegatee_skey, delegatee_address = get_signing_info(
        delegatee_wallet, network=network
    )

    governance_token = token_from_string(gov_token)

    datum = delegated_staking.DelegationDatum(
        delegation_expiry=delegate_until,
        owner=delegator_address.payment_part.payload,
    )

    builder = TransactionBuilder(context)
    builder.auxiliary_data = AuxiliaryData(
        data=AlonzoMetadata(
            metadata=Metadata({674: {"msg": ["Open Delegated Staking Position"]}})
        )
    )
    builder.add_input_address(delegator_address)
    builder.add_output(
        with_min_lovelace(
            TransactionOutput(
                address=delegated_staking_address,
                amount=value_from_token(governance_token, stake_amount),
                datum=datum,
            ),
            context,
        )
    )

    delegation_token = Token(
        policy_id=delegated_staking_policy_id.payload,
        token_name=delegated_staking.bytes_big_from_unsigned_int(
            datum.delegation_expiry
        ),
    )

    builder.mint = asset_from_token(delegation_token, stake_amount)

    builder.add_output(
        with_min_lovelace(
            TransactionOutput(
                address=delegatee_address,
                amount=value_from_token(delegation_token, stake_amount),
            ),
            context,
        )
    )

    builder.add_minting_script(
        delegated_staking_ref_utxo or delegated_staking_script,
        Redeemer(
            delegated_staking.OpenDelegationPositionRedeemer(
                delegatee_address=to_address(delegatee_address),
                delegatee_output_index=1,
            )
        ),
    )

    signed_tx = builder.build_and_sign(
        signing_keys=[delegator_skey],
        change_address=delegator_address,
        merge_change=True,
    )

    context.submit_tx(signed_tx)
    show_tx(signed_tx)
    return signed_tx


if __name__ == "__main__":
    fire.Fire(main)
