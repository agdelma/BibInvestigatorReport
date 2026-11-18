"""Optional vector-PDF summaries of the report's existing paper assignments."""

from __future__ import annotations

import math
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from .colors import COLLABORATION_BLUE

if TYPE_CHECKING:
    from .report import Period


@dataclass(frozen=True)
class DotSummary:
    """Counts and deduplicated cells in the supplied investigator/year order."""

    cell_keys: tuple[tuple[tuple[str, ...], ...], ...]
    year_category_counts: tuple[tuple[int, int, int], ...]
    investigator_totals: tuple[int, ...]
    unique_papers: int
    collaborative_papers: int


def _category(key: str, entry_inv_count: dict[str, int]) -> int:
    # Every assigned paper belongs to at least one roster investigator.
    return max(1, min(entry_inv_count.get(key, 1), 3))


def build_summary_data(
    *,
    investigators: Sequence[tuple[str, str]],
    periods: Sequence[Period],
    inv_to_period_keys: dict[tuple[str, str], dict[int, list[str]]],
    entry_inv_count: dict[str, int],
) -> DotSummary:
    """Count only included assignments, without adding coauthor duplicates."""
    cells = tuple(
        tuple(
            tuple(sorted(
                set(inv_to_period_keys.get(inv, {}).get(period.index, [])),
                key=lambda key: (_category(key, entry_inv_count), key),
            ))
            for period in periods
        )
        for inv in investigators
    )
    per_year = [
        {key for row in cells for key in row[column]}
        for column in range(len(periods))
    ]
    all_keys = {key for keys in per_year for key in keys}
    return DotSummary(
        cell_keys=cells,
        year_category_counts=tuple(
            tuple(sum(_category(key, entry_inv_count) == category for key in keys)
                  for category in (1, 2, 3))
            for keys in per_year
        ),
        investigator_totals=tuple(len({key for cell in row for key in cell}) for row in cells),
        unique_papers=len(all_keys),
        collaborative_papers=sum(_category(key, entry_inv_count) > 1 for key in all_keys),
    )


# Dimensions are points, so text and markers keep their size as the data grows.
_WIDTH = 468.0  # 6.5 inches, matching the report's US-letter text width.
_MAX_HEIGHT = 504.0
_LEFT = 4.0
_GRID_LEFT = 141.0
_GRID_RIGHT = 427.0
_TOTAL_X = 450.0
_BODY_TOP = 228.0
_FOOTER_HEIGHT = 34.0
_ROW_SPACE = _MAX_HEIGHT - _BODY_TOP - _FOOTER_HEIGHT
_YEARS_PER_PAGE = 5
_COLORS = ("#4F5965", COLLABORATION_BLUE, "#CB7725")
_MARKERS = ("o", "D", "s")
_INK, _MUTED, _RULE = "#1C2D3C", "#52616E", "#E4E9ED"


@dataclass(frozen=True)
class _Row:
    investigator: int
    name_lines: tuple[str, ...]
    cells: tuple[tuple[str, ...], ...]
    height: float


def _wrap_name(name, text_width):
    """Wrap at words (or characters for a long token), keeping the full name."""
    lines = []
    current = ""
    for word in name.split():
        candidate = f"{current} {word}".strip()
        if text_width(candidate) <= _GRID_LEFT - 15:
            current = candidate
            continue
        if current:
            lines.append(current)
        current = ""
        for character in word:
            if current and text_width(current + character) > _GRID_LEFT - 15:
                lines.append(current)
                current = character
            else:
                current += character
    if current or not lines:
        lines.append(current)
    return tuple(lines)


