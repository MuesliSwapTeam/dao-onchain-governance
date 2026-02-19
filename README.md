MuesliSwap On-Chain Governance
------------------------------

This repository contains the documentation and code for the MuesliSwap DAO.

**Delegation** — This implementation includes on-chain delegation as part of the [Catalyst project 1300146: Next-Gen DAOs: On-Chain Delegation, Hierarchies & Reputation](https://milestones.projectcatalyst.io/projects/1300146). Delegation allows token holders to delegate their voting power to representatives (delegatees) who can vote on their behalf. Delegators lock governance tokens in the delegated staking contract and receive fungible delegation tokens (with expiry encoded in the token name) that are transferred to their chosen representative. The representative can then use these tokens in the staking contract to participate in tallies. Delegation positions can be opened, updated (stake amount, expiry, or representative), and revoked. The system also supports consolidation of multiple delegation tokens and reclaiming tokens after expiry.

### Structure

The directory `report` contains a detailed report on the outline and planned implementation and integration
of the On-Chain Governance system into the MuesliSwap governance platform.
It further outlines a short comparison to alternative implementations.

The directory `muesliswap_onchain_governance` contains the code for the blockchain part of the On-Chain Governance system.
The following subdirectories are present:

- `onchain`: Contains the code for the on-chain part of the governance system i.e. Smart Contracts written in OpShin
- `offchain`: Contains the code for the off-chain part of the governance system i.e. building and submitting transactions for interaction with the Smart Contracts
- `api`: Contains code for the REST API that provides information about the governance system
    - `chain_querier`: Contains the code for querying the blockchain for information about the governance system and tracking the current state of the system in a database
    - `db_querier`: Contains the code for querying data from the database to prepare it for the REST API
    - `server`: Contains the code for the server that supplies information about the governance system via a REST API
- `onchain/delegation`: Contains the delegated staking smart contract (OpShin) for on-chain delegation
- `offchain/delegation`: Contains scripts for opening, extending, revoking, and consolidating delegation positions

### Delegation (Catalyst 1300146)

Delegation enables token holders to delegate voting power to representatives. Key components:

- **On-chain implementation** (`onchain/delegation/delegated_staking.py`):
  - **Contract**: OpShin validator that locks governance tokens and mints fungible delegation tokens. The token name encodes the delegation expiry (POSIX time in milliseconds as big-endian bytes).
  - **Datums**: `DelegationDatum` (expiry, owner pubkey hash) for standard positions; `ConsolidationDatum` (lower_bound, owner, amount) for consolidated positions.
  - **Redeemers**:
    - `OpenDelegationPosition` — Lock gov tokens, mint delegation tokens, send them to delegatee address.
    - `RevokeDelegationBeforeExpiry` — Owner signs; burn delegation tokens to unlock gov tokens early.
    - `ReclaimExpiredDelegation` — Owner signs; reclaim gov tokens after expiry (no burn required).
    - `BurnExpiredDelegationTokens` — Burn expired delegation tokens (utility).
    - `RenewDelegationBeforeExpiry` / `RenewDelegationAfterExpiry` — Burn old and mint new delegation tokens with updated expiry.
    - `ConsolidateDelegation` — Merge multiple delegation tokens (different expiries) into one with a `lower_bound` expiry.
    - `DeconsolidateDelegation` — Split a consolidated token back; owner must sign.
  - **Integration with staking**: The staking contract accepts delegation tokens (via `delegation_policy` in gov params). A delegation token counts as voting weight only if its expiry ≥ tally end time. Delegation tokens and vault FT tokens together form the variable governance weight used in vote validation. Contract outputs (locked gov tokens) remain at the delegation address; minted delegation tokens are sent to the delegatee, who deposits them into the staking contract to vote.
- **REST API**:
  - `GET /api/v1/delegation/positions?pkh=<pubkey_hash>` — Open delegation positions for a wallet
  - `GET /api/v1/delegation/history?pkh=<pubkey_hash>` — Delegation history for a wallet
  - `POST /api/v1/delegation/delegate` — Construct open delegation position transaction
  - `POST /api/v1/delegation/update_delegation` — Construct delegation update transaction
  - `POST /api/v1/delegation/revoke_delegation` — Construct revoke delegation transaction
- **Offchain scripts** (in `offchain/delegation/`): `open_position`, `extend_delegation`, `close_position_early`, `consolidate_delegation_tokens`, `deconsolidate_delegation_tokens`, `retrieve_tokens_after_expiry`, `pipeline`

### Environments

The smart contracts were built using opshin 0.23.1. Inorder to rebuild the contracts, copy the contents of pyproject-build.toml into pyproject.toml and install the project. For all other operations, copy the contents of pyproject-api.toml into pyproject.toml before installation.

### Operating the DAO

The DAO can be initialized by deploying the smart contracts in the `onchain` directory using the scripts provided in the `offchain` directory.
For this, you need to have an Ogmios endpoint available and set the environment variables `OGMIOS_API_HOST`, `OGMIOS_API_PROTOCOL` and `OGMIOS_API_PORT` to the respective values (default `localhost`, `ws` and `1337`).
Further, install the current project.

```bash
poetry install
```

Create and fund two wallets for the DAO administration and for voting.
You can use the [testnet faucet](https://docs.cardano.org/cardano-testnet/tools/faucet/) to fund them, make sure to select `preprod` network!.

```bash
python3 -m muesliswap_onchain_governance.create_key_pair creator
python3 -m muesliswap_onchain_governance.create_key_pair voter
python3 -m muesliswap_onchain_governance.create_key_pair vault_admin
```

Then, build the smart contracts. Note that this requires the [`aiken`](https://aiken-lang.org) executable present in the `PATH` environment variable. The original contract was built with version `aiken v1.0.26-alpha+075668b`.

```bash
python3 -m muesliswap_onchain_governance.build
``` 

Create a governance thread using the `creator` wallet.

```bash
python3 -m muesliswap_onchain_governance.offchain.gov_state.init --wallet creator --governance_token bd976e131cfc3956b806967b06530e48c20ed5498b46a5eb836b61c2.744d494c4b7632
```

This will create a new governance thread and print the thread id. You can use this thread id to interact with the governance system.
For convenience, you can update the `GOV_STATE_NFT_TK_NAME` in `muesliswap_onchain_governance/offchain/util.py` to the thread id.
Next, you can create a tally using the `creator` wallet.

```bash
python3 -m muesliswap_onchain_governance.offchain.gov_state.create_tally --wallet creator
```

The default for this tally is to open for 10 minutes and allow choosing between a treasury payout to `voter` and a license mint.
> Note: in a production environment you would never want a tally with expiry date for licenses, as this would allow for a license to be minted indefinitely.
Next, you can register the `voter` wallet as a voter by locking the governance tokens in the staking contract and using the stake to vote.

```bash
python3 -m muesliswap_onchain_governance.offchain.staking.init --wallet voter
python3 -m muesliswap_onchain_governance.offchain.tally.add_vote_tally --wallet voter --proposal_id 1 --proposal_index 1
```

This will lock the governance tokens in the staking contract and use the stake to vote for the second (index 1) proposal in the first tally.
This proposal empowers the DAO to a treasury payout to the `voter` wallet.
After the proposal ended (i.e. default 10 minutes), you can execute the tally using any wallet.
For this you need to first initialize the treasury (again for convenience update the `TREASURER_STATE_NFT_TK_NAME`), deposit funds and then execute the tally.

```bash
python3 -m muesliswap_onchain_governance.offchain.treasury.init --wallet creator
python3 -m muesliswap_onchain_governance.offchain.treasury.deposit --wallet creator
python3 -m muesliswap_onchain_governance.offchain.treasury.payout --wallet voter
```

### Upgrading a liquidity pool

The DAO can also be used to upgrade a liquidity pool. For this, you need to create a new liquidity pool and a proposal to upgrade the liquidity pool.
The following commands will create a new liquidity pool and a proposal to upgrade the liquidity pool.

```bash
python3 -m muesliswap_onchain_governance.offchain.simple_pool.init --wallet creator
python3 -m muesliswap_onchain_governance.offchain.gov_state.create_tally --wallet creator
python3 -m muesliswap_onchain_governance.offchain.tally.add_vote_tally --wallet voter --proposal_index 3
python3 -m muesliswap_onchain_governance.offchain.simple_pool.upgrade --wallet voter
```

### Running the API

First, make sure that Ogmios is set up correctly. Then, you can start the querier to track the blockchain using the following command.

```bash
python3 -m muesliswap_onchain_governance.api.chain_querier & 
```

To start the REST API, use the following command.

```bash
uvicorn muesliswap_onchain_governance.api.server:app --reload --port 8001
```


