"""Coauthor counts, report hierarchy, and optional network-figure integration."""

import builtins
import contextlib
import datetime as dt
import importlib.util
import io
import math
import re
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from bib_investigator_report import network, report
from bib_investigator_report.colors import COLLABORATION_BLUE


class CoauthorDataTests(unittest.TestCase):
    def setUp(self):
        self.investigators = [
            ("Jane", "Doe"), ("John", "Roe"), ("Sam", "Smith"), ("Zero", "Papers"),
        ]
        self.periods = report.build_periods(dt.date(2025, 1, 1), dt.date(2026, 12, 31))
        self.mapping = {
            self.investigators[0]: {
                1: ["shared", "triple", "solo", "shared"],
                2: ["shared", "repeat-pair", "later"],
            },
            self.investigators[1]: {1: ["shared", "triple"], 2: ["repeat-pair"]},
            self.investigators[2]: {1: ["triple"], 2: ["solo-smith"]},
            self.investigators[3]: {},
            ("Outside", "Roster"): {1: ["shared", "not-in-roster"]},
        }

    def build(self, **overrides):
        args = dict(
            investigators=self.investigators, periods=self.periods,
            inv_to_period_keys=self.mapping,
        )
        args.update(overrides)
        return network.build_coauthor_network(**args)

    def test_shared_papers_count_once_per_pair_and_triples_connect_all_three_pairs(self):
        data = self.build()
        self.assertEqual(data.investigators, tuple(self.investigators))
        self.assertEqual(data.node_totals, (5, 3, 2, 0))
        self.assertEqual(data.edges, ((0, 1, 3), (0, 2, 1), (1, 2, 1)))
        self.assertEqual(data.unique_papers, 6)
        self.assertEqual(data.collaborative_papers, 3)

    def test_unrequested_periods_and_outside_investigators_are_excluded(self):
        data = self.build(periods=self.periods[:1])
        self.assertEqual(data.node_totals, (3, 2, 1, 0))
        self.assertEqual(data.edges, ((0, 1, 2), (0, 2, 1), (1, 2, 1)))
        self.assertEqual(data.unique_papers, 3)
        self.assertEqual(data.collaborative_papers, 2)

    def test_duplicate_roster_rows_do_not_create_duplicate_nodes_or_self_edges(self):
        data = self.build(investigators=[
            self.investigators[0], self.investigators[0], self.investigators[1],
        ])
        self.assertEqual(data.investigators, tuple(self.investigators[:2]))
        self.assertEqual(data.node_totals, (5, 3))
        self.assertEqual(data.edges, ((0, 1, 3),))

    def test_solo_and_zero_paper_investigators_remain_visible_without_false_edges(self):
        data = self.build(inv_to_period_keys={
            self.investigators[0]: {1: ["a"]}, self.investigators[1]: {1: ["b"]},
        })
        self.assertEqual(data.investigators, tuple(self.investigators))
        self.assertEqual(data.node_totals, (1, 1, 0, 0))
        self.assertEqual(data.edges, ())
        self.assertEqual(data.unique_papers, 2)
        self.assertEqual(data.collaborative_papers, 0)

    def test_empty_roster_or_periods_produce_no_edges(self):
        for overrides in ({"investigators": []}, {"periods": []}):
            with self.subTest(overrides=overrides):
                data = self.build(**overrides)
                self.assertEqual(data.edges, ())
                self.assertEqual(data.unique_papers, 0)
                self.assertEqual(data.collaborative_papers, 0)
                self.assertTrue(all(count == 0 for count in data.node_totals))

    def test_missing_plotting_dependency_has_an_actionable_error(self):
        original_import = builtins.__import__

        def no_matplotlib(name, *args, **kwargs):
            if name == "matplotlib" or name.startswith("matplotlib."):
                raise ModuleNotFoundError("No module named 'matplotlib'", name="matplotlib")
            return original_import(name, *args, **kwargs)

        with TemporaryDirectory() as temporary_dir, \
                patch("builtins.__import__", side_effect=no_matplotlib), \
                self.assertRaisesRegex(RuntimeError, r"bib-investigator-report\[plots\]"):
            network.write_coauthor_network(
                path=Path(temporary_dir) / "network.pdf", investigators=self.investigators,
                periods=self.periods, inv_to_period_keys=self.mapping,
            )


