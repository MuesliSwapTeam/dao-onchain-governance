Configurable gov state

```bash
python3 -m muesliswap_onchain_governance.offchain.gov_state.init --min_quorum 1000000 --min_proposal_duration 600
```

Create new treasury

```bash
python3 -m muesliswap_onchain_governance.offchain.treasury.init
```

Deposit into treasury

```bash
python3 -m muesliswap_onchain_governance.offchain.treasury.deposit --deposit_amount 5000000
python3 -m muesliswap_onchain_governance.offchain.treasury.deposit --deposit_amount 5000000 --deposit_token '.'
```



Make new tally
```bash
python3 -m dev.new_tally --treasury_benefactor addr_test1qpqchd994g4cgv67uv346zvmhqu290ah7wwyqqty4at2akf84q8sdhrug5rnwx7p7rgvtqhx6wzkxfcx5tcwkcsy4akqcee0wx --duration_open 10
```

Make new batcher license tally
```bash
python3 -m dev.batcher_license_tally --license_recipient addr_test1qpqchd994g4cgv67uv346zvmhqu290ah7wwyqqty4at2akf84q8sdhrug5rnwx7p7rgvtqhx6wzkxfcx5tcwkcsy4akqcee0wx
```

Vote
```bash
python3 -m muesliswap_onchain_governance.offchain.tally.add_vote_tally --proposal_id 4 --proposal_index 1 --voting_power 1000000
```

Mint batcher license
```bash
python3 -m dev.mint_batcher_license --target_address addr_test1vpsud8wwkxr6lvalky0yd5x06uvkqqar397vfcwkfj9d4cc68kmcl 
```