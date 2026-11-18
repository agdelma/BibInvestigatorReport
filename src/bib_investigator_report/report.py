r"""Generate a LaTeX report of BibTeX citations per investigator per project-year.

Inputs:
  1) BibTeX (.bib) file
  2) Investigators CSV (at minimum: Firstname, Lastname)
  3) --start-date=YYYY-MM-DD
  4) --end-date=YYYY-MM-DD

Output:
  - A .tex file organized by investigator and project-year.
  - A summary_pubs.csv file (investigators x years) with BibTeX keys per cell.

Project-year definition:
  Year 01 is the 12-month period starting at --start-date.
  Year 02 is the next 12-month period, etc, until --end-date.

Inclusion logic:
  A BibTeX entry is included for an investigator in a project-year if:
    - the investigator's name matches an author in the BibTeX 'author' field, AND
    - the inferred entry date falls inside that project-year.

Date inference:
  An explicit 'date-added' field is authoritative, even if other dates disagree.
  If it is empty or unparseable, the entry is omitted with a diagnostic.
  Only when 'date-added' is absent, this script tries, in order:
    1) 'date' field (ISO formats: YYYY, YYYY-MM, YYYY-MM-DD)
    2) 'year' + 'month' fields
    3) fallback: mid-year (July 1) for the given 'year'

You can force a particular field via --date-field.

LaTeX generation:
  - Uses \usepackage{multibib}.
  - Creates one bibliography per project-year via \newcites{one}{Year 01}, ...
  - Color-codes each citation by how many investigators from your CSV are on that paper:
      1 investigator: black
      2 investigators: blue
      3+ investigators: orange

PDF compilation:
  If --compile is set, the script runs pdflatex + bibtex (for each multibib aux) + pdflatex twice.

Notes on BibTeX parsing:
  This script includes a lightweight, dependency-free BibTeX parser. If you have
  pybtex or bibtexparser installed, it can be extended, but this version does not
  require external libraries.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import html
import re
import shutil
import subprocess
import sys
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from pathlib import Path

from .cleanup import cleanup_latex_artifacts, collect_latex_suffixes
from .colors import COLLABORATION_BLUE
from .network import write_coauthor_network
from .summary import write_dot_summary

try:
    from docx import Document
except ImportError:
    Document = None


# ----------------------------
# Utilities: dates
# ----------------------------


def parse_iso_date(s: str) -> dt.date | None:
    """Parse YYYY, YYYY-MM, or YYYY-MM-DD into a date.

    - YYYY -> July 1 of that year
    - YYYY-MM -> 15th of that month
    - YYYY-MM-DD -> exact
    - Invalid calendar dates or timestamps -> None
    """
    s = s.strip()
    if not s:
        return None
    s = s.replace("/", "-")
    # BibDesk/Zotero exports may include a time and timezone. Reporting uses
    # the written calendar date, without shifting it to a different timezone.
    timestamp = re.fullmatch(
        r"(\d{4}-\d{2}-\d{2})[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?"
        r"(?:\s*(?:Z|UTC|GMT|[+-]\d{2}:?\d{2}))?",
        s,
    )
    if timestamp:
        # Normalize export timezone spellings for Python 3.9's ISO parser.
        value = re.sub(r"\s*(?:Z|UTC|GMT)$", "+00:00", s)
        value = re.sub(r"\s+([+-]\d{2}:?\d{2})$", r"\1", value)
        value = re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", value)
        try:
            return dt.datetime.fromisoformat(value).date()
        except ValueError:
            return None

    m = re.fullmatch(r"(\d{4})(?:-(\d{1,2})(?:-(\d{1,2}))?)?", s)
    if m:
        y = int(m.group(1))
        mo = int(m.group(2)) if m.group(2) is not None else 7
        d = int(m.group(3)) if m.group(3) is not None else (15 if m.group(2) else 1)
        try:
            return dt.date(y, mo, d)
        except ValueError:
            return None
    return None


def add_years(d: dt.date, years: int) -> dt.date:
    """Add years to a date, clamping Feb 29 to Feb 28 as needed."""
    try:
        return d.replace(year=d.year + years)
    except ValueError:
        return d.replace(month=2, day=28, year=d.year + years)


@dataclass(frozen=True)
class Period:
    index: int
    start: dt.date  # inclusive
    end: dt.date    # exclusive

    @property
    def label(self) -> str:
        return f"Year {self.index:02d}"


def build_periods(start: dt.date, end_inclusive: dt.date) -> list[Period]:
    periods: list[Period] = []
    idx = 1
    cur = start
    end_exclusive = end_inclusive + dt.timedelta(days=1)
    while cur < end_exclusive:
        nxt = add_years(cur, 1)
        periods.append(Period(index=idx, start=cur, end=min(nxt, end_exclusive)))
        cur = nxt
        idx += 1
    return periods


# ----------------------------
# Utilities: BibTeX parsing
# ----------------------------


def _split_top_level(s: str, sep: str = ",") -> list[str]:
    """Split on sep at brace depth 0 and outside quotes."""
    parts: list[str] = []
    buf: list[str] = []
    depth = 0
    in_quotes = False
    escape = False

    for ch in s:
        if escape:
            buf.append(ch)
            escape = False
            continue
        if ch == "\\":
            buf.append(ch)
            escape = True
            continue
        if ch == '"' and depth == 0:
            in_quotes = not in_quotes
            buf.append(ch)
            continue

        if ch == "{":
            depth += 1
        elif ch == "}":
            depth = max(0, depth - 1)
        if ch == sep and depth == 0 and not in_quotes:
            part = "".join(buf).strip()
            if part:
                parts.append(part)
            buf = []
            continue

        buf.append(ch)

    tail = "".join(buf).strip()
    if tail:
        parts.append(tail)
    return parts


def _strip_enclosing(value: str) -> str:
    value = value.strip()
    if value.endswith(","):
        value = value[:-1].rstrip()
    if len(value) >= 2 and (
        (value[0] == "{" and value[-1] == "}") or (value[0] == '"' and value[-1] == '"')
    ):
        value = value[1:-1].strip()
    return value


@dataclass
class BibEntry:
    key: str
    entry_type: str
    fields: dict[str, str]
    raw: str

    def get(self, field: str, default: str = "") -> str:
        return self.fields.get(field.lower(), default)


@dataclass
class BibParseDiagnostics:
    """Account for source records, including records that cannot be returned."""

    total_records: int = 0
    skipped_records: list[tuple[str, str]] = dataclass_field(default_factory=list)
    warnings: list[tuple[str, str]] = dataclass_field(default_factory=list)


def _print_bib_error(msg: str, raw: str) -> None:
    sys.stderr.write("\n" + "=" * 88 + "\n")
    sys.stderr.write(msg.rstrip() + "\n")
    sys.stderr.write("-" * 88 + "\n")
    sys.stderr.write(raw.rstrip() + "\n")
    sys.stderr.write("=" * 88 + "\n")


def _bibtex_entry_end(text: str, opening: int, *, comment: bool = False) -> int | None:
    """Find the closing delimiter, respecting braced and quoted field values."""
    closing = "}" if text[opening] == "{" else ")"
    depth = 0
    in_quotes = False
    escape = False
    for index in range(opening + 1, len(text)):
        char = text[index]
        if escape:
            escape = False
            continue
        if char == "\\":
            escape = True
        elif char == '"' and depth == 0 and not comment:
            in_quotes = not in_quotes
        elif char == "{":
            depth += 1
        elif char == "}" and depth > 0:
            depth -= 1
        elif char == closing and depth == 0 and not in_quotes:
            return index + 1
    return None


def parse_bibtex_file(
    path: Path, *, diagnostics: BibParseDiagnostics | None = None
) -> list[BibEntry]:
    """Parse a BibTeX file into entries.

    Malformed and duplicate records are counted and skipped. BibTeX directives
    (comment, preamble, string) are not bibliography records. Duplicate fields
    retain the first value, matching BibTeX's behavior.
    """
    text = path.read_text(encoding="utf-8", errors="replace")
    diagnostics = diagnostics if diagnostics is not None else BibParseDiagnostics()
    header = re.compile(r"@\s*([A-Za-z][A-Za-z0-9_-]*)\s*([({])")
    recovery_header = re.compile(r"^[ \t]*@\s*[A-Za-z][A-Za-z0-9_-]*\s*[({]", re.MULTILINE)
    i = 0
    entries: list[BibEntry] = []
    seen_keys = set()

    while i < len(text):
        match = header.search(text, i)
        if match is None:
            break
        at = match.start()
        # Ignore whole-line percent comments that contain entry-like examples.
        line_start = text.rfind("\n", 0, at) + 1
        if text[line_start:at].lstrip().startswith("%"):
            newline = text.find("\n", at)
            i = len(text) if newline == -1 else newline + 1
            continue
        entry_type = match.group(1).lower()
        opening = match.end() - 1
        is_directive = entry_type in {"comment", "preamble", "string"}
        end = _bibtex_entry_end(text, opening, comment=entry_type == "comment")
        if end is None:
            following = recovery_header.search(text, match.end())
            i = following.start() if following is not None else len(text)
        else:
            i = end
        raw_entry = text[at:i]
        if is_directive:
            if end is None:
                _print_bib_error(
                    f"BibTeX parse error: unterminated @{entry_type} directive.", raw_entry
                )
            continue

        diagnostics.total_records += 1
        content = text[opening + 1:i - 1] if end is not None else text[opening + 1:i]
        key_part, separator, body = content.partition(",")
        key = key_part.strip()
        line_number = text.count("\n", 0, at) + 1
        valid_key = key and not re.search(r"[\s{}()=]", key)
        key_label = key if valid_key else f"<record at line {line_number}>"
        try:
            if end is None:
                raise ValueError("unmatched braces/parentheses or unterminated quoted value")
            if not separator:
                raise ValueError("could not find key comma")
            if not key:
                raise ValueError("empty citation key")
            if key != key_label:
                raise ValueError("invalid citation key")
            if key in seen_keys:
                raise ValueError("duplicate citation key; keeping the first record")

            fields: dict[str, str] = {}
            for part in _split_top_level(body, sep=","):
                if "=" not in part:
                    raise ValueError(f"field is missing '=': {part!r}")
                name, val = part.split("=", 1)
                name = name.strip().lower()
                if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*", name):
                    raise ValueError(f"invalid field name: {name!r}")
                if not val.strip():
                    raise ValueError(f"field {name!r} has no value")
                val = _strip_enclosing(val)
                if name in fields:
                    diagnostics.warnings.append((
                        key,
                        f"duplicate field {name!r}; keeping first value {fields[name]!r}, "
                        f"ignoring {val!r}",
                    ))
                else:
                    fields[name] = val
            entries.append(BibEntry(key=key, entry_type=entry_type, fields=fields, raw=raw_entry))
            seen_keys.add(key)
        except Exception as ex:
            diagnostics.skipped_records.append((key_label, str(ex)))
            _print_bib_error(f"BibTeX parse error for record (key={key_label!r}): {ex}", raw_entry)

    return entries


# ----------------------------
# Utilities: name matching
# ----------------------------


def _strip_latex(s: str) -> str:
    if s is None:
        return ""
    s = s.replace(r"\i", "i").replace(r"\j", "j")
    s = re.sub(r"\\['`\"^~=.]\s*\{?([A-Za-z])\}?", r"\1", s)
    s = re.sub(r"\\[uvHc]\s*\{([A-Za-z])\}", r"\1", s)
    s = re.sub(r"[{}]", "", s)
    s = re.sub(r"\\[A-Za-z]+", "", s)
    s = s.replace("~", " ")
    return s


def _normalize_for_compare(s: str) -> str:
    s = _strip_latex(s)
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = s.lower()
    s = re.sub(r"[\s\.,\-\,\'`\"]+", "", s)
    return s


def _normalize_tokens(s: str) -> list[str]:
    s = _strip_latex(s)
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = s.replace("~", " ")
    s = re.sub(r"[^A-Za-z\s]", " ", s)
    return [t.lower() for t in s.split() if t.strip()]


def _parse_author_name(author: str) -> tuple[str, str]:
    author = author.strip()
    if not author:
        return "", ""
    if "," in author:
        last, first = author.split(",", 1)
        return last.strip(), first.strip()
    parts = author.split()
    if len(parts) == 1:
        return parts[0], ""
    return parts[-1], " ".join(parts[:-1])


def author_matches_investigator(author: str, inv_first: str, inv_last: str) -> bool:
    last, first = _parse_author_name(author)
    if _normalize_for_compare(last) != _normalize_for_compare(inv_last):
        return False

    inv_tokens = _normalize_tokens(inv_first)
    inv_full = "".join(inv_tokens)
    inv_initial = inv_full[0] if inv_full else ""

    auth_tokens = _normalize_tokens(first)
    auth_full = "".join(auth_tokens)

    if not auth_tokens:
        return True

    is_initials = all(len(t) == 1 for t in auth_tokens)
    if is_initials:
        return bool(inv_initial) and inv_initial == auth_tokens[0][0]

    if inv_full and auth_full:
        if inv_full == auth_full:
            return True
        if len(inv_full) >= 3 and auth_full.startswith(inv_full):
            return True
        if len(auth_full) >= 3 and inv_full.startswith(auth_full):
            return True

    return False


def entry_investigators(
    entry: BibEntry, investigators: Sequence[tuple[str, str]]
) -> list[tuple[str, str]]:
    author_field = entry.get("author", "")
    if not author_field:
        return []
    authors = re.split(r"\s+and\s+", author_field)
    matches: list[tuple[str, str]] = []
    for inv_first, inv_last in investigators:
        for a in authors:
            if author_matches_investigator(a, inv_first, inv_last):
                matches.append((inv_first, inv_last))
                break
    return matches


def sort_investigators(investigators: Sequence[tuple[str, str]]) -> list[tuple[str, str]]:
    return sorted(
        investigators,
        key=lambda inv: (_normalize_for_compare(inv[1]), _normalize_for_compare(inv[0])),
    )


# ----------------------------
# Date inference
# ----------------------------


def infer_entry_date(
    entry: BibEntry, *, date_field: str = "auto"
) -> tuple[dt.date | None, str]:
    """Infer a date and identify the fields that supplied it."""
    df = date_field.lower()

    def get_by_field(field: str) -> dt.date | None:
        v = entry.get(field, "")
        if not v:
            return None
        return parse_iso_date(v)

    if df != "auto":
        d = get_by_field(df)
        return d, df

    # Presence is authoritative: do not silently substitute publication dates
    # when an explicitly supplied date-added is empty or cannot be parsed.
    if "date-added" in entry.fields:
        return get_by_field("date-added"), "date-added"

    # Fallbacks apply only when date-added is absent.
    for field in ["date", "year-month", "year"]:
        if field == "year-month":
            y = entry.get("year", "").strip()
            mo = entry.get("month", "").strip()
            if y and mo:
                mo_norm = mo.lower().strip()
                month_map = {
                    "jan": 1,
                    "january": 1,
                    "feb": 2,
                    "february": 2,
                    "mar": 3,
                    "march": 3,
                    "apr": 4,
                    "april": 4,
                    "may": 5,
                    "jun": 6,
                    "june": 6,
                    "jul": 7,
                    "july": 7,
                    "aug": 8,
                    "august": 8,
                    "sep": 9,
                    "sept": 9,
                    "september": 9,
                    "oct": 10,
                    "october": 10,
                    "nov": 11,
                    "november": 11,
                    "dec": 12,
                    "december": 12,
                }
                mo_i: int | None
                try:
                    mo_i = (
                        int(re.sub(r"\D", "", mo_norm))
                        if re.search(r"\d", mo_norm) else month_map.get(mo_norm)
                    )
                except ValueError:
                    mo_i = None
                if mo_i and y.isdigit():
                    return dt.date(int(y), mo_i, 15), "year + month"
            continue

        d = get_by_field(field)
        if d is not None:
            return d, field

    y = entry.get("year", "").strip()
    if y.isdigit():
        return dt.date(int(y), 7, 1), "year"

    return None, df


def guess_entry_date(entry: BibEntry, *, date_field: str = "auto") -> dt.date | None:
    return infer_entry_date(entry, date_field=date_field)[0]


# ----------------------------
# Report data model
# ----------------------------


NUM_WORDS = {
    1: "one",
    2: "two",
    3: "three",
    4: "four",
    5: "five",
    6: "six",
    7: "seven",
    8: "eight",
    9: "nine",
    10: "ten",
    11: "eleven",
    12: "twelve",
    13: "thirteen",
    14: "fourteen",
    15: "fifteen",
    16: "sixteen",
    17: "seventeen",
    18: "eighteen",
    19: "nineteen",
    20: "twenty",
}


def suffix_for_year(year_index: int) -> str:
    word = NUM_WORDS.get(year_index)
    if word:
        return word
    return f"y{year_index:02d}"


def cite_command_for_suffix(suffix: str) -> str:
    return f"cite{suffix}"


SUPPORT_FULL = "full"
SUPPORT_PARTIAL = "partial"
SUPPORT_NOT_INCLUDED = "not_included"
SUPPORT_CATEGORIES = (SUPPORT_FULL, SUPPORT_PARTIAL, SUPPORT_NOT_INCLUDED)
SUPPORT_LABELS = {
    SUPPORT_FULL: "Full Support",
    SUPPORT_PARTIAL: "Partial Support",
    SUPPORT_NOT_INCLUDED: "Support Not Included",
}
SUPPORT_SUFFIX_PARTS = {
    SUPPORT_FULL: "full",
    SUPPORT_PARTIAL: "partial",
    SUPPORT_NOT_INCLUDED: "nosupport",
}


def color_for_investigator_count(n: int) -> str:
    if n <= 1:
        return "black"
    if n == 2:
        return "invBlue"
    return "invOrange"


def support_category_for_entry(entry: BibEntry) -> str:
    """Return the support grouping for a BibTeX entry.

    Use values such as support={full} or support={partial}. Missing or blank
    support fields are grouped separately so they can be fixed in the source .bib.
    """
    if "support" not in entry.fields or not entry.get("support", "").strip():
        return SUPPORT_NOT_INCLUDED
    raw = entry.get("support", "")
    normalized = re.sub(r"[^a-z]+", "", _strip_latex(raw).lower())
    if normalized.startswith("partial") or "partialsupport" in normalized:
        return SUPPORT_PARTIAL
    if normalized.startswith("full") or "fullsupport" in normalized:
        return SUPPORT_FULL
    return SUPPORT_NOT_INCLUDED


def suffix_for_support_category(year_index: int, support_category: str) -> str:
    return f"{suffix_for_year(year_index)}{SUPPORT_SUFFIX_PARTS[support_category]}"


def compute_assignments(
    *,
    entries: Sequence[BibEntry],
    investigators: Sequence[tuple[str, str]],
    periods: Sequence[Period],
    start_date: dt.date,
    end_date: dt.date,
    date_field: str,
) -> tuple[
    dict[str, dt.date],
    dict[str, list[tuple[str, str]]],
    dict[str, int],
    dict[tuple[str, str], dict[int, list[str]]],
]:
    """Compute mapping from investigators to period -> bib keys.

    Returns:
      entry_dates: key -> date
      entry_inv_matches: key -> list of investigators (first,last) on that paper
      entry_inv_count: key -> number of investigators on that paper
      inv_to_period_keys: inv -> period_index -> list of keys
    """

    entry_dates: dict[str, dt.date] = {}
    entry_inv_matches: dict[str, list[tuple[str, str]]] = {}
    entry_inv_count: dict[str, int] = {}

    for e in entries:
        try:
            d = guess_entry_date(e, date_field=date_field)
            if d is not None:
                entry_dates[e.key] = d
        except Exception as ex:
            _print_bib_error(f"Error inferring date for key={e.key!r}: {ex}", e.raw)

        try:
            matches = entry_investigators(e, investigators)
            entry_inv_matches[e.key] = matches
            entry_inv_count[e.key] = len(matches)
        except Exception as ex:
            _print_bib_error(f"Error matching investigators for key={e.key!r}: {ex}", e.raw)
            entry_inv_matches[e.key] = []
            entry_inv_count[e.key] = 0

    inv_to_period_keys: dict[tuple[str, str], dict[int, list[str]]] = {
        inv: {p.index: [] for p in periods} for inv in investigators
    }

    for e in entries:
        try:
            d = entry_dates.get(e.key)
            if d is None:
                continue
            if d < start_date or d > end_date:
                continue

            period_idx: int | None = None
            for p in periods:
                if p.start <= d < p.end:
                    period_idx = p.index
                    break
            if period_idx is None:
                continue

            matching_invs = entry_inv_matches.get(e.key, [])
            for inv in matching_invs:
                if inv in inv_to_period_keys:
                    inv_to_period_keys[inv][period_idx].append(e.key)
        except Exception as ex:
            _print_bib_error(f"Error processing record key={e.key!r}: {ex}", e.raw)
            continue

    # sort within each cell: date desc, then key
    for _inv, per_map in inv_to_period_keys.items():
        for _idx, keys in per_map.items():
            keys.sort(key=lambda k: (entry_dates.get(k, dt.date.min), k), reverse=True)

    return entry_dates, entry_inv_matches, entry_inv_count, inv_to_period_keys


def included_bib_keys(inv_to_period_keys) -> set[str]:
    return {
        key
        for per_map in inv_to_period_keys.values()
        for keys in per_map.values()
        for key in keys
    }


def print_report_diagnostics(
    *, entries, diagnostics, entry_dates, entry_inv_matches, inv_to_period_keys,
    start_date: dt.date, end_date: dt.date, date_field: str,
) -> None:
    """Account for every input record, counting shared publications only once."""
    included = included_bib_keys(inv_to_period_keys)
    print(
        f"BibTeX records: {diagnostics.total_records} "
        f"(parsed: {len(entries)}; skipped: {len(diagnostics.skipped_records)})"
    )
    print(f"Included in report: {len(included)} unique records")
    print(f"Not included in report: {diagnostics.total_records - len(included)} records")
    for key, reason in diagnostics.skipped_records:
        print(f"  - {key}: {reason}")
    for entry in entries:
        if entry.key in included:
            continue
        reasons = []
        date = entry_dates.get(entry.key)
        if date is None:
            if date_field.lower() == "auto" and "date-added" in entry.fields:
                reasons.append(
                    f"no usable authoritative date-added value {entry.get('date-added')!r}; "
                    "other date fields ignored"
                )
            else:
                reasons.append(f"no usable date (--date-field={date_field})")
        elif not start_date <= date <= end_date:
            _, source = infer_entry_date(entry, date_field=date_field)
            values = ", ".join(f"{field}={entry.get(field)!r}" for field in source.split(" + "))
            reasons.append(
                f"inferred date {date.isoformat()} from {source} ({values}) is outside "
                f"{start_date.isoformat()} through {end_date.isoformat()}"
            )
        if not entry_inv_matches.get(entry.key):
            reasons.append("no matching investigators in author field")
        if not reasons:
            reasons.append("not assigned to a project-year")
        print(f"  - {entry.key}: {'; '.join(reasons)}")
    if diagnostics.warnings:
        print("BibTeX warnings:")
        for key, reason in diagnostics.warnings:
            print(f"  - {key}: {reason}")


# ----------------------------
# CSV output
# ----------------------------


def write_summary_csv(
    *,
    path: Path,
    investigators: Sequence[tuple[str, str]],
    periods: Sequence[Period],
    inv_to_period_keys: dict[tuple[str, str], dict[int, list[str]]],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    header = ["Investigator"] + [p.label for p in periods]
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        for inv_first, inv_last in investigators:
            inv_name = f"{inv_first} {inv_last}".strip()
            row = [inv_name]
            per_map = inv_to_period_keys.get((inv_first, inv_last), {})
            for p in periods:
                keys = per_map.get(p.index, [])
                row.append("; ".join(keys))
            w.writerow(row)


# ----------------------------
# LaTeX generation
# ----------------------------


def latex_escape(s: str) -> str:
    """Escape a small set of LaTeX special chars for investigator names."""
    # Names typically do not include much, but do basic safety.
    repl = {
        "\\": r"\textbackslash{}",
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
    }
    out = []
    for ch in s:
        out.append(repl.get(ch, ch))
    return "".join(out)


def latex_citations_for_keys(
    *,
    keys: Sequence[str],
    year_index: int,
    entry_inv_count: dict[str, int],
    entries_by_key: dict[str, BibEntry],
    add_support: bool = False,
    highlight_full_support: bool = False,
) -> str:
    if not keys:
        return ""
    parts: list[str] = []
    for k in keys:
        c = color_for_investigator_count(entry_inv_count.get(k, 0))
        entry = entries_by_key.get(k)
        support = support_category_for_entry(entry) if entry is not None else SUPPORT_NOT_INCLUDED
        if add_support:
            cite_cmd = cite_command_for_suffix(suffix_for_support_category(year_index, support))
            cite = rf"\{cite_cmd}{{{k}}}"
        else:
            cite_cmd = cite_command_for_suffix(suffix_for_year(year_index))
            cite = rf"\{cite_cmd}{{{k}}}"
        if highlight_full_support and support == SUPPORT_FULL:
            cite = rf"\underline{{{cite}}}"
        parts.append(rf"\textcolor{{{c}}}{{{cite}}}")
    return ", ".join(parts)


def _format_author_for_reference(author: str) -> str:
    author = author.strip()
    if not author:
        return ""
    if "," not in author:
        return author
    last, first = _parse_author_name(author)
    if first:
        return f"{first} {last}".strip()
    return last


def _format_author_for_bibtex_with_bold(
    author: str,
    investigators: Sequence[tuple[str, str]],
) -> str:
    if not any(author_matches_investigator(author, first, last) for first, last in investigators):
        return author.strip()
    name = _format_author_for_reference(author)
    if not name:
        return author.strip()
    return rf"{{\textbf{{{name}}}}}"


def write_bibtex_with_bold_investigators(
    *,
    path: Path,
    entries: Sequence[BibEntry],
    investigators: Sequence[tuple[str, str]],
) -> None:
    lines: list[str] = []
    for entry in entries:
        lines.append(rf"@{entry.entry_type}{{{entry.key},")
        for field, value in entry.fields.items():
            out_value = value
            if field == "author":
                authors = re.split(r"\s+and\s+", value)
                out_value = " and ".join(
                    _format_author_for_bibtex_with_bold(author, investigators) for author in authors
                )
            lines.append(rf"  {field} = {{{out_value}}},")
        lines.append("}")
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def build_support_period_groups(
    *,
    entries: Sequence[BibEntry],
    periods: Sequence[Period],
    inv_to_period_keys: dict[tuple[str, str], dict[int, list[str]]],
) -> tuple[dict[int, dict[str, list[str]]], bool, bool]:
    entries_by_key = {entry.key: entry for entry in entries}
    period_grouped: dict[int, dict[str, list[str]]] = {
        p.index: {category: [] for category in SUPPORT_CATEGORIES} for p in periods
    }
    included_keys: set[str] = set()
    has_not_included = False

    for p in periods:
        period_keys: set[str] = set()
        for per_map in inv_to_period_keys.values():
            period_keys.update(per_map.get(p.index, []))
        for key in period_keys:
            entry = entries_by_key.get(key)
            if entry is None:
                continue
            support = support_category_for_entry(entry)
            if support == SUPPORT_NOT_INCLUDED:
                has_not_included = True
            period_grouped[p.index][support].append(key)
            included_keys.add(key)

    return period_grouped, bool(included_keys), has_not_included


def generate_support_bibliography(
    *,
    entries: Sequence[BibEntry],
    periods: Sequence[Period],
    inv_to_period_keys: dict[tuple[str, str], dict[int, list[str]]],
    bib_base: str,
    bibliography_style: str,
) -> str:
    period_grouped, has_included_keys, has_not_included = build_support_period_groups(
        entries=entries,
        periods=periods,
        inv_to_period_keys=inv_to_period_keys,
    )

    lines: list[str] = []
    lines.append(r"\clearpage")
    lines.append(r"\section*{References}")
    if not has_included_keys:
        lines.append("None")
        return "\n".join(lines)

    support_categories = list(SUPPORT_CATEGORIES)
    if not has_not_included:
        support_categories.remove(SUPPORT_NOT_INCLUDED)

    for p in periods:
        period_end = p.end - dt.timedelta(days=1)
        period_label = f"{p.label}: {p.start.isoformat()} -- {period_end.isoformat()}"
        lines.append(rf"\subsection*{{{period_label}}}")
        for category in support_categories:
            lines.append(rf"\subsubsection*{{{SUPPORT_LABELS[category]}}}")
            keys = period_grouped[p.index].get(category, [])
            if not keys:
                lines.append(r"\noindent None")
                lines.append("")
                continue
            suffix = suffix_for_support_category(p.index, category)
            lines.append(rf"\bibliographystyle{suffix}{{{bibliography_style}}}")
            lines.append(rf"\bibliography{suffix}{{{bib_base}}}")
            lines.append("")
    return "\n".join(lines)


def generate_summary_longtable(
    *,
    investigators: Sequence[tuple[str, str]],
    periods: Sequence[Period],
    inv_to_period_keys: dict[tuple[str, str], dict[int, list[str]]],
    entry_inv_count: dict[str, int],
    entries_by_key: dict[str, BibEntry],
    add_support: bool,
) -> str:
    year_totals: list[int] = []
    for p in periods:
        keys: set[str] = set()
        for per_map in inv_to_period_keys.values():
            keys.update(per_map.get(p.index, []))
        year_totals.append(len(keys))

    investigator_col = r">{\raggedright\arraybackslash}p{1.2in}"
    year_col = r">{\raggedright\arraybackslash}p{1.0in}"
    colspec_str = "@{}" + investigator_col + "".join(year_col for _ in periods) + "@{}"

    lines: list[str] = []
    lines.append(r"\subsection*{Summary Table}")
    lines.append(r"\scriptsize")
    lines.append(r"\setlength{\LTpre}{0pt}")
    lines.append(r"\setlength{\LTpost}{0pt}")
    lines.append(r"\renewcommand{\arraystretch}{1.25}")
    lines.append(r"\setlength\tabcolsep{4pt}")

    lines.append(rf"\begin{{longtable}}{{{colspec_str}}}")
    lines.append(r"\toprule")
    header_cells = ["Investigator"] + [f"{p.label} ({n})" for p, n in zip(periods, year_totals)]
    header_row = " & ".join(rf"\textbf{{{latex_escape(c)}}}" for c in header_cells) + r"\\"
    lines.append(header_row)
    lines.append(r"\midrule")
    lines.append(r"\endfirsthead")

    lines.append(r"\toprule")
    lines.append(header_row)
    lines.append(r"\midrule")
    lines.append(r"\endhead")

    for inv_first, inv_last in investigators:
        inv_name = latex_escape(f"{inv_first} {inv_last}".strip())
        per_map = inv_to_period_keys.get((inv_first, inv_last), {})
        row_cells: list[str] = [inv_name]
        for p in periods:
            keys = per_map.get(p.index, [])
            cites = latex_citations_for_keys(
                keys=keys,
                year_index=p.index,
                entry_inv_count=entry_inv_count,
                entries_by_key=entries_by_key,
                add_support=add_support,
            )
            row_cells.append(cites if cites else "")
        lines.append(" & ".join(row_cells) + r"\\")

    lines.append(r"\bottomrule")
    lines.append(r"\end{longtable}")
    lines.append(r"\normalsize")
    return "\n".join(lines)


def generate_tex(
    *,
    entries: Sequence[BibEntry],
    investigators: Sequence[tuple[str, str]],
    periods: Sequence[Period],
    start_date: dt.date,
    end_date: dt.date,
    bib_resource_filename: str,
    inv_to_period_keys: dict[tuple[str, str], dict[int, list[str]]],
    entry_dates: dict[str, dt.date],
    entry_inv_count: dict[str, int],
    include_bibliography: bool,
    bibliography_style: str,
    add_support: bool,
    annual_report: bool,
    summary_style: str = "table",
    summary_filename: str | None = None,
    summary_pages: int = 1,
    network_filename: str | None = None,
) -> str:
    if summary_style not in {"table", "dots"}:
        raise ValueError(f"Unknown summary style: {summary_style}")
    if summary_style == "dots" and (not summary_filename or summary_pages < 1):
        raise ValueError("A dot summary requires a PDF filename and at least one page")
    bib_base = Path(bib_resource_filename).stem
    entries_by_key = {entry.key: entry for entry in entries}

    # Precompute total pubs per investigator (unique keys across all periods)
    inv_total: dict[tuple[str, str], int] = {}
    for inv in investigators:
        per_map = inv_to_period_keys.get(inv, {})
        s: set[str] = set()
        for keys in per_map.values():
            s.update(keys)
        inv_total[inv] = len(s)

    # Preamble
    lines: list[str] = []
    lines.append(r"\documentclass[11pt]{article}")
    lines.append(r"\usepackage[margin=1in]{geometry}")
    lines.append(r"\usepackage[hidelinks]{hyperref}")
    lines.append(r"\usepackage{xcolor}")
    lines.append(rf"\definecolor{{invBlue}}{{HTML}}{{{COLLABORATION_BLUE.lstrip('#')}}}")
    lines.append(r"\definecolor{invOrange}{RGB}{255,130,0}")
    lines.append(r"\usepackage{array}")
    lines.append(r"\usepackage{longtable}")
    if summary_style == "dots" or network_filename:
        lines.append(r"\usepackage{graphicx}")
    lines.append(r"""