class NetworkCliTests(unittest.TestCase):
    def setUp(self):
        temporary_dir = TemporaryDirectory()
        self.addCleanup(temporary_dir.cleanup)
        self.directory = Path(temporary_dir.name)
        self.bib = self.directory / "input.bib"
        self.bib.write_text(
            "@article{shared,author={Doe, Jane and Roe, John},date={2026-06-01},support={full}}\n"
            "@article{solo,author={Smith, Sam},date={2026-06-01}}\n"
            "@article{outside,author={Doe, Jane and Smith, Sam},date={2022-01-01}}\n",
            encoding="utf-8",
        )
        self.investigators = self.directory / "investigators.csv"
        self.investigators.write_text("Firstname,Lastname\nJane,Doe\nJohn,Roe\nSam,Smith\n")
        self.out = self.directory / "annual report_v3.tex"
        self.network_path = self.directory / "annual report_v3_coauthors.pdf"
        self.args = [
            str(self.bib), str(self.investigators), "--start-date", "2025-01-01",
            "--end-date", "2026-12-31", "--out", str(self.out),
        ]

    def run_main(self, *extra):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(report.main(self.args + list(extra)), 0)
        return self.out.read_text()

    @staticmethod
    def fake_network(**kwargs):
        kwargs["path"].write_bytes(b"%PDF-1.4\nnetwork fixture\n")

    @staticmethod
    def fake_summary(**kwargs):
        kwargs["path"].write_bytes(b"%PDF-1.4\ndot fixture\n")
        return 1

    def test_default_report_has_two_main_sections_then_references_without_plotting(self):
        original_import = builtins.__import__

        def no_plotting(name, *args, **kwargs):
            if name.split(".")[0] in {"matplotlib", "numpy", "networkx"}:
                raise AssertionError("Table mode must not import plotting dependencies")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=no_plotting), \
                patch.object(report, "write_coauthor_network") as render:
            tex = self.run_main()
        render.assert_not_called()
        self.assertEqual(re.findall(r"\\section(\*?)\{([^{}]+)\}", tex), [
            ("", "Summary"), ("", "Per-Investigator Products"), ("*", "References"),
        ])
        self.assertIn(r"\subsection*{Jane Doe (1)}", tex)
        self.assertIn(r"\begin{longtable}", tex)
        self.assertNotIn(r"\includegraphics", tex)
        self.assertFalse(self.network_path.exists())

    def test_network_is_in_summary_for_both_styles_and_bibliography_groupings(self):
        for style in ("table", "dots"):
            for support in (False, True):
                network_patch = patch.object(
                    report, "write_coauthor_network", side_effect=self.fake_network,
                )
                with self.subTest(style=style, support=support), network_patch, \
                        patch.object(report, "write_dot_summary", side_effect=self.fake_summary):
                    extra = ["--coauthor-network", "--summary-style", style]
                    if support:
                        extra += ["--add-support", "--annual-report"]
                    tex = self.run_main(*extra)
                    sections = re.findall(r"\\section(\*?)\{([^{}]+)\}", tex)
                    self.assertEqual(sections, [
                        ("", "Summary"), ("", "Per-Investigator Products"),
                        ("*", "References"),
                    ])
                    summary_start = tex.index(r"\section{Summary}")
                    products_start = tex.index(r"\section{Per-Investigator Products}")
                    reference_start = tex.index(r"\section*{References}")
                    self.assertLess(summary_start, products_start)
                    self.assertLess(products_start, reference_start)
                    self.assertIn(
                        r"\detokenize{annual report_v3_coauthors.pdf}",
                        tex[summary_start:products_start],
                    )
                    self.assertNotIn(str(self.directory), tex)
                    self.assertIn(r"\usepackage{graphicx}", tex)
                    self.assertEqual(tex.count(r"\includegraphics"), 2 if style == "dots" else 1)
                    suffix = "twofull" if support else "two"
                    self.assertEqual(
                        tex[products_start:reference_start].count(
                            rf"\underline{{\cite{suffix}{{shared}}}}"
                        ), 2,
                    )
                    self.assertNotIn(r"\underline", tex[reference_start:])

    def test_both_summary_styles_use_chart_blue_in_legends_and_shared_citations(self):
        for style in ("table", "dots"):
            with self.subTest(style=style), \
                    patch.object(report, "write_dot_summary", side_effect=self.fake_summary):
                tex = self.run_main("--summary-style", style)
            self.assertIn(
                rf"\definecolor{{invBlue}}{{HTML}}{{{COLLABORATION_BLUE[1:]}}}", tex,
            )
            self.assertIn(r"\textcolor{invBlue}{blue = 2}", tex)
            self.assertEqual(
                tex.count(r"\textcolor{invBlue}{\underline{\citetwo{shared}}}"), 2,
            )
            self.assertIn(r"\textcolor{black}{\citetwo{solo}}", tex)
            self.assertNotIn(r"\textcolor{blue}", tex)

    def test_network_receives_only_included_assignments_and_does_not_change_csv(self):
        self.run_main()
        original_csv = (self.directory / "summary_pubs.csv").read_bytes()
        with patch.object(
            report, "write_coauthor_network", side_effect=self.fake_network,
        ) as render:
            self.run_main("--coauthor-network")
        kwargs = render.call_args.kwargs
        self.assertEqual(kwargs["path"], self.network_path)
        included = {
            key for periods in kwargs["inv_to_period_keys"].values()
            for keys in periods.values() for key in keys
        }
        self.assertEqual(included, {"shared", "solo"})
        self.assertEqual((self.directory / "summary_pubs.csv").read_bytes(), original_csv)

    def test_no_bibliography_keeps_summary_and_products_sections(self):
        with patch.object(report, "write_coauthor_network", side_effect=self.fake_network):
            tex = self.run_main("--coauthor-network", "--no-bibliography")
        self.assertEqual(re.findall(r"\\section(\*?)\{([^{}]+)\}", tex), [
            ("", "Summary"), ("", "Per-Investigator Products"),
        ])
        self.assertIn(r"\detokenize{annual report_v3_coauthors.pdf}", tex)

    def test_cleanup_retains_network_pdf(self):
        def fake_compile(*args, **kwargs):
            self.out.with_suffix(".pdf").touch()
            self.out.with_suffix(".log").write_text("compile diagnostics")
            (self.directory / "two.bbl").write_text(
                "\\bibitem{shared} A shared paper.\n\\bibitem{solo} A solo paper.\n"
            )

        with patch.object(report, "write_coauthor_network", side_effect=self.fake_network), \
                patch.object(report, "compile_latex", side_effect=fake_compile):
            self.run_main("--coauthor-network", "--compile", "--clean")
        self.assertTrue(self.network_path.read_bytes().startswith(b"%PDF-"))
        self.assertTrue(self.out.with_suffix(".pdf").exists())
        self.assertFalse(self.out.with_suffix(".log").exists())
        self.assertFalse((self.directory / "two.bbl").exists())


