import pytest

from ml.fraud import pipeline


@pytest.fixture(scope="session")
def transactions():
    """The full synthetic table, loaded once. The gates need whole card histories, so no subsampling."""
    return pipeline.load_transactions()
