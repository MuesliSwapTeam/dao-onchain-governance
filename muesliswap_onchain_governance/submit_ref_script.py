# create reference UTxOs
import logging
from time import sleep

import fire
from pycardano import (TransactionBuilder, TransactionOutput, Value,
                       min_lovelace)

from muesliswap_onchain_governance.onchain.delegation import delegated_staking
from muesliswap_onchain_governance.onchain.gov_state import (gov_state,
                                                             gov_state_nft)
from muesliswap_onchain_governance.onchain.licenses import licenses
from muesliswap_onchain_governance.onchain.simple_pool import simple_pool
from muesliswap_onchain_governance.onchain.staking import (staking,
                                                           staking_vote_nft,
                                                           vault_ft,
                                                           vote_permission_nft)
from muesliswap_onchain_governance.onchain.tally import tally, tally_auth_nft
from muesliswap_onchain_governance.onchain.treasury import (treasurer,
                                                            treasurer_nft,
                                                            value_store)
from muesliswap_onchain_governance.onchain.vault import vault

from .utils import get_signing_info, network
from .utils.contracts import get_contract, get_ref_utxo, module_name
from .utils.network import context, show_tx

logging.getLogger("PyCardano").setLevel(logging.ERROR)


def main(compress: bool = True):
    owner = "scripts"
    payment_vkey, payment_skey, payment_address = get_signing_info(
        owner, network=network
    )
    signed_tx = None

    for contract in [
        delegated_staking,
        simple_pool,
        tally,
        tally_auth_nft,
        staking_vote_nft,
        staking,
        treasurer,
        value_store,
        licenses,
        treasurer_nft,
        gov_state_nft,
        gov_state,
        vote_permission_nft,
        vault_ft,
        vault,
    ]:
        while True:
            try:
                contract_script, _, contract_address = get_contract(
                    module_name(contract), compressed=compress
                )
                ref_utxo = get_ref_utxo(contract_script, context)
                if ref_utxo:
                    print(
                        f"reference script UTXO for {module_name(contract)} already exists at {ref_utxo.input.transaction_id}"
                    )
                    break
                txbuilder = TransactionBuilder(context)
                output = TransactionOutput(
                    contract_address, amount=1_000_000, script=contract_script
                )
                output.amount = Value(min_lovelace(context, output))
                txbuilder.add_output(output)
                txbuilder.add_input_address(payment_address)

                signed_tx = txbuilder.build_and_sign(
                    signing_keys=[payment_skey], change_address=payment_address
                )
                context.submit_tx(signed_tx)
                print(
                    f"creating {module_name(contract)} reference script UTXO; transaction id: {signed_tx.id}"
                )
                show_tx(signed_tx)
                break
            except KeyboardInterrupt:
                exit()
            except Exception as e:
                if "Transaction size" in str(e):
                    print(f"Transaction size too large for {module_name(contract)}")
                    break
                print(f"Error: {e}")
                sleep(1)
    return signed_tx


if __name__ == "__main__":
    fire.Fire(main)
