#!/usr/bin/env bash

POETRY_BIN=/home/cardano-preprod/.local/bin/poetry

# exit when any command fails
set -e

# cd into the right directory
cd "$(dirname "$0")"

cp pyproject-build.toml pyproject.toml

$POETRY_BIN lock
$POETRY_BIN install

$POETRY_BIN run python3 -m muesliswap_onchain_governance.build 

cp pyproject-api.toml pyproject.toml
$POETRY_BIN lock
$POETRY_BIN install