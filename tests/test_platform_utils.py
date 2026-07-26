from unittest.mock import patch

from andro_cfw.platform_utils import _add_to_posix_user_path, add_to_user_path


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
