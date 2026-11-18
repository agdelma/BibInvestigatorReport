"""Publication counts, optional plotting, and dot-summary CLI integration."""

import builtins
import contextlib
import datetime as dt
import importlib.util
import io
import re
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from bib_investigator_report import report, summary


class SummaryDataTests(unittest.TestCase):
    def setUp(self):
        self.investigators = [("Jane", "Doe"), ("John", "Roe"), ("Sam", "Smith")]
        self.periods = report.build_periods(dt.date(2025, 1, 1), dt.date(2026, 12, 31))
        self.mapping = {
            self.investigators[0]: {1: ["shared", "solo", "shared"], 2: ["team"]},
            self.investigators[1]: {1: ["shared"], 2: ["team"]},
            self.investigators[2]: {1: [], 2: ["team"]},
            ("Excluded", "Person"): {1: ["not-in-roster"], 2: []},
        }
        self.collaboration = {"solo": 1, "shared": 2, "team": 3, "not-in-roster": 1}

    def data(self, **overrides):
        args = dict(
            investigators=self.investigators, periods=self.periods,
            inv_to_period_keys=self.mapping, entry_inv_count=self.collaboration,
        )
        args.update(overrides)
        return summary.build_summary_data(**args)

    def test_counts_unique_papers_and_retains_every_investigator_attribution(self):
        data = self.data()
        self.assertEqual(data.unique_papers, 3)
        self.assertEqual(data.collaborative_papers, 2)
        self.assertEqual(data.year_category_counts, ((1, 1, 0), (0, 0, 1)))
        self.assertEqual(data.investigator_totals, (3, 2, 1))
        self.assertEqual(
            data.cell_keys,
            ((("solo", "shared"), ("team",)), (("shared",), ("team",)), ((), ("team",))),
        )

    def test_excludes_unrequested_periods_from_all_totals(self):
        data = self.data(periods=self.periods[:1])
        self.assertEqual(data.unique_papers, 2)
        self.assertEqual(data.collaborative_papers, 1)
        self.assertEqual(data.investigator_totals, (2, 1, 0))
        self.assertEqual(data.year_category_counts, ((1, 1, 0),))

    def test_three_or_more_category_counts_papers_once_regardless_of_team_size(self):
        self.collaboration["team"] = 7
        data = self.data()
        self.assertEqual(data.year_category_counts[1], (0, 0, 1))
        self.assertEqual(data.collaborative_papers, 2)

    def test_empty_assignments_preserve_zero_rows_and_years(self):
        data = self.data(inv_to_period_keys={})
        self.assertEqual(data.unique_papers, 0)
        self.assertEqual(data.collaborative_papers, 0)
        self.assertEqual(data.investigator_totals, (0, 0, 0))
        self.assertEqual(data.cell_keys, (((), ()), ((), ()), ((), ())))
        self.assertEqual(data.year_category_counts, ((0, 0, 0), (0, 0, 0)))

    def test_missing_matplotlib_has_actionable_install_message(self):
        original_import = builtins.__import__

        def no_matplotlib(name, *args, **kwargs):
            if name == "matplotlib" or name.startswith("matplotlib."):
                raise ModuleNotFoundError("No module named 'matplotlib'", name="matplotlib")
            return original_import(name, *args, **kwargs)

        with TemporaryDirectory() as temporary_dir, \
                patch("builtins.__import__", side_effect=no_matplotlib), \
                self.assertRaisesRegex(RuntimeError, r"bib-investigator-report\[plots\]"):
            summary.write_dot_summary(
                path=Path(temporary_dir) / "summary.pdf", investigators=self.investigators,
                periods=self.periods, inv_to_period_keys=self.mapping,
                entry_inv_count=self.collaboration,
            )


