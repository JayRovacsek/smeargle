"""Shared fixtures for the smeargle test suite."""

from __future__ import annotations

import pytest

from smeargle.oscal_build import facade


@pytest.fixture(scope="session", autouse=True)
def _oscal_support(tmp_path_factory):
    support = tmp_path_factory.mktemp("oscal-support") / "oscal_support.db"
    facade.configure_support_file(support)
