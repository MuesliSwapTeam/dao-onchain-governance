from pycardano import (
    Transaction,
    TransactionWitnessSet,
)
from fastapi import HTTPException


def append_signature(
    tx_cbor: str,
    tx_body_cbor: str,
    witness_set_cbor: str,
):
    """
    Appends the user's signature while ensuring that the tx body
    is not modified.
    """
    try:
        tx: Transaction = Transaction.from_cbor(tx_cbor)
    except Exception as e:
        raise HTTPException(422, "Invalid transaction CBOR")

    witness_set = tx.transaction_witness_set
    original_witness_cbor = witness_set.to_cbor_hex()

    # Removed check that original witness set is in the tx cbor because, when there are multiple signatures,
    # the order of the signatures can change which changes the witness set cbor but not the correctness of the tx.

    # if original_witness_cbor not in tx_cbor:
    #     raise ValueError(
    #         f"Inconsistent serialisation of the transaction witness set. Original tx cbor: {tx_cbor}, reconstructed witness set cbor: {original_witness_cbor}"
    #     )

    if witness_set.vkey_witnesses is None:
        witness_set.vkey_witnesses = []

    if not isinstance(witness_set.vkey_witnesses, list):
        witness_set.vkey_witnesses = list(witness_set.vkey_witnesses)

    original_vkeys = [w.vkey.to_primitive() for w in witness_set.vkey_witnesses]

    try:
        new_witness_set: TransactionWitnessSet = TransactionWitnessSet.from_cbor(
            witness_set_cbor
        )
    except Exception as e:
        raise HTTPException(422, "Invalid witness set CBOR")

    assert (
        new_witness_set.vkey_witnesses is not None
    ), "Signed witness set must contain a vkey witness"

    new_vkeys = {w.vkey.to_primitive(): w for w in new_witness_set.vkey_witnesses}

    for vkey, witness in new_vkeys.items():
        if vkey not in original_vkeys:
            witness_set.vkey_witnesses.append(witness)

    new_transaction = Transaction(
        transaction_body=tx.transaction_body,
        transaction_witness_set=witness_set,
        auxiliary_data=tx.auxiliary_data,
    )

    return new_transaction.to_cbor_hex().replace(
        new_transaction.transaction_body.to_cbor_hex(), tx_body_cbor
    )


if __name__ == "__main__":
    import ipdb

    signed_tx = "84ad00d9010281825820406159fe66c72557a4a9dbb73eedb8ef14b526be94fd80586f12fddfe79013e600018182583900418bb4a5aa2b84335ee3235d099bb838a2bfb7f39c400164af56aed927a80f06dc7c4507371bc1f0d0c582e6d385632706a2f0eb6204af6c821b00000001276229cca2581c083288ce68f0ed033982bf7d7fbbc1024a2b4e24326f7b74a215e7f3a146019cd5f1c6b01a01312d00581cbd976e131cfc3956b806967b06530e48c20ed5498b46a5eb836b61c2a147744d494c4b76321a00989680021a000443be031a06102b4d0758204c8e543478bd7afa300473b687c028c221548e974538acb1e2b5fb2970233d02081a0610005509a1581c083288ce68f0ed033982bf7d7fbbc1024a2b4e24326f7b74a215e7f3a146019cd5f1c6b01a009896800b5820927143267a5222e2a73beef8e197b03462f44b62e806ecb2438b2fef0fcb13030dd901028182582090e725765d52d9df74763fe6575b197dcbdafbb7f0211e2a25d19cce5ddcdc37000ed9010281581c7dbe7d14bc3648d39432bfb1a5f0d16793d6c00948aeb1c3a872a7b31082581d6025bbfc857c7777b4bf62d664d1f274f540ec30801ba115a0e2b83cb41a00607644111a0038203c12d9010282825820489e300ff9ccb218c54af891de0076499a71c2ac871377798e4fae15c97a5d7400825820462926e63a55cc850126b51f22391380af56f6657e40dd93aaf709e946b6214d00a200d9010282825820a553fb06c81dcca64c8712414b61982b9795182e29024c329aede9c4f2fb1dbb584080791c2c72fd69d8c473dc0a7915e454bf86b713d82b2c94acaab9f28696b4a8a7fb0edb0b6f3c452820cbc266d485f8cb19d055708ecdcc78112b21cfcdb8038258205a6f2f292d8ad26a7b5705b8c9eb3eb302e3a1fec2da85729b728ff5e1bf95635840fa44d7930674efe1ad7454561738c2ff3135fe0a7a956f29253246d5993d5ca0cefa240119bfa5c1ea38651142829696a7fbe8e3cac407190d359da1a76ca80a05a182010082d87a9f01ff821a00073e611a0869a928f5d90103a100a11902a2a1636d7367816d4d696e74205661756c74204654"
    tx_body = "ad00d9010281825820406159fe66c72557a4a9dbb73eedb8ef14b526be94fd80586f12fddfe79013e600018182583900418bb4a5aa2b84335ee3235d099bb838a2bfb7f39c400164af56aed927a80f06dc7c4507371bc1f0d0c582e6d385632706a2f0eb6204af6c821b00000001276229cca2581c083288ce68f0ed033982bf7d7fbbc1024a2b4e24326f7b74a215e7f3a146019cd5f1c6b01a01312d00581cbd976e131cfc3956b806967b06530e48c20ed5498b46a5eb836b61c2a147744d494c4b76321a00989680021a000443be031a06102b4d0758204c8e543478bd7afa300473b687c028c221548e974538acb1e2b5fb2970233d02081a0610005509a1581c083288ce68f0ed033982bf7d7fbbc1024a2b4e24326f7b74a215e7f3a146019cd5f1c6b01a009896800b5820927143267a5222e2a73beef8e197b03462f44b62e806ecb2438b2fef0fcb13030dd901028182582090e725765d52d9df74763fe6575b197dcbdafbb7f0211e2a25d19cce5ddcdc37000ed9010281581c7dbe7d14bc3648d39432bfb1a5f0d16793d6c00948aeb1c3a872a7b31082581d6025bbfc857c7777b4bf62d664d1f274f540ec30801ba115a0e2b83cb41a00607644111a0038203c12d9010282825820489e300ff9ccb218c54af891de0076499a71c2ac871377798e4fae15c97a5d7400825820462926e63a55cc850126b51f22391380af56f6657e40dd93aaf709e946b6214d00"
    witness_set = "a10081825820867cc9b2cb41eb7b77d971f6473f83d35f0d5cae5b5bba9e0e53eb0024be809d584034959525553d012f0adf0af10efd45beeca12f1d34447b793dd3c82d8b56afecb502c12ad3fe33fde668805a807e9029cecb3e306b92fb04bb50a549b3d25608"

    try:
        new_tx_cbor = append_signature(signed_tx, tx_body, witness_set)

        tx: Transaction = Transaction.from_cbor(new_tx_cbor)

        print(f"Required signers: {tx.transaction_body.required_signers}")
        print(
            f"Signed by : {[w.vkey.hash().payload.hex() for w in tx.transaction_witness_set.vkey_witnesses]}"
        )
    except Exception as e:
        print(e)
        ipdb.post_mortem()
