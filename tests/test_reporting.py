"""Regression coverage for date filtering, accounting, and CLI cleanup ordering."""

import contextlib
import datetime as dt
import io
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from bib_investigator_report import report


class DateTests(unittest.TestCase):
    def test_export_timestamps_keep_written_calendar_date(self):
        for value in (
            "2026-11-04 00:00:00 GMT", "2026-11-04T23:30:00-0500",
            "2026-11-04T23:30:00.123Z", "2026-11-04 00:00:00 +00:00",
        ):
            with self.subTest(value=value):
                self.assertEqual(report.parse_iso_date(value), dt.date(2026, 11, 4))

    def test_date_added_overrides_publication_date_year_and_month(self):
        entry = report.BibEntry("future", "article", {
            "year": "2026", "month": "Dec", "date": "2027-01-10",
            "date-added": "2026-11-04 00:00:00 GMT",
        }, "")
        self.assertEqual(report.infer_entry_date(entry), (dt.date(2026, 11, 4), "date-added"))
        entry.fields["month"] = "invalid month"
        self.assertEqual(report.infer_entry_date(entry), (dt.date(2026, 11, 4), "date-added"))

    def test_explicit_date_field_overrides_auto_selection_without_fallback(self):
        entry = report.BibEntry("paper", "article", {
            "date": "2027-01-10", "date-added": "2026-11-04 00:00:00 GMT",
        }, "")
        self.assertEqual(
            report.infer_entry_date(entry, date_field="date"),
            (dt.date(2027, 1, 10), "date"),
        )
        self.assertEqual(
            report.infer_entry_date(entry, date_field="date-added"),
            (dt.date(2026, 11, 4), "date-added"),
        )
        self.assertEqual(report.infer_entry_date(entry, date_field="year"), (None, "year"))

    def test_absent_date_added_falls_back_to_publication_dates(self):
        entry = report.BibEntry("paper", "article", {"year": "2026", "month": "Dec"}, "")
        self.assertEqual(report.infer_entry_date(entry), (dt.date(2026, 12, 15), "year + month"))
        entry.fields["date"] = "2026-11-04"
        self.assertEqual(report.infer_entry_date(entry), (dt.date(2026, 11, 4), "date"))
        del entry.fields["date"]
        del entry.fields["month"]
        self.assertEqual(report.infer_entry_date(entry), (dt.date(2026, 7, 1), "year"))

    def test_unusable_date_added_does_not_fall_back_to_other_dates(self):
        for value in ("", " ", "not-a-date"):
            with self.subTest(value=value):
                entry = report.BibEntry("paper", "article", {
                    "date-added": value, "date": "2026-11-04", "year": "2026", "month": "Nov",
                }, "")
                self.assertEqual(report.infer_entry_date(entry), (None, "date-added"))

    def test_invalid_date_added_components_are_rejected_without_fallback(self):
        for value in (
            "2026-02-31", "2026-02-29", "2026-13", "2026-11-00", "0000",
            "2026-01-01 99:99:99 GMT",
        ):
            for date_field in ("auto", "date-added"):
                with self.subTest(value=value, date_field=date_field):
                    entry = report.BibEntry("paper", "article", {
                        "date-added": value, "date": "2026-11-04",
                        "year": "2026", "month": "Nov",
                    }, "")
                    self.assertEqual(
                        report.infer_entry_date(entry, date_field=date_field),
                        (None, "date-added"),
                    )

    def test_valid_calendar_dates_and_partial_date_defaults_are_preserved(self):
        cases = {
            "2024-02-29": dt.date(2024, 2, 29),
            "2024-02-29T23:59:59Z": dt.date(2024, 2, 29),
            "2026": dt.date(2026, 7, 1),
            "2026-02": dt.date(2026, 2, 15),
            "2026-12-31": dt.date(2026, 12, 31),
        }
        for value, expected in cases.items():
            with self.subTest(value=value):
                self.assertEqual(report.parse_iso_date(value), expected)


