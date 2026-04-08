#!/usr/bin/env bash

export BLOCKFROST_PROJECT_ID=preprodqWLNyA9zERJ1OTxjQb1Gs44DoDvuqm5e

POETRY_BIN=/home/cardano-preprod/.local/bin/poetry

# exit when any command fails
set -e

# cd into the right directory
cd "$(dirname "$0")"

$POETRY_BIN install

$POETRY_BIN run python3 -m muesliswap_onchain_governance.api.chain_querier
