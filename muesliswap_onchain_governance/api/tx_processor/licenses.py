import datetime

import pycardano

from . import from_db
from .to_db import (
    add_address,
    add_token,
    add_transaction,
    add_output,
)
from ..config import licenses_policy_id
from ..db_models import (
    Block,
    TransactionOutput,
    Transaction,
    TallyState,
    TreasurerState,
)
from ..db_models import (
    TrackedGovStates,
)
from ..db_models.licenses import LicenseMint, LicenseOutput

from ...onchain.licenses import licenses as onchain_licenses

import logging


_LOGGER = logging.getLogger(__name__)


def process_tx(
    tx: pycardano.Transaction,
    block: Block,
    block_index: int,
):
    """
    Process a transaction and update the database accordingly.
    """

    # add outputs if they contain licenses
    for i, output in enumerate(tx.transaction_body.outputs):
        if output.amount.multi_asset.get(licenses_policy_id, {}):
            db_output = add_output(output, i, tx.id.payload.hex(), block, block_index)
            for license_token_name in output.amount.multi_asset.get(
                licenses_policy_id, {}
            ).keys():
                LicenseOutput.create(
                    transaction_output=db_output,
                    license_nft=add_token(licenses_policy_id, license_token_name),
                )
    # add mints if they contain licenses
    license_mint = (
        tx.transaction_body.mint.get(licenses_policy_id)
        if tx.transaction_body.mint
        else None
    )
    if not license_mint:
        return
    license_token_name, license_mint_amount = list(license_mint.items())[0]

    receiver = None
    for i, output in enumerate(tx.transaction_body.outputs):
        if (
            output.amount.multi_asset.get(licenses_policy_id, {}).get(
                license_token_name, 0
            )
            > 0
        ):
            receiver = output.address
            break
    release_license_redeemer = None
    redeemers = None
    if isinstance(tx.transaction_witness_set.redeemer, pycardano.RedeemerMap):
        redeemers = tx.transaction_witness_set.redeemer.items()
    else:
        redeemers = [
            (redeemer, redeemer) for redeemer in tx.transaction_witness_set.redeemer
        ]
    for redeemer_key, redeemer_value in redeemers:
        if redeemer_key.tag != pycardano.RedeemerTag.MINT:
            continue
        if (
            sorted(tx.transaction_body.mint, key=lambda x: x.payload)[
                redeemer_key.index
            ]
            != licenses_policy_id
        ):
            continue
        try:
            release_license_redeemer: onchain_licenses.ReleaseLicenses = (
                onchain_licenses.ReleaseLicenses.from_cbor(
                    redeemer_value.data.to_cbor()
                )
            )
        except Exception as e:
            _LOGGER.debug(f"Mint was executed with invalid redeemer")
            continue
    # we can find the tally input here
    if release_license_redeemer is not None:
        input: pycardano.TransactionInput = sorted(
            tx.transaction_body.reference_inputs,
            key=lambda x: (x.transaction_id.payload, x.index),
        )[release_license_redeemer.tally_input_index]
        tally_state = (
            TallyState.select()
            .join(TransactionOutput)
            .where(
                TransactionOutput.transaction_hash
                == input.transaction_id.payload.hex(),
                TransactionOutput.output_index == input.index,
            )
            .first()
        )
    if receiver is not None and tally_state is not None:
        LicenseMint.create(
            transaction=add_transaction(tx.id.payload.hex(), block, block_index),
            receiver=add_address(receiver),
            used_tally_state=tally_state,
            amount=license_mint_amount,
            license_nft=add_token(licenses_policy_id, license_token_name),
            expiration_date=datetime.datetime.fromtimestamp(
                onchain_licenses.unsigned_int_from_bytes_big(
                    license_token_name.payload[16:]
                )
                // 1000
            ),
            tally_proposal_id=onchain_licenses.unsigned_int_from_bytes_big(
                license_token_name.payload[:16]
            ),
        )