@unittest.skipUnless(importlib.util.find_spec("matplotlib"), "requires optional plots dependency")
class NetworkPdfTests(unittest.TestCase):
    def test_isolated_nodes_fit_axes_and_do_not_overlap_across_rows(self):
        from matplotlib.backends.backend_pdf import PdfPages
        from matplotlib.patches import Circle

        periods = report.build_periods(dt.date(2026, 1, 1), dt.date(2026, 12, 31))
        original_save = PdfPages.savefig
        for count in (1, 7):
            investigators = [(f"Investigator {i}", "Example") for i in range(count)]
            mapping = {inv: {1: [f"solo-{i}"]} for i, inv in enumerate(investigators)}
            inspected = []

            def inspect_and_save(pdf, figure, *args, inspected=inspected, **kwargs):
                for axes in figure.axes:
                    circles = [artist for artist in axes.patches if isinstance(artist, Circle)]
                    inspected.extend(circles)
                    xmin, xmax = sorted(axes.get_xlim())
                    ymin, ymax = sorted(axes.get_ylim())
                    for circle in circles:
                        x, y = circle.center
                        radius = circle.radius
                        self.assertGreaterEqual(x - radius, xmin)
                        self.assertLessEqual(x + radius, xmax)
                        self.assertGreaterEqual(y - radius, ymin)
                        self.assertLessEqual(y + radius, ymax)
                    for index, left in enumerate(circles):
                        for right in circles[index + 1:]:
                            self.assertGreaterEqual(
                                math.dist(left.center, right.center), left.radius + right.radius,
                            )
                return original_save(pdf, figure, *args, **kwargs)

            with self.subTest(investigators=count), TemporaryDirectory() as temporary_dir, \
                    patch.object(PdfPages, "savefig", new=inspect_and_save):
                network.write_coauthor_network(
                    path=Path(temporary_dir) / "network.pdf", investigators=investigators,
                    periods=periods, inv_to_period_keys=mapping,
                )
                self.assertEqual(len(inspected), count)

    def test_network_and_empty_cases_render_single_page_vector_pdfs(self):
        periods = report.build_periods(dt.date(2026, 1, 1), dt.date(2026, 12, 31))
        investigators = [("Jane", "Doe"), ("John", "Roe"), ("Zero", "Papers")]
        for roster, mapping in (
            (investigators, {investigators[0]: {1: ["shared"]},
                            investigators[1]: {1: ["shared"]}}),
            (investigators, {}),
            ([], {}),
        ):
            with self.subTest(roster=roster, mapping=mapping), \
                    TemporaryDirectory() as temporary_dir:
                path = Path(temporary_dir) / "network.pdf"
                network.write_coauthor_network(
                    path=path, investigators=roster, periods=periods,
                    inv_to_period_keys=mapping,
                )
                pdf = path.read_bytes()
                self.assertTrue(pdf.startswith(b"%PDF-"))
                self.assertEqual(len(re.findall(rb"/Type\s*/Page\b", pdf)), 1)


if __name__ == "__main__":
    unittest.main()