def _make_row_pages(data, investigators, column_indices, dots_per_line, text_width):
    """Wrap dense cells and split long rosters or a very dense row across pages."""
    pages, page, used = [], [], 0.0
    max_dot_lines = int((_ROW_SPACE - 7) // 8)
    max_dots = dots_per_line * max_dot_lines
    for index, investigator in enumerate(investigators):
        name_lines = _wrap_name(" ".join(investigator).strip(), text_width)
        cells = tuple(data.cell_keys[index][column] for column in column_indices)
        largest_cell = max((len(cell) for cell in cells), default=0)
        for offset in range(0, max(1, largest_cell), max_dots):
            fragment = tuple(cell[offset:offset + max_dots] for cell in cells)
            labels = name_lines + (("(continued)",) if offset else ())
            marker_lines = max(
                (math.ceil(len(cell) / dots_per_line) for cell in fragment), default=1
            )
            height = max(15, len(labels) * 10.5 + 4, marker_lines * 8 + 7)
            if height > _ROW_SPACE:
                raise ValueError("Investigator name is too long to fit on a summary page")
            if page and used + height > _ROW_SPACE:
                pages.append(page)
                page, used = [], 0.0
            page.append(_Row(index, labels, fragment, height))
            used += height
    if page or not pages:
        pages.append(page)
    return pages


def _draw_page(
    *, Figure, data, periods, investigators, entry_inv_count,
    columns, rows, dots_per_line, page_number, page_count,
):
    body_height = sum(row.height for row in rows)
    height = max(275, _BODY_TOP + body_height + _FOOTER_HEIGHT)
    fig = Figure(figsize=(_WIDTH / 72, height / 72), facecolor="white")
    ax = fig.add_axes((0, 0, 1, 1))
    ax.set(xlim=(0, _WIDTH), ylim=(height, 0))
    ax.axis("off")

    def text(x, y, value, *, size=9, color=_INK, **kwargs):
        return ax.text(x, y, value, fontsize=size, color=color, fontfamily="DejaVu Sans",
                       va="center", **kwargs)

    for x, value, label in (
        (_LEFT, data.unique_papers, "Unique papers"),
        (164, len(investigators), "Investigators in roster"),
        (319, f"{data.collaborative_papers}/{data.unique_papers}",
         "Papers with 2+ investigators"),
    ):
        text(x, 15, str(value), size=22, fontweight="bold")
        text(x, 34, label, size=8, color=_MUTED)
    ax.plot((_LEFT, _WIDTH - _LEFT), (47, 47), color=_RULE, linewidth=.7)
    text(_LEFT, 61, "Unique papers by project year", size=11, fontweight="bold")
    for x, marker, color, label in zip(
        (10, 145, 280), _MARKERS, _COLORS,
        ("1 investigator", "2 investigators", "3+ investigators"),
    ):
        ax.scatter(x, 77, s=22, marker=marker, color=color, linewidth=0)
        text(x + 12, 77, label, size=8.5)

    cell_width = (_GRID_RIGHT - _GRID_LEFT) / max(1, len(columns))
    centers = [_GRID_LEFT + (index + .5) * cell_width for index in range(len(columns))]
    totals = [sum(data.year_category_counts[column]) for column in columns]
    maximum = max((sum(counts) for counts in data.year_category_counts), default=0)
    chart_bottom, chart_height = 151, 53
    for center, column, total in zip(centers, columns, totals):
        cumulative, small_labels = 0, []
        bar_width = min(27, .36 * cell_width)
        for color, count in zip(_COLORS, data.year_category_counts[column]):
            segment_height = chart_height * count / max(1, maximum)
            top = chart_bottom - chart_height * (cumulative + count) / max(1, maximum)
            ax.bar(center, segment_height, width=bar_width, bottom=top,
                   color=color, linewidth=0)
            if count:
                midpoint = top + segment_height / 2
                if segment_height >= 10:
                    text(center, midpoint, str(count), size=8, color="white", ha="center")
                else:
                    small_labels.append((midpoint, count, color))
            cumulative += count
        # Outside labels retain exact small counts without overlapping thin segments.
        label_positions = []
        for midpoint, count, color in sorted(small_labels):
            label_y = max(midpoint, label_positions[-1][0] + 10 if label_positions else 0)
            label_positions.append((label_y, midpoint, count, color))
        overflow = max(0, label_positions[-1][0] - chart_bottom + 3) if label_positions else 0
        for label_y, midpoint, count, color in label_positions:
            label_y -= overflow
            end_x = center + bar_width / 2 + 8
            ax.plot((center + bar_width / 2 + 1, end_x), (midpoint, label_y),
                    color=color, linewidth=.6)
            text(end_x + 2, label_y, str(count), size=8)
        total_y = chart_bottom - chart_height * total / max(1, maximum) - 9
        text(center, total_y, str(total), size=10, ha="center", fontweight="bold")
        text(center, 164, periods[column].label, size=9, ha="center")
    if not columns:
        text(_GRID_LEFT, 124, "No project years", color=_MUTED)

    text(_LEFT, 187, "Papers by investigator", size=11, fontweight="bold")
    text(_LEFT, 202, "One marker = one paper", size=8.5, color=_MUTED)
    for center, column in zip(centers, columns):
        text(center, 216, periods[column].label, size=8.5, ha="center", fontweight="bold")
    text(_TOTAL_X, 216, "Total", size=8.5, ha="center", fontweight="bold")
    y = _BODY_TOP
    for row in rows:
        midpoint = y + row.height / 2
        text(_GRID_LEFT - 10, midpoint, "\n".join(row.name_lines), size=9, ha="right",
             multialignment="right", linespacing=1.15)
        text(_TOTAL_X, midpoint, str(data.investigator_totals[row.investigator]),
             size=9, ha="center", fontweight="bold")
        for center, cell in zip(centers, row.cells):
            if not cell:
                text(center, midpoint, "0", size=8.5, color="#89949D", ha="center")
                continue
            dot_lines = math.ceil(len(cell) / dots_per_line)
            for line in range(dot_lines):
                keys = cell[line * dots_per_line:(line + 1) * dots_per_line]
                dot_y = midpoint + (line - (dot_lines - 1) / 2) * 8
                for position, key in enumerate(keys):
                    category = _category(key, entry_inv_count) - 1
                    dot_x = center + (position - (len(keys) - 1) / 2) * 8
                    ax.scatter(dot_x, dot_y, s=20, marker=_MARKERS[category],
                               color=_COLORS[category], linewidth=0)
        y += row.height
        ax.plot((_GRID_LEFT, _GRID_RIGHT), (y, y), color=_RULE, linewidth=.4)
    if not rows:
        text(_LEFT, _BODY_TOP + 12, "No investigators", color=_MUTED)

    text(_LEFT, height - 22,
         "Shared papers appear in each investigator's row; yearly totals count them once.",
         size=7.8, color=_MUTED)
    text(_LEFT, height - 9,
         "Investigator totals cover all project years. "
         "Colors and shapes refer to roster investigators.",
         size=7.8, color=_MUTED)
    if page_count > 1:
        text(_WIDTH - _LEFT, 187, f"{page_number}/{page_count}", size=8, color=_MUTED,
             ha="right")
    return fig


def write_dot_summary(
    *,
    path: Path,
    investigators: Sequence[tuple[str, str]],
    periods: Sequence[Period],
    inv_to_period_keys: dict[tuple[str, str], dict[int, list[str]]],
    entry_inv_count: dict[str, int],
) -> int:
    """Write vector-PDF summary pages and return their count.

    Matplotlib is optional and imported only here. Long rosters, more than five
    years, or densely populated cells produce additional pages with readable
    labels and one marker per assigned paper. The caller embeds every page.
    """
    try:
        from matplotlib import rc_context
        from matplotlib.backends.backend_pdf import PdfPages
        from matplotlib.figure import Figure
        from matplotlib.font_manager import FontProperties
        from matplotlib.textpath import TextPath
    except ImportError as exc:
        raise RuntimeError(
            "Dot summaries require Matplotlib. Install it with: "
            "pip install 'bib-investigator-report[plots]'"
        ) from exc

    data = build_summary_data(
        investigators=investigators, periods=periods,
        inv_to_period_keys=inv_to_period_keys, entry_inv_count=entry_inv_count,
    )
    font = FontProperties(family="DejaVu Sans", size=9)

    def text_width(value):
        return TextPath((0, 0), value, prop=font).get_extents().width if value else 0

    panels = []
    for first in range(0, max(1, len(periods)), _YEARS_PER_PAGE):
        columns = list(range(first, min(first + _YEARS_PER_PAGE, len(periods))))
        cell_width = (_GRID_RIGHT - _GRID_LEFT) / max(1, len(columns))
        dots_per_line = max(1, int((cell_width - 12) // 8))
        for rows in _make_row_pages(data, investigators, columns, dots_per_line, text_width):
            panels.append((columns, rows, dots_per_line))

    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(suffix=".pdf", prefix=".bibreport-", dir=path.parent,
                                     delete=False) as temporary_file:
        temporary = Path(temporary_file.name)
    try:
        with rc_context({"pdf.fonttype": 42, "text.usetex": False}), PdfPages(temporary) as pdf:
            for number, (columns, rows, dots_per_line) in enumerate(panels, 1):
                figure = _draw_page(
                    Figure=Figure, data=data, periods=periods,
                    investigators=investigators, entry_inv_count=entry_inv_count,
                    columns=columns, rows=rows, dots_per_line=dots_per_line,
                    page_number=number, page_count=len(panels),
                )
                pdf.savefig(figure)
                figure.clear()
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
    return len(panels)
