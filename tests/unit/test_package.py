from typer.testing import CliRunner

from swiggy import __version__
from swiggy.cli import app


def test_package_and_cli_are_importable() -> None:
    assert __version__ == "0.1.0"
    result = CliRunner().invoke(app, ["--version"])
    assert result.exit_code == 0
    assert result.stdout.strip() == "swiggy-py 0.1.0"
