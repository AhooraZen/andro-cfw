import pytest
from andro_cfw.errors import (
    AndroCFWError,
    SessionNotFoundError,
    DeploymentError,
    ToolchainMissingError,
)

def test_errors_hierarchy():
    assert issubclass(SessionNotFoundError, AndroCFWError)
    assert issubclass(DeploymentError, AndroCFWError)
    assert issubclass(ToolchainMissingError, AndroCFWError)

    err = SessionNotFoundError("test message")
    assert str(err) == "test message"
    assert isinstance(err, AndroCFWError)
