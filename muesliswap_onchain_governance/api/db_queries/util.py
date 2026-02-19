def parse_merged_assets(policy_ids, asset_names, amounts):
    """
    Parse the merged assets
    :param policy_ids: The policy ids
    :param asset_names: The asset names
    :param amounts: The amounts
    :return: A list of assets
    """
    policy_ids = policy_ids.split(";")
    asset_names = asset_names.split(";")
    amounts = amounts.split(";")
    assets = [
        {
            "policy_id": policy_id,
            "asset_name": asset_name,
            "amount": amount,
        }
        for policy_id, asset_name, amount in zip(policy_ids, asset_names, amounts)
    ]
    return assets
