"""
Bootstrap script: initialise a fresh governance thread with the new contract
(which includes reputation_policy) and create 3 sample tallies so the
frontend has content to display.

Uses Ogmios (evaluation_context) — Blockfrost is not required.

Run from project root:
    poetry run python dev/bootstrap_gov_and_tallies.py
"""

import datetime
import json
import sys
import time
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fractions import Fraction

from opshin.ledger.api_v2 import NoOutputDatum, NoScriptHash, TxOut
from opshin.prelude import Token
from pycardano import (
    Address,
    AlonzoMetadata,
    AuxiliaryData,
    Metadata,
    PlutusV2Script,
    Redeemer,
    TransactionBuilder,
    TransactionOutput,
    Value,
    plutus_script_hash,
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
from muesliswap_onchain_governance.onchain.reputation import reputation
from muesliswap_onchain_governance.onchain.tally import tally, tally_auth_nft
from muesliswap_onchain_governance.onchain.treasury import treasurer
from muesliswap_onchain_governance.onchain.licenses import licenses
from muesliswap_onchain_governance.onchain.simple_pool import (
    classes as simple_pool_classes,
)
from muesliswap_onchain_governance.utils import get_signing_info, network
from muesliswap_onchain_governance.utils.contracts import get_contract, module_name
from muesliswap_onchain_governance.utils.network import evaluation_context

# ── Patch cost models from node (Ogmios returns 175 V2 params; Conway node has 332) ─
import dataclasses as _dc
from pycardano.backend.base import ProtocolParameters as _PP

_NODE_PARAMS_PATH = os.environ.get(
    "NODE_PROTOCOL_PARAMS",
    "/tmp/protocol_params.json",
)
if os.path.exists(_NODE_PARAMS_PATH):
    with open(_NODE_PARAMS_PATH) as _f:
        _node_pp_raw = json.load(_f)
    _patched_cm = {}
    for _ver, _model in _node_pp_raw.get("costModels", {}).items():
        # cardano-cli returns lists; convert to {index: value} dict preserving order
        _patched_cm[_ver] = (
            {i: v for i, v in enumerate(_model)}
            if isinstance(_model, list)
            else _model
        )
    # Freeze a new ProtocolParameters with patched cost_models
    _pp_new = _dc.replace(evaluation_context.protocol_param, cost_models=_patched_cm)
    # Monkeypatch the context instance so every call to .protocol_param returns the patched version
    _ctx_class = type(evaluation_context)
    _ctx_class.protocol_param = property(lambda self: _pp_new)
    print(
        f"Patched cost models: "
        f"V1={len(_patched_cm.get('PlutusV1', {}))}, "
        f"V2={len(_patched_cm.get('PlutusV2', {}))}, "
        f"V3={len(_patched_cm.get('PlutusV3', {}))}"
    )
else:
    print(f"Warning: {_NODE_PARAMS_PATH} not found — cost models may be incomplete")
from muesliswap_onchain_governance.utils.to_script_context import (
    to_address,
    to_fraction,
    to_tx_out_ref,
)
from muesliswap_onchain_governance.offchain.util import (
    TALLY_METADATA_KEY,
    asset_from_token,
    sorted_utxos,
    with_min_lovelace,
)

# ── load contracts ─────────────────────────────────────────────────────────────
gov_state_nft_script, gov_state_nft_policy_id, _ = get_contract(module_name(gov_state_nft), True)
gov_state_script,     _,                         gov_state_address = get_contract(module_name(gov_state), True)
tally_script,         _,                         tally_address      = get_contract(module_name(tally), True)
tally_auth_nft_script, tally_auth_nft_policy_id, _                 = get_contract(module_name(tally_auth_nft), True)
staking_script,       _,                         staking_address    = get_contract(module_name(staking), True)
_,                    staking_vote_nft_policy_id, _                 = get_contract(module_name(staking_vote_nft), True)
_,                    vault_ft_policy_id,         _                 = get_contract(module_name(vault_ft), True)
_,                    delegated_staking_policy_id, _                = get_contract(module_name(delegated_staking), True)
_,                    reputation_policy_id,        _                = get_contract(module_name(reputation), True)

ctx = evaluation_context   # Ogmios

# ── get_ref_utxo using evaluation_context ─────────────────────────────────────
def get_ref_utxo_ev(script: PlutusV2Script):
    addr = Address(payment_part=plutus_script_hash(script), network=network)
    for u in ctx.utxos(addr):
        if u.output.script == script:
            return u
    return None


# ── wallet ────────────────────────────────────────────────────────────────────
payment_vkey, payment_skey, payment_address = get_signing_info("creator", network=network)
print(f"Creator wallet : {payment_address.encode()}")

utxos = ctx.utxos(payment_address)
ada = sum(u.output.amount.coin for u in utxos)
print(f"  ADA balance  : {ada / 1_000_000:.2f} ADA")

# ── gov token ─────────────────────────────────────────────────────────────────
GOV_POLICY = bytes.fromhex("bd976e131cfc3956b806967b06530e48c20ed5498b46a5eb836b61c2")
GOV_NAME   = bytes.fromhex("744d494c4b7632")
governance_token = Token(policy_id=GOV_POLICY, token_name=GOV_NAME)


# ══════════════════════════════════════════════════════════════════════════════
#  STEP 1 — Initialise governance thread
# ══════════════════════════════════════════════════════════════════════════════

def init_governance():
    all_utxos = sorted_utxos(ctx.utxos(payment_address))
    unique_utxo = all_utxos[0]
    unique_utxo_index = 0

    gov_nft_name = gov_state_nft.gov_state_nft_name(to_tx_out_ref(unique_utxo.input))
    gov_nft_token = Token(
        policy_id=gov_state_nft_policy_id.payload,
        token_name=gov_nft_name,
    )
    print(f"\n[INIT] gov_state_nft token name : {gov_nft_name.hex()}")
    print(f"[INIT] gov_state_nft policy     : {gov_state_nft_policy_id.payload.hex()}")

    gov_state_datum = gov_state.GovStateDatum(
        gov_state.GovStateParams(
            tally_address=to_address(tally_address),
            staking_address=to_address(staking_address),
            governance_token=governance_token,
            vault_ft_policy=vault_ft_policy_id.payload,
            delegation_policy=delegated_staking_policy_id.payload,
            min_quorum=10,                              # very low for testing
            min_winning_threshold=to_fraction(Fraction(1, 4)),
            min_proposal_duration=1000,                 # 1 second (easy testing)
            gov_state_nft=gov_nft_token,
            tally_auth_nft_policy=tally_auth_nft_policy_id.payload,
            staking_vote_nft_policy=staking_vote_nft_policy_id.payload,
            latest_applied_proposal_id=gov_state.ALWAYS_EARLY_PROPOSAL_ID,
            parent_gov_nft=Token(policy_id=b"", token_name=b""),
            parent_tally_auth_nft_policy=b"",
            latest_applied_parent_proposal_id=gov_state.ALWAYS_EARLY_PROPOSAL_ID,
        ),
        last_proposal_id=gov_state.INITIAL_PROPOSAL_ID,
    )

    gov_nft_ref_utxo = get_ref_utxo_ev(gov_state_nft_script)

    builder = TransactionBuilder(ctx)
    builder.auxiliary_data = AuxiliaryData(
        data=AlonzoMetadata(
            metadata=Metadata({674: {"msg": ["MuesliSwap DAO — Create Governance Thread"]}})
        )
    )
    builder.add_input(unique_utxo)
    builder.add_input_address(payment_address)
    builder.add_minting_script(
        gov_nft_ref_utxo or gov_state_nft_script,
        Redeemer(OneShotMintRedeemer(unique_utxo_index=unique_utxo_index)),
    )
    output = with_min_lovelace(
        TransactionOutput(
            address=gov_state_address,
            amount=Value(coin=2_000_000, multi_asset=asset_from_token(gov_nft_token, 1)),
            datum=gov_state_datum,
        ),
        ctx,
    )
    builder.add_output(output)
    builder.mint = asset_from_token(gov_nft_token, 1)
    builder.ttl = ctx.last_block_slot + 100

    signed_tx = builder.build_and_sign(
        signing_keys=[payment_skey],
        change_address=payment_address,
    )
    ctx.submit_tx(signed_tx)
    print(f"[INIT] Submitted TX : {signed_tx.id}")
    print(f"[INIT] Gov NFT name : {gov_nft_name.hex()}")
    return signed_tx, gov_nft_name


# ══════════════════════════════════════════════════════════════════════════════
#  STEP 2 — Create a tally
# ══════════════════════════════════════════════════════════════════════════════

def create_tally(gov_nft_name: bytes, tally_state_datum: "tally.TallyState", metadata: dict, duration_minutes: int = 120):
    gov_nft_tk = Token(policy_id=gov_state_nft_policy_id.payload, token_name=gov_nft_name)
    auth_nft_tk = Token(policy_id=tally_auth_nft_policy_id.payload, token_name=gov_nft_name)

    gov_utxos = ctx.utxos(gov_state_address)
    gov_state_utxo = None
    for u in gov_utxos:
        if u.output.amount.multi_asset.get(
            __import__("pycardano").ScriptHash(gov_nft_tk.policy_id), {}
        ).get(__import__("pycardano").AssetName(gov_nft_tk.token_name)):
            gov_state_utxo = u
            break
    assert gov_state_utxo, f"Gov state UTxO not found for NFT {gov_nft_name.hex()[:16]}..."

    prev_datum = gov_state.GovStateDatum.from_cbor(gov_state_utxo.output.datum.cbor)
    new_proposal_id = gov_state.increment_proposal_id(prev_datum.last_proposal_id)
    new_gov_datum = gov_state.GovStateDatum(
        params=prev_datum.params,
        last_proposal_id=new_proposal_id,
    )

    payment_utxos = ctx.utxos(payment_address)
    all_inputs = sorted_utxos([gov_state_utxo] + payment_utxos)
    gov_input_index = all_inputs.index(gov_state_utxo)

    # Override proposal params with correct values from on-chain datum
    p = prev_datum.params
    end_time_ms = int((datetime.datetime.now() + datetime.timedelta(minutes=duration_minutes)).timestamp()) * 1000
    tally_state_datum.params.quorum = p.min_quorum
    tally_state_datum.params.winning_threshold = p.min_winning_threshold
    tally_state_datum.params.end_time = tally.FinitePOSIXTime(end_time_ms)
    tally_state_datum.params.proposal_id = new_proposal_id
    tally_state_datum.params.tally_auth_nft = auth_nft_tk
    tally_state_datum.params.staking_vote_nft_policy = p.staking_vote_nft_policy
    tally_state_datum.params.staking_address = p.staking_address
    tally_state_datum.params.governance_token = p.governance_token
    tally_state_datum.params.vault_ft_policy = p.vault_ft_policy
    tally_state_datum.params.delegation_policy = p.delegation_policy
    tally_state_datum.params.reputation_policy = reputation_policy_id.payload

    gov_state_script_ref = get_ref_utxo_ev(gov_state_script)
    tally_auth_nft_ref    = get_ref_utxo_ev(tally_auth_nft_script)

    builder = TransactionBuilder(ctx)
    builder.auxiliary_data = AuxiliaryData(
        data=AlonzoMetadata(
            metadata=Metadata({
                674: {"msg": ["MuesliSwap DAO Tally Creation"]},
                TALLY_METADATA_KEY: metadata,
            })
        )
    )
    for u in payment_utxos:
        builder.add_input(u)
    builder.add_script_input(
        gov_state_utxo,
        gov_state_script_ref or gov_state_script,
        None,
        Redeemer(gov_state.CreateNewTally(
            gov_state_input_index=gov_input_index,
            gov_state_output_index=1,
            tally_output_index=0,
        )),
    )
    builder.add_minting_script(
        tally_auth_nft_ref or tally_auth_nft_script,
        Redeemer(tally_auth_nft.AuthRedeemer(
            spent_utxo_index=gov_input_index,
            governance_nft_name=gov_nft_tk.token_name,
        )),
    )
    builder.mint = asset_from_token(auth_nft_tk, 1)

    builder.add_output(with_min_lovelace(
        TransactionOutput(
            address=tally_address,
            amount=Value(coin=2_000_000, multi_asset=asset_from_token(auth_nft_tk, 1)),
            datum=tally_state_datum,
        ),
        ctx,
    ))
    builder.add_output(TransactionOutput(
        address=gov_state_address,
        amount=gov_state_utxo.output.amount,
        datum=new_gov_datum,
    ))
    builder.ttl = ctx.last_block_slot + 100

    signed_tx = builder.build_and_sign(
        signing_keys=[payment_skey],
        change_address=payment_address,
    )
    ctx.submit_tx(signed_tx)
    print(f"  [TALLY] TX {signed_tx.id}  proposal_id={new_proposal_id}")
    return signed_tx


def wait_for_utxo(tx_hash: str, max_wait: int = 120):
    """Poll until the given tx appears in a UTxO at gov_state_address."""
    print(f"  Waiting for TX {tx_hash[:16]}... to be confirmed", end="", flush=True)
    deadline = time.time() + max_wait
    while time.time() < deadline:
        for u in ctx.utxos(gov_state_address):
            if u.input.transaction_id.payload.hex() == tx_hash:
                print(" confirmed!")
                return True
        print(".", end="", flush=True)
        time.sleep(8)
    print(" TIMEOUT")
    return False


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    # ── Check if governance thread already exists for new contract ─────────────
    existing_new_format = []
    for u in ctx.utxos(gov_state_address):
        try:
            d = gov_state.GovStateDatum.from_cbor(u.output.datum.cbor)
            existing_new_format.append((u, d))
            print(f"Found existing new-format gov thread: {u.input.transaction_id.payload.hex()[:16]}#{u.input.index}")
            print(f"  NFT name       : {d.params.gov_state_nft.token_name.hex()}")
            print(f"  last_proposal  : {d.last_proposal_id}")
        except Exception:
            pass  # old format

    if existing_new_format:
        gov_nft_name = existing_new_format[0][1].params.gov_state_nft.token_name
        print(f"\nUsing existing governance thread (NFT: {gov_nft_name.hex()[:32]}...)")
    else:
        print("\nNo new-format governance thread found — initialising...")
        init_tx, gov_nft_name = init_governance()
        wait_for_utxo(init_tx.id.payload.hex())

    # ── Tally 1: Community Improvement Proposal ───────────────────────────────
    print("\n[TALLY 1] Approve Community Improvement Fund")
    dummy_addr = to_address(payment_address)
    t1 = tally.TallyState(
        votes=[0, 0, 0],
        params=tally.ProposalParams(
            quorum=10,
            winning_threshold=to_fraction(Fraction(1, 4)),
            proposals=[
                tally.Nothing(),
                treasurer.FundPayoutParams(
                    output=TxOut(
                        address=dummy_addr,
                        value={b"": {b"": 50_000_000}},
                        datum=NoOutputDatum(),
                        reference_script=NoScriptHash(),
                    ),
                ),
                tally.Nothing(),  # placeholder Reject-equivalent
            ],
            end_time=tally.FinitePOSIXTime(0),  # will be overridden
            proposal_id=0,
            tally_auth_nft=Token(b"", b""),
            staking_vote_nft_policy=b"",
            staking_address=to_address(payment_address),
            governance_token=governance_token,
            vault_ft_policy=b"",
            delegation_policy=b"",
            reputation_policy=b"",
        ),
    )
    m1 = {
        "title": "Community Improvement Fund Q2",
        "description": [
            "Proposal to allocate 50 ADA from the treasury to fund ",
            "community-driven development initiatives in Q2 2026. ",
            "Funds will be managed by the community council.",
        ],
        "short_description": ["Allocate 50 ADA for Q2 community development."],
        "creator_name": "MuesliSwap DAO",
        "forum_link": "https://muesliswap.com",
        "proposals": [
            {"title": "Reject", "description": ["Do not allocate any funds."]},
            {"title": "Approve 50 ADA payout", "description": ["Allocate 50 ADA to the community council."]},
            {"title": "Abstain", "description": ["Neither approve nor reject; allow others to decide."]},
        ],
    }
    tx1 = create_tally(gov_nft_name, t1, m1, duration_minutes=2880)  # 2 days
    wait_for_utxo(tx1.id.payload.hex())

    # ── Tally 2: Protocol Parameter Update ───────────────────────────────────
    print("\n[TALLY 2] Adjust Quorum and Winning Threshold")
    t2 = tally.TallyState(
        votes=[0, 0, 0],
        params=tally.ProposalParams(
            quorum=10,
            winning_threshold=to_fraction(Fraction(1, 4)),
            proposals=[
                tally.Nothing(),
                tally.Nothing(),  # placeholder for GovStateUpdate
                tally.Nothing(),
            ],
            end_time=tally.FinitePOSIXTime(0),
            proposal_id=0,
            tally_auth_nft=Token(b"", b""),
            staking_vote_nft_policy=b"",
            staking_address=to_address(payment_address),
            governance_token=governance_token,
            vault_ft_policy=b"",
            delegation_policy=b"",
            reputation_policy=b"",
        ),
    )
    m2 = {
        "title": "Governance Parameter Update v2",
        "description": [
            "Update governance parameters: raise quorum to 1000 tMILK",
            "and winning threshold to 33%.",
            "This strengthens voter participation requirements.",
        ],
        "short_description": ["Update quorum to 1000 tMILK, threshold to 33%."],
        "creator_name": "MuesliSwap DAO",
        "forum_link": "https://muesliswap.com",
        "proposals": [
            {"title": "Keep current parameters", "description": ["No changes to governance parameters."]},
            {"title": "Increase quorum only", "description": ["Set min quorum to 1000 tMILK; keep threshold."]},
            {"title": "Update both parameters", "description": ["Set min quorum to 1000 and threshold to 33%."]},
        ],
    }
    tx2 = create_tally(gov_nft_name, t2, m2, duration_minutes=4320)  # 3 days
    wait_for_utxo(tx2.id.payload.hex())

    # ── Tally 3: Reputation-Weighted Staking Incentive ────────────────────────
    print("\n[TALLY 3] Reputation-Based Staking Rewards")
    t3 = tally.TallyState(
        votes=[0, 0],
        params=tally.ProposalParams(
            quorum=10,
            winning_threshold=to_fraction(Fraction(1, 4)),
            proposals=[
                tally.Nothing(),
                tally.Nothing(),  # placeholder
            ],
            end_time=tally.FinitePOSIXTime(0),
            proposal_id=0,
            tally_auth_nft=Token(b"", b""),
            staking_vote_nft_policy=b"",
            staking_address=to_address(payment_address),
            governance_token=governance_token,
            vault_ft_policy=b"",
            delegation_policy=b"",
            reputation_policy=b"",
        ),
    )
    m3 = {
        "title": "Enable Reputation-Weighted Voting Rewards",
        "description": [
            "Proposal to activate reputation-weighted staking rewards. ",
            "Voters who accumulate reputation tokens by participating in ",
            "governance will receive a multiplier on their staking yields. ",
            "This incentivises long-term engagement with the DAO.",
        ],
        "short_description": ["Activate reputation multiplier for staking rewards."],
        "creator_name": "MuesliSwap DAO",
        "forum_link": "https://muesliswap.com",
        "proposals": [
            {"title": "Reject", "description": ["Do not activate reputation rewards."]},
            {"title": "Activate rewards", "description": ["Enable reputation-weighted staking yield multiplier."]},
        ],
    }
    tx3 = create_tally(gov_nft_name, t3, m3, duration_minutes=1440)  # 1 day

    print(f"\n{'='*60}")
    print("Bootstrap complete!")
    print(f"  Gov NFT name : {gov_nft_name.hex()}")
    print(f"  Tally 1 TX   : {tx1.id}")
    print(f"  Tally 2 TX   : {tx2.id}")
    print(f"  Tally 3 TX   : {tx3.id}")
    print(f"  Gov state    : {gov_state_address.encode()}")
    print(f"\nUpdate GOV_STATE_NFT_TK_NAME in offchain/util.py to:")
    print(f"  {gov_nft_name.hex()}")
