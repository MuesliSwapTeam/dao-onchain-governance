"""
The vault FT contract.
This FT represents a single governance token locked into a staking vault until a fixed amount of time.

This contract is intended to have inputs from these contracts:
- the staking Vault contract (if minted for existing vault positions)


Outputs of this contract may go to:
- the staking vault contract (when minted for a new position)
- any address (intended: user wallet, but no restriction is necessary)


It is not allowed to mint several vault FTs with different names in a single transaction. It is allowed to mint several of the same name.
"""

from muesliswap_onchain_governance.onchain.staking.staking_util import *
from opshin.std.math import *


@dataclass
class ExistingVaultFTMint(PlutusData):
    """
    Mint FT for an existing vault position
    Only the owner of the vault may mint this FT and only for a limited time
    """

    CONSTR_ID = 1
    vault_ref_input_index: int


@dataclass
class NewVaultFTMint(PlutusData):
    """
    Mint FT for a new vault position
    Indicate in the datum the output to the vault contract
    """

    CONSTR_ID = 2
    vault_output_index: int


@dataclass
class BurnVaultFT(PlutusData):
    """
    Burn FT for a vault position
    """

    CONSTR_ID = 3


VaultFTRedeemer = Union[ExistingVaultFTMint, NewVaultFTMint, BurnVaultFT]


def vault_ft_token_name(vault_datum: VaultDatum) -> TokenName:
    """
    The name of the vault FT is the expiration time of the vault position
    """
    return bytes_big_from_unsigned_int(vault_datum.release_time)


def check_vault_owner_allowed(
    tx_info: TxInfo,
    latest_existing_mint_time: ExtendedPOSIXTime,
    vault_owner: PubKeyHash,
) -> None:
    """
    Check that the vault owner is allowed to mint a new FT
    """
    assert before_ext(
        tx_info.valid_range, latest_existing_mint_time
    ), "Trying to mint a new FT after the latest existing mint"
    assert vault_owner in tx_info.signatories, f"Vault owner must sign the transaction"


def extract_vault_output(redeemer: VaultFTRedeemer, tx_info: TxInfo) -> TxOut:
    """
    Extract the vault datum based on the redeemer. Ensure that the redeemer is valid.
    """
    if isinstance(redeemer, ExistingVaultFTMint):
        # I think this is incorrect
        # vault_output = tx_info.inputs[redeemer.vault_ref_input_index].resolved
        vault_output = tx_info.reference_inputs[redeemer.vault_ref_input_index].resolved
    elif isinstance(redeemer, NewVaultFTMint):
        vault_output = tx_info.outputs[redeemer.vault_output_index]
    else:
        assert False, f"Invalid redeemer {redeemer}"
    return vault_output


def validator(
    vault_contract_address: Address,
    latest_existing_mint_time: ExtendedPOSIXTime,
    vault_admin: PubKeyHash,
    # token that is worth 1_000_000 new governance tokens because of lacking decimals
    old_governance_token: Token,
    new_governance_token: Token,
    redeemer: VaultFTRedeemer,
    context: ScriptContext,
) -> None:
    """
    Vault position FT

    This FT is substrate for the Goverance token locked in a vault position because those tokens can not participate in governance votes anymore.
    The name of the token is the same as the expiration time of the vault position.
    """
    purpose = get_minting_purpose(context)
    tx_info = context.tx_info

    own_mint = tx_info.mint[purpose.policy_id]
    if isinstance(redeemer, BurnVaultFT):
        # Burning FTs is always allowed
        # but we need to make sure that all mints with this policy are burning
        assert all(
            [amount < 0 for amount in own_mint.values()]
        ), "Only burning is allowed in this transaction"
    else:
        if isinstance(redeemer, ExistingVaultFTMint):
            check_vault_owner_allowed(tx_info, latest_existing_mint_time, vault_admin)
        vault_output = extract_vault_output(redeemer, tx_info)
        assert (
            vault_output.address == vault_contract_address
        ), "Vault position must be at the vault contract address"
        vault_datum: VaultDatum = resolve_datum_unsafe(vault_output, tx_info)
        vault_amount = amount_of_token_in_output(
            new_governance_token, vault_output
        ) + 1_000_000 * amount_of_token_in_output(old_governance_token, vault_output)
        token_name = vault_ft_token_name(vault_datum)
        check_mint_exactly_n_with_name(
            tx_info.mint, vault_amount, purpose.policy_id, token_name
        )
