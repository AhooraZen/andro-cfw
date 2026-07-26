import subprocess
from unittest.mock import MagicMock, mock_open, patch

from andro_cfw.platform_utils import (
    SystemInfo,
    _add_to_posix_user_path,
    _first_available,
    _install_linux,
    _install_macos,
    _install_windows,
    _read_os_release,
    _run,
    _sudo_noninteractive_ok,
    add_to_user_path,
    detect_system,
    install_nodejs,
)


def test_system_info_pretty():
    info_linux = SystemInfo("linux", "arch", "arch", "pacman", True, "x86_64")
    assert "Linux (arch, package manager: pacman)" in info_linux.pretty()

    info_linux_unknown = SystemInfo("linux", None, None, None, False, "x86_64")
    assert "Linux (unknown distro, package manager: none found)" in info_linux_unknown.pretty()

    info_mac = SystemInfo("macos", None, None, "brew", False, "arm64")
    assert "macOS (package manager: brew)" in info_mac.pretty()

    info_win = SystemInfo("windows", None, None, "winget", True, "AMD64")
    assert "Windows (package manager: winget)" in info_win.pretty()

    info_other = SystemInfo("freebsd", None, None, None, False, "x86_64")
    assert "freebsd (unrecognized)" in info_other.pretty()


def test_read_os_release():
    mock_content = 'ID=arch\nID_LIKE="arch debian"\nNAME="Arch Linux"\n'
    with patch("os.path.exists", return_value=True):
        with patch("builtins.open", mock_open(read_data=mock_content)):
            res = _read_os_release()
            assert res.get("ID") == "arch"
            assert res.get("ID_LIKE") == "arch debian"

    with patch("os.path.exists", return_value=False):
        assert _read_os_release() == {}

    with patch("os.path.exists", return_value=True):
        with patch("builtins.open", side_effect=OSError("Read error")):
            assert _read_os_release() == {}


def test_first_available():
    with patch("shutil.which") as mock_which:
        mock_which.side_effect = lambda cmd: "/usr/bin/" + cmd if cmd == "pacman" else None
        assert _first_available("apt", "pacman", "dnf") == "pacman"
        assert _first_available("apt", "dnf") is None


def test_detect_system():
    # Windows
    with patch("platform.system", return_value="Windows"), \
         patch("platform.machine", return_value="AMD64"), \
         patch("andro_cfw.platform_utils._first_available", return_value="winget"):
        info = detect_system()
        assert info.os_family == "windows"
        assert info.package_manager == "winget"
        assert info.is_root is True

    # Darwin / macOS
    with patch("platform.system", return_value="Darwin"), \
         patch("platform.machine", return_value="arm64"), \
         patch("andro_cfw.platform_utils._first_available", return_value="brew"), \
         patch("os.geteuid", return_value=1000, create=True):
        info = detect_system()
        assert info.os_family == "macos"
        assert info.package_manager == "brew"
        assert info.is_root is False

    # Linux (Ubuntu)
    with patch("platform.system", return_value="Linux"), \
         patch("platform.machine", return_value="x86_64"), \
         patch("andro_cfw.platform_utils._read_os_release", return_value={"ID": "ubuntu"}), \
         patch("andro_cfw.platform_utils._first_available", return_value="apt-get"), \
         patch("os.geteuid", return_value=0, create=True):
        info = detect_system()
        assert info.os_family == "linux"
        assert info.distro == "ubuntu"
        assert info.package_manager == "apt-get"
        assert info.is_root is True

    # Linux (Fedora)
    with patch("platform.system", return_value="Linux"), \
         patch("platform.machine", return_value="x86_64"), \
         patch("andro_cfw.platform_utils._read_os_release", return_value={"ID": "fedora"}), \
         patch("andro_cfw.platform_utils._first_available", return_value="dnf"):
        info = detect_system()
        assert info.distro == "fedora"
        assert info.package_manager == "dnf"

    # Linux (Arch)
    with patch("platform.system", return_value="Linux"), \
         patch("platform.machine", return_value="x86_64"), \
         patch("andro_cfw.platform_utils._read_os_release", return_value={"ID": "arch"}), \
         patch("andro_cfw.platform_utils._first_available", return_value="pacman"):
        info = detect_system()
        assert info.distro == "arch"
        assert info.package_manager == "pacman"

    # Linux (openSUSE)
    with patch("platform.system", return_value="Linux"), \
         patch("platform.machine", return_value="x86_64"), \
         patch("andro_cfw.platform_utils._read_os_release", return_value={"ID": "opensuse"}), \
         patch("andro_cfw.platform_utils._first_available", return_value="zypper"):
        info = detect_system()
        assert info.package_manager == "zypper"

    # Linux (Alpine)
    with patch("platform.system", return_value="Linux"), \
         patch("platform.machine", return_value="x86_64"), \
         patch("andro_cfw.platform_utils._read_os_release", return_value={"ID": "alpine"}), \
         patch("andro_cfw.platform_utils._first_available", return_value="apk"):
        info = detect_system()
        assert info.package_manager == "apk"

    # Unknown OS
    with patch("platform.system", return_value="UnknownOS"):
        info = detect_system()
        assert info.os_family == "unknownos"


