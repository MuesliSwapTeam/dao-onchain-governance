from fractions import Fraction

import fire
from opshin.ledger.api_v2 import POSIXTime
from opshin.prelude import Token
from pycardano import (
    AlonzoMetadata,
    AuxiliaryData,
    Metadata,
    Redeemer,
    TransactionBuilder,
    TransactionOutput,
    Value,
)

from muesliswap_onchain_governance.onchain.delegation import delegated_staking
from muesliswap_onchain_governance.onchain.gov_state import gov_state, gov_state_nft
from muesliswap_onchain_governance.onchain.gov_state.gov_state_nft import (
    OneShotMintRedeemer,
)
from muesliswap_onchain_governance.onchain.staking import (
    staking,
    staking_vote_nft,
    vault_ft,
)
from muesliswap_onchain_governance.onchain.tally import tally, tally_auth_nft
from muesliswap_onchain_governance.utils.network import context, show_tx

from ...utils import get_signing_info, network
from ...utils.contracts import get_contract, get_ref_utxo, module_name
from ...utils.to_script_context import to_address, to_fraction, to_tx_out_ref
from ..util import asset_from_token, sorted_utxos, token_from_string, with_min_lovelace

(_, vault_ft_policy_id, _) = get_contract(module_name(vault_ft), True)
(_, delegated_staking_policy_id, _) = get_contract(module_name(delegated_staking), True)


def main(
    wallet: str = "creator",
    governance_token: str = "bd976e131cfc3956b806967b06530e48c20ed5498b46a5eb836b61c2.744d494c4b7632",
    min_quorum: int = 10,
    min_winning_threshold: Fraction = Fraction(1, 4),
    min_proposal_duration: POSIXTime = 1000,
    vault_ft_policy_id: bytes = vault_ft_policy_id.payload,
    delegated_staking_policy_id: bytes = delegated_staking_policy_id.payload,
):
    governance_token = token_from_string(governance_token)
    # Load script info
    (
        gov_state_nft_script,
        gov_state_nft_policy_id,
        _,
    ) = get_contract(module_name(gov_state_nft), True)
    gov_nft_ref_utxo = get_ref_utxo(gov_state_nft_script, context)
    (
        gov_state_script,
        gov_state_policy_id,
        gov_state_address,
    ) = get_contract(module_name(gov_state), True)
    (
        tally_script,
        tally_policy_id,
        tally_address,
    ) = get_contract(module_name(tally), True)
    (
        _,
        tally_auth_nft_policy_id,
        _,
    ) = get_contract(module_name(tally_auth_nft), True)
    (
        _,
        staking_vote_nft_policy_id,
        _,
    ) = get_contract(module_name(staking_vote_nft), True)
    (
        staking_script,
        staking_policy_id,
        staking_address,
    ) = get_contract(module_name(staking), True)

    # Get payment address
    payment_vkey, payment_skey, payment_address = get_signing_info(
        wallet, network=network
    )

    # Select UTxO to define the governance thread ID.
    # Pick the sorted-first UTxO so it is always at index 0 in the final
    # transaction regardless of any additional fee inputs the builder selects
    # (all other inputs from this address sort after it).
    utxos = context.utxos(payment_address)
    all_inputs = sorted_utxos(utxos)
    unique_utxo = all_inputs[0]
    unique_utxo_index = 0

    # generate expected gov_nft name
    gov_nft_name = gov_state_nft.gov_state_nft_name(to_tx_out_ref(unique_utxo.input))
    gov_nft_token = Token(
        policy_id=gov_state_nft_policy_id.payload,
        token_name=gov_nft_name,
    )

    # generate redeemer for the gov nft
    gov_nft_redeemer = Redeemer(OneShotMintRedeemer(unique_utxo_index=unique_utxo_index))

    # Make the datum of the GovState
    # Root DAOs use sentinel values for the parent fields (no parent)
    gov_state_datum = gov_state.GovStateDatum(
        gov_state.GovStateParams(
            tally_address=to_address(tally_address),
            staking_address=to_address(staking_address),
            governance_token=governance_token,
            vault_ft_policy=vault_ft_policy_id,
            delegation_policy=delegated_staking_policy_id,
            min_quorum=min_quorum,
            min_winning_threshold=to_fraction(min_winning_threshold),
            min_proposal_duration=min_proposal_duration,
            gov_state_nft=gov_nft_token,
            tally_auth_nft_policy=tally_auth_nft_policy_id.payload,
            staking_vote_nft_policy=staking_vote_nft_policy_id.payload,
            latest_applied_proposal_id=gov_state.ALWAYS_EARLY_PROPOSAL_ID,
            # root DAO has no parent — use sentinel values
            parent_gov_nft=Token(policy_id=b"", token_name=b""),
            parent_tally_auth_nft_policy=b"",
            latest_applied_parent_proposal_id=gov_state.ALWAYS_EARLY_PROPOSAL_ID,
        ),
        last_proposal_id=gov_state.INITIAL_PROPOSAL_ID,
    )

    # Build the transaction
    builder = TransactionBuilder(context)
    builder.auxiliary_data = AuxiliaryData(
        data=AlonzoMetadata(
            metadata=Metadata({674: {"msg": ["Create Governance Thread"]}})
        )
    )
    builder.add_input(unique_utxo)
    builder.add_input_address(payment_address)
    builder.add_minting_script(
        gov_nft_ref_utxo or gov_state_nft_script,
        gov_nft_redeemer,
    )
    output = with_min_lovelace(
        TransactionOutput(
            address=gov_state_address,
            amount=Value(
                coin=2000000,
                multi_asset=asset_from_token(gov_nft_token, 1),
            ),
            datum=gov_state_datum,
        ),
        context,
    )
    builder.add_output(output)
    builder.mint = asset_from_token(gov_nft_token, 1)

    # Sign the transaction
    signed_tx = builder.build_and_sign(
        signing_keys=[payment_skey],
        change_address=payment_address,
    )

    # Submit the transaction
    context.submit_tx(signed_tx)

    print(f"Created governance thread with gov_nft_name: {gov_nft_name.hex()}")

    show_tx(signed_tx)

    return signed_tx, gov_nft_name.hex()


if __name__ == "__main__":
    fire.Fire(main)
