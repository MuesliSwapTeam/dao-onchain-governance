import pycardano


def resolve_redeemers(tx: pycardano.Transaction):
    """
    Resolve redeemers from the transaction.

    The return value is a list of tuples, where the first item in the tuple
    behaves like a redeemer key, and the second like a redeemer value
    """
    if isinstance(tx.transaction_witness_set.redeemer, pycardano.RedeemerMap):
        redeemers = tx.transaction_witness_set.redeemer.items()
    else:
        redeemers = [
            (redeemer, redeemer) for redeemer in tx.transaction_witness_set.redeemer
        ]
    return redeemers
