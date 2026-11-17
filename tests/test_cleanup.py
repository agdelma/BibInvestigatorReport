"""Cleanup deletes only build artifacts owned by the requested report."""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from bib_investigator_report.cleanup import (
    MAIN_EXTENSIONS,
    cleanup_latex_artifacts,
    collect_latex_suffixes,
)


class CleanupTests(unittest.TestCase):
    def test_removes_artifacts_and_preserves_inputs_outputs_and_unrelated_files(self):
        with TemporaryDirectory() as temporary_dir:
            directory = Path(temporary_dir)
            tex_path = directory / "report.v2.tex"
            artifacts = {f"report.v2.{extension}" for extension in MAIN_EXTENSIONS}
            artifacts.update({"one.aux", "one.bbl", "one.blg"})
            preserved = {
                "report.v2.tex", "report.v2.pdf", "report.v2.docx", "references.bib",
                "style.bst", "summary_pubs.csv", "other.aux", "other.log",
                "two.aux", "onefull.bbl", "one.pdf", "one.bib",
            }
            for name in artifacts | preserved:
                (directory / name).write_text("preserve contents", encoding="utf-8")

            removed = cleanup_latex_artifacts(tex_path, year_suffixes=["one"])

            self.assertEqual({path.name for path in removed}, artifacts)
            self.assertEqual({path.name for path in directory.iterdir()}, preserved)
            for name in preserved:
                self.assertEqual((directory / name).read_text(), "preserve contents")
            self.assertEqual(cleanup_latex_artifacts(tex_path, year_suffixes=["one"]), [])

    def test_previous_source_and_recorder_capture_stale_support_artifacts(self):
        with TemporaryDirectory() as temporary_dir:
            directory = Path(temporary_dir)
            tex_path = directory / "report.tex"
            tex_path.write_text(
                "\\newcites{one}{Year 01}\n"
                "\\newcites{y21partial}{\\phantom{.}}\n"
                "% \\newcites{twenty}{Year 20}\n"
                "\\newcites{unrelated}{Other}\n"
                "\\newcites{../three}{Unsafe}\n",
                encoding="utf-8",
            )
            (directory / "report.fls").write_text(
                "OUTPUT ./onefull.aux\n"
                "OUTPUT onenosupport.aux\n"
                f"OUTPUT {directory / 'twopartial.aux'}\n"
                "INPUT three.bbl\n"
                "OUTPUT unrelated.aux\n"
                "OUTPUT ../four.aux\n"
                "OUTPUT sub/five.aux\n"
                "OUTPUT six.pdf\n",
                encoding="utf-8",
            )
            old_suffixes = collect_latex_suffixes(tex_path)
            self.assertEqual(
                old_suffixes, {"one", "y21partial", "onefull", "onenosupport", "twopartial"}
            )

            # The new run has a shorter range and no support grouping.
            tex_path.write_text("\\newcites{one}{Year 01}\n", encoding="utf-8")
            for suffix in old_suffixes:
                for extension in ("aux", "bbl", "blg"):
                    (directory / f"{suffix}.{extension}").touch()
            removed = cleanup_latex_artifacts(
                tex_path, year_suffixes=["one"], previous_year_suffixes=old_suffixes,
            )
            self.assertEqual(len(removed), 1 + 3 * len(old_suffixes))
            self.assertEqual(list(directory.iterdir()), [tex_path])

    def test_missing_sources_and_artifacts_are_harmless(self):
        with TemporaryDirectory() as temporary_dir:
            tex_path = Path(temporary_dir) / "absent.tex"
            self.assertEqual(collect_latex_suffixes(tex_path), set())
            self.assertEqual(cleanup_latex_artifacts(tex_path, year_suffixes=["one"]), [])

    def test_symlinks_are_unlinked_without_deleting_their_targets(self):
        with TemporaryDirectory() as temporary_dir:
            directory = Path(temporary_dir)
            output_dir = directory / "output"
            output_dir.mkdir()
            source = directory / "source.txt"
            source.write_text("keep this", encoding="utf-8")
            (output_dir / "report.log").symlink_to(source)
            (output_dir / "one.bbl").symlink_to(source)
            (output_dir / "one.blg").symlink_to(directory / "absent.txt")
            (output_dir / "report.aux").mkdir()

            removed = cleanup_latex_artifacts(output_dir / "report.tex", year_suffixes=["one"])

            self.assertEqual({path.name for path in removed}, {"report.log", "one.bbl", "one.blg"})
            self.assertEqual(source.read_text(), "keep this")
            self.assertTrue((output_dir / "report.aux").is_dir())

    def test_rejects_path_traversal_before_removing_any_artifacts(self):
        with TemporaryDirectory() as temporary_dir:
            directory = Path(temporary_dir)
            artifact = directory / "report.log"
            artifact.touch()
            with self.assertRaises(ValueError):
                cleanup_latex_artifacts(directory / "report.tex", year_suffixes=["../one"])
            self.assertTrue(artifact.exists())


if __name__ == "__main__":
    unittest.main()
