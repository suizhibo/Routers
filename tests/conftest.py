from __future__ import annotations

import pytest

pytest_plugins = ["pytest_asyncio"]


@pytest.fixture(scope="session")
def anyio_backend():
    return "asyncio"