% -------------------------------------------------------------------------------   
% Tables
% -------------------------------------------------------------------------------   
\usepackage{booktabs}

% this improves table legibility
\AtBeginDocument{%
\heavyrulewidth=.08em
\lightrulewidth=.05em
\cmidrulewidth=.03em
\belowrulesep=.65ex
\belowbottomsep=0pt
\aboverulesep=.4ex
\abovetopsep=0pt
\cmidrulesep=\doublerulesep
\cmidrulekern=.5em
\defaultaddspace=.5em
}
% -------------------------------------------------------------------------------   
""")
    lines.append(r"\usepackage[numbers,sort&compress]{natbib}")
    if annual_report:
        lines.append(r"\renewcommand{\bibnumfmt}[1]{}")
        lines.append(r"\makeatletter")
        lines.append(r"\renewcommand{\@biblabel}[1]{}")
        lines.append(r"\makeatother")
    if add_support:
        lines.append(r"\usepackage{url}")
        lines.append(r"\providecommand{\doi}[1]{DOI: #1}")
        lines.append(r"\usepackage{multibib}")
    else:
        lines.append(r"\usepackage{multibib}")
    # Keep year/support headings within the final References section.
    if add_support:
        lines.append(r"\renewcommand{\bibsection}{}")
    else:
        lines.append(r"\renewcommand{\bibsection}{\subsection*{\refname}}")

    # multibib declarations: one per year, or one per year/support bucket.
    if add_support:
        for p in periods:
            for category in SUPPORT_CATEGORIES:
                suffix = suffix_for_support_category(p.index, category)
                lines.append(rf"\newcites{{{suffix}}}{{\phantom{{.}}}}")
    else:
        for p in periods:
            suffix = suffix_for_year(p.index)
            lines.append(rf"\newcites{{{suffix}}}{{{p.label}}}")

    lines.append("")
    lines.append(r"\begin{document}")
    lines.append("")
    lines.append(
        r"\noindent{\Large\bfseries IRG1 Investigator Publications by Project Year\par}"
    )
    lines.append(r"\medskip")
    lines.append(
        rf"\noindent Project date range: {start_date.isoformat()} $\to$ {end_date.isoformat()}\par"
    )
    lines.append(r"\section{Summary}")
    lines.append("")

    # Summary at top; citations remain in the investigator sections in either mode.
    if summary_style == "dots":
        lines.append(r"\medskip")
        for page in range(1, summary_pages + 1):
            lines.append(
                rf"\noindent\includegraphics[page={page},width=\linewidth,"
                rf"height=0.78\textheight,keepaspectratio]{{\detokenize{{{summary_filename}}}}}"
            )
            if page < summary_pages:
                lines.append(r"\clearpage")
    else:
        lines.append(
            r"\noindent Citation colors: black = 1 investigator on the paper, "
            r"\textcolor{invBlue}{blue = 2}, \textcolor{invOrange}{orange = 3+}.\par"
        )
        lines.append(generate_summary_longtable(
            investigators=investigators,
            periods=periods,
            inv_to_period_keys=inv_to_period_keys,
            entry_inv_count=entry_inv_count,
            entries_by_key=entries_by_key,
            add_support=add_support,
        ))
    lines.append("")
    if network_filename:
        lines.append(r"\clearpage")
        lines.append(r"\subsection*{Co-authorship Network}")
        lines.append(
            r"\noindent\includegraphics[width=\linewidth,height=0.82\textheight,"
            rf"keepaspectratio]{{\detokenize{{{network_filename}}}}}"
        )

    # Investigator sections
    lines.append(r"\clearpage")
    lines.append(r"\section{Per-Investigator Products}")
    lines.append(
        r"\noindent Citation colors: black = 1 investigator on the paper, "
        r"\textcolor{invBlue}{blue = 2}, \textcolor{invOrange}{orange = 3+}.\par\smallskip"
    )
    full_support_keys = {
        entry.key for entry in entries if support_category_for_entry(entry) == SUPPORT_FULL
    }
    if full_support_keys & included_bib_keys(inv_to_period_keys):
        lines.append(
            r"\noindent Full-support papers have underlined citation numbers "
            r"in the lists below.\par\smallskip"
        )
    for inv_first, inv_last in investigators:
        inv_name = latex_escape(f"{inv_first} {inv_last}".strip())
        total = inv_total.get((inv_first, inv_last), 0)
        lines.append(rf"\subsection*{{{inv_name} ({total})}}")
        lines.append(r"\begin{itemize}")

        per_map = inv_to_period_keys.get((inv_first, inv_last), {})
        for p in periods:
            keys = per_map.get(p.index, [])
            cites = latex_citations_for_keys(
                keys=keys,
                year_index=p.index,
                entry_inv_count=entry_inv_count,
                entries_by_key=entries_by_key,
                add_support=add_support,
                highlight_full_support=True,
            )
            if not cites:
                cites = "None"
            lines.append(rf"\item \textbf{{{p.label}:}} {cites}")

        lines.append(r"\end{itemize}")
        lines.append("")

    # Yearly bibliographies
    if include_bibliography:
        if add_support:
            lines.append(generate_support_bibliography(
                entries=entries,
                periods=periods,
                inv_to_period_keys=inv_to_period_keys,
                bib_base=bib_base,
                bibliography_style=bibliography_style,
            ))
        else:
            lines.append(r"\clearpage")
            lines.append(r"\section*{References}")
            lines.append("")
            for p in periods:
                suffix = suffix_for_year(p.index)
                lines.append(rf"\bibliographystyle{suffix}{{{bibliography_style}}}")
                lines.append(rf"\bibliography{suffix}{{{bib_base}}}")
                lines.append("")

    lines.append(r"\end{document}")
    return "\n".join(lines) + "\n"


def _strip_tex_braces(s: str) -> str:
    prev = None
    while prev != s:
        prev = s
        s = s.replace("{", "").replace("}", "")
    return s


def _latex_to_plain_text(s: str) -> str:
    """Best-effort cleanup of BibTeX-generated .bbl text for Word output."""
    s = s.replace("\n", " ")
    s = s.replace("~", " ")
    s = s.replace(r"\i", "i").replace(r"\j", "j")
    s = re.sub(r"\\['`\"^~=.]\s*\{?([A-Za-z])\}?", r"\1", s)
    s = re.sub(r"\\[uvHc]\s*\{([A-Za-z])\}", r"\1", s)

    s = re.sub(r"\\newblock\s*", " ", s)
    s = re.sub(r"\\url\{([^}]*)\}", r"\1", s)
    s = re.sub(r"\\doi\{([^}]*)\}", r"DOI: \1", s)
    s = re.sub(r"\\href\{[^}]*\}\{([^}]*)\}", r"\1", s)
    s = re.sub(r"\\emph\{([^}]*)\}", r"\1", s)
    s = re.sub(r"\\textit\{([^}]*)\}", r"\1", s)
    s = re.sub(r"\\textbf\{([^}]*)\}", r"\1", s)
    s = re.sub(r"\\textsc\{([^}]*)\}", r"\1", s)
    s = re.sub(r"\\enquote\{([^}]*)\}", r"\1", s)
    s = re.sub(r"\\[a-zA-Z]+\*?\s*", " ", s)

    s = _strip_tex_braces(s)
    s = s.replace("``", '"').replace("''", '"')
    s = s.replace(r"\&", "&").replace(r"\%", "%").replace(r"\_", "_")
    s = s.replace(r"\$", "$").replace(r"\#", "#")
    s = html.unescape(s)
    s = re.sub(r"\s+([,.;:])", r"\1", s)
    s = re.sub(r"\(\s+", "(", s)
    s = re.sub(r"\s+\)", ")", s)
    s = re.sub(r"\s{2,}", " ", s)
    return s.strip()


def _find_bibitem_key_end(text: str, start: int) -> tuple[str, int] | None:
    i = start
    n = len(text)
    while i < n and text[i].isspace():
        i += 1

    if i < n and text[i] == "[":
        depth = 1
        i += 1
        while i < n and depth > 0:
            if text[i] == "\\":
                i += 2
                continue
            if text[i] == "[":
                depth += 1
            elif text[i] == "]":
                depth -= 1
            i += 1
        while i < n and text[i].isspace():
            i += 1

    if i >= n or text[i] != "{":
        return None
    depth = 1
    key_start = i + 1
    i += 1
    while i < n and depth > 0:
        if text[i] == "\\":
            i += 2
            continue
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[key_start:i].strip(), i + 1
        i += 1
    return None


def parse_bbl_text(text: str) -> list[tuple[str, str]]:
    """Return [(bibkey, rendered_text), ...] from BibTeX-generated .bbl text."""
    entries: list[tuple[str, str]] = []
    matches: list[tuple[str, int, int]] = []
    for m in re.finditer(r"\\bibitem\b", text):
        parsed = _find_bibitem_key_end(text, m.end())
        if parsed is None:
            continue
        key, body_start = parsed
        matches.append((key, m.start(), body_start))

    for i, (key, _item_start, body_start) in enumerate(matches):
        end = matches[i + 1][1] if i + 1 < len(matches) else len(text)
        start = body_start
        body = text[start:end]
        body = re.sub(r"\\end\{thebibliography\}.*$", "", body, flags=re.DOTALL)
        rendered = _latex_to_plain_text(body)
        if rendered:
            entries.append((key, rendered))
    return entries


def parse_bbl_file(path: Path) -> list[tuple[str, str]]:
    """Return [(bibkey, rendered_text), ...] from a BibTeX-generated .bbl file."""
    text = path.read_text(encoding="utf-8", errors="replace")
    return parse_bbl_text(text)


def _docx_add_bibliography_items(
    doc: Document,
    items: Sequence[tuple[str, str]],
    *,
    numbered: bool,
) -> None:
    if not items:
        doc.add_paragraph("None")
        return
    style = "List Number" if numbered else None
    for _, rendered in items:
        doc.add_paragraph(rendered, style=style)


def _docx_add_expected_bibliography_items(
    doc: Document,
    items: Sequence[tuple[str, str]],
    expected_keys: Sequence[str],
    *,
    numbered: bool,
) -> None:
    if not expected_keys:
        doc.add_paragraph("None")
        return

    expected = set(expected_keys)
    filtered = [(key, rendered) for key, rendered in items if key in expected]
    if not filtered and items:
        filtered = list(items)

    if filtered:
        _docx_add_bibliography_items(doc, filtered, numbered=numbered)
        return

    doc.add_paragraph(f"Missing rendered bibliography entries: {', '.join(expected_keys)}")


def write_docx_from_bbl(
    *,
    path: Path,
    periods: Sequence[Period],
    tex_dir: Path,
    annual_report: bool,
) -> None:
    if Document is None:
        raise RuntimeError("python-docx is not available. Install it with: pip install python-docx")

    doc = Document()
    doc.add_heading("Yearly Bibliographies", level=1)

    for p in periods:
        suffix = suffix_for_year(p.index)
        bbl_path = tex_dir / f"{suffix}.bbl"
        doc.add_heading(p.label, level=2)

        if not bbl_path.exists():
            doc.add_paragraph(f"Missing bibliography file: {bbl_path.name}")
            continue

        items = parse_bbl_file(bbl_path)
        _docx_add_bibliography_items(doc, items, numbered=not annual_report)

    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(path)


def write_support_docx_from_bbl(
    *,
    path: Path,
    entries: Sequence[BibEntry],
    periods: Sequence[Period],
    inv_to_period_keys: dict[tuple[str, str], dict[int, list[str]]],
    tex_dir: Path,
    annual_report: bool,
) -> None:
    if Document is None:
        raise RuntimeError("python-docx is not available. Install it with: pip install python-docx")

    period_grouped, has_included_keys, has_not_included = build_support_period_groups(
        entries=entries,
        periods=periods,
        inv_to_period_keys=inv_to_period_keys,
    )
    support_categories = list(SUPPORT_CATEGORIES)
    if not has_not_included:
        support_categories.remove(SUPPORT_NOT_INCLUDED)

    doc = Document()
    doc.add_heading("Supported Publications", level=1)
    if not has_included_keys:
        doc.add_paragraph("None")
        path.parent.mkdir(parents=True, exist_ok=True)
        doc.save(path)
        return

    for p in periods:
        period_end = p.end - dt.timedelta(days=1)
        doc.add_heading(f"{p.label}: {p.start.isoformat()} -- {period_end.isoformat()}", level=2)
        for category in support_categories:
            doc.add_heading(SUPPORT_LABELS[category], level=3)
            expected_keys = period_grouped[p.index].get(category, [])
            if not expected_keys:
                doc.add_paragraph("None")
                continue
            suffix = suffix_for_support_category(p.index, category)
            bbl_path = tex_dir / f"{suffix}.bbl"
            if not bbl_path.exists():
                doc.add_paragraph(f"Missing bibliography file: {bbl_path.name}")
                continue
            items = parse_bbl_file(bbl_path)
            _docx_add_expected_bibliography_items(
                doc,
                items,
                expected_keys,
                numbered=not annual_report,
            )

    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(path)


# ----------------------------
# LaTeX compilation
# ----------------------------


def compile_latex(
    tex_path: Path, *, year_suffixes: Sequence[str], include_bibliography: bool
) -> None:
    """Compile LaTeX using pdflatex + bibtex (multibib) + pdflatex twice."""
    workdir = tex_path.parent

    bibtex_exe = shutil.which("bibtex")
    if bibtex_exe is None:
        # In some environments (including minimal TeXLive installs),
        # the bibtex symlink can be missing.
        bibtex_exe = shutil.which("bibtex.original") or "bibtex.original"

    # Clean old auxiliary and bibliography artifacts for deterministic builds
    stem = tex_path.stem
    for ext in ["aux", "bbl", "blg", "log", "out", "toc"]:
        try:
            (workdir / f"{stem}.{ext}").unlink()
        except FileNotFoundError:
            pass
    for suf in year_suffixes:
        for ext in ["aux", "bbl", "blg"]:
            try:
                (workdir / f"{suf}.{ext}").unlink()
            except FileNotFoundError:
                pass

    def run(cmd: Sequence[str]) -> None:
        proc = subprocess.run(
            cmd,
            cwd=str(workdir),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        if proc.returncode != 0:
            sys.stderr.write(proc.stdout)
            raise RuntimeError(f"Command failed: {' '.join(cmd)}")

    run(["pdflatex", "-interaction=nonstopmode", "-halt-on-error", tex_path.name])

    if include_bibliography:
        # multibib creates aux files named exactly '<suffix>.aux'
        for suf in year_suffixes:
            aux = workdir / f"{suf}.aux"
            if not aux.exists():
                continue
            # Only run bibtex if bibdata appears; otherwise bibtex fails noisily.
            try:
                content = aux.read_text(encoding="utf-8", errors="replace")
            except Exception:
                content = ""
            if "\\bibdata" not in content:
                continue
            if "\\citation" not in content:
                # No citations for this year; skip bibtex to avoid nonzero exit status.
                continue
            run([bibtex_exe, suf])

    run(["pdflatex", "-interaction=nonstopmode", "-halt-on-error", tex_path.name])
    run(["pdflatex", "-interaction=nonstopmode", "-halt-on-error", tex_path.name])


def verify_rendered_bibliographies(
    tex_path: Path, *, year_suffixes: Sequence[str], expected_keys: set[str]
) -> None:
    """Fail visibly if BibTeX did not render a selected publication."""
    rendered = set()
    for suffix in year_suffixes:
        bbl_path = tex_path.parent / f"{suffix}.bbl"
        if bbl_path.exists():
            rendered.update(key for key, _ in parse_bbl_file(bbl_path))
    missing = expected_keys - rendered
    if missing:
        raise RuntimeError(
            "Selected records missing from compiled bibliographies: "
            + ", ".join(sorted(missing))
            + ". LaTeX intermediate files have been retained for inspection."
        )
    print(f"Compiled bibliography: all {len(expected_keys)} selected records found")


# ----------------------------
# CLI
# ----------------------------


def load_investigators(csv_path: Path) -> list[tuple[str, str]]:
    """Load investigators from CSV.

    Required columns (case-insensitive):
      - Firstname (or: first, given, givenname, first_name, given_name)
      - Lastname  (or: last, family, familyname, surname, last_name, family_name)

    Returns list of (first,last) in file order.
    """
    with csv_path.open(newline="", encoding="utf-8", errors="replace") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            raise ValueError("Investigators CSV has no header row.")

        headers = [h.strip() for h in reader.fieldnames]
        header_map = {h.lower().strip(): h for h in headers}

        def find_col(candidates: Sequence[str]) -> str | None:
            for c in candidates:
                if c in header_map:
                    return header_map[c]
            return None

        first_col = find_col(
            ["firstname", "first", "given", "givenname", "first_name", "given_name"]
        )
        last_col = find_col(
            ["lastname", "last", "family", "familyname", "surname", "last_name", "family_name"]
        )
        if not first_col or not last_col:
            raise ValueError(
                f"Investigators CSV must contain first/last name columns. Found: {headers}"
            )

        out: list[tuple[str, str]] = []
        for row in reader:
            first = (row.get(first_col) or "").strip()
            last = (row.get(last_col) or "").strip()
            if not first and not last:
                continue
            out.append((first, last))
        return out


def main(argv: Sequence[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description=(
            "Generate a LaTeX report of citations per investigator per project-year (multibib)."
        )
    )
    p.add_argument("bib", type=Path, help="Input .bib file")
    p.add_argument("investigators", type=Path, help="Investigators CSV")
    p.add_argument("--start-date", required=True, help="YYYY-MM-DD")
    p.add_argument("--end-date", required=True, help="YYYY-MM-DD")
    p.add_argument(
        "--out", dest="out_tex", type=Path, default=Path("report.tex"), help="Output .tex file"
    )
    p.add_argument(
        "--summary-csv",
        dest="summary_csv",
        type=Path,
        default=None,
        help="Optional path for summary CSV (default: summary_pubs.csv next to --out).",
    )
    p.add_argument(
        "--summary-style",
        choices=("table", "dots"),
        default="table",
        help=(
            "Summary format: table (default) or a dot matrix with yearly publication bars. "
            "Dots writes a companion PDF and requires the optional plots dependency."
        ),
    )
    p.add_argument(
        "--coauthor-network",
        action="store_true",
        help=(
            "Include a co-authorship network of roster investigators in the Summary section. "
            "Writes a companion PDF and requires the optional plots dependency."
        ),
    )
    p.add_argument(
        "--date-field",
        default="auto",
        help=(
            "Which BibTeX field to use for dates: "
            "auto (default), date, date-added, year, month, etc. "
            "In auto mode, date-added is authoritative when present. "
            "If not auto, no fallback is used."
        ),
    )
    p.add_argument(
        "--bibliography-style",
        default="plain",
        help="BibTeX bibliography style to use for each year (default: plain).",
    )
    p.add_argument(
        "--no-bibliography",
        action="store_true",
        help=r"Do not include per-year bibliographies in the output TeX.",
    )
    p.add_argument(
        "--add-support",
        action="store_true",
        help=(
            "Use BibTeX support={full|partial} fields to generate a chronological "
            "support-grouped reference list with investigator authors bolded."
        ),
    )
    p.add_argument(
        "--annual-report",
        action="store_true",
        help="Suppress bibliography citation numbers for easier copy/paste into annual reports.",
    )
    p.add_argument(
        "--compile",
        action="store_true",
        help="Compile to PDF with pdflatex + bibtex (multibib).",
    )
    p.add_argument(
        "--clean",
        action="store_true",
        help=(
            "Remove this report's LaTeX intermediate files after successful compilation "
            "and optional Word export (requires --compile or --docx)."
        ),
    )
    p.add_argument(
        "--docx",
        action="store_true",
        help=(
            "Also write a .docx file containing only the rendered yearly bibliographies "
            "from the generated .bbl files."
        ),
    )
    p.add_argument(
        "--docx-out",
        dest="docx_out",
        type=Path,
        default=None,
        help="Optional path for .docx output (default: same stem as --out, with .docx suffix).",
    )

    args = p.parse_args(argv)
    if args.clean and not (args.compile or args.docx):
        p.error("--clean requires --compile or --docx")
    if args.docx and args.no_bibliography:
        p.error("--docx cannot be used with --no-bibliography")

    start = parse_iso_date(args.start_date)
    end = parse_iso_date(args.end_date)
    if start is None or end is None:
        raise ValueError("--start-date and --end-date must be valid ISO dates (YYYY-MM-DD).")
    if end < start:
        raise ValueError("--end-date must be >= --start-date")

    investigators = load_investigators(args.investigators)
    if not investigators:
        raise ValueError("No investigators found in CSV")
    investigators = sort_investigators(investigators)

    diagnostics = BibParseDiagnostics()
    entries = parse_bibtex_file(args.bib, diagnostics=diagnostics)
    periods = build_periods(start, end)

    entry_dates, entry_inv_matches, entry_inv_count, inv_to_period_keys = compute_assignments(
        entries=entries,
        investigators=investigators,
        periods=periods,
        start_date=start,
        end_date=end,
        date_field=args.date_field,
    )
    print_report_diagnostics(
        entries=entries,
        diagnostics=diagnostics,
        entry_dates=entry_dates,
        entry_inv_matches=entry_inv_matches,
        inv_to_period_keys=inv_to_period_keys,
        start_date=start,
        end_date=end,
        date_field=args.date_field,
    )

    out_tex = args.out_tex
    previous_year_suffixes = collect_latex_suffixes(out_tex) if args.clean else []
    out_tex.parent.mkdir(parents=True, exist_ok=True)

    # Copy or render a BibTeX file next to TeX output for compilation portability.
    if args.add_support:
        bib_dest = out_tex.parent / f"{args.bib.stem}_support{args.bib.suffix}"
    else:
        bib_dest = out_tex.parent / args.bib.name
    if args.add_support:
        write_bibtex_with_bold_investigators(
            path=bib_dest,
            entries=entries,
            investigators=investigators,
        )
    elif args.bib.resolve() != bib_dest.resolve():
        shutil.copy2(args.bib, bib_dest)

    # Write summary CSV
    summary_csv_path = args.summary_csv or (out_tex.parent / "summary_pubs.csv")
    write_summary_csv(
        path=summary_csv_path,
        investigators=investigators,
        periods=periods,
        inv_to_period_keys=inv_to_period_keys,
    )

    summary_pdf = None
    summary_pages = 1
    if args.summary_style == "dots":
        summary_pdf = out_tex.with_name(f"{out_tex.stem}_summary.pdf")
        summary_pages = write_dot_summary(
            path=summary_pdf,
            investigators=investigators,
            periods=periods,
            inv_to_period_keys=inv_to_period_keys,
            entry_inv_count=entry_inv_count,
        )

    network_pdf = None
    if args.coauthor_network:
        network_pdf = out_tex.with_name(f"{out_tex.stem}_coauthors.pdf")
        write_coauthor_network(
            path=network_pdf,
            investigators=investigators,
            periods=periods,
            inv_to_period_keys=inv_to_period_keys,
        )

    # Write TeX
    tex = generate_tex(
        entries=entries,
        investigators=investigators,
        periods=periods,
        start_date=start,
        end_date=end,
        bib_resource_filename=bib_dest.name,
        inv_to_period_keys=inv_to_period_keys,
        entry_dates=entry_dates,
        entry_inv_count=entry_inv_count,
        include_bibliography=not args.no_bibliography,
        bibliography_style=args.bibliography_style,
        add_support=args.add_support,
        annual_report=args.annual_report,
        summary_style=args.summary_style,
        summary_filename=summary_pdf.name if summary_pdf else None,
        summary_pages=summary_pages,
        network_filename=network_pdf.name if network_pdf else None,
    )
    out_tex.write_text(tex, encoding="utf-8")

    if args.add_support:
        year_suffixes = [
            suffix_for_support_category(p.index, category)
            for p in periods
            for category in SUPPORT_CATEGORIES
        ]
    else:
        year_suffixes = [suffix_for_year(p.index) for p in periods]

    if args.compile or args.docx:
        compile_latex(
            out_tex,
            year_suffixes=year_suffixes,
            include_bibliography=not args.no_bibliography,
        )
        if not args.no_bibliography:
            verify_rendered_bibliographies(
                out_tex,
                year_suffixes=year_suffixes,
                expected_keys=included_bib_keys(inv_to_period_keys),
            )

    if args.docx:
        if args.add_support:
            docx_path = args.docx_out or out_tex.with_suffix(".docx")
            write_support_docx_from_bbl(
                path=docx_path,
                entries=entries,
                periods=periods,
                inv_to_period_keys=inv_to_period_keys,
                tex_dir=out_tex.parent,
                annual_report=args.annual_report,
            )
        else:
            docx_path = args.docx_out or out_tex.with_suffix(".docx")
            write_docx_from_bbl(
                path=docx_path,
                periods=periods,
                tex_dir=out_tex.parent,
                annual_report=args.annual_report,
            )

    if args.clean:
        removed = cleanup_latex_artifacts(
            out_tex,
            year_suffixes=year_suffixes,
            previous_year_suffixes=previous_year_suffixes,
        )
        print(f"Cleaned {len(removed)} LaTeX intermediate files")

    print(f"Wrote LaTeX: {out_tex}")
    print(f"Wrote summary CSV: {summary_csv_path}")
    if summary_pdf is not None:
        print(f"Wrote summary figure: {summary_pdf}")
    if network_pdf is not None:
        print(f"Wrote co-authorship network: {network_pdf}")
    if args.compile or args.docx:
        print(f"Wrote PDF: {out_tex.with_suffix('.pdf')}")
    if args.docx:
        print(f"Wrote Word document: {docx_path}")

    return 0
