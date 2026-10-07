import pytest

from server.backend.console.fr24_control_plane import _float, _int
from server.backend.console.repositories.normalize import as_float, as_int


@pytest.mark.parametrize("value", ["nan", "NaN", "inf", "-Infinity", "1e999", float("inf")])
def test_console_numbers_reject_nonfinite(value):
    assert as_float(value) is None
    assert as_int(value) is None
    assert _float(value) is None
    assert _int(value) is None


def test_console_numbers_preserve_zero_and_finite_values():
    assert as_float("0") == 0
    assert as_int("12.5") == 12
    assert _float("12.5") == 12.5
