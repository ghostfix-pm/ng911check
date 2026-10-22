"""Turn findings into text, CSV rows and JSON. Pure: no file is opened here."""
import csv
import io
import json
from collections import Counter

from .model import SEVERITY

_ORDER = {SEVERITY.ERROR: 0, SEVERITY.WARNING: 1, SEVERITY.INFO: 2}
CSV_COLUMNS = ("check_id", "check_name", "family", "severity", "layer", "row", "nguid",
               "description", "x", "y")


def ordered(records):
    """Most severe first, then by check, layer and row, so a report reads the same each run."""
    return sorted(records, key=lambda r: (_ORDER[r.severity], r.check_id, r.source_layer,
                                          r.source_oid, r.description))


def counts(records):
    """{severity: n} for all three severities, zeros included."""
    c = Counter(r.severity for r in records)
    return {s: c.get(s, 0) for s in (SEVERITY.ERROR, SEVERITY.WARNING, SEVERITY.INFO)}


def by_check(records):
    """[(check_id, severity, n)] most severe first."""
    c = Counter((r.check_id, r.severity) for r in records)
    return sorted(((cid, sev, n) for (cid, sev), n in c.items()),
                  key=lambda t: (_ORDER[t[1]], t[0]))


def exit_status(records):
    """1 when any finding is an ERROR after the overrides, else 0."""
    return 1 if any(r.severity == SEVERITY.ERROR for r in records) else 0


def _xy(record, frame):
    if record.xy is None:
        return ("", "")
    x, y = frame.inverse(record.xy[0], record.xy[1])
    fmt = "%.7f" if frame.units == "degrees" else "%.3f"
    return (fmt % x, fmt % y)


def to_rows(records, frame):
    """One dict per finding, with coordinates back in the input file's own units."""
    rows = []
    for r in ordered(records):
        x, y = _xy(r, frame)
        rows.append({"check_id": r.check_id, "check_name": r.check_name, "family": r.family,
                     "severity": r.severity, "layer": r.source_layer, "row": r.source_oid,
                     "nguid": r.source_nguid, "description": r.description, "x": x, "y": y})
    return rows


def to_csv_text(rows):
    """The rows as CSV text (RFC 4180 quoting, LF line ends), header first."""
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(CSV_COLUMNS)
    for row in rows:
        writer.writerow([row[c] for c in CSV_COLUMNS])
    return buf.getvalue()


def to_json(rows, notices, summary):
    return json.dumps({"summary": summary, "notices": notices, "findings": rows},
                      indent=2, sort_keys=True)


def format_text(records, notices, settings_lines, tally_lines, input_lines, rollups, show):
    """The console report. `rollups` is a list of (title, [line, ...]) sections."""
    out = ["ng911check report", "-" * 68]
    out.extend(input_lines)
    out.append("")
    out.extend(settings_lines)
    if tally_lines:
        out.append("Override effects on this run:")
        out.extend(tally_lines)
    if notices:
        out.append("")
        out.extend("NOTICE: " + n for n in notices)
    c = counts(records)
    out.append("")
    out.append("Findings: %d ERROR, %d WARNING, %d INFO" % (
        c[SEVERITY.ERROR], c[SEVERITY.WARNING], c[SEVERITY.INFO]))
    for cid, sev, n in by_check(records):
        out.append("  %-18s %-8s %d" % (cid, sev, n))
    for title, lines in rollups:
        out.append("")
        out.append(title)
        out.extend(lines)
    shown = ordered(records)[:show]
    if shown:
        out.append("")
        out.append("First %d finding(s), most severe first:" % len(shown))
        for r in shown:
            out.append("  %-7s %-10s %s row %d: %s" % (r.severity, r.check_id, r.source_layer,
                                                       r.source_oid, r.description))
        rest = len(records) - len(shown)
        if rest > 0:
            out.append("  ... %d more. Write them all with --out FILE --apply." % rest)
    return "\n".join(out)
