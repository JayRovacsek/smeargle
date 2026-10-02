import pytest

from smeargle import errors


@pytest.mark.parametrize(
    ("exc", "code"),
    [
        (errors.UsageError("x"), 2),
        (errors.InputError("x"), 3),
        (errors.CatalogError("x"), 4),
        (errors.ServiceError("x"), 5),
        (errors.GapsError("x"), 6),
        (errors.IntegrityError("x"), 7),
        (errors.AbortedError("x"), 8),
        (errors.SmeargleError("x"), 1),
    ],
)
def test_exit_code_for_smeargle_error(exc, code):
    assert errors.exit_code_for(exc) == code


def test_exit_code_for_unknown_is_unexpected():
    assert errors.exit_code_for(ValueError("x")) == errors.EXIT_UNEXPECTED


def test_exit_code_constants_match_spec():
    assert errors.EXIT_SUCCESS == 0
    assert errors.EXIT_ABORTED == 8
