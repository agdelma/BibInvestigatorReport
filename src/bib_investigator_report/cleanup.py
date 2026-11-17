"""Remove known build artifacts belonging to a generated report."""

from __future__ import annotations

import re
from collections.abc import Iterable
from pathlib import Path

MAIN_EXTENSIONS = (
    "aux", "bbl", "blg", "log", "out", "toc", "lof", "lot",
    "fls", "fdb_latexmk", "synctex", "synctex.gz",
)
BIBLIOGRAPHY_EXTENSIONS = ("aux", "bbl", "blg")
_SUFFIX_PATTERN = re.compile(
    r"(?:one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|"
    r"thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|y\d{2,})"
    r"(?:full|partial|nosupport)?"
)


def collect_latex_suffixes(tex_path: Path) -> set[str]:
    r"""Find multibib namespaces recorded by this report's previous build.

    Call before overwriting the report's TeX source. Its ``\newcites``
    declarations and recorder file can identify artifacts from an older date
    range or support grouping. Only generated suffix names in the same output
    directory qualify; unrelated recorder paths are never cleanup targets.
    """
    suffixes: set[str] = set()
    try:
        tex = tex_path.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        tex = ""
    for match in re.finditer(r"^\s*\\newcites\{([^{}]+)\}", tex, re.MULTILINE):
        suffix = match.group(1)
        if _SUFFIX_PATTERN.fullmatch(suffix):
            suffixes.add(suffix)

    try:
        recorder = tex_path.with_suffix(".fls").read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return suffixes

    output_dir = tex_path.parent.resolve()
    for line in recorder.splitlines():
        if not line.startswith("OUTPUT "):
            continue
        recorded_path = Path(line[len("OUTPUT "):].strip())
        if not recorded_path.is_absolute():
            recorded_path = output_dir / recorded_path
        # Compare parents, not the file target: unlinking a symlink must never
        # delete its target, even when the target is outside the output folder.
        if recorded_path.parent.resolve() != output_dir:
            continue
        if recorded_path.suffix.lstrip(".") not in BIBLIOGRAPHY_EXTENSIONS:
            continue
        if _SUFFIX_PATTERN.fullmatch(recorded_path.stem):
            suffixes.add(recorded_path.stem)
    return suffixes


def cleanup_latex_artifacts(
    tex_path: Path,
    *,
    year_suffixes: Iterable[str],
    previous_year_suffixes: Iterable[str] = (),
) -> list[Path]:
    """Remove exact report auxiliary paths and return the removed files.

    Call only after successful compilation and any requested Word export.
    Source files and final outputs are retained. Previous namespaces must come
    from ``collect_latex_suffixes``; no directory-wide glob is used. Symlinks
    are unlinked without following their targets, and directories are skipped.
    """
    suffixes = set(year_suffixes) | set(previous_year_suffixes)
    if any(not _SUFFIX_PATTERN.fullmatch(suffix) for suffix in suffixes):
        raise ValueError("Unexpected multibib suffix in cleanup request")

    paths = {
        tex_path.parent / f"{tex_path.stem}.{extension}"
        for extension in MAIN_EXTENSIONS
    }
    paths.update(
        tex_path.parent / f"{suffix}.{extension}"
        for suffix in suffixes
        for extension in BIBLIOGRAPHY_EXTENSIONS
    )
    removed: list[Path] = []
    for path in sorted(paths):
        if not (path.is_file() or path.is_symlink()):
            continue
        try:
            path.unlink()
        except FileNotFoundError:
            continue
        removed.append(path)
    return removed
