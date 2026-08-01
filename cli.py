"""
CLI entry point.

Usage:
    python cli.py extract input/my_file.xlsx
    python cli.py extract input/my_file.xlsx --output-dir output --config config.yaml
    python cli.py extract input/my_file.xlsx --enable-local-llm --verbose
"""

from __future__ import annotations

from pathlib import Path

import typer

from src.orchestrator import Supervisor
from src.utils.file_helpers import load_config

app = typer.Typer(add_completion=False, help="Free, local-first Excel extraction agent.")


@app.command()
def extract(
    input_file: Path = typer.Argument(..., exists=True, readable=True,
                                       help="Path to the .xlsx file to process."),
    output_dir: Path = typer.Option(Path("output"), "--output-dir", "-o",
                                     help="Base directory for run outputs."),
    config_path: Path = typer.Option(Path("config.yaml"), "--config", "-c",
                                      help="Path to config.yaml."),
    enable_local_llm: bool = typer.Option(False, "--enable-local-llm",
                                           help="Use a local Ollama model for ambiguous headers."),
    sqlite_db: Path = typer.Option(None, "--sqlite-db",
                                    help="Also append extracted records to this local SQLite "
                                         "database file (created if it doesn't exist)."),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose console logging."),
) -> None:
    """Extract structured data from a messy Excel workbook."""
    config = load_config(config_path)
    if enable_local_llm:
        config["enable_local_llm"] = True

    supervisor = Supervisor(config=config)
    ctx = supervisor.run(input_file, output_dir, verbose=verbose, sqlite_db_path=sqlite_db)

    typer.echo("")
    typer.echo(f"Done. {len(ctx.records)} records extracted from {len(ctx.sheet_profiles)} sheet(s).")
    typer.echo(f"Output written to: {ctx.output_dir}")
    if sqlite_db:
        typer.echo(f"Records also appended to SQLite database: {sqlite_db}")


if __name__ == "__main__":
    app()
