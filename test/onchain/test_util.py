from copy import copy

from hypothesis import strategies as st
from hypothesis import given

from muesliswap_onchain_governance.onchain.util import remove_participation_at_index


@given(st.lists(st.integers()), st.integers())
def test_remove_participation_at_index(participants: list, index):
    try:
        assert 0 <= index < len(participants)
        exp_parts = copy(participants)
        exp_parts.pop(index)
    except AssertionError:
        exp_parts = None
    try:
        res_parts = remove_participation_at_index(participants, index)
    except AssertionError:
        res_parts = None
    assert res_parts == exp_parts
