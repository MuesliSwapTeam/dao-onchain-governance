#!/usr/bin/env bash

sudo systemctl restart preprod-dao-api-querier.service
sudo systemctl restart preprod-dao-api-server.service
sudo systemctl restart preprod-dao-vote-retract-batcher.service
sudo systemctl restart preprod-dao-votes-batcher.service