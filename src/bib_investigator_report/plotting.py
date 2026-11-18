"""Shared font choices for optional Matplotlib figures, without eager imports."""

from __future__ import annotations

PLOT_FONTS = ("default", "computer-modern")


def plot_font_family(plot_font: str, *, bold: bool = False) -> list[str]:
    """Select Matplotlib's bundled fonts, including Computer Modern's bold face."""
    if plot_font == "default":
        return ["DejaVu Sans"]
    if plot_font == "computer-modern":
        # The bundled roman and bold faces have separate family names. A serif
        # fallback retains characters outside Computer Modern's limited glyph set
        # on Matplotlib backends that support per-character font fallback.
        return ["cmb10" if bold else "cmr10", "DejaVu Serif"]
    raise ValueError(f"Unknown plot font: {plot_font!r}")


def plot_rc_params(plot_font: str) -> dict:
    """Keep rendering independent of TeX and contain settings in rc_context."""
    settings = {"pdf.fonttype": 42, "text.usetex": False}
    if plot_font == "computer-modern":
        settings["mathtext.fontset"] = "cm"
    return settings
