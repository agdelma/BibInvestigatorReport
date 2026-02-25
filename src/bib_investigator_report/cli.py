"""Console entrypoint for bib-investigator-report."""

from __future__ import annotations

from .report import main


def main_cli() -> None:
    """Entry point for the `bib-investigator-report` console script."""
    raise SystemExit(main())
