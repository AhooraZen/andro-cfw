from unittest.mock import MagicMock, patch

import pytest

from andro_cfw.errors import ToolchainMissingError
from andro_cfw.platform_utils import SystemInfo
from andro_cfw.toolchain import (
    _manual_instructions,
    _node_present,
    _run_version,
    check_node_toolchain,
)


def test_run_version():
    with patch("shutil.which", return_value="/usr/bin/node"), \
         patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(stdout="v20.0.0\n", stderr="")
        assert _run_version("node") == "v20.0.0"

    with patch("shutil.which", return_value=None):
        assert _run_version("node") is None

    with patch("shutil.which", return_value="/usr/bin/node"), \
         patch("subprocess.run", side_effect=Exception("error")):
        assert _run_version("node") is None


def test_node_present():
    with patch("andro_cfw.toolchain._run_version") as mock_ver:
        mock_ver.side_effect = lambda cmd: "v20.0.0" if cmd in ("node", "npx") else None
        assert _node_present() is True

    with patch("andro_cfw.toolchain._run_version") as mock_ver:
        mock_ver.side_effect = lambda cmd: "v20.0.0" if cmd == "node" else None
        assert _node_present() is False


def test_check_node_toolchain():
    info = SystemInfo("linux", "arch", "arch", "pacman", False, "x86_64")

    # Already present
    with patch("andro_cfw.toolchain.detect_system", return_value=info), \
         patch("andro_cfw.toolchain._node_present", return_value=True):
        res = check_node_toolchain()
        assert res == info

    # Missing and auto_install=False
    with patch("andro_cfw.toolchain.detect_system", return_value=info), \
         patch("andro_cfw.toolchain._node_present", return_value=False):
        with pytest.raises(ToolchainMissingError) as exc_info:
            check_node_toolchain(auto_install=False)
        assert "pacman" in str(exc_info.value)

    # Missing, auto_install succeeds
    with patch("andro_cfw.toolchain.detect_system", return_value=info), \
         patch("andro_cfw.toolchain._node_present", side_effect=[False, True]), \
         patch("andro_cfw.toolchain.install_nodejs", return_value=True):
        res = check_node_toolchain(auto_install=True)
        assert res == info

    # Missing, auto_install fails
    with patch("andro_cfw.toolchain.detect_system", return_value=info), \
         patch("andro_cfw.toolchain._node_present", return_value=False), \
         patch("andro_cfw.toolchain.install_nodejs", return_value=False):
        with pytest.raises(ToolchainMissingError):
            check_node_toolchain(auto_install=True)


def test_manual_instructions():
    win_info = SystemInfo("windows", None, None, "winget", True, "AMD64")
    assert "winget install" in _manual_instructions(win_info)

    mac_info = SystemInfo("macos", None, None, "brew", False, "arm64")
    assert "brew install node" in _manual_instructions(mac_info)

    lin_info = SystemInfo("linux", "ubuntu", "debian", "apt-get", False, "x86_64")
    assert "apt-get" in _manual_instructions(lin_info)

    other_info = SystemInfo("unknown", None, None, None, False, "x86_64")
    assert "nodejs.org" in _manual_instructions(other_info)


def test_auto_install_can_be_disabled_by_environment(monkeypatch):
    """
    Installing system packages is a privileged, machine-wide side effect. CI
    and locked-down machines must be able to refuse it.
    """
    from andro_cfw import toolchain
    from andro_cfw.errors import ToolchainMissingError

    monkeypatch.setenv("ANDRO_CFW_NO_AUTO_INSTALL", "1")
    monkeypatch.setattr(toolchain, "_node_present", lambda: False)
    called = []
    monkeypatch.setattr(toolchain, "install_nodejs", lambda info: called.append(info) or True)

    with pytest.raises(ToolchainMissingError):
        toolchain.check_node_toolchain(auto_install=True)
    assert called == []
