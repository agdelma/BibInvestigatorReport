# Changelog

## 0.6.0 - 2026-11-18
- Organized reports into Summary, Per-Investigator Products, and References, with investigator and bibliography groups as subsections
- Added `--coauthor-network` to generate and include a weighted investigator co-authorship network in the summary
- Matched two-investigator citation and legend colors to the blue used in the charts
- Added regression coverage for co-authorship counts, isolated investigators, report structure, and consistent citation colors

## 0.5.0 - 2026-11-18
- Added `--summary-style dots` for an automatically included vector PDF with a dot matrix, investigator totals, and yearly collaboration bars
- Kept the original citation table as the default and as `--summary-style table`
- Added the optional `plots` dependency for dot-matrix rendering
- Underlined full-support citation numbers only in the per-investigator lists, preserving collaboration colors and other citation styles
- Preserved individual citation lists and CSV output, with automatic pagination for larger matrices
- Added regression coverage for shared-paper counts, optional plotting, and summary PDF integration

## 0.4.0 - 2026-11-17
- Added console record totals and per-record omission reasons, including inferred dates and date sources
- Added parser diagnostics for malformed records, duplicate keys, and duplicate fields; duplicate fields now use the first value consistently with BibTeX
- Excluded BibTeX directives from publication record counts
- Made `date-added` authoritative in automatic date inference whenever present; blank or invalid values omit the entry without falling back to other dates
- Added support for timestamp-formatted date fields
- Reject invalid calendar dates and timestamps instead of silently adjusting them
- Added `--clean` to remove report intermediates after successful PDF compilation and optional Word export
- Added regression tests for parsing, reporting diagnostics, dates, and cleanup

## 0.3.0
- Added `--add-support` for support-grouped publication lists by project-year period
- Added Full Support, Partial Support, and Support Not Included bibliography sections
- Added investigator author bolding in support-grouped LaTeX bibliographies
- Added `--annual-report` to suppress bibliography numbering for copy/paste workflows
- Added support-grouped `.docx` export and automatic LaTeX/BibTeX compilation for `--docx`
- Improved BibTeX/BBL parsing for LaTeX-accented names and custom bibliography styles

## 0.2.0
- Added totals to year headers in summary table
- beta version of .docx output of reference list (untested)

## 0.1.0
- Initial packaging of the original `bib_investigator_report.py` script as an installable Python package.
