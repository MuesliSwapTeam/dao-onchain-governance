from test.offchain.util import wait_for_tx
from muesliswap_onchain_governance.submit_ref_script import main as submit_ref_scripts


def test_submit_ref_script():
    tx = submit_ref_scripts(compress=True)
    if tx is not None:
        wait_for_tx(tx)
