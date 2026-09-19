import pytest
from src.filtering.impact_filter import passes_impact_filter


@pytest.mark.parametrize(("value", "expected"), [(0, False), (1, False), (2, False), (3, True), (4, True), (100, True), (None, False)])
def test_impact_threshold(value, expected):
    assert passes_impact_filter({"changed_files": value}) is expected

