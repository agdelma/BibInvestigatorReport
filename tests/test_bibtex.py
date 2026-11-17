import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from bib_investigator_report.report import BibParseDiagnostics, parse_bibtex_file


class BibtexParsingTests(unittest.TestCase):
    def parse(self, source):
        diagnostics = BibParseDiagnostics()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "input.bib"
            path.write_text(source, encoding="utf-8")
            errors = io.StringIO()
            with contextlib.redirect_stderr(errors):
                entries = parse_bibtex_file(path, diagnostics=diagnostics)
        return entries, diagnostics, errors.getvalue()

    def test_counts_records_but_not_directives_or_comments(self):
        entries, diagnostics, errors = self.parse(r'''
@comment{An example @article{not-a-record, year={1999}} with a literal " quote}
@string{journalname = "A Journal"}
@preamble{"A preamble without a comma"}
% @article{commented-out, year={2020}}
@article{first, title={A quoted " symbol, and {nested} text}, year={2026}}
@book(second, title="A {braced \"o} title, with (parentheses)", year=2025)
''')
        self.assertEqual([entry.key for entry in entries], ["first", "second"])
        self.assertEqual(entries[0].get("year"), "2026")
        self.assertEqual(entries[1].get("year"), "2025")
        self.assertEqual(diagnostics.total_records, 2)
        self.assertEqual(diagnostics.skipped_records, [])
        self.assertEqual(errors, "")

    def test_duplicate_fields_keep_first_value_like_bibtex(self):
        entries, diagnostics, errors = self.parse(
            "@article{paper, year={2026}, YEAR={2025}, title={First}, title={Second}}"
        )
        self.assertEqual(entries[0].get("year"), "2026")
        self.assertEqual(entries[0].get("title"), "First")
        self.assertEqual(diagnostics.total_records, 1)
        self.assertEqual(len(diagnostics.warnings), 2)
        self.assertEqual(diagnostics.warnings[0][0], "paper")
        self.assertIn("keeping first value '2026'", diagnostics.warnings[0][1])
        self.assertEqual(errors, "")

    def test_duplicate_keys_are_counted_and_skipped(self):
        entries, diagnostics, errors = self.parse('''
@article{duplicate, year={2026}}
@article{duplicate, year={2025}}
@article{other, year={2024}}
''')
        self.assertEqual([entry.key for entry in entries], ["duplicate", "other"])
        self.assertEqual(diagnostics.total_records, 3)
        self.assertEqual(len(diagnostics.skipped_records), 1)
        self.assertEqual(diagnostics.skipped_records[0][0], "duplicate")
        self.assertIn("duplicate citation key", diagnostics.skipped_records[0][1])
        self.assertIn("duplicate citation key", errors)

    def test_recovers_after_missing_key_comma_and_empty_key(self):
        entries, diagnostics, errors = self.parse('''
@article{missing-comma}
@article{, year={2025}}
@article{valid, year={2026}}
''')
        self.assertEqual([entry.key for entry in entries], ["valid"])
        self.assertEqual(diagnostics.total_records, 3)
        self.assertEqual(len(diagnostics.skipped_records), 2)
        self.assertEqual(diagnostics.skipped_records[0][0], "missing-comma")
        self.assertIn("empty citation key", errors)

    def test_recovers_after_unmatched_braces(self):
        entries, diagnostics, errors = self.parse('''
@article{broken, title={No closing braces
@article{valid, year={2026}}
''')
        self.assertEqual([entry.key for entry in entries], ["valid"])
        self.assertEqual(diagnostics.total_records, 2)
        self.assertEqual(diagnostics.skipped_records[0][0], "broken")
        self.assertIn("unmatched braces", errors)

    def test_recovers_after_unterminated_quote(self):
        entries, diagnostics, errors = self.parse('''
@article{broken, title="No closing quote}
@article{valid, year={2026}}
''')
        self.assertEqual([entry.key for entry in entries], ["valid"])
        self.assertEqual(diagnostics.total_records, 2)
        self.assertEqual(len(diagnostics.skipped_records), 1)
        self.assertIn("unterminated quoted value", errors)

    def test_invalid_fields_are_reported_instead_of_silently_discarded(self):
        entries, diagnostics, errors = self.parse('''
@article{broken, title}
@article{valid, year={2026}}
''')
        self.assertEqual([entry.key for entry in entries], ["valid"])
        self.assertEqual(diagnostics.total_records, 2)
        self.assertEqual(diagnostics.skipped_records, [("broken", "field is missing '=': 'title'")])
        self.assertIn("field is missing '='", errors)

    def test_legacy_call_without_diagnostics_returns_entries(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "input.bib"
            path.write_text("@article{paper, year={2026}}", encoding="utf-8")
            self.assertEqual(parse_bibtex_file(path)[0].key, "paper")


if __name__ == "__main__":
    unittest.main()
