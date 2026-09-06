"""Command-line interface for swiggy-py."""

from typing import Annotated

import typer

from swiggy import __version__

app = typer.Typer(add_completion=False)


@app.callback(invoke_without_command=True)
def main(
    version: Annotated[
        bool,
        typer.Option("--version", help="Show the version and exit.", is_eager=True),
    ] = False,
) -> None:
    """Run the swiggy-py command-line interface."""
    if version:
        typer.echo(f"swiggy-py {__version__}")
        raise typer.Exit
