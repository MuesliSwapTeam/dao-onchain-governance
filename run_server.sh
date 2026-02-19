#!/usr/bin/env bash

POETRY_BIN=/home/cardano-preprod/.local/bin/poetry

# exit when any command fails
set -e

# cd into the right directory
cd "$(dirname "$0")"

$POETRY_BIN install

$POETRY_BIN run uvicorn muesliswap_onchain_governance.api.server:app --host localhost --port 8001
