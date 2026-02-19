import fire

from muesliswap_onchain_governance.onchain.tally import tally_auth_nft
from muesliswap_onchain_governance.utils.network import show_tx, context
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

from ..util import (
    token_from_string,
    asset_from_token,
    with_min_lovelace,
    value_from_token,
    GOV_STATE_NFT_TK_NAME,
)
from muesliswap_onchain_governance.onchain.simple_pool import (
    simple_pool,
    pool_nft,
    lp_token,
)
from ...utils import get_signing_info, ogmios_url, network, kupo_url
from ...utils.contracts import get_contract, get_ref_utxo, module_name
from ...utils.to_script_context import to_address, to_tx_out_ref


def main(
    wallet: str = "creator",
    token_a: str = ".",
    token_a_amount: int = 5000000,
    token_b: str = "bd976e131cfc3956b806967b06530e48c20ed5498b46a5eb836b61c2.744d494c4b7632",
    token_b_amount: int = 300,
    gov_state_nft_tk_name: str = GOV_STATE_NFT_TK_NAME,
):
    token_a = token_from_string(token_a)
    token_b = token_from_string(token_b)
    # Load script info
    (
        pool_nft_script,
        pool_nft_policy_id,
        _,
    ) = get_contract(module_name(pool_nft), True)
    (
        lp_token_script,
        lp_token_policy_id,
        _,
    ) = get_contract(module_name(lp_token), True)
    (
        _,
        _,
        simple_pool_address,
    ) = get_contract(module_name(simple_pool), True)
    (
        _,
        auth_nft_policy_id,
        _,
    ) = get_contract(module_name(tally_auth_nft), True)

    # Get payment address
    payment_vkey, payment_skey, payment_address = get_signing_info(
        wallet, network=network
    )

    # Select UTxO to define the governance thread ID
    utxos = context.utxos(payment_address)
    unique_utxo = utxos[0]

    # generate expected pool_nft name
    pool_nft_name = pool_nft.pool_nft_name(to_tx_out_ref(unique_utxo.input))
    pool_nft_token = Token(
        policy_id=pool_nft_policy_id.payload,
        token_name=pool_nft_name,
    )

    # generate redeemer for the pool nft
    pool_nft_redeemer = Redeemer(0)

    # Make the datum of the Pool
    pool_state_datum = simple_pool.PoolState(
        im_pool_params=simple_pool.ImmutablePoolParams(
            token_a=token_a,
            token_b=token_b,
            pool_nft=pool_nft_token,
            pool_lp_token=Token(
                policy_id=lp_token_policy_id.payload,
                token_name=pool_nft_name,
            ),
        ),
        up_pool_params=simple_pool.UpgradeablePoolParams(
            fee=simple_pool.Fraction(3, 1000),
            auth_nft=Token(
                policy_id=auth_nft_policy_id.payload,
                token_name=bytes.fromhex(gov_state_nft_tk_name),
            ),
            license_policy_id=bytes.fromhex(""),
            last_applied_proposal_id=0,
        ),
        global_liquidity_tokens=1000,
        spent_for=simple_pool.Nothing(),
    )

    # Build the transaction
    builder = TransactionBuilder(context)
    builder.auxiliary_data = AuxiliaryData(
        data=AlonzoMetadata(metadata=Metadata({674: {"msg": ["Create Pool"]}}))
    )
    builder.add_input(unique_utxo)
    builder.add_input_address(payment_address)
    builder.add_minting_script(
        pool_nft_script,
        pool_nft_redeemer,
    )
    output = with_min_lovelace(
        TransactionOutput(
            address=simple_pool_address,
            amount=value_from_token(
                pool_nft_token,
                1,
            )
            + value_from_token(
                token_a,
                token_a_amount,
            )
            + value_from_token(
                token_b,
                token_b_amount,
            ),
            datum=pool_state_datum,
        ),
        context,
    )
    builder.add_output(output)
    builder.mint = asset_from_token(pool_nft_token, 1)

    # Sign the transaction
    signed_tx = builder.build_and_sign(
        signing_keys=[payment_skey],
        change_address=payment_address,
    )

    # Submit the transaction
    context.submit_tx(signed_tx)

    print(f"Created pool with pool_nft_name: {pool_nft_name.hex()}")

    show_tx(signed_tx)


if __name__ == "__main__":
    fire.Fire(main)
