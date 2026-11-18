"""Co-authorship counts and an optional, deterministic vector network figure."""

from __future__ import annotations

import math
import tempfile
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from itertools import combinations
from pathlib import Path
from typing import TYPE_CHECKING

from .colors import COLLABORATION_BLUE

if TYPE_CHECKING:
    from .report import Period


@dataclass(frozen=True)
class CoauthorNetwork:
    """Roster nodes and undirected, shared-paper edges in stable input order."""

    investigators: tuple[tuple[str, str], ...]
    node_totals: tuple[int, ...]
    edges: tuple[tuple[int, int, int], ...]
    unique_papers: int
    collaborative_papers: int


def build_coauthor_network(
    *,
    investigators: Sequence[tuple[str, str]],
    periods: Sequence[Period],
    inv_to_period_keys: dict[tuple[str, str], dict[int, list[str]]],
) -> CoauthorNetwork:
    """Count each included paper once per investigator and unordered pair.

    A paper with three roster investigators contributes one to all three pairs.
    Repeated roster names and repeated assignments do not multiply edge weights.
    Authors outside the supplied roster and unrequested periods are excluded.
    """
    roster = tuple(dict.fromkeys(investigators))
    paper_nodes: dict[str, set[int]] = {}
    totals = []
    for index, investigator in enumerate(roster):
        per_period = inv_to_period_keys.get(investigator, {})
        keys = {key for period in periods for key in per_period.get(period.index, [])}
        totals.append(len(keys))
        for key in keys:
            paper_nodes.setdefault(key, set()).add(index)
    pairs = Counter(
        pair for nodes in paper_nodes.values() for pair in combinations(sorted(nodes), 2)
    )
    return CoauthorNetwork(
        investigators=roster,
        node_totals=tuple(totals),
        edges=tuple((left, right, count) for (left, right), count in sorted(pairs.items())),
        unique_papers=len(paper_nodes),
        collaborative_papers=sum(len(nodes) > 1 for nodes in paper_nodes.values()),
    )


def _positions(np, nodes, edges):
    """A fixed-seed force layout; no optional graph-library dependency needed."""
    if not nodes:
        return {}
    if len(nodes) == 1:
        return {nodes[0]: (234.0, 210.0)}
    indices = {node: index for index, node in enumerate(nodes)}
    adjacency = np.zeros((len(nodes), len(nodes)))
    for left, right, weight in edges:
        if left in indices and right in indices:
            a, b = indices[left], indices[right]
            adjacency[a, b] = adjacency[b, a] = math.sqrt(weight)
    rng = np.random.default_rng(27)
    points = rng.uniform(-1, 1, (len(nodes), 2))
    distance_target = 1.0 / math.sqrt(len(nodes))
    for iteration in range(600):
        delta = points[:, None, :] - points[None, :, :]
        distances = np.maximum(np.linalg.norm(delta, axis=2), .01)
        forces = distance_target ** 2 / distances ** 2 - adjacency * distances / distance_target
        displacement = np.einsum('ijk,ij->ik', delta, forces)
        lengths = np.maximum(np.linalg.norm(displacement, axis=1), .01)
        temperature = .08 * (1 - iteration / 600)
        points += displacement * (temperature / lengths)[:, None]
        points -= points.mean(axis=0)
    # Fit independently to available width/height; this is a relationship diagram,
    # not a geographic map or quantitative position encoding.
    low, high = points.min(axis=0), points.max(axis=0)
    points = (points - low) / np.maximum(high - low, .001)
    points = points * np.array((320.0, 250.0)) + np.array((74.0, 108.0))
    return {node: tuple(point) for node, point in zip(nodes, points)}


def _overlap(a, b):
    width = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    height = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    return width * height