def test_sudo_noninteractive_ok():
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        assert _sudo_noninteractive_ok() is True

        mock_run.return_value = MagicMock(returncode=1)
        assert _sudo_noninteractive_ok() is False

        mock_run.side_effect = Exception("error")
        assert _sudo_noninteractive_ok() is False


def test_run():
    with patch("subprocess.run") as mock_run, \
         patch("shutil.which", return_value="/usr/bin/sudo"), \
         patch("os.geteuid", return_value=1000, create=True), \
         patch("andro_cfw.platform_utils._sudo_noninteractive_ok", return_value=True):
        _run(["apt-get", "install"], use_sudo=True)
        mock_run.assert_called_with(["sudo", "-n", "apt-get", "install"], timeout=600)


def test_install_windows():
    info_winget = SystemInfo("windows", None, None, "winget", True, "AMD64")
    with patch("andro_cfw.platform_utils._run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        assert _install_windows(info_winget) is True

    info_choco = SystemInfo("windows", None, None, "choco", True, "AMD64")
    with patch("andro_cfw.platform_utils._run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        assert _install_windows(info_choco) is True

    info_scoop = SystemInfo("windows", None, None, "scoop", True, "AMD64")
    with patch("andro_cfw.platform_utils._run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        assert _install_windows(info_scoop) is True

    info_none = SystemInfo("windows", None, None, None, True, "AMD64")
    assert _install_windows(info_none) is False


def test_install_macos():
    info_brew = SystemInfo("macos", None, None, "brew", False, "arm64")
    with patch("andro_cfw.platform_utils._run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        assert _install_macos(info_brew) is True

    info_port = SystemInfo("macos", None, None, "port", False, "arm64")
    with patch("andro_cfw.platform_utils._run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        assert _install_macos(info_port) is True

    info_none = SystemInfo("macos", None, None, None, False, "arm64")
    assert _install_macos(info_none) is False


def test_install_linux():
    # Apt with curl success
    info_apt = SystemInfo("linux", "ubuntu", "debian", "apt-get", False, "x86_64")
    with patch("shutil.which") as mock_which, \
         patch("subprocess.run") as mock_sub_run, \
         patch("andro_cfw.platform_utils._run") as mock_run:
        mock_which.side_effect = lambda cmd: "/usr/bin/" + cmd if cmd in ("curl", "apt-get") else None
        mock_sub_run.return_value = MagicMock(returncode=0, stdout=b"echo setup")
        mock_run.return_value = MagicMock(returncode=0)
        assert _install_linux(info_apt) is True

    # Pacman
    info_pacman = SystemInfo("linux", "arch", "arch", "pacman", False, "x86_64")
    with patch("andro_cfw.platform_utils._run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        assert _install_linux(info_pacman) is True

    # Dnf
    info_dnf = SystemInfo("linux", "fedora", "fedora", "dnf", False, "x86_64")
    with patch("andro_cfw.platform_utils._run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        assert _install_linux(info_dnf) is True

    # Yum
    info_yum = SystemInfo("linux", "centos", "rhel", "yum", False, "x86_64")
    with patch("andro_cfw.platform_utils._run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        assert _install_linux(info_yum) is True

    # Zypper
    info_zypper = SystemInfo("linux", "opensuse", "suse", "zypper", False, "x86_64")
    with patch("andro_cfw.platform_utils._run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        assert _install_linux(info_zypper) is True

    # Apk
    info_apk = SystemInfo("linux", "alpine", "alpine", "apk", False, "x86_64")
    with patch("andro_cfw.platform_utils._run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        assert _install_linux(info_apk) is True

    # No package manager
    info_none = SystemInfo("linux", "custom", None, None, False, "x86_64")
    assert _install_linux(info_none) is False


def test_install_nodejs_dispatcher():
    info_win = SystemInfo("windows", None, None, "winget", True, "AMD64")
    with patch("andro_cfw.platform_utils._install_windows", return_value=True):
        assert install_nodejs(info_win) is True

    info_mac = SystemInfo("macos", None, None, "brew", False, "arm64")
    with patch("andro_cfw.platform_utils._install_macos", return_value=True):
        assert install_nodejs(info_mac) is True

    info_lin = SystemInfo("linux", "arch", "arch", "pacman", False, "x86_64")
    with patch("andro_cfw.platform_utils._install_linux", return_value=True):
        assert install_nodejs(info_lin) is True

    with patch("andro_cfw.platform_utils._install_linux", side_effect=subprocess.TimeoutExpired("cmd", 60)):
        assert install_nodejs(info_lin) is False

    with patch("andro_cfw.platform_utils._install_linux", side_effect=Exception("error")):
        assert install_nodejs(info_lin) is False

    info_other = SystemInfo("unknown", None, None, None, False, "x86_64")
    assert install_nodejs(info_other) is False


def test_add_to_user_path_posix(tmp_path):
    target_dir = tmp_path / "bin"
    target_dir.mkdir()

    with patch("platform.system", return_value="Linux"), \
         patch("andro_cfw.platform_utils._add_to_posix_user_path", return_value=True) as mock_posix:
        assert add_to_user_path(target_dir) is True
        mock_posix.assert_called_once_with(target_dir)


def test_add_to_posix_user_path_already_in_env(tmp_path):
    target_dir = tmp_path / "bin"
    target_dir.mkdir()

    with patch.dict("os.environ", {"PATH": f"/usr/bin:{target_dir.resolve()}"}):
        assert _add_to_posix_user_path(target_dir) is True


def test_add_to_posix_user_path_append_rc(tmp_path):
    target_dir = tmp_path / "bin"
    target_dir.mkdir()
    fake_home = tmp_path / "home"
    fake_home.mkdir()

    rc_file = fake_home / ".bashrc"
    rc_file.write_text("export FOO=1\n")

    with patch.dict("os.environ", {"PATH": "/usr/bin", "SHELL": "/bin/bash"}), \
         patch("pathlib.Path.home", return_value=fake_home), \
         patch("andro_cfw.platform_utils.add_to_user_path", import_from=True):
        assert _add_to_posix_user_path(target_dir) is True
        content = rc_file.read_text()
        assert str(target_dir.resolve()) in content


def test_add_to_posix_user_path_creates_executable_wrapper(tmp_path):
    target_dir = tmp_path / ".local" / "bin"
    fake_home = tmp_path / "home"
    fake_home.mkdir()

    with patch.dict("os.environ", {"PATH": "/usr/bin", "SHELL": "/bin/zsh"}), \
         patch("pathlib.Path.home", return_value=fake_home):
        assert _add_to_posix_user_path(target_dir) is True
        wrapper = target_dir / "andro-cfw"
        assert wrapper.exists()
        content = wrapper.read_text()
        assert "#!/bin/sh" in content
        assert "exec" in content



def test_nodesource_is_opt_in_only(monkeypatch):
    """
    Piping a downloaded shell script into `sudo bash` is a trust decision the
    user has to make explicitly; the distro package is the default.
    """
    from andro_cfw import platform_utils as pu

    monkeypatch.delenv("ANDRO_CFW_ALLOW_NODESOURCE", raising=False)
    assert pu._nodesource_opt_in() is False

    calls = []
    monkeypatch.setattr(pu, "_install_via_nodesource", lambda: calls.append("nodesource") or True)
    monkeypatch.setattr(pu, "_run", lambda *a, **k: MagicMock(returncode=0))

    info = pu.SystemInfo("linux", "debian", None, "apt-get", False, "x86_64")
    assert pu._install_linux(info) is True
    assert calls == []


def test_nodesource_runs_when_explicitly_allowed(monkeypatch):
    from andro_cfw import platform_utils as pu

    monkeypatch.setenv("ANDRO_CFW_ALLOW_NODESOURCE", "1")
    assert pu._nodesource_opt_in() is True

    calls = []
    monkeypatch.setattr(pu, "_install_via_nodesource", lambda: calls.append("nodesource") or True)

    info = pu.SystemInfo("linux", "ubuntu", None, "apt-get", False, "x86_64")
    assert pu._install_linux(info) is True
    assert calls == ["nodesource"]