class SummaryCliTests(unittest.TestCase):
    def setUp(self):
        temporary_dir = TemporaryDirectory()
        self.addCleanup(temporary_dir.cleanup)
        self.directory = Path(temporary_dir.name)
        self.bib = self.directory / "input.bib"
        self.bib.write_text(
            "@article{included,author={Doe, Jane and Roe, John},year={2026},support={partial}}\n",
            encoding="utf-8",
        )
        self.investigators = self.directory / "investigators.csv"
        self.investigators.write_text("Firstname,Lastname\nJane,Doe\nJohn,Roe\n")
        self.out = self.directory / "annual report_v2.tex"
        self.args = [
            str(self.bib), str(self.investigators), "--start-date", "2023-05-01",
            "--end-date", "2026-11-30", "--out", str(self.out),
        ]
        self.summary_path = self.directory / "annual report_v2_summary.pdf"

    def run_main(self, *extra):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(report.main(self.args + list(extra)), 0)
        return self.out.read_text()

    @staticmethod
    def fake_summary(**kwargs):
        kwargs["path"].write_bytes(b"%PDF-1.4\nsummary fixture\n")
        return 2

    def test_default_and_explicit_table_require_no_plotting_and_match(self):
        original_import = builtins.__import__

        def no_matplotlib(name, *args, **kwargs):
            if name == "matplotlib" or name.startswith("matplotlib."):
                raise AssertionError("The original table must not import Matplotlib")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=no_matplotlib), \
                patch.object(report, "write_dot_summary") as render:
            default_tex = self.run_main()
            explicit_tex = self.run_main("--summary-style", "table")
            cm_tex = self.run_main("--plot-font", "computer-modern")
        render.assert_not_called()
        self.assertEqual(default_tex, explicit_tex)
        self.assertEqual(default_tex, cm_tex)
        self.assertIn(r"\begin{longtable}", default_tex)
        self.assertNotIn(r"\includegraphics", default_tex)
        self.assertFalse(self.summary_path.exists())

    def test_dots_embeds_each_page_from_relative_pdf_and_preserves_citations_and_csv(self):
        self.run_main()
        original_csv = (self.directory / "summary_pubs.csv").read_bytes()
        self.out.with_suffix(".pdf").write_bytes(b"existing compiled report")
        with patch.object(report, "write_dot_summary", side_effect=self.fake_summary) as render:
            tex = self.run_main("--summary-style", "dots")
        self.assertEqual(render.call_args.kwargs["path"], self.summary_path)
        self.assertEqual(render.call_args.kwargs["plot_font"], "default")
        self.assertEqual(tex.count(r"\includegraphics"), 2)
        self.assertIn("page=1", tex)
        self.assertIn("page=2", tex)
        self.assertIn(r"\detokenize{annual report_v2_summary.pdf}", tex)
        self.assertNotIn(str(self.directory), tex)
        self.assertIn(r"\usepackage{graphicx}", tex)
        self.assertNotIn(r"\begin{longtable}", tex)
        self.assertEqual(tex.count(r"\citefour{included}"), 2)
        self.assertIn(r"\subsection*{Jane Doe (1)}", tex)
        self.assertEqual((self.directory / "summary_pubs.csv").read_bytes(), original_csv)
        self.assertEqual(self.out.with_suffix(".pdf").read_bytes(), b"existing compiled report")

    def test_dots_keeps_support_grouped_and_unnumbered_bibliography_behavior(self):
        with patch.object(report, "write_dot_summary", side_effect=self.fake_summary):
            tex = self.run_main("--summary-style", "dots", "--add-support", "--annual-report")
        self.assertEqual(tex.count(r"\citefourpartial{included}"), 2)
        self.assertIn(r"\renewcommand{\bibnumfmt}[1]{}", tex)
        self.assertIn(r"\section*{References}", tex)
        self.assertIn(r"\bibliographyfourpartial{input_support}", tex)

    def test_cleanup_preserves_summary_pdf_after_compilation(self):
        def fake_compile(*args, **kwargs):
            self.out.with_suffix(".pdf").touch()
            self.out.with_suffix(".log").write_text("compile diagnostics")
            (self.directory / "four.bbl").write_text(r"\bibitem{included} Example publication.")

        with patch.object(report, "write_dot_summary", side_effect=self.fake_summary), \
                patch.object(report, "compile_latex", side_effect=fake_compile):
            self.run_main("--summary-style", "dots", "--compile", "--clean")
        self.assertTrue(self.summary_path.read_bytes().startswith(b"%PDF-"))
        self.assertTrue(self.out.with_suffix(".pdf").exists())
        self.assertFalse(self.out.with_suffix(".log").exists())
        self.assertFalse((self.directory / "four.bbl").exists())