def _place_labels(data, positions, radii, text_width):
    """Choose readable full-name labels while avoiding nodes and other labels."""
    rectangles, labels = [], {}
    # Place the largest labels first; all choices and tie-breaking are stable.
    order = sorted(positions, key=lambda node: (-data.node_totals[node], node))
    for node in order:
        first, last = data.investigators[node]
        lines = (first, f"{last} ({data.node_totals[node]})")
        lines = tuple(line for line in lines if line)
        width = max(text_width(line) for line in lines) + 5
        height = 21.0
        x, y = positions[node]
        radius = radii[node]
        candidates = []
        outward = math.atan2(y - 230, x - 234)
        for angle_index in range(16):
            angle = outward + (angle_index // 2 + 1) * (1 if angle_index % 2 else -1) * math.pi / 8
            for extra in (4, 12, 22):
                dx, dy = math.cos(angle), math.sin(angle)
                center_x = x + dx * (radius + extra + width / 2)
                center_y = y + dy * (radius + extra + height / 2)
                rectangle = (center_x - width / 2, center_y - height / 2,
                             center_x + width / 2, center_y + height / 2)
                # Keep labels in the graph's own region, clear of heading/footer.
                outside = (max(0, 4 - rectangle[0]) + max(0, rectangle[2] - 464)
                           + max(0, 88 - rectangle[1]) + max(0, rectangle[3] - 393))
                collisions = sum(_overlap(rectangle, old) for old in rectangles)
                for other, (ox, oy) in positions.items():
                    r = radii[other] + 2
                    collisions += _overlap(rectangle, (ox - r, oy - r, ox + r, oy + r))
                score = outside * 500 + collisions * 5 + extra + angle_index * .15
                candidates.append((score, rectangle, center_x, center_y))
        _, rectangle, center_x, center_y = min(candidates)
        rectangles.append(rectangle)
        labels[node] = (center_x, center_y, "\n".join(lines), rectangle)
    return labels


def write_coauthor_network(
    *,
    path: Path,
    investigators: Sequence[tuple[str, str]],
    periods: Sequence[Period],
    inv_to_period_keys: dict[tuple[str, str], dict[int, list[str]]],
) -> None:
    """Render a single-page vector figure, retaining unconnected roster members."""
    try:
        import numpy as np
        from matplotlib import rc_context
        from matplotlib.backends.backend_pdf import PdfPages
        from matplotlib.figure import Figure
        from matplotlib.font_manager import FontProperties
        from matplotlib.patches import Circle
        from matplotlib.textpath import TextPath
    except ImportError as exc:
        raise RuntimeError(
            "Co-authorship networks require Matplotlib. Install it with: "
            "pip install 'bib-investigator-report[plots]'"
        ) from exc

    data = build_coauthor_network(
        investigators=investigators, periods=periods, inv_to_period_keys=inv_to_period_keys,
    )
    connected = sorted({node for left, right, _ in data.edges for node in (left, right)})
    isolated = [node for node in range(len(data.investigators)) if node not in connected]
    # The layout's physical size preserves label readability in the usual report.
    # Extra isolated nodes use additional rows rather than being omitted.
    isolate_rows = math.ceil(len(isolated) / 3)
    isolates_top = 401 if connected else 160
    isolate_row_height = 44
    isolate_first_y = isolates_top + 55
    height = (
        isolate_first_y + (isolate_rows - 1) * isolate_row_height + 35
        if isolated else isolates_top + 35
    )
    ink, muted, blue, rule = '#1C2D3C', '#52616E', COLLABORATION_BLUE, '#E4E9ED'
    font = FontProperties(family='DejaVu Sans', size=8.5)

    def text_width(value):
        return TextPath((0, 0), value, prop=font).get_extents().width if value else 0

    positions = _positions(np, connected, data.edges)
    radius_scale = 18.5 / math.sqrt(max(data.node_totals, default=1) or 1)
    radii = {node: radius_scale * math.sqrt(data.node_totals[node]) for node in connected}
    labels = _place_labels(data, positions, radii, text_width)
    with rc_context({'pdf.fonttype': 42, 'text.usetex': False}):
        figure = Figure(figsize=(6.5, height / 72), facecolor='white')
        ax = figure.add_axes((0, 0, 1, 1))
        ax.set(xlim=(0, 468), ylim=(height, 0))
        ax.axis('off')

        def text(x, y, value, *, size=9, color=ink, **kwargs):
            return ax.text(x, y, value, fontsize=size, fontfamily='DejaVu Sans',
                           color=color, va='center', **kwargs)

        text(4, 14,
             f'{data.collaborative_papers} shared papers  /  {len(data.edges)} coauthor pairs  /  '
             f'{len(connected)} connected investigators', size=10, fontweight='bold')
        text(4, 38, 'Node area and (total): papers per investigator.', size=8.5, color=muted)
        text(4, 53, 'Line width and number: papers shared by that pair.', size=8.5, color=muted)
        if not connected:
            text(234, 115, 'No co-authored papers among the listed investigators.',
                 ha='center', size=11, color=muted)
        edge_label_boxes = []
        width_scale = min(1.05, 3.15 / max((edge[2] for edge in data.edges), default=1))
        for left, right, weight in data.edges:
            x1, y1 = positions[left]
            x2, y2 = positions[right]
            ax.plot((x1, x2), (y1, y2), color=blue, alpha=.38,
                    linewidth=.8 + width_scale * weight, zorder=1, solid_capstyle='round')
            # Place count labels away from node labels and near the edge midpoint.
            candidates = []
            for fraction in (.5, .35, .65, .25, .75):
                x, y = x1 + fraction * (x2 - x1), y1 + fraction * (y2 - y1)
                box = (x - 5, y - 5, x + 5, y + 5)
                penalty = sum(_overlap(box, label[3]) for label in labels.values())
                penalty += sum(_overlap(box, old) for old in edge_label_boxes)
                for node, (nx, ny) in positions.items():
                    r = radii[node] + 3
                    penalty += _overlap(box, (nx - r, ny - r, nx + r, ny + r))
                candidates.append((penalty, abs(fraction - .5), x, y))
            _, _, x, y = min(candidates)
            edge_label_boxes.append((x - 6, y - 6, x + 6, y + 6))
            text(x, y, str(weight), ha='center', size=8, color=blue, zorder=4,
                 bbox={'boxstyle': 'round,pad=.14', 'facecolor': 'white', 'edgecolor': 'none'})
        for node in connected:
            x, y = positions[node]
            ax.add_patch(Circle((x, y), radii[node], facecolor=blue, alpha=.88,
                                edgecolor='white', linewidth=.8, zorder=3))
            tx, ty, label, _ = labels[node]
            text(tx, ty, label, ha='center', multialignment='center', linespacing=1.15,
                 size=8.5, zorder=5,
                 bbox={'facecolor': 'white', 'edgecolor': 'none', 'pad': .6, 'alpha': .9})
        if isolated:
            ax.plot((4, 464), (isolates_top, isolates_top), color=rule, linewidth=.7)
            text(4, isolates_top + 12, 'No shared papers with another listed investigator', size=9,
                 fontweight='bold')
            text(464, isolates_top + 24, 'Hollow circle: no included papers',
                 size=7.5, color=muted, ha='right')
            for index, node in enumerate(isolated):
                column, row = index % 3, index // 3
                x, y = 24 + column * 155, isolate_first_y + row * isolate_row_height
                total = data.node_totals[node]
                radius = radius_scale * math.sqrt(total) if total else 4.2
                ax.add_patch(Circle((x, y), radius, facecolor=blue if total else 'white',
                                    edgecolor=blue if total else '#89949D',
                                    linewidth=.8, alpha=.88))
                first, last = data.investigators[node]
                text(x + radius + 7, y, f'{first}\n{last} ({total})', size=8.5,
                     linespacing=1.15)
        text(4, height - 10,
             'Included papers only; authors outside the investigator roster are not shown.',
             size=8, color=muted)
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(suffix='.pdf', prefix='.bibreport-network-',
                                         dir=path.parent, delete=False) as temporary_file:
            temporary = Path(temporary_file.name)
        try:
            with PdfPages(temporary) as pdf:
                pdf.savefig(figure)
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
            figure.clear()