class CliTests(unittest.TestCase):
    def setUp(self):
        self.temporary_dir = TemporaryDirectory()
        self.addCleanup(self.temporary_dir.cleanup)
        self.directory = Path(self.temporary_dir.name)
        self.bib = self.directory / "input.bib"
        self.bib.write_text(
            "@article{included,author={Doe, Jane and Roe, John},year={2026}}\n",
            encoding="utf-8",
        )
        self.investigators = self.directory / "investigators.csv"
        self.investigators.write_text("Firstname,Lastname\nJane,Doe\nJohn,Roe\n")
        self.out = self.directory / "report.tex"
        self.args = [
            str(self.bib), str(self.investigators), "--start-date", "2023-05-01",
            "--end-date", "2026-11-30", "--out", str(self.out),
        ]

    def run_main(self, *extra):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(io.StringIO()):
            result = report.main(self.args + list(extra))
        self.assertEqual(result, 0)
        return stdout.getvalue()

    def fake_compile(self, *args, **kwargs):
        self.out.with_suffix(".pdf").touch()
        self.out.with_suffix(".log").write_text("diagnostics")
        (self.directory / "four.bbl").write_text("\\bibitem{included} Example publication.")

    def test_accounts_for_all_records_without_counting_coauthors_twice(self):
        self.bib.write_text(
            "@comment{Not a publication}\n"
            "@article{first,author={Doe, Jane and Roe, John},date={2023-05-01}}\n"
            "@article{last,author={Doe, Jane},date={2026-11-30}}\n"
            "@article{future,author={Doe, Jane},year={2026},month={Dec}}\n"
            "@article{unknown,author={Else, Someone},year={2026}}\n"
            "@article{undated,author={Doe, Jane}}\n"
            "@article{broken,author={Doe, Jane}\n"
        )
        output = self.run_main()
        self.assertIn("BibTeX records: 6 (parsed: 5; skipped: 1)", output)
        self.assertIn("Included in report: 2 unique records", output)
        self.assertIn("Not included in report: 4 records", output)
        self.assertIn("future: inferred date 2026-12-15 from year + month", output)
        self.assertIn("unknown: no matching investigators", output)
        self.assertIn("undated: no usable date", output)
        self.assertIn("broken:", output)
        tex = self.out.read_text()
        self.assertIn("{first}", tex)
        self.assertIn("{last}", tex)
        self.assertNotIn("{future}", tex)

    def test_date_added_controls_inclusion_and_project_year(self):
        self.bib.write_text(
            "@article{included,author={Doe, Jane},year={2026},month={Dec},"
            "date={2027-01-10},date-added={2026-11-04 00:00:00 GMT}}\n"
            "@article{earlier,author={Doe, Jane},year={2026},month={Nov},"
            "date-added={2024-04-30}}\n"
            "@article{outside,author={Doe, Jane},year={2026},month={Nov},"
            "date-added={2026-12-01}}\n"
            "@article{invalid,author={Doe, Jane},year={2026},month={Nov},"
            "date-added={unknown}}\n"
        )
        output = self.run_main()
        self.assertIn("Included in report: 2 unique records", output)
        self.assertIn("Not included in report: 2 records", output)
        self.assertIn("outside: inferred date 2026-12-01 from date-added", output)
        self.assertIn("invalid: no usable authoritative date-added value 'unknown'", output)
        tex = self.out.read_text()
        self.assertIn(r"\citefour{included}", tex)
        self.assertIn(r"\citeone{earlier}", tex)
        self.assertNotIn("{outside}", tex)
        self.assertNotIn("{invalid}", tex)

    def test_invalid_authoritative_dates_are_listed_as_omissions(self):
        invalid_dates = (
            "2026-02-31", "2026-13", "2026-11-00", "0000",
            "2026-01-01 99:99:99 GMT",
        )
        source = self.bib.read_text()
        for index, value in enumerate(invalid_dates):
            source += (
                f"@article{{invalid{index},author={{Doe, Jane}},date-added={{{value}}},"
                "date={2026-11-04},year={2026},month={Nov}}\n"
            )
        self.bib.write_text(source)
        output = self.run_main()
        self.assertIn("BibTeX records: 6 (parsed: 6; skipped: 0)", output)
        self.assertIn("Included in report: 1 unique records", output)
        self.assertIn("Not included in report: 5 records", output)
        tex = self.out.read_text()
        self.assertIn(r"\citefour{included}", tex)
        for index, value in enumerate(invalid_dates):
            with self.subTest(value=value):
                self.assertIn(
                    f"invalid{index}: no usable authoritative date-added value {value!r}; "
                    "other date fields ignored",
                    output,
                )
                self.assertNotIn(f"{{invalid{index}}}", tex)

    def test_clean_requires_a_build_before_writing_anything(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
            report.main(self.args + ["--clean"])
        self.assertEqual(error.exception.code, 2)
        self.assertFalse(self.out.exists())

    def test_clean_runs_after_word_export_and_preserves_outputs(self):
        self.out.write_text("\\newcites{onepartial}{Old grouping}\n")
        (self.directory / "onepartial.aux").touch()

        def fake_docx(**kwargs):
            self.assertTrue((self.directory / "four.bbl").exists())
            kwargs["path"].touch()

        with patch.object(report, "compile_latex", side_effect=self.fake_compile), \
                patch.object(report, "write_docx_from_bbl", side_effect=fake_docx):
            output = self.run_main("--docx", "--clean")
        self.assertIn("Compiled bibliography: all 1 selected records found", output)
        self.assertIn("Cleaned 3 LaTeX intermediate files", output)
        for name in ("report.tex", "report.pdf", "report.docx", "input.bib", "summary_pubs.csv"):
            self.assertTrue((self.directory / name).exists(), name)
        self.assertFalse((self.directory / "four.bbl").exists())
        self.assertFalse((self.directory / "onepartial.aux").exists())

    def test_no_clean_preserves_intermediates(self):
        with patch.object(report, "compile_latex", side_effect=self.fake_compile):
            self.run_main("--compile")
        self.assertTrue((self.directory / "four.bbl").exists())
        self.assertTrue(self.out.with_suffix(".log").exists())

    def test_compile_failure_retains_diagnostics(self):
        def failing_compile(*args, **kwargs):
            self.out.with_suffix(".log").write_text("failure")
            raise RuntimeError("compile failed")

        with patch.object(report, "compile_latex", side_effect=failing_compile), \
                contextlib.redirect_stdout(io.StringIO()), self.assertRaisesRegex(
                    RuntimeError, "compile failed"
                ):
            report.main(self.args + ["--compile", "--clean"])
        self.assertEqual(self.out.with_suffix(".log").read_text(), "failure")

    def test_word_failure_retains_bibliographies(self):
        with patch.object(report, "compile_latex", side_effect=self.fake_compile), \
                patch.object(
                    report, "write_docx_from_bbl", side_effect=RuntimeError("Word failed")
                ), \
                contextlib.redirect_stdout(io.StringIO()), self.assertRaisesRegex(
                    RuntimeError, "Word failed"
                ):
            report.main(self.args + ["--docx", "--clean"])
        self.assertTrue((self.directory / "four.bbl").exists())

    def test_selected_publications_missing_from_bbl_fail_and_retain_files(self):
        def empty_compile(*args, **kwargs):
            self.out.with_suffix(".log").touch()

        with patch.object(report, "compile_latex", side_effect=empty_compile), \
                contextlib.redirect_stdout(io.StringIO()), self.assertRaisesRegex(
                    RuntimeError, "missing from compiled bibliographies: included"
                ):
            report.main(self.args + ["--compile", "--clean"])
        self.assertTrue(self.out.with_suffix(".log").exists())


if __name__ == "__main__":
    unittest.main()
