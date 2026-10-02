import smeargle


def test_version_is_exposed():
    assert smeargle.__version__ == "0.1.0"


def test_respx_is_importable():
    import respx  # noqa: F401
