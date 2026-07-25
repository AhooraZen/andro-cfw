import pytest
from andro_cfw.deploy import _load_template


def test_worker_template_file_validity():
    content = _load_template("worker.ts")
    assert isinstance(content, str)
    assert len(content) > 100

    # Verify essential endpoints, exports, and handlers exist
    assert "export default {" in content
    assert "async fetch(" in content
    assert "api.telegram.org" in content
    assert "CORS_HEADERS" in content
    assert "/webhook" in content
    assert "/start" in content
    assert "/ping" in content
    assert "/status" in content
