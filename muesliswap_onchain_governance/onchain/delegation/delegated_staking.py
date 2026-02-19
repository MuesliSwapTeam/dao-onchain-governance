"""
The delegated staking contract

A user may lock tokens at this contract and mint in return fungible tokens
that represent their voting power.

The name of the minted token indicates the expiry date of the delegation rights.

Outputs of this contract may go to:
- staking/staking
"""

from muesliswap_onchain_governance.onchain.util import *


def get_linear_input_state(inputs: List[TxInInfo], own_addr: Address) -> TxInInfo:
    own_inputs = [i for i in inputs if i.resolved.address == own_addr]
    assert len(own_inputs) == 1, (
        "Trying to spend more than one utxos from the contract at once"
    )
    own_input = own_inputs[0]
    return own_input


def get_linear_output_state(outputs: List[TxOut], own_addr: Address) -> TxOut:
    own_outputs = [o for o in outputs if o.address == own_addr]
    assert len(own_outputs) == 1, "Found more than one output to the contract address"
    own_output = own_outputs[0]
    return own_output


def count_tokens_expiring_after_bound(
    value: Value, policy_id: PolicyId, lower_bound: POSIXTime
) -> int:
    ret = 0
    for tokenname, amount in value.get(policy_id, {b"": 0}).items():
        expiry_time = unsigned_int_from_bytes_big(tokenname)
        if expiry_time >= lower_bound:
            ret += amount
    return ret


############# Datums ###################


@dataclass
class DelegationDatum(PlutusData):
    """
    The datum of the delegated staking contract
    """

    CONSTR_ID = 1
    # POSIX time in milliseconds
    delegation_expiry: POSIXTime
    owner: PubKeyHash


@dataclass
class ConsolidationDatum(PlutusData):
    """
    The datum for consolidating multiple delegation tokens into one
    """

    CONSTR_ID = 2
    lower_bound: POSIXTime
    owner: PubKeyHash
    amount: int


############# Redeemers ###################


@dataclass
class OpenDelegationPositionRedeemer(PlutusData):
    """
    A redeemer storing the address of the delegatee and the expiry date
    of the delegation rights.
    """

    CONSTR_ID = 1
    delegatee_address: Address
    delegatee_output_index: int


@dataclass
class RevokeDelegationBeforeExpiry(PlutusData):
    """
    A redeemer to reclaim tokens by burning the delegation tokens
    before their expiry
    """

    CONSTR_ID = 2


@dataclass
class ReclaimExpiredDelegation(PlutusData):
    """
    A redeemer to close an expired delegation position without having to
    burn the delegation tokens.
    """

    CONSTR_ID = 3


@dataclass
class BurnExpiredDelegationTokens(PlutusData):
    """
    A redeemer for burning delegation tokens that have expired.
    """

    CONSTR_ID = 4


@dataclass
class RenewDelegationBeforeExpiry(PlutusData):
    """
    A redeemer for renewing an existing delegation position by burning
    the existing delegation tokens and minting new ones with a new expiry date.
    """

    CONSTR_ID = 5
    delegatee_address: Address
    delegatee_output_index: int


@dataclass
class RenewDelegationAfterExpiry(PlutusData):
    """
    A redeemer for renewing an existing delegation position after expiry
    by minting new delegation tokens.
    """

    CONSTR_ID = 6
    delegatee_address: Address
    delegatee_output_index: int


@dataclass
class ConsolidateDelegation(PlutusData):
    """
    A redeemer for consolidating multiple different delegation tokens into one.
    """

    CONSTR_ID = 7
    lower_bound: POSIXTime


@dataclass
class DeconsolidateDelegation(PlutusData):
    """
    A redeemer for deconsolidating a delegation token into multiple previously locked ones.
    """

    CONSTR_ID = 8


