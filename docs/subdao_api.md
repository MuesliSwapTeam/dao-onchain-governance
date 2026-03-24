# Sub-DAO API Reference

## Overview

Sub-DAOs are independently governed threads that are authorized by a parent DAO. They share the same on-chain contracts (same `gov_state_nft` policy, same tally/staking contracts) but each has its own governance NFT, governance parameters, and proposal history.

The hierarchy is:

```
Root DAO (gov_nft.asset_name = GOV_STATE_NFT_TK_NAME)
  └── Sub-DAO A (gov_nft.asset_name = <hash of pre-committed UTxO>)
        └── Sub-DAO A1 (further nesting is possible)
  └── Sub-DAO B
```

A sub-DAO is linked to its parent via the `parent_gov_nft` field in `GovStateParams`. Root DAOs use sentinel values (`policy_id = ""`, `asset_name = ""`).

---

## How Sub-DAOs Work On-Chain

### Key Types

**`GovStateParams`** (stored in every DAO's datum):
- `gov_state_nft` — this DAO's unique NFT (policy_id + token_name)
- `tally_auth_nft_policy` — minting policy for this DAO's tally auth NFTs
- `parent_gov_nft` — parent DAO's NFT (`Token("", "")` for root)
- `parent_tally_auth_nft_policy` — parent's tally policy (`""` for root)
- `latest_applied_parent_proposal_id` — last parent proposal applied to this sub-DAO

**`CreateSubDaoParams`** (vote outcome, CONSTR_ID 101):
- Stored inside a tally's proposals list
- Contains the full `GovStateParams` for the to-be-created sub-DAO
- Contains the `address` where the sub-DAO will live (must differ from parent)

### Sub-DAO Creation Flow

1. **Create tally** — A parent DAO member calls `POST /api/v1/gov/create-sub-dao-tally`. This creates a tally in the parent DAO with a `CreateSubDaoParams` proposal. The sub-DAO's NFT token name is derived deterministically from a pre-committed UTxO that the proposer must keep unspent.

2. **Voting** — Governance token holders vote during the tally's open period using existing vote endpoints.

3. **Execute** — After the tally expires and quorum is reached, anyone calls `POST /api/v1/gov/execute-sub-dao`. This spends the pre-committed UTxO, mints the sub-DAO's governance NFT (one-shot policy), and creates the initial `GovStateDatum` at the address specified in the proposal.

4. **Sub-DAO is live** — The new sub-DAO appears in `GET /api/v1/gov/state` with `is_root_dao: false`. Its tallies can be queried via `GET /api/v1/tallies/by-dao`.

### Tally Auth NFT Filtering

Every tally has a `tally_auth_nft` whose token name equals the governance thread's `gov_state_nft.asset_name`. This is how tallies are scoped to a specific DAO. The existing `GET /api/v1/tallies` endpoint filters to the root DAO's token name. `GET /api/v1/tallies/by-dao` accepts any token name.

---

## What Changed in the API

### DB (`api/db_models/gov_state.py`)
`GovParams` gained four new nullable columns:
- `parent_gov_nft_policy` — parent DAO's NFT policy ID (empty string for root)
- `parent_gov_nft_name` — parent DAO's NFT token name (empty string for root)
- `parent_tally_auth_nft_policy` — parent's tally auth NFT policy (empty string for root)
- `latest_applied_parent_proposal_id` — last parent proposal applied

Migration runs automatically at startup via `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`.

### TX Processor (`api/tx_processor/gov_state.py`)
Now extracts the four parent fields from `GovStateParams` and stores them in `GovParams`.

### Gov State Query (`api/db_queries/gov_state.py`)
`query_current_gov_state()` now returns **all** governance threads (root + sub-DAOs). The previous hardcoded root-only filter was removed. Each result includes `parent_gov_nft`, `parent_tally_auth_nft_policy`, `latest_applied_parent_proposal_id`, and `is_root_dao`.

### Tally Query (`api/db_queries/tally.py`)
- `query_tallies()` now accepts an optional `gov_nft_asset_name` parameter. When provided, returns only tallies for that DAO. When omitted, defaults to the root DAO's token names (backward-compatible).
- Constructor 101 proposal parsing now tries `CreateSubDaoParams` before `LicenseReleaseParams` (they share the same CONSTR_ID; disambiguation is done by field structure).
- The redundant root-DAO-only filter was removed from `query_tally_details_by_auth_nft_proposal_id` and `query_all_user_votes_for_tally` (those functions already filter in SQL).

---

## API Endpoints

### `GET /api/v1/gov/state`

Returns all governance threads (root DAO + all sub-DAOs).

**Response** (array):
```json
[
  {
    "transaction_hash": "abc123...",
    "output_index": 0,
    "last_proposal_id": 5,
    "tally_address": "addr1...",
    "staking_address": "addr1...",
    "gov_token": { "policy_id": "afbe91...", "asset_name": "4d494c..." },
    "min_quorum": 1000000,
    "min_proposal_duration": 3600000,
    "min_winning_threshold": "1/4",
    "gov_nft": { "policy_id": "471b0b...", "asset_name": "4d494c..." },
    "tally_auth_nft_policy": "471b0b...",
    "staking_vote_nft_policy": "...",
    "latest_applied_proposal_id": 4,
    "utxo_assets": { "lovelace": 2000000, "471b0b....4d494c...": 1 },
    "parent_gov_nft": { "policy_id": "", "asset_name": "" },
    "parent_tally_auth_nft_policy": "",
    "latest_applied_parent_proposal_id": null,
    "is_root_dao": true
  },
  {
    "gov_nft": { "policy_id": "471b0b...", "asset_name": "bc0a47..." },
    "parent_gov_nft": { "policy_id": "471b0b...", "asset_name": "4d494c..." },
    "is_root_dao": false,
    ...
  }
]
```

**How to build the DAO tree**: Match `parent_gov_nft.asset_name` to the `gov_nft.asset_name` of the parent entry. Root DAOs have `parent_gov_nft.asset_name == ""`.

---

### `GET /api/v1/gov/sub-daos`

Returns only sub-DAO entries (where `is_root_dao = false`). Same shape as `/api/v1/gov/state`.

---

### `GET /api/v1/tallies/by-dao`

Returns tallies for a specific DAO.

**Query parameters**:
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `gov_nft_asset_name` | string | yes | Hex token name of the DAO's gov state NFT (from `gov_nft.asset_name` in `/api/v1/gov/state`) |
| `open` | bool | no | Include open tallies (default: true) |
| `closed` | bool | no | Include closed tallies (default: true) |
| `contains_proposal_type` | string | no | Comma-separated proposal type filter (default: "any") |

**Example**:
```
GET /api/v1/tallies/by-dao?gov_nft_asset_name=bc0a47f8459162152c33913f9d4e50d2340459ce4b6197761967d64368e0e50c&open=true&closed=false
```

**Response**: Same shape as `GET /api/v1/tallies`.

A `CreateSubDaoParams` proposal appears in the votes array with `details.sub_dao_params` populated:
```json
{
  "proposal": { "constructor": 101, ... },
  "proposal_type": "LicenseReleaseOrCreateSubDao",
  "details": {
    "sub_dao_params": {
      "gov_state_nft": { "policy_id": "471b0b...", "asset_name": "bc0a47..." },
      "tally_address": "addr1...",
      "governance_token": { "policy_id": "...", "asset_name": "..." },
      "tally_auth_nft_policy": "...",
      "parent_gov_nft": { "policy_id": "471b0b...", "asset_name": "4d494c..." },
      "min_quorum": 1000000,
      "min_winning_threshold": "1/4",
      "min_proposal_duration": 3600
    },
    "address": "addr1..."
  }
}
```

Detect `CreateSubDaoParams` proposals by checking `details.sub_dao_params != null`.

---

### `POST /api/v1/gov/create-sub-dao-tally`

Creates a tally in the parent DAO proposing the creation of a new sub-DAO.

**Important**: The `nft_utxo` is NOT spent in this transaction. The proposer must keep it unspent until `POST /api/v1/gov/execute-sub-dao` is called.

**Request body**:
```json
{
  "proposer_address": "<hex-encoded address, e.g. pycardano Address.to_primitive().hex()>",
  "parent_gov_nft_name": "<hex token name of parent DAO's gov NFT>",
  "nft_utxo_tx_hash": "<tx hash of UTxO to pre-commit>",
  "nft_utxo_index": 0,
  "sub_dao_address": "<bech32 address for sub-DAO — must differ from parent gov_state address>",
  "duration_minutes": 1500,
  "sub_dao_min_quorum": null,
  "sub_dao_min_winning_threshold_num": 1,
  "sub_dao_min_winning_threshold_den": 4,
  "sub_dao_min_proposal_duration": null,
  "title": "Create Sub-DAO",
  "description": "This proposal creates a new sub-DAO governance thread."
}
```

Fields with `null` inherit from the parent DAO.

**Response**:
```json
{
  "signed_tx": "<CBOR hex, partially signed by server collateral key>",
  "tx_body": "<CBOR hex of unsigned TX body>",
  "sub_dao_nft_name": "<hex token name of the sub-DAO NFT that will be minted>"
}
```

**Save `sub_dao_nft_name`** — it is required for `POST /api/v1/gov/execute-sub-dao` and will be the `gov_nft.asset_name` of the new sub-DAO in `GET /api/v1/gov/state` once created.

**Frontend flow**:
1. Add the proposer's signature: `POST /api/v1/append_signature` with `tx=signed_tx`
2. Submit the returned TX to the blockchain

---

### `POST /api/v1/gov/execute-sub-dao`

Executes a winning `CreateSubDaoParams` tally, minting the sub-DAO NFT and creating the initial governance state.

**Prerequisites**:
- The tally's voting period must have ended
- The `CreateSubDaoParams` proposal must have the most votes
- The `nft_utxo` must still be unspent at the proposer's address

**Request body**:
```json
{
  "proposer_address": "<hex-encoded address>",
  "parent_gov_nft_name": "<hex token name of parent DAO's gov NFT>",
  "nft_utxo_tx_hash": "<same tx hash used in create-sub-dao-tally>",
  "nft_utxo_index": 0
}
```

**Response**:
```json
{
  "signed_tx": "<CBOR hex, partially signed by server collateral key>",
  "tx_body": "<CBOR hex of unsigned TX body>"
}
```

**Frontend flow**:
1. Add the proposer's signature: `POST /api/v1/append_signature`
2. Submit the TX
3. The sub-DAO now appears in `GET /api/v1/gov/state` with `is_root_dao: false`

---

## Frontend Integration Checklist

### Displaying the DAO Tree

```typescript
// 1. Fetch all DAOs
const states = await fetch('/api/v1/gov/state').then(r => r.json());

// 2. Build tree
const rootDaos = states.filter(s => s.is_root_dao);
const subDaos = states.filter(s => !s.is_root_dao);

function getChildren(parentNftName: string) {
  return subDaos.filter(s => s.parent_gov_nft.asset_name === parentNftName);
}
```

### Fetching Proposals for a DAO

```typescript
// Replace GOV_STATE_NFT_TK_NAME with the specific DAO's gov_nft.asset_name
const nftName = daoState.gov_nft.asset_name;
const proposals = await fetch(
  `/api/v1/tallies/by-dao?gov_nft_asset_name=${nftName}&open=true&closed=true`
).then(r => r.json());
```

### Detecting CreateSubDao Proposals

```typescript
for (const vote of proposal.votes) {
  if (vote.details?.sub_dao_params) {
    // This is a CreateSubDaoParams proposal
    const subDaoNftName = vote.details.sub_dao_params.gov_state_nft.asset_name;
    const subDaoAddress = vote.details.address;
  }
}
```

### Creating a Sub-DAO Proposal

```typescript
// Step 1: User picks a UTxO from their wallet to pre-commit
const nftUtxo = wallet.getUtxos()[0];  // any UTxO the user controls

// Step 2: Build the tally TX
const response = await fetch('/api/v1/gov/create-sub-dao-tally', {
  method: 'POST',
  body: JSON.stringify({
    proposer_address: wallet.getAddressHex(),
    parent_gov_nft_name: parentDao.gov_nft.asset_name,
    nft_utxo_tx_hash: nftUtxo.txHash,
    nft_utxo_index: nftUtxo.outputIndex,
    sub_dao_address: 'addr1...',  // sub-DAO script address
    duration_minutes: 1500,
  })
}).then(r => r.json());

// Save sub_dao_nft_name for later!
const subDaoNftName = response.sub_dao_nft_name;

// Step 3: Add user's signature
const finalTx = await fetch('/api/v1/append_signature', {
  method: 'POST',
  body: JSON.stringify({ tx: response.signed_tx, ... })
}).then(r => r.json());

// Step 4: Submit TX (wallet-specific)
await wallet.submitTx(finalTx);

// Later, after voting period ends:

// Step 5: Execute the winning tally
const execResponse = await fetch('/api/v1/gov/execute-sub-dao', {
  method: 'POST',
  body: JSON.stringify({
    proposer_address: wallet.getAddressHex(),
    parent_gov_nft_name: parentDao.gov_nft.asset_name,
    nft_utxo_tx_hash: nftUtxo.txHash,
    nft_utxo_index: nftUtxo.outputIndex,
  })
}).then(r => r.json());

// Step 6: Sign and submit execution TX
```

---

## Integration Checklist (What Was Changed)

To add sub-DAO support to an existing governance API deployment:

- [x] **DB migration** — `api/db_models/__init__.py` runs `ALTER TABLE govparams ADD COLUMN IF NOT EXISTS` at startup (automatic)
- [x] **DB model** — `api/db_models/gov_state.py` — `GovParams` has 4 new nullable fields
- [x] **TX processor** — `api/tx_processor/gov_state.py` — extracts and stores parent fields from `GovStateParams`
- [x] **Gov state query** — `api/db_queries/gov_state.py` — returns all DAOs with parent fields; root-only filter removed
- [x] **Tally query** — `api/db_queries/tally.py` — `query_tallies()` accepts optional `gov_nft_asset_name`; constructor 101 disambiguation added; detail/votes query root filter removed
- [x] **New GET endpoints** — `api/server.py` — `/api/v1/gov/sub-daos` and `/api/v1/tallies/by-dao`
- [x] **New POST endpoints** — `api/server.py` — `/api/v1/gov/create-sub-dao-tally` and `/api/v1/gov/execute-sub-dao`
- [x] **TX builders** — `api/cardano/sub_dao_txs.py` — new module
- [x] **Schema** — `api/schema.py` — `CreateSubDaoTallyRequest`, `CreateSubDaoTallyResponse`, `ExecuteSubDaoRequest`

**No changes required to**: on-chain validators, tally processor, staking processor, delegation processor, or frontend token metadata API.

**Re-sync note**: Existing governance states already in the DB will have `NULL` for the four parent fields. They will be updated the next time those UTxOs are processed (spent and re-created). For immediate population, re-sync from the block before the first governance state was created.
