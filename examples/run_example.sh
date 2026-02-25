#!/usr/bin/env bash
set -euo pipefail

# Run from repository root:
#   bash examples/run_example.sh

./bin/bibreport \
  examples/sample.bib \
  examples/investigators.csv \
  --start-date 2020-01-01 \
  --end-date 2022-12-31 \
  --out examples/output/report.tex

echo "Wrote examples/output/report.tex and examples/output/summary_pubs.csv"
