from typer.testing import CliRunner

from swiggy import SwiggyClient, __version__
from swiggy.cli import app


def test_package_and_cli_are_importable() -> None:
    assert SwiggyClient.__name__ == "SwiggyClient"
    assert __version__ == "0.1.0"
    result = CliRunner().invoke(app, ["--version"])
    assert result.exit_code == 0
    assert result.stdout.strip() == "swiggy-py 0.1.0"
