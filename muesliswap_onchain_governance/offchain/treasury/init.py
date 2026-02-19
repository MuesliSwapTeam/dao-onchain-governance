import fire

from muesliswap_onchain_governance.onchain.treasury import (
    treasurer_nft,
    treasurer,
    value_store,
)
from muesliswap_onchain_governance.utils.network import show_tx, context
from opshin.ledger.api_v2 import (
    POSIXTime,
)
from opshin.prelude import Token
from pycardano import (
    TransactionBuilder,
    Redeemer,
    AuxiliaryData,
    AlonzoMetadata,
    Metadata,
    TransactionOutput,
    Value,
)

from ..util import (
    token_from_string,
    asset_from_token,
    with_min_lovelace,
    GOV_STATE_NFT_TK_NAME,
)
from muesliswap_onchain_governance.onchain.staking import (
    staking_vote_nft,
    staking,
    vault_ft,
)
from muesliswap_onchain_governance.onchain.tally import tally_auth_nft, tally
from muesliswap_onchain_governance.onchain.gov_state import gov_state_nft, gov_state
from ...utils import get_signing_info, ogmios_url, network, kupo_url
from ...utils.contracts import get_contract, get_ref_utxo, module_name
from ...utils.to_script_context import to_address, to_tx_out_ref


def main(
    wallet: str = "creator",
    auth_nft_token_name: str = GOV_STATE_NFT_TK_NAME,
):
    # Load script info
    (
        _,
        tally_auth_nft_policy_id,
        _,
    ) = get_contract(module_name(tally_auth_nft), True)
    (
        treasurer_nft_script,
        treasurer_nft_policy_id,
        _,
    ) = get_contract(module_name(treasurer_nft), True)
    treasurer_nft_ref_utxo = get_ref_utxo(treasurer_nft_script, context)
    (
        treasurer_script,
        treasurer_policy_id,
        treasurer_address,
    ) = get_contract(module_name(treasurer), True)
    (_, _, value_store_address) = get_contract(module_name(value_store), True)

    # Get payment address
    payment_vkey, payment_skey, payment_address = get_signing_info(
        wallet, network=network
    )

    # Select UTxO to define the governance thread ID
    utxos = context.utxos(payment_address)
    unique_utxo = utxos[0]

    # generate expected gov_nft name
    treasurer_nft_name = treasurer_nft.treasurer_nft_name(
        to_tx_out_ref(unique_utxo.input)
    )
    treasurer_nft_token = Token(
        policy_id=treasurer_nft_policy_id.payload,
        token_name=treasurer_nft_name,
    )

    auth_nft_token = Token(
        policy_id=tally_auth_nft_policy_id.payload,
        token_name=bytes.fromhex(auth_nft_token_name),
    )

    # generate redeemer for the treasurer nft
    treasurer_nft_redeemer = Redeemer(0)

    # Make the datum of the GovState
    treasurer_state_datum = treasurer.TreasurerState(
        treasurer.TreasurerParams(
            auth_nft=auth_nft_token,
            value_store=to_address(value_store_address),
            treasurer_nft=treasurer_nft_token,
        ),
        last_applied_proposal_id=treasurer.INITIAL_PROPOSAL_ID,
    )

    # Build the transaction
    builder = TransactionBuilder(context)
    builder.auxiliary_data = AuxiliaryData(
        data=AlonzoMetadata(
            metadata=Metadata({674: {"msg": ["Create Treasurer Thread"]}})
        )
    )
    builder.add_input(unique_utxo)
    builder.add_input_address(payment_address)
    builder.add_minting_script(
        treasurer_nft_ref_utxo or treasurer_nft_script,
        treasurer_nft_redeemer,
    )
    output = with_min_lovelace(
        TransactionOutput(
            address=treasurer_address,
            amount=Value(
                coin=2000000,
                multi_asset=asset_from_token(treasurer_nft_token, 1),
            ),
            datum=treasurer_state_datum,
        ),
        context,
    )
    builder.add_output(output)
    builder.mint = asset_from_token(treasurer_nft_token, 1)

    # Sign the transaction
    signed_tx = builder.build_and_sign(
        signing_keys=[payment_skey],
        change_address=payment_address,
    )

    # Submit the transaction
    context.submit_tx(signed_tx)

    print(
        f"Created treasury thread with treasurer_nft_name: {treasurer_nft_name.hex()}"
    )

    show_tx(signed_tx)
    return signed_tx, treasurer_nft_name.hex()


if __name__ == "__main__":
    fire.Fire(main)
