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