def validator(
    governance_token: Token,
    _datum: Union[DelegationDatum, ConsolidationDatum],
    redeemer: Union[
        OpenDelegationPositionRedeemer,
        RevokeDelegationBeforeExpiry,
        ReclaimExpiredDelegation,
        BurnExpiredDelegationTokens,
        RenewDelegationBeforeExpiry,
        RenewDelegationAfterExpiry,
        ConsolidateDelegation,
        DeconsolidateDelegation,
    ],
    context: ScriptContext,
) -> None:
    """
    The validator of the delegated staking contract
    """
    tx_info = context.tx_info
    purpose = context.purpose
    mint = tx_info.mint

    if isinstance(redeemer, OpenDelegationPositionRedeemer):
        assert isinstance(purpose, Minting)
        own_pid = purpose.policy_id
        own_addr = own_address(own_pid)
        contract_utxo = get_linear_output_state(tx_info.outputs, own_addr)
        datum: DelegationDatum = resolve_datum_unsafe(contract_utxo, tx_info)
        assert isinstance(datum, DelegationDatum)

        num_staked_tokens = contract_utxo.value.get(
            governance_token.policy_id, {b"": 0}
        ).get(governance_token.token_name, 0)

        expected_token_name = bytes_big_from_unsigned_int(datum.delegation_expiry)
        check_mint_exactly_n_with_name(
            mint, num_staked_tokens, own_pid, expected_token_name
        )

        delegatee_output = tx_info.outputs[redeemer.delegatee_output_index]

        assert delegatee_output.address == redeemer.delegatee_address, (
            "Delegatee output address mismatch"
        )
        assert (
            delegatee_output.value.get(own_pid, {b"": 0}).get(expected_token_name, 0)
            == num_staked_tokens
        ), "Expected delegatee to receive delegation tokens"

    elif isinstance(redeemer, RevokeDelegationBeforeExpiry):
        if isinstance(purpose, Minting):
            own_addr = own_address(purpose.policy_id)
            own_pid = purpose.policy_id
            own_utxo = get_linear_input_state(tx_info.inputs, own_addr).resolved
        elif isinstance(purpose, Spending):
            own_utxo = own_spent_utxo(tx_info.inputs, purpose)
            own_pid = own_policy_id(own_utxo)
            own_addr = own_utxo.address

        datum: DelegationDatum = resolve_datum_unsafe(own_utxo, tx_info)
        assert isinstance(datum, DelegationDatum)

        # NOTE: The contract only checks if the owner signed the tx. It does not check where the unlocked
        # gov tokens go.
        assert datum.owner in tx_info.signatories, "Owner must sign the transaction"
        num_staked_tokens = own_utxo.value.get(
            governance_token.policy_id, {b"": 0}
        ).get(governance_token.token_name, 0)
        expected_token_name = bytes_big_from_unsigned_int(datum.delegation_expiry)
        # To unlock early the delegation tokens must be burned
        check_mint_exactly_n_with_name(
            mint, -num_staked_tokens, own_pid, expected_token_name
        )

    elif isinstance(redeemer, ReclaimExpiredDelegation):
        assert isinstance(purpose, Spending)
        own_utxo = own_spent_utxo(tx_info.inputs, purpose)

        datum: DelegationDatum = resolve_datum_unsafe(own_utxo, tx_info)
        assert isinstance(datum, DelegationDatum)
        # NOTE: The contract only checks if the owner signed the tx. It does not check where the unlocked
        # gov tokens go.
        assert datum.owner in tx_info.signatories, "Owner must sign the transaction"
        expiry = FinitePOSIXTime(datum.delegation_expiry)
        assert after_ext(tx_info.valid_range, expiry), "Delegation has not expired yet"

    elif isinstance(redeemer, BurnExpiredDelegationTokens):
        # Utility redeemer to burn delegation tokens that have expired and
        # are therefore useless.
        assert isinstance(purpose, Minting)
        own_pid = purpose.policy_id
        own_mint = tx_info.mint[own_pid]
        for token_name in own_mint.keys():
            amount = own_mint[token_name]
            assert amount < 0, "Must burn delegation tokens"
            expiry_time = unsigned_int_from_bytes_big(token_name)
            expiry = FinitePOSIXTime(expiry_time)
            assert after_ext(tx_info.valid_range, expiry), (
                "Delegation token has not expired yet"
            )

    elif isinstance(redeemer, RenewDelegationBeforeExpiry) or isinstance(
        redeemer, RenewDelegationAfterExpiry
    ):
        if isinstance(purpose, Minting):
            own_addr = own_address(purpose.policy_id)
            own_pid = purpose.policy_id
            own_input_utxo = get_linear_input_state(tx_info.inputs, own_addr).resolved
        elif isinstance(purpose, Spending):
            own_input_utxo = own_spent_utxo(tx_info.inputs, purpose)
            own_pid = own_policy_id(own_input_utxo)
            own_addr = own_input_utxo.address
        own_output_utxo = get_linear_output_state(tx_info.outputs, own_addr)
        old_datum: DelegationDatum = resolve_datum_unsafe(own_input_utxo, tx_info)
        assert isinstance(old_datum, DelegationDatum)
        new_datum: DelegationDatum = resolve_datum_unsafe(own_output_utxo, tx_info)
        assert isinstance(new_datum, DelegationDatum)
        expected_old_token_name = bytes_big_from_unsigned_int(
            old_datum.delegation_expiry
        )
        expected_new_token_name = bytes_big_from_unsigned_int(
            new_datum.delegation_expiry
        )
        assert new_datum.owner == old_datum.owner, (
            "Owner must not change when renewing delegation"
        )
        assert new_datum.owner in tx_info.signatories, "Owner must sign the transaction"
        own_mint = tx_info.mint[own_pid]
        num_previously_staked_tokens = own_input_utxo.value.get(
            governance_token.policy_id, {b"": 0}
        ).get(governance_token.token_name, 0)
        num_currently_staked_tokens = own_output_utxo.value.get(
            governance_token.policy_id, {b"": 0}
        ).get(governance_token.token_name, 0)
        if isinstance(redeemer, RenewDelegationBeforeExpiry):
            # Check that the old delegation tokens are burned
            assert own_mint[expected_old_token_name] == -num_previously_staked_tokens, (
                "Old delegation tokens not burned correctly"
            )
            expected_num_token_names = 2
        else:
            expected_num_token_names = 1
        # Mint new delegation tokens
        assert own_mint[expected_new_token_name] == num_currently_staked_tokens, (
            "New delegation tokens not minted correctly"
        )
        assert len(own_mint.keys()) == expected_num_token_names, (
            "Unexpected number of token names minted"
        )
        # Check that the delegatee output is correct
        delegatee_output = tx_info.outputs[redeemer.delegatee_output_index]
        assert delegatee_output.address == redeemer.delegatee_address, (
            "Delegatee output address mismatch"
        )
        assert (
            delegatee_output.value.get(own_pid, {b"": 0}).get(
                expected_new_token_name, 0
            )
            == num_currently_staked_tokens
        ), "Expected delegatee to receive renewed delegation tokens"

    elif isinstance(redeemer, ConsolidateDelegation):
        assert isinstance(purpose, Minting)
        own_pid = purpose.policy_id
        own_addr = own_address(own_pid)
        contract_utxo = get_linear_output_state(tx_info.outputs, own_addr)
        datum: ConsolidationDatum = resolve_datum_unsafe(contract_utxo, tx_info)
        assert isinstance(datum, ConsolidationDatum)
        expected_amount = count_tokens_expiring_after_bound(
            contract_utxo.value, own_pid, datum.lower_bound
        )
        assert expected_amount == datum.amount, "Consolidation amount mismatch"
        expected_token_name = bytes_big_from_unsigned_int(datum.lower_bound)
        check_mint_exactly_n_with_name(mint, datum.amount, own_pid, expected_token_name)

    elif isinstance(redeemer, DeconsolidateDelegation):
        if isinstance(purpose, Minting):
            own_addr = own_address(purpose.policy_id)
            own_pid = purpose.policy_id
            own_input_utxo = get_linear_input_state(tx_info.inputs, own_addr).resolved
        elif isinstance(purpose, Spending):
            own_input_utxo = own_spent_utxo(tx_info.inputs, purpose)
            own_pid = own_policy_id(own_input_utxo)
            own_addr = own_input_utxo.address

        datum: ConsolidationDatum = resolve_datum_unsafe(own_input_utxo, tx_info)
        assert isinstance(datum, ConsolidationDatum)

        # NOTE: The contract only checks if the owner signed the tx. It does not check where the unlocked
        # delegation tokens go.
        assert datum.owner in tx_info.signatories, "Owner must sign the transaction"

        expected_token_name = bytes_big_from_unsigned_int(datum.lower_bound)
        # To deconsolidate, the consolidation token must be burned
        check_mint_exactly_n_with_name(
            mint, -datum.amount, own_pid, expected_token_name
        )
    else:
        assert False, "Invalid redeemer"
