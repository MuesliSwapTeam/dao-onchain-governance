"""
Seed script: insert 10 example wallets with reputation tokens into the DB
for frontend demonstration purposes. Real on-chain data will naturally
supersede these once reputation tokens are minted live.

Run from the project root:
    poetry run python dev/seed_reputation.py
"""

import hashlib
import os
import sys

import pycardano

# Ensure we're running from the project root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from muesliswap_onchain_governance.api.db_models import (
    Address,
    Block,
    Datum,
    StakingParams,
    StakingState,
    Token,
    Transaction,
    TransactionOutput,
    TransactionOutputValue,
    sqlite_db,
)
from muesliswap_onchain_governance.offchain.util import GOV_STATE_NFT_TK_NAME

# Reputation policy from friend's deployed contracts (reputationVoting branch)
REPUTATION_POLICY_ID = "031d0e9a19b4c9752c4699cd96a09c82041484eae3359f855d34426a"

# Governance token (preprod tMILK)
GOV_POLICY_ID = "bd976e131cfc3956b806967b06530e48c20ed5498b46a5eb836b61c2"
GOV_ASSET_NAME = "744d494c4b7632"

# Tally auth NFT (root DAO — friend's deployed contracts)
TALLY_AUTH_POLICY = "cd9e11cb9eecf0850830c3cdad33936d573454ce07b0ede5d734d9bd"
TALLY_AUTH_NAME = GOV_STATE_NFT_TK_NAME

# Vault FT and delegation policies (from friend's deployed contracts)
VAULT_FT_POLICY = "880428212e96c056d66b2b1e92475d98976111c11f92095048d62872"
DELEGATION_POLICY = "f55036e67f4f8500e099f522ac0a3618e899947221ffeb6e5ea35659"

# 10 example wallets as bech32 Cardano preprod addresses, with reputation counts.
# The first entry is the real demo wallet used by the friend during the reputation demo.
EXAMPLE_WALLETS = [
    ("addr_test1vp5rxp4jcc905zgnczq3906k6l3teyt2vhzeerqpdhkuvggmy9qzu", 5),
    ("addr_test1vrqvjz9t2sr9s37gttqmm45nelkk2lqylfs7cx3nra96gnsl7hn9l", 4),
    ("addr_test1vrast2qqzfj33a3pfxmr3smwz506ks2w7avmnlzjl05fqccme4fdn", 4),
    ("addr_test1vpfuezta7nrjur74jg4e93z8658k5c272f7qrr0epn7c7hq8pv5pk", 3),
    ("addr_test1vp6y6e6hjzlrv3vsvj72efg0a4hu939asqzw6632c570hzg7rsva5", 3),
    ("addr_test1vr9d455k2kvsswttnu0v5ftq8gcfs2vn8w8yy93rmn93a7q23yhm8", 2),
    ("addr_test1vqt26e49zm949zvf8yxl42zj6pnxnsc9flzuq0jmvc58gzgp5uzmp", 2),
    ("addr_test1vr0wv8ymt9mhv4ckjksm8cln2x54j0cwfrttha8rg450kwqm8re89", 1),
    ("addr_test1vz8eqsy3fn87sq2hgtmdm0srmzcqxftfez9mkqxdj7nckasadgy8x", 1),
    ("addr_test1vpd3xs5c33g0ddjjcs67wjqlxkua99xgkclewtv7rwavcrs6l7264", 1),
]

SEED_BLOCK_HASH = "seed0000000000000000000000000000000000000000000000000000000000000"
SEED_SLOT = 99_999_999


def reputation_token_name(pkh_hex: str) -> str:
    return hashlib.sha256(bytes.fromhex(pkh_hex)).hexdigest()


def seed():
    with sqlite_db.atomic():
        # Create a synthetic block for seed data
        block, _ = Block.get_or_create(
            hash=SEED_BLOCK_HASH,
            defaults={"slot": SEED_SLOT, "height": 999_999},
        )

        gov_token, _ = Token.get_or_create(
            policy_id=GOV_POLICY_ID,
            asset_name=GOV_ASSET_NAME,
        )
        tally_auth_token, _ = Token.get_or_create(
            policy_id=TALLY_AUTH_POLICY,
            asset_name=TALLY_AUTH_NAME,
        )
        ada_token, _ = Token.get_or_create(policy_id="", asset_name="")

        inserted = 0
        for idx, (addr_bech32, rep_count) in enumerate(EXAMPLE_WALLETS):
            addr = pycardano.Address.decode(addr_bech32)
            wallet_hex = addr.to_primitive().hex()
            pkh = addr.payment_part.payload.hex()

            rep_name = reputation_token_name(pkh)
            wallet_rep_token, _ = Token.get_or_create(
                policy_id=REPUTATION_POLICY_ID,
                asset_name=rep_name,
            )

            owner_addr, _ = Address.get_or_create(address_raw=wallet_hex)

            staking_params, _ = StakingParams.get_or_create(
                owner=owner_addr,
                governance_token=gov_token,
                vault_ft_policy=VAULT_FT_POLICY,
                delegation_policy=DELEGATION_POLICY,
                reputation_policy=REPUTATION_POLICY_ID,
                tally_auth_nft=tally_auth_token,
            )

            tx_hash = f"seed{idx:04d}" + "0" * 60
            tx, _ = Transaction.get_or_create(
                transaction_hash=tx_hash,
                defaults={"block": block, "block_index": idx},
            )

            # Minimal datum (empty bytes)
            datum_hex = "00"
            datum, _ = Datum.get_or_create(
                hash=hashlib.sha256(bytes.fromhex(datum_hex)).hexdigest()[:64],
                defaults={"data": bytes.fromhex(datum_hex)},
            )

            txo, created = TransactionOutput.get_or_create(
                transaction_hash=tx_hash,
                output_index=0,
                defaults={
                    "transaction": tx,
                    "address": owner_addr,
                    "datum_hash": datum,
                    "spent_in_block": None,
                },
            )
            if not created:
                print(f"  skipping {addr_bech32} (already exists)")
                continue

            StakingState.create(
                transaction_output=txo,
                staking_params=staking_params,
            )

            # ADA (2 ADA min)
            TransactionOutputValue.create(
                transaction_output=txo, token=ada_token, amount=2_000_000
            )
            # Governance tokens (1000 MILK)
            TransactionOutputValue.create(
                transaction_output=txo, token=gov_token, amount=1_000_000_000
            )
            # Reputation tokens
            TransactionOutputValue.create(
                transaction_output=txo, token=wallet_rep_token, amount=rep_count
            )

            print(f"  inserted {addr_bech32} with {rep_count} reputation token(s)")
            inserted += 1

        print(f"\nSeeded {inserted} example reputation holders.")
        print(f"Reputation policy ID: {REPUTATION_POLICY_ID}")


if __name__ == "__main__":
    seed()
