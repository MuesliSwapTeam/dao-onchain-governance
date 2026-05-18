import datetime

import fire
import pycardano
from opshin import apply_parameters
import opshin.prelude as opshin

from muesliswap_onchain_governance.offchain.licenses.util import create_license_name
from muesliswap_onchain_governance.onchain.licenses import licenses
from muesliswap_onchain_governance.onchain.simple_pool import simple_pool, pool_nft
from muesliswap_onchain_governance.onchain.treasury import (
    treasurer_nft,
    treasurer,
    value_store,
)
from muesliswap_onchain_governance.utils.from_script_context import (
    from_value,
    from_output_datum,
    from_address,
)
from muesliswap_onchain_governance.utils.network import show_tx, context
from opshin.ledger.api_v2 import (
    POSIXTime,
)
from opshin.prelude import Token
from pycardano import (
    OgmiosChainContext,
    TransactionBuilder,
    Redeemer,
    AuxiliaryData,
    AlonzoMetadata,
    Metadata,
    TransactionOutput,
    Value,
)

from muesliswap_onchain_governance.offchain.util import (
    token_from_string,
    asset_from_token,
    with_min_lovelace,
    TREASURER_STATE_NFT_TK_NAME,
    sorted_utxos,
    GOV_STATE_NFT_TK_NAME,
)
from muesliswap_onchain_governance.onchain.staking import (
    staking_vote_nft,
    staking,
    vault_ft,
)
from muesliswap_onchain_governance.onchain.tally import tally_auth_nft, tally
from muesliswap_onchain_governance.onchain.gov_state import gov_state_nft, gov_state
from muesliswap_onchain_governance.utils import (
    get_signing_info,
    ogmios_url,
    network,
    kupo_url,
)
from muesliswap_onchain_governance.utils.contracts import (
    get_contract,
    get_ref_utxo,
    module_name,
)
from muesliswap_onchain_governance.utils.to_script_context import (
    to_address,
    to_tx_out_ref,
)


def main(
    wallet: str = "voter",
    license_auth_nft: str = GOV_STATE_NFT_TK_NAME,
    target_address: str = None,
):
    target_address_pyc = (
        pycardano.Address.from_primitive(target_address) if target_address else None
    )
    target_address = to_address(target_address_pyc) if target_address else None
    # Load script info
    (
        _,
        _,
        tally_address,
    ) = get_contract(module_name(tally), True)
    (
        license_script,
        license_policy_id,
        _,
    ) = get_contract(module_name(licenses), True)
    (
        _,
        pool_nft_policy_id,
        _,
    ) = get_contract(module_name(pool_nft), True)
    (
        _,
        tally_auth_nft_policy_id,
        _,
    ) = get_contract(module_name(tally_auth_nft), True)

    license_auth_nft = Token(
        tally_auth_nft_policy_id.payload,
        bytes.fromhex(license_auth_nft),
    )
    # license_script = apply_parameters(
    #     license_script_raw,
    #     license_auth_nft,
    # )
    # license_policy_id = pycardano.script_hash(license_script)
    # license_script = get_ref_utxo(license_script, context) or license_script

    # Get payment address
    payment_vkey, payment_skey, payment_address = get_signing_info(
        wallet, network=network
    )

    # Select tally thread
    tally_utxos = context.utxos(tally_address)
    tally_state_utxo = None
    winning_proposal = None
    tally_state = None
    for u in tally_utxos:
        try:
            datum = tally.TallyState.from_cbor(u.output.datum.cbor)
        except Exception:
            continue
        if datum.params.tally_auth_nft != license_auth_nft:
            continue
        tally_state = datum
        winning_proposal_index = max(enumerate(tally_state.votes), key=lambda x: x[1])[
            0
        ]
        winning_proposal = tally_state.params.proposals[winning_proposal_index]
        try:
            winning_proposal: licenses.LicenseReleaseParams = (
                licenses.LicenseReleaseParams.from_cbor(winning_proposal.to_cbor())
            )
        except Exception as e:
            continue
        if target_address and winning_proposal.address != target_address:
            continue
        tally_state_utxo = u
        break
    assert tally_state_utxo, "No tally thread found"

    own_utxos = context.utxos(payment_address)
    all_utxos = sorted_utxos(
        own_utxos,
    )

    all_reference_utxos = sorted_utxos([tally_state_utxo])
    tally_input_index = all_reference_utxos.index(tally_state_utxo)

    maximum_license_validity = int(
        (
            datetime.datetime.now()
            + datetime.timedelta(milliseconds=winning_proposal.maximum_future_validity)
            - datetime.timedelta(minutes=5)
        ).timestamp()
        * 1000
    )
    license_name = create_license_name(
        proposal_id=tally_state.params.proposal_id,
        license_validity=maximum_license_validity,
    )

    # Build the transaction
    builder = TransactionBuilder(context)
    builder.auxiliary_data = AuxiliaryData(
        data=AlonzoMetadata(metadata=Metadata({674: {"msg": ["Distribute License"]}}))
    )
    builder.add_input_address(payment_address)
    builder.add_minting_script(
        license_script,
        Redeemer(
            licenses.ReleaseLicenses(
                license_name=license_name,
                release_index=0,
                tally_input_index=tally_input_index,
            )
        ),
    )
    # Add the output that releases the license to the target address
    output_multiasset = pycardano.MultiAsset()
    output_multiasset[license_policy_id] = pycardano.Asset()
    output_multiasset[license_policy_id][pycardano.AssetName(license_name)] = 1

    builder.mint = output_multiasset

    builder.add_output(
        with_min_lovelace(
            pycardano.TransactionOutput(
                address=target_address_pyc,
                amount=pycardano.Value(coin=1_000_000, multi_asset=output_multiasset),
                datum=(
                    winning_proposal.datum.datum
                    if isinstance(winning_proposal.datum, opshin.SomeOutputDatum)
                    else None
                ),
            ),
            context,
        )
    )
    builder.reference_inputs.add(tally_state_utxo)
    builder.validity_start = context.last_block_slot
    builder.ttl = context.last_block_slot + 200

    # Sign the transaction
    signed_tx = builder.build_and_sign(
        signing_keys=[payment_skey],
        change_address=payment_address,
    )

    # Submit the transaction
    context.submit_tx(signed_tx)

    show_tx(signed_tx)


if __name__ == "__main__":
    import ipdb

    try:
        fire.Fire(main)
    except Exception as e:
        print(e)
        ipdb.post_mortem()
