# bib-investigator-report

Generate a LaTeX report of BibTeX citations per investigator per project-year, plus a CSV summary table.

- Input: a `.bib` file and an investigators CSV (at minimum: `Firstname`, `Lastname`)
- Output:
  - a `.tex` report (organized by investigator and project-year)
  - `summary_pubs.csv` (investigators × years, with BibTeX keys per cell)
  - optionally a compiled PDF (requires a LaTeX toolchain)

## Install (from GitHub)

If your repository is on GitHub, you can install directly with:

```bash
pip install "git+https://github.com/agdelma/BibInvestigatorReport"
```

After install, the console command is available:

```bash
bibreport --help
```

(`bib-investigator-report` is also installed as an alias.)

## Quickstart (example data)

This repo includes small example inputs under `examples/`.

From the repo root (without installing), you can run:

```bash
./bin/bibreport \
  examples/sample.bib \
  examples/investigators.csv \
  --start-date 2020-01-01 \
  --end-date 2022-12-31 \
  --out examples/output/report.tex
```

(You can still run `python -m bib_investigator_report ...` if you prefer.)

The output directory will contain:

- `examples/output/report.tex`
- `examples/output/summary_pubs.csv`
- a copy of the `.bib` file next to the `.tex` (for portability)

If you have LaTeX installed and want a PDF:

```bash
./bin/bibreport \
  examples/sample.bib \
  examples/investigators.csv \
  --start-date 2020-01-01 \
  --end-date 2022-12-31 \
  --out examples/output/report.tex \
  --compile
```

## Usage

```bash
bibreport INPUT.bib investigators.csv \
  --start-date YYYY-MM-DD \
  --end-date   YYYY-MM-DD \
  [--out report.tex] \
  [--summary-csv summary_pubs.csv] \
  [--date-field auto|date|date-added|year|...] \
  [--bibliography-style plain|unsrt|abbrv|...] \
  [--add-support] \
  [--annual-report] \
  [--no-bibliography] \
  [--compile]
```

### Project-year definition

- Year 01 is the 12-month period starting at `--start-date`
- Year 02 is the next 12-month period, etc., until `--end-date`

### Inclusion logic

A BibTeX entry is included for an investigator in a project-year if:

- the investigator name matches an author in the BibTeX `author` field, and
- the inferred entry date falls inside that project-year

### Date inference

BibTeX entries often only contain a `year`. In `--date-field auto` mode, the script tries:

1. `date` (ISO formats like `YYYY`, `YYYY-MM`, `YYYY-MM-DD`)
2. `year` + `month`
3. `date-added` (common in Zotero exports)
4. fallback to mid-year (`July 1`) for a bare `year`

You can override inference with `--date-field <FIELDNAME>`.

### Support-grouped reference list

Add `--add-support` to replace the BibTeX-generated yearly bibliographies with a
chronological reference list grouped by project-year period, then by `Full Support`
and `Partial Support`.

Use an optional `support` field in each BibTeX entry:

```bibtex
@article{example2024,
  author={Smith, Alice and Doe, John},
  title={An Example Paper},
  journal={Journal of Examples},
  year={2024},
  support={partial},
}
```

Supported values include `full` and `partial`; missing, blank, or unrecognized
values are grouped as `Support Not Included`. Authors who match names in
`investigators.csv` are bolded in the generated `.tex` references.

Add `--annual-report` when you want bibliography entries without visible
citation numbers, which makes the compiled PDF easier to copy/paste into a
number-free publication list.

When `--docx` is used, the LaTeX/BibTeX compile step is run automatically so the
rendered `.bbl` bibliography files are available for Word export.

## Notes on LaTeX compilation

- `--compile` runs: `pdflatex` → `bibtex` (for each multibib aux) → `pdflatex` → `pdflatex`
- You must have `pdflatex` and `bibtex` on your PATH.

Typical installations:

- macOS: MacTeX
- Linux: TeX Live packages
- Windows: MiKTeX or TeX Live

## Development

Optional dev tools are listed in `requirements-dev.txt`.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
ruff check .
```

## License

MIT. See `LICENSE`.