@unittest.skipUnless(importlib.util.find_spec("matplotlib"), "requires optional plots dependency")
class SummaryPdfTests(unittest.TestCase):
    def test_font_selection_is_embedded_without_changing_global_settings(self):
        from matplotlib import rc_context, rcParams

        investigators = [("Jane", "Doe")]
        periods = report.build_periods(dt.date(2026, 1, 1), dt.date(2026, 12, 31))
        for options, expected_fonts in (
            ({}, (b"DejaVuSans", b"DejaVuSans-Bold")),
            ({"plot_font": "computer-modern"}, (b"Cmr10", b"Cmb10")),
            ({"plot_font": "default"}, (b"DejaVuSans", b"DejaVuSans-Bold")),
        ):
            with self.subTest(options=options), TemporaryDirectory() as temporary_dir, \
                    rc_context({"text.usetex": True, "mathtext.fontset": "stix"}):
                settings = ("font.family", "text.usetex", "mathtext.fontset", "pdf.fonttype")
                before = {key: rcParams[key] for key in settings}
                path = Path(temporary_dir) / "summary.pdf"
                summary.write_dot_summary(
                    path=path, investigators=investigators, periods=periods,
                    inv_to_period_keys={investigators[0]: {1: ["paper"]}},
                    entry_inv_count={"paper": 1}, **options,
                )
                self.assertEqual({key: rcParams[key] for key in settings}, before)
                embedded_fonts = re.findall(rb"/BaseFont\s*/([^\s/]+)", path.read_bytes())
                for expected in expected_fonts:
                    self.assertTrue(any(name.endswith(expected) for name in embedded_fonts),
                                    (expected, embedded_fonts))
                if options.get("plot_font") == "computer-modern":
                    self.assertFalse(any(b"DejaVuSans" in name for name in embedded_fonts))

    def render(self, investigators, periods, mapping, collaboration):
        with TemporaryDirectory() as temporary_dir:
            path = Path(temporary_dir) / "summary.pdf"
            pages = summary.write_dot_summary(
                path=path, investigators=investigators, periods=periods,
                inv_to_period_keys=mapping, entry_inv_count=collaboration,
            )
            pdf = path.read_bytes()
        self.assertTrue(pdf.startswith(b"%PDF-"))
        self.assertEqual(len(re.findall(rb"/Type\s*/Page\b", pdf)), pages)
        return pages

    def test_empty_report_renders_a_valid_page(self):
        periods = report.build_periods(dt.date(2026, 1, 1), dt.date(2026, 12, 31))
        self.assertEqual(self.render([("Jane", "Doe")], periods, {}, {}), 1)

    def test_many_years_and_investigators_paginate(self):
        investigators = [(f"Investigator {i}", "Example") for i in range(40)]
        periods = report.build_periods(dt.date(2020, 1, 1), dt.date(2026, 12, 31))
        self.assertGreater(self.render(investigators, periods, {}, {}), 1)

    def test_yearly_bars_share_a_scale_across_year_panels(self):
        from matplotlib.backends.backend_pdf import PdfPages
        from matplotlib.container import BarContainer

        investigators = [("Jane", "Doe")]
        periods = report.build_periods(dt.date(2020, 1, 1), dt.date(2025, 12, 31))
        first_year_keys = [f"paper-{i}" for i in range(100)]
        mapping = {investigators[0]: {1: first_year_keys, 6: ["last-year-paper"]}}
        collaboration = dict.fromkeys([*first_year_keys, "last-year-paper"], 1)
        bar_heights = []
        original_save = PdfPages.savefig

        def record_and_save(pdf, figure, *args, **kwargs):
            bar_heights.extend(
                patch.get_height()
                for axes in figure.axes for container in axes.containers
                if isinstance(container, BarContainer)
                for patch in container.patches if patch.get_height() > 0
            )
            return original_save(pdf, figure, *args, **kwargs)

        with patch.object(PdfPages, "savefig", new=record_and_save):
            pages = self.render(investigators, periods, mapping, collaboration)
        self.assertGreaterEqual(pages, 2)
        self.assertEqual(len(bar_heights), 2)
        self.assertAlmostEqual(max(bar_heights) / min(bar_heights), 100)

    def test_dense_cells_render_without_discarding_papers(self):
        from matplotlib.backends.backend_pdf import PdfPages
        from matplotlib.collections import PathCollection

        investigators = [("Jane", "Doe")]
        periods = report.build_periods(dt.date(2026, 1, 1), dt.date(2026, 12, 31))
        keys = [f"paper-{i}" for i in range(180)]
        mapping = {investigators[0]: {1: keys}}
        collaboration = dict.fromkeys(keys, 1)
        data = summary.build_summary_data(
            investigators=investigators, periods=periods, inv_to_period_keys=mapping,
            entry_inv_count=collaboration,
        )
        self.assertEqual(len(data.cell_keys[0][0]), len(keys))
        marker_counts = []
        original_save = PdfPages.savefig

        def record_and_save(pdf, figure, *args, **kwargs):
            marker_counts.append(sum(
                len(collection.get_offsets())
                for axes in figure.axes for collection in axes.collections
                if isinstance(collection, PathCollection)
            ))
            return original_save(pdf, figure, *args, **kwargs)

        with patch.object(PdfPages, "savefig", new=record_and_save):
            pages = self.render(investigators, periods, mapping, collaboration)
        # Each output page repeats the three category legend markers.
        self.assertEqual(sum(marker_counts) - 3 * pages, len(keys))


if __name__ == "__main__":
    unittest.main()
