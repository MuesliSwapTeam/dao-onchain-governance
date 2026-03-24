import pycardano


def resolve_redeemers(tx: pycardano.Transaction):
    """
    Resolve redeemers from the transaction.

    The return value is a list of tuples, where the first item in the tuple
    behaves like a redeemer key, and the second like a redeemer value
    """
    redeemer = tx.transaction_witness_set.redeemer
    if redeemer is None:
        redeemers = []
    elif isinstance(redeemer, pycardano.RedeemerMap):
        redeemers = redeemer.items()
    else:
        redeemers = [(r, r) for r in redeemer]
    return redeemers
