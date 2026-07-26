
from andro_cfw.colors import (
    COLOR_BOLD,
    COLOR_CYAN,
    COLOR_GREEN,
    COLOR_RED,
    COLOR_RESET,
    ColoredHelpFormatter,
    log_dim,
    log_error,
    log_info,
    log_notice,
    log_step,
    log_success,
    log_warn,
    log_working,
)


def test_colors_constants_type():
    assert isinstance(COLOR_RESET, str)
    assert isinstance(COLOR_BOLD, str)
    assert isinstance(COLOR_RED, str)
    assert isinstance(COLOR_GREEN, str)
    assert isinstance(COLOR_CYAN, str)


def test_logging_functions(capsys):
    log_info("Info message")
    out, _err = capsys.readouterr()
    assert "Info message" in out

    log_success("Success message")
    out, _err = capsys.readouterr()
    assert "Success message" in out

    log_error("Error message")
    out, _err = capsys.readouterr()
    assert "Error message" in out

    log_warn("Warn message")
    out, _err = capsys.readouterr()
    assert "Warn message" in out

    log_step("Step message")
    out, _err = capsys.readouterr()
    assert "Step message" in out

    log_working("Working message")
    out, _err = capsys.readouterr()
    assert "Working message" in out

    log_notice("Notice message")
    out, _err = capsys.readouterr()
    assert "Notice message" in out

    log_dim("Dim message")
    out, _err = capsys.readouterr()
    assert "Dim message" in out


def test_colored_help_formatter():
    formatter = ColoredHelpFormatter(prog="andro-cfw")
    formatted = formatter.add_usage(usage="andro-cfw [options]", actions=[], groups=[])
    assert formatted is None or isinstance(formatted, type(None))
