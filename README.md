# bib-investigator-report

Generate a LaTeX report of BibTeX citations per investigator per project-year, plus a CSV summary table.

- Input: a `.bib` file and an investigators CSV (at minimum: `Firstname`, `Lastname`)
- Output:
  - a `.tex` report (organized by investigator and project-year)
  - `summary_pubs.csv` (investigators × years, with BibTeX keys per cell)
  - an optional dot-matrix summary PDF, automatically included in the `.tex` report
  - an optional co-authorship network PDF, also included in the summary
  - optionally a compiled PDF (requires a LaTeX toolchain)
  - console diagnostics showing record totals and why any records were omitted

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
  --compile --clean
```

## Usage

```bash
bibreport INPUT.bib investigators.csv \
  --start-date YYYY-MM-DD \
  --end-date   YYYY-MM-DD \
  [--out report.tex] \
  [--summary-csv summary_pubs.csv] \
  [--summary-style table|dots] \
  [--coauthor-network] \
  [--date-field auto|date|date-added|year|...] \
  [--bibliography-style plain|unsrt|abbrv|...] \
  [--add-support] \
  [--annual-report] \
  [--no-bibliography] \
  [--compile] \
  [--docx] \
  [--clean]
```

### Project-year definition

- Year 01 is the 12-month period starting at `--start-date`
- Year 02 is the next 12-month period, etc., until `--end-date`

### Visual publication summary

The report is organized into **Summary**, **Per-Investigator Products**, and
**References**. Each investigator has a subsection under Per-Investigator
Products; the references retain their project-year and optional support groups.

Use `--summary-style dots` to replace the opening citation table with a dot
matrix and stacked yearly publication bars. Install the optional plotting
dependency first (from a source checkout):

```bash
python -m pip install -e ".[plots]"
```

Then add the option to your usual command:

```bash
bibreport INPUT.bib investigators.csv \
  --start-date 2023-05-01 --end-date 2026-11-30 \
  --summary-style dots --out report.tex --compile
```

Each marker represents one paper. Marker color and shape distinguish papers
with one, two, or three-or-more investigators from the supplied roster. Yearly
bars and the overall paper total count shared papers once; a shared paper
appears in every participating investigator's row. The individual investigator
citation lists, bibliographies, and summary CSV are retained.

The script writes `report_summary.pdf` next to `report.tex` and includes it
automatically using LaTeX's `graphicx` package. The summary PDF is generated
even without `--compile`; keep it alongside the `.tex` when moving the report.
Large matrices continue across multiple summary pages. `--clean` preserves the
summary PDF. Word export continues to contain only the bibliographies.

Use `--summary-style table` for the original citation table. This remains the
default and does not require Matplotlib.

### Co-authorship network

Add `--coauthor-network` to include a second summary figure showing collaborations
among the investigators in your CSV. It works with either summary style and uses
the same optional `plots` dependency:

```bash
bibreport INPUT.bib investigators.csv \
  --start-date 2023-05-01 --end-date 2026-11-30 \
  --summary-style dots --coauthor-network --out report.tex --compile
```

Each node is an investigator, sized by their total number of included papers.
Connections join investigators who share an included paper; line widths and
labels show how many unique papers they share. A paper with three investigators
contributes to each of its three pairs. Investigators without a shared paper
remain visible, including those with no included papers. Coauthors outside the
supplied roster are not shown.

The script writes `report_coauthors.pdf` next to `report.tex` and automatically
includes it within Summary. Keep this companion PDF with the `.tex` when moving
the report. `--clean` preserves it.

### Inclusion logic

A BibTeX entry is included for an investigator in a project-year if:

- the investigator name matches an author in the BibTeX `author` field, and
- the inferred entry date falls inside that project-year

Each run prints the total number of bibliography records, the number of unique
records included, and the omitted records with their keys and reasons. Reasons
include dates outside the requested range, missing or invalid dates, unmatched
investigators, and records that could not be parsed. A paper shared by several
investigators counts once in the included total.

The input total includes malformed and duplicate records, but excludes BibTeX
directives such as `@comment`, `@preamble`, and `@string`. Duplicate fields produce
a warning; the first value is used, matching BibTeX's behavior. Duplicate citation
keys are reported and later occurrences are skipped.

### Date inference

In `--date-field auto` mode, a `date-added` field is authoritative whenever it is
present. The script ignores the entry's other dates, including `date`, `year`,
and `month`. If `date-added` is blank or cannot be parsed, the entry is omitted
with a diagnostic; it does not fall back to another date.

When `date-added` is absent, the script tries:

1. `date` (ISO formats like `YYYY`, `YYYY-MM`, `YYYY-MM-DD`)
2. `year` + `month`
3. fallback to mid-year (`July 1`) for a bare `year`

An incomplete `YYYY-MM` date, including `year` + `month`, uses the 15th of the
month. Export timestamps such as `2026-11-04 00:00:00 GMT` are also supported;
only their calendar date is used. Omission diagnostics show the inferred date and
the field used to obtain it.

You can override automatic inference with `--date-field <FIELDNAME>`, including
selecting another field when `date-added` is present. An explicit field selection
has no fallback: entries without a usable value in that field are omitted.

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

In the per-investigator publication lists, citation numbers for `support={full}`
papers are underlined while retaining their collaboration colors. This applies
with or without `--add-support`. Partial, blank, missing, or unrecognized support
values keep their usual citation styling. The summary table and bibliography
entries are not underlined.

Add `--annual-report` when you want bibliography entries without visible
citation numbers, which makes the compiled PDF easier to copy/paste into a
number-free publication list.

When `--docx` is used, the LaTeX/BibTeX compile step is run automatically so the
rendered `.bbl` bibliography files are available for Word export.

## Notes on LaTeX compilation

- `--compile` runs: `pdflatex` → `bibtex` (for each multibib aux) → `pdflatex` → `pdflatex`
- You must have `pdflatex` and `bibtex` on your PATH.

After compilation, the tool checks that every selected publication appears in
the generated bibliographies and reports any missing keys as an error.

Add `--clean` with `--compile` or `--docx` to remove intermediate LaTeX files
after all requested outputs have been generated successfully. This removes the
report's auxiliary files (including `.aux`, `.log`, `.out`, `.fls`, and
`.fdb_latexmk`) and its multibib `.aux`, `.bbl`, and `.blg` files. Previous report
declarations and recorder output are used to identify obsolete multibib files
from earlier runs.

Cleanup preserves `.tex`, `.pdf`, `.bib`, `.bst`, `.csv`, and `.docx` files, and
does not sweep unrelated files in the output directory. Word export finishes
before `.bbl` files are removed. If compilation or export fails, cleanup is
skipped so the build diagnostics remain available. Recompiling a cleaned report
requires running BibTeX again; rerunning the command with `--compile` handles this.

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
PYTHONPATH=src python -m unittest discover -s tests -v
ruff check .
```

## License

MIT. See `LICENSE`.
