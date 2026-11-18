"""Full-support emphasis is confined to investigator citation lists."""

import datetime as dt
import unittest

from bib_investigator_report import report


class SupportCitationTests(unittest.TestCase):
    def render_citations(self, entries, *, add_support=False, highlight=True):
        return report.latex_citations_for_keys(
            keys=list(entries), year_index=1,
            entry_inv_count={key: index % 3 + 1 for index, key in enumerate(entries)},
            entries_by_key={key: entry for key, entry in entries.items() if entry is not None},
            add_support=add_support, highlight_full_support=highlight,
        )

    def test_underlines_full_support_without_changing_collaboration_colors(self):
        entries = {
            key: report.BibEntry(key, "article", {"support": value}, "")
            for key, value in (
                ("solo", "full"), ("pair", " FULL "), ("team", "Full Support"),
            )
        }
        for add_support in (False, True):
            with self.subTest(add_support=add_support):
                citations = self.render_citations(entries, add_support=add_support)
                suffix = "onefull" if add_support else "one"
                for key, color in zip(entries, ("black", "invBlue", "invOrange")):
                    self.assertIn(
                        rf"\textcolor{{{color}}}{{\underline{{\cite{suffix}{{{key}}}}}}}",
                        citations,
                    )
                self.assertEqual(citations.count(r"\underline"), 3)

    def test_partial_blank_missing_and_unknown_support_keep_original_citations(self):
        entries = {
            key: report.BibEntry(key, "article", fields, "")
            for key, fields in (
                ("partial", {"support": "partial"}),
                ("partial_label", {"support": "Partial Support"}),
                ("blank", {"support": ""}),
                ("whitespace", {"support": "  "}),
                ("missing", {}),
                ("unknown", {"support": "unrecognized"}),
            )
        }
        entries["missing_entry"] = None
        for add_support in (False, True):
            with self.subTest(add_support=add_support):
                highlighted = self.render_citations(entries, add_support=add_support)
                original = self.render_citations(
                    entries, add_support=add_support, highlight=False,
                )
                self.assertEqual(highlighted, original)
                self.assertNotIn(r"\underline", highlighted)
                if add_support:
                    self.assertIn(r"\citeonepartial{partial}", highlighted)
                    self.assertIn(r"\citeonenosupport{missing_entry}", highlighted)

    def test_emphasis_is_opt_in_for_callers_such_as_the_summary_table(self):
        entry = report.BibEntry("full", "article", {"support": "full"}, "")
        citations = report.latex_citations_for_keys(
            keys=[entry.key], year_index=1, entry_inv_count={entry.key: 2},
            entries_by_key={entry.key: entry},
        )
        self.assertEqual(citations, r"\textcolor{invBlue}{\citeone{full}}")

    def test_generated_reports_emphasize_only_full_support_in_investigator_lists(self):
        start, end = dt.date(2026, 1, 1), dt.date(2026, 12, 31)
        periods = report.build_periods(start, end)
        investigator = ("Jane", "Doe")
        entries = [
            report.BibEntry("full", "article", {"support": "full"}, ""),
            report.BibEntry("partial", "article", {"support": "partial"}, ""),
            report.BibEntry("missing", "article", {}, ""),
        ]
        keys = [entry.key for entry in entries]
        for add_support in (False, True):
            for style in ("table", "dots"):
                with self.subTest(add_support=add_support, style=style):
                    tex = report.generate_tex(
                        entries=entries, investigators=[investigator], periods=periods,
                        start_date=start, end_date=end, bib_resource_filename="references.bib",
                        inv_to_period_keys={investigator: {1: keys}},
                        entry_dates=dict.fromkeys(keys, dt.date(2026, 7, 1)),
                        entry_inv_count=dict.fromkeys(keys, 1), include_bibliography=True,
                        bibliography_style="plain", add_support=add_support,
                        annual_report=False, summary_style=style,
                        summary_filename="summary.pdf" if style == "dots" else None,
                    )
                    prefix, investigator_section = tex.split(r"\subsection*{Jane Doe (3)}", 1)
                    investigator_section, bibliography = investigator_section.split(
                        r"\section*{References}", 1,
                    )
                    suffix = "onefull" if add_support else "one"
                    self.assertIn(
                        rf"\underline{{\cite{suffix}{{full}}}}", investigator_section,
                    )
                    self.assertEqual(investigator_section.count(r"\underline"), 1)
                    if style == "table":
                        table = prefix.split(r"\begin{longtable}", 1)[1]
                        table = table.split(r"\end{longtable}", 1)[0]
                        self.assertNotIn(r"\underline", table)
                        self.assertIn(rf"\cite{suffix}{{full}}", table)
                    self.assertNotIn(r"\underline", bibliography)


if __name__ == "__main__":
    unittest.main()
