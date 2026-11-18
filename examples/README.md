# Examples

- `investigators.csv`: sample investigators list
- `sample.bib`: sample BibTeX with a few entries
- `run_example.sh`: generates `examples/output/report.tex` and `summary_pubs.csv`

The example does **not** run LaTeX compilation by default.

To generate a PDF and remove the report's intermediate LaTeX files, run from
the repository root:

```bash
./bin/bibreport examples/sample.bib examples/investigators.csv \
  --start-date 2020-01-01 --end-date 2022-12-31 \
  --out examples/output/report.tex --compile --clean
```

The command prints record totals and lists any omitted keys with their reasons.
`--clean` preserves the final PDF, TeX source, bibliography, and summary CSV.

For a dot-matrix summary with yearly publication bars, install plotting support
and select `dots`:

```bash
python -m pip install -e ".[plots]"
./bin/bibreport examples/sample.bib examples/investigators.csv \
  --start-date 2020-01-01 --end-date 2022-12-31 \
  --out examples/output/report.tex --summary-style dots --compile --clean
```

This also creates `examples/output/report_summary.pdf`, which the `.tex` includes
automatically and `--clean` preserves. Use `--summary-style table` (the default)
for the original citation table without the plotting dependency.

Add `--coauthor-network` to either summary style to show shared-paper
relationships among the sample investigators. This creates and includes
`examples/output/report_coauthors.pdf` and also requires plotting support.

To match the LaTeX report font more closely in both figures, add
`--plot-font computer-modern`:

```bash
./bin/bibreport examples/sample.bib examples/investigators.csv \
  --start-date 2020-01-01 --end-date 2022-12-31 \
  --out examples/output/report.tex --summary-style dots --coauthor-network \
  --plot-font computer-modern
```

This uses fonts bundled with Matplotlib and does not require LaTeX to generate
the figures. Omit the option or use `--plot-font default` to keep DejaVu Sans.
