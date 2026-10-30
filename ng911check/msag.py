"""MSAG load + reconciliation engine.

Treats the authoritative MSAG file as READ-ONLY. The CSV is parsed once into a normalized
in-memory list of records; reconciliation against GIS-derived MSAG records follows NENA 71-501
(bidirectional, range-containment). On top of that coverage match this module reports three
things the match rate alone hides:

  exact-tuple rate  the share of MSAG records whose extent equals one whole GIS run for the
                    same community, street, parity and ESN. Coverage can be met by a GIS run
                    that is wider than the MSAG record; this rate cannot.
  roll-up           the findings grouped by street, so one street's problems read as one row.
  source age        how many days old the MSAG file is, because a stale file makes any
                    match rate describe a world that no longer exists.

Pure Python 3 standard library. The reconcile/build/normalize helpers operate on plain dicts
so they are unit-testable without a spreadsheet or a geodatabase. Only the load_* functions
touch a file.
"""
import csv
import hashlib
import json
import os
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional

from .common import normalize, is_addressable

# Canonical MSAG field keys the engine reasons about.
CANONICAL_FIELDS = ("prefix", "street_name", "type", "suffix",
                    "low", "high", "community", "parity", "esn")
# Fields that MUST resolve to a real column for the file to be usable.
REQUIRED_FIELDS = ("street_name", "low", "high", "community", "parity", "esn")

# Tokens used to auto-detect the real header row when a banner sits above it.
HEADER_TOKENS = ("PREFIX", "STREET NAME", "TYPE", "SUFFIX",
                 "LOW", "HIGH", "COMMUNITY", "SIDE", "ESN")

DEFAULT_FIELD_MAP = {
    "prefix": "PREFIX",
    "street_name": "STREET NAME",
    "type": "TYPE",
    "suffix": "SUFFIX",
    "low": "LOW",
    "high": "HIGH",
    "community": "COMMUNITY",
    "parity": "SIDE",
    "esn": "ESN",
}

SECONDS_PER_DAY = 86400
ESN_MAX_DIGITS = 5   # the widest ESN ADDR-05 accepts


@dataclass
class MsagConfig:
    source_path: Optional[str] = None         # the MSAG CSV; --msag can supply it instead
    header_row: int = 0                       # 1-based; 0 finds the header row by its tokens
    field_map: dict = field(default_factory=lambda: dict(DEFAULT_FIELD_MAP))
    esn_pad_width: int = 3
    exceptions_path: Optional[str] = None     # CSV, see load_exceptions
    names_path: Optional[str] = None          # CSV, see load_authoritative_names
    min_match_rate: float = 0.98
    max_source_age_days: Optional[int] = None  # None reports the age and never warns on it
    source_hash: Optional[str] = None         # when set, the source must hash to this


def _is_text(value):
    return value is None or isinstance(value, str)


def _is_count(value, low=0):
    return isinstance(value, int) and not isinstance(value, bool) and value >= low


def _is_field_map(value):
    return value is None or (isinstance(value, dict)
                             and all(isinstance(v, str) for v in value.values()))


def _is_fraction(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and 0 <= value <= 1


# (key, test, what the key must be). A wrong type would otherwise crash the run with exit 70.
_CONFIG_RULES = (
    ("source_path", _is_text, "text or null"),
    ("exceptions_path", _is_text, "text or null"),
    ("names_path", _is_text, "text or null"),
    ("source_hash", _is_text, "text or null"),
    ("field_map", _is_field_map, "an object of column names"),
    ("header_row", _is_count, "a whole number, 0 or more"),
    ("esn_pad_width", _is_count, "a whole number, 0 or more"),
    ("max_source_age_days", lambda v: v is None or _is_count(v), "a whole number of days, or null"),
    ("min_match_rate", _is_fraction, "a fraction from 0 to 1, for example 0.98"),
)


def load_config(path):
    """Read an MSAG config. Every refusal is a ValueError that names the file and the key."""
    with open(path, "r", encoding="utf-8-sig") as f:
        try:
            data = json.load(f)
        except ValueError as exc:
            raise ValueError("%s: not valid JSON (%s)" % (path, exc))
    if not isinstance(data, dict):
        raise ValueError("%s: expected a JSON object of MSAG settings" % path)
    for key, test, want in _CONFIG_RULES:
        if key in data and not test(data[key]):
            raise ValueError("%s: %s must be %s, got %r" % (path, key, want, data[key]))
    fm = dict(DEFAULT_FIELD_MAP)
    fm.update(data.get("field_map") or {})
    data["field_map"] = fm
    unknown = set(data) - set(MsagConfig.__dataclass_fields__)
    if unknown:
        raise ValueError("%s: unknown MSAG config key(s): %s - check for typos"
                         % (path, ", ".join(sorted(unknown))))
    cfg = MsagConfig(**data)
    # Resolve RELATIVE paths against the config file's own folder, so a config kept next to
    # its data is portable across machines.
    base = os.path.dirname(os.path.abspath(path))
    for attr in ("source_path", "exceptions_path", "names_path"):
        value = getattr(cfg, attr)
        if value and not os.path.isabs(value):
            setattr(cfg, attr, os.path.normpath(os.path.join(base, value)))
    return cfg


def file_hash(path):
    """SHA-256 of a file's bytes; used to detect that the source file changed."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_source_hash(config):
    """Refuse a source file that no longer hashes to the value the config was written for."""
    if config.source_hash is None:
        return
    got = file_hash(config.source_path)
    pinned = config.source_hash.strip().lower()   # Get-FileHash prints upper case
    if got != pinned:
        raise ValueError("MSAG source %s changed: its SHA-256 is %s but the config pins %s. "
                         "Review the file, then update source_hash."
                         % (config.source_path, got[:12], pinned[:12]))


def source_age_days(path, now=None):
    """Whole days since the file was last modified. `now` is a Unix time, for tests."""
    now = time.time() if now is None else now
    return max(0, int((now - os.path.getmtime(path)) // SECONDS_PER_DAY))


# --- normalization helpers ---------------------------------------------------

def pad_esn(value, width=3):
    """Zero-pad an ESN to a fixed width for comparison. Non-numeric -> upper/trim.
    Blank -> ''. '6' and '006' compare equal at width 3."""
    if isinstance(value, float) and value.is_integer():
        value = int(value)   # a numeric ESN 13.0 -> '13', not '13.0'
    s = "" if value is None else str(value).strip()
    if s == "":
        return ""
    if s.isdigit():
        return s.zfill(width)
    return s.upper()


def norm_parity(value):
    """Coerce a side/parity value to one of {'O','E','B',''}."""
    s = "" if value is None else str(value).strip().upper()
    if s in ("O", "ODD"):
        return "O"
    if s in ("E", "EVEN"):
        return "E"
    if s in ("B", "BOTH"):
        return "B"
    return ""


def _to_int(value):
    if value is None:
        return None
    if isinstance(value, int):
        return value
    s = str(value).strip()
    if s == "":
        return None
    try:
        return int(float(s))
    except (ValueError, OverflowError):   # OverflowError on 'inf'/'nan'
        return None


def name_key(prefix, street_name, type_, suffix):
    """Normalized PREFIX + STREET NAME + TYPE + SUFFIX key."""
    return normalize(prefix, street_name, type_, suffix)


# --- header detection / schema validation ------------------------------------

def detect_header_row(rows, expected_tokens=HEADER_TOKENS, scan_rows=10):
    """Return the 1-based row whose cells best match the core MSAG tokens.

    `rows` is a list of cell lists. Scans the first scan_rows rows; the row with the most
    token hits wins. Ties resolve to the earliest row.
    """
    wanted = {normalize(t) for t in expected_tokens}
    best_row, best_score = 1, -1
    for row_idx, row in enumerate(rows[:scan_rows], start=1):
        cells = {normalize(c) for c in row}
        cells.discard("")
        score = len(wanted & cells)
        if score > best_score:
            best_row, best_score = row_idx, score
    return best_row


def validate_msag_schema(headers, field_map):
    """(ok, errors): every REQUIRED canonical field must map to a present header.

    `headers` is the iterable of actual column names on the header row.
    """
    present = {("" if h is None else str(h).strip()) for h in headers}
    errors = []
    for canonical in REQUIRED_FIELDS:
        actual = field_map.get(canonical)
        if not actual:
            errors.append("Required column for '%s' is not mapped; add it to "
                          "field_map in the MSAG config." % canonical)
        elif actual not in present:
            errors.append("Required column for '%s' not found (expected header "
                          "'%s'). Fix the column name in field_map or the file."
                          % (canonical, actual))
    return (not errors, errors)


# --- CSV loading -------------------------------------------------------------

def _read_rows(path):
    with open(path, "r", encoding="utf-8-sig", newline="") as fh:
        return [row for row in csv.reader(fh)]


def _row_is_blank(values):
    return all(v is None or str(v).strip() == "" for v in values)


def load_msag_csv(config):
    """Parse the MSAG CSV into normalized record dicts.

    Returns a list of {community, name_key, prefix, street_name, type, suffix,
    low(int|None), high(int|None), parity('O'/'E'/'B'/''), esn(zero-padded str)}.
    Skips fully-blank rows; tolerates banner rows above the header via header_row.
    Refuses a file whose required columns are missing, or whose hash is not the pinned one.
    """
    verify_source_hash(config)
    rows = _read_rows(config.source_path)
    header_idx = config.header_row or detect_header_row(rows)
    if header_idx > len(rows):
        raise ValueError("MSAG header_row %d is past the end of %s (%d rows)"
                         % (header_idx, config.source_path, len(rows)))
    headers = [str(c).strip() for c in rows[header_idx - 1]]
    ok, errors = validate_msag_schema(headers, config.field_map)
    if not ok:
        raise ValueError("MSAG file %s: %s" % (config.source_path, " ".join(errors)))
    col_of = {h: i for i, h in enumerate(headers) if h}
    cols = {c: col_of.get(config.field_map.get(c)) for c in CANONICAL_FIELDS}
    records = []
    for values in rows[header_idx:]:
        if _row_is_blank(values):
            continue

        def get(canonical):
            i = cols[canonical]
            return values[i] if (i is not None and i < len(values)) else None

        prefix = "" if get("prefix") is None else str(get("prefix")).strip()
        street = "" if get("street_name") is None else str(get("street_name")).strip()
        type_ = "" if get("type") is None else str(get("type")).strip()
        suffix = "" if get("suffix") is None else str(get("suffix")).strip()
        records.append({
            "community": "" if get("community") is None else str(get("community")).strip().upper(),
            "name_key": name_key(prefix, street, type_, suffix),
            "prefix": prefix,
            "street_name": street,
            "type": type_,
            "suffix": suffix,
            "low": _to_int(get("low")),
            "high": _to_int(get("high")),
            "parity": norm_parity(get("parity")),
            "esn": pad_esn(get("esn"), config.esn_pad_width),
        })
    return records


# --- exceptions --------------------------------------------------------------

@dataclass
class Exceptions:
    """MSAG-not-GIS suppression rules loaded from the exceptions CSV."""
    # (normalized street name, padded ESN) -> True ; ESN '' means any-ESN for that name
    by_name_esn: set = field(default_factory=set)
    by_name_any_esn: set = field(default_factory=set)     # normalized street name
    permanent: set = field(default_factory=set)           # (community, name_key, padded ESN)
    esn_pad_width: int = 3


ESN_999 = "999"  # convention: any record on ESN 999 is excluded


def _dict_rows(path, required):
    """(line, dict) pairs of a CSV, keyed by lower-case header. Refuses a missing column."""
    rows = _read_rows(path)
    header = [h.strip().lower() for h in (rows[0] if rows else [])]
    missing = [c for c in required if c not in header]
    if missing:
        raise ValueError("%s: missing column(s) %s; header is %s"
                         % (path, ", ".join(missing), ",".join(header)))
    out = []
    for line, values in enumerate(rows[1:], start=2):
        if _row_is_blank(values):
            continue
        out.append((line, {h: (values[i].strip() if i < len(values) else "")
                           for i, h in enumerate(header)}))
    return out


def load_exceptions(path, esn_pad_width=3):
    """Build an Exceptions structure from a CSV.

    Header: kind,community,prefix,street,type,suffix,esn. `kind` is `name` (suppress the
    street, on one ESN, or on any ESN when esn is blank) or `permanent` (suppress one
    community, street and ESN). Community is read only for `permanent` rows."""
    exc = Exceptions(esn_pad_width=esn_pad_width)
    for line, r in _dict_rows(path, ("kind", "community", "prefix", "street", "type",
                                     "suffix", "esn")):
        nk = name_key(r["prefix"], r["street"], r["type"], r["suffix"])
        padded = pad_esn(r["esn"], esn_pad_width)
        kind = r["kind"].lower()
        if kind == "name":
            if not nk:
                continue   # a blank name would suppress every record that has no name
            if padded == "":
                exc.by_name_any_esn.add(nk)
            else:
                exc.by_name_esn.add((nk, padded))
        elif kind == "permanent":
            exc.permanent.add((r["community"].upper(), nk, padded))
        else:
            raise ValueError("%s line %d: kind %r is not name or permanent"
                             % (path, line, r["kind"]))
    return exc


def load_authoritative_names(path):
    """Build the authoritative {(community_upper, name_key)} set from a CSV.

    Header: community,street_name. A row with a blank street name is skipped."""
    names = set()
    for _line, r in _dict_rows(path, ("community", "street_name")):
        nk = normalize(r["street_name"])
        if nk:
            names.add((r["community"].upper(), nk))
    return names


def authoritative_names_from_msag(records):
    """Build {(community_upper, name_key)} from the parsed MSAG rows themselves.

    A separate street-name table is a frozen copy: nothing rebuilds it, and it drifts from the
    MSAG it is supposed to mirror, so STREET-11 would warn on names the MSAG says are valid.
    The MSAG file IS the authority these tools follow, and it is the artifact the analyst
    actually maintains, so its names count as authoritative too. Unioning the two means adding
    a road to the MSAG is enough.

    Keys are emitted PREFIX-STRIPPED to match street_checks._street_name_candidates, which
    compares prefix-stripped forms because a name table stores '20TH', not 'SE 20TH PL'.
    Emitting the MSAG's own 'SE 20TH PL' would add an entry nothing can ever match. Both the
    full (street+type+suffix) and bare (street only) forms are emitted, since either source may
    carry the type where the other omits it.
    """
    out = set()
    for r in records:
        comm = (r.get("community") or "").strip().upper()
        street = r.get("street_name")
        for nk in (name_key("", street, r.get("type"), r.get("suffix")),
                   name_key("", street, "", "")):
            if nk:
                out.add((comm, nk))
    return out


def is_excepted(rec, exceptions, convention_only=False):
    """True if a reconcile finding for `rec` should be suppressed.

    `convention_only=True` applies ONLY the symmetric structural sentinels (ESN-999,
    0-0 placeholder range, out-of-domain pseudo-ESN) - used for the GIS-not-MSAG
    direction. The data-driven by_name/permanent exceptions are MSAG-side authoritative
    omissions and must NOT suppress a real GIS-side defect, so they apply only when
    convention_only is False (the MSAG-not-GIS direction).
    """
    # The pure-convention sentinel suppressions (ESN-999, 0-0 placeholder range,
    # 6+ digit pseudo-ESN) do NOT depend on a loaded exceptions file,
    # which is Optional; fall back to the standard 3-digit pad when it is absent.
    pad = exceptions.esn_pad_width if exceptions is not None else 3
    if rec.get("esn") == pad_esn(ESN_999, pad):
        return True
    # Sentinel placeholder rows carry a structurally non-coverable 0-0 range (some MSAGs use
    # LOW=0 HIGH=0 for a routing placeholder). build_gis_msag can never emit such a range, so
    # they are guaranteed-flagged noise, not a real reconciliation defect. Require an explicit
    # 0 on at least one side so a record carrying no range info at all is not silently
    # suppressed.
    _lo, _hi = rec.get("low"), rec.get("high")
    if _lo in (None, 0) and _hi in (None, 0) and (_lo == 0 or _hi == 0):
        return True
    # Non-geographic service pseudo-records (wireless or VoIP caller routing rows) can carry
    # out-of-domain ESNs. ADDR-05 accepts one to five digits, so only a numeric ESN longer than
    # that (and longer than the pad width) can never match a GIS range.
    esn = rec.get("esn", "")
    if esn.isdigit() and len(esn) > max(pad, ESN_MAX_DIGITS):
        return True
    if exceptions is None or convention_only:
        return False   # data-driven suppressions need the exceptions file and are MSAG-direction only
    nk = rec.get("name_key", "")
    if nk in exceptions.by_name_any_esn:
        return True
    if (nk, rec.get("esn", "")) in exceptions.by_name_esn:
        return True
    if (rec.get("community", ""), nk, rec.get("esn", "")) in exceptions.permanent:
        return True
    return False


# --- GIS-side MSAG roll-up ---------------------------------------------------

def _side_record(community, prefix, name, type_, suffix, lo, hi, parity, esn, pad):
    lo_i, hi_i = _to_int(lo), _to_int(hi)
    if lo_i is None or hi_i is None or (lo_i == 0 and hi_i == 0):
        return None
    if lo_i > hi_i:
        lo_i, hi_i = hi_i, lo_i
    return {
        "community": "" if community is None else str(community).strip().upper(),
        "name_key": name_key(prefix, name, type_, suffix),
        "low": lo_i,
        "high": hi_i,
        "parity": norm_parity(parity),
        "esn": pad_esn(esn, pad),
    }


def build_gis_msag(streets, esn_pad_width=3):
    """Roll street centerlines into MSAG-style records, one per populated side."""
    out = []
    for s in streets:
        prefix = s.get("PREFIX")
        name = s.get("NAME")
        type_ = s.get("TYPE")
        suffix = s.get("SUFFIX")
        oid, xy = s.get("_OID"), s.get("_XY")   # carry source so XLAYER-16 GIS-side findings are mappable
        left = _side_record(s.get("LCITY"), prefix, name, type_, suffix,
                            s.get("FROMLEFT"), s.get("TOLEFT"),
                            s.get("Parity_L"), s.get("LESN"), esn_pad_width)
        if left:
            left["_oid"], left["_xy"] = oid, xy
            out.append(left)
        right = _side_record(s.get("RCITY"), prefix, name, type_, suffix,
                             s.get("FROMRIGHT"), s.get("TORIGHT"),
                             s.get("Parity_R"), s.get("RESN"), esn_pad_width)
        if right:
            right["_oid"], right["_xy"] = oid, xy
            out.append(right)
    return out


# --- reconciliation ----------------------------------------------------------

def ranges_cover(target_lo, target_hi, gis_ranges):
    """True if [target_lo, target_hi] is fully covered by the union of gis_ranges.

    gis_ranges is an iterable of (lo, hi) inclusive integer ranges. Coverage is
    by union of overlapping/adjacent ranges (an inclusive range).
    """
    if target_lo is None or target_hi is None:
        return False
    if target_lo > target_hi:
        target_lo, target_hi = target_hi, target_lo
    spans = sorted((min(a, b), max(a, b)) for a, b in gis_ranges
                   if a is not None and b is not None)
    cursor = target_lo
    for lo, hi in spans:
        if lo > cursor:
            return False            # gap before we reach `cursor`
        if hi >= cursor:
            cursor = hi + 1
        if cursor > target_hi:
            return True
    return cursor > target_hi


def _covered_by(rec, gis_in_group):
    """Whether the MSAG record's range is covered by its compatible GIS sides.

    A 'B' (both-sides) MSAG range needs its EVEN house numbers covered by an even/B
    GIS side AND its ODD numbers by an odd/B side -- a lone even side must not mask a
    missing odd side. E/O records only need their own parity covered.
    """
    p = (rec.get("parity") or "").strip().upper()
    lo, hi = rec.get("low"), rec.get("high")
    if p in ("E", "O"):
        return ranges_cover_parity(lo, hi, p, [(g["low"], g["high"]) for g in gis_in_group])

    def side_ranges(want):
        return [(g["low"], g["high"]) for g in gis_in_group
                if (g.get("parity") or "").strip().upper() in (want, "B", "")]
    return (ranges_cover_parity(lo, hi, "E", side_ranges("E"))
            and ranges_cover_parity(lo, hi, "O", side_ranges("O")))


def ranges_cover_parity(target_lo, target_hi, parity, gis_ranges):
    """Parity-aware coverage of [target_lo, target_hi] by the union of gis_ranges.

    For parity 'E'/'O', only the same-parity house numbers in [lo, hi] must be
    covered -- opposite-parity integers are un-addressable on that side, so a
    GIS even-side segment that skips odd numbers does not create a real gap.
    For 'B'/'' parity, defers to the full integer-union ranges_cover.
    """
    p = (parity or "").strip().upper()
    if p not in ("E", "O"):
        return ranges_cover(target_lo, target_hi, gis_ranges)
    if target_lo is None or target_hi is None:
        return False
    if target_lo > target_hi:
        target_lo, target_hi = target_hi, target_lo
    start = target_lo if (target_lo % 2 == 0) == (p == "E") else target_lo + 1
    if start > target_hi:
        # The range holds no house number of the requested parity (a parity/number
        # contradiction). Don't vacuously report it covered -- fall back to integer
        # coverage so the reconcile still flags a genuine miss.
        return ranges_cover(target_lo, target_hi, gis_ranges)
    spans = [(min(a, b), max(a, b)) for a, b in gis_ranges
             if a is not None and b is not None]
    for n in range(start, target_hi + 1, 2):
        if not any(lo <= n <= hi for lo, hi in spans):
            return False
    return True


def uncovered_spans(target_lo, target_hi, parity, gis_ranges, max_spans=3):
    """The parity-aware portions of [target_lo, target_hi] that gis_ranges do NOT cover,
    as a list of (lo, hi) tuples.

    Reported so a range-mismatch finding can name the numbers that are actually missing.
    Without it the finding could read "GIS 3000-3200 vs MSAG 3000-3200" -- true (the spans
    match) but self-contradictory to an analyst, because the real defect is a HOLE inside a
    span whose endpoints agree. Returns at most max_spans entries; the caller says "and N
    more" rather than printing a wall of numbers.
    """
    if target_lo is None or target_hi is None:
        return []
    if target_lo > target_hi:
        target_lo, target_hi = target_hi, target_lo
    p = (parity or "").strip().upper()
    step = 2 if p in ("E", "O") else 1
    start = target_lo
    if step == 2 and ((target_lo % 2 == 0) != (p == "E")):
        start = target_lo + 1
    spans = [(min(a, b), max(a, b)) for a, b in gis_ranges
             if a is not None and b is not None]
    out, run_lo, prev = [], None, None
    for n in range(start, target_hi + 1, step):
        if any(lo <= n <= hi for lo, hi in spans):
            if run_lo is not None:
                out.append((run_lo, prev)); run_lo = None
        else:
            if run_lo is None:
                run_lo = n
            prev = n
    if run_lo is not None:
        out.append((run_lo, prev))
    return out[:max_spans] if max_spans else out


def uncovered_for_record(rec, gis_in_group, max_spans=3):
    """The house-number spans of `rec` that its compatible GIS sides do NOT cover.

    MIRRORS _covered_by exactly, including the per-side rule for a 'B' record: evens must be
    covered by an even/B side and odds by an odd/B side, checked SEPARATELY. Computing gaps
    against the flat union instead would be a weaker test than the coverage decision, so a
    record could be reported "not covered" while this returned no gaps to show -- which is
    precisely the self-contradictory finding this exists to prevent.
    """
    p = (rec.get("parity") or "").strip().upper()
    lo, hi = rec.get("low"), rec.get("high")
    if p in ("E", "O"):
        return uncovered_spans(lo, hi, p,
                               [(g["low"], g["high"]) for g in gis_in_group], max_spans)

    def side_ranges(want):
        return [(g["low"], g["high"]) for g in gis_in_group
                if (g.get("parity") or "").strip().upper() in (want, "B", "")]
    gaps = (uncovered_spans(lo, hi, "E", side_ranges("E"), None)
            + uncovered_spans(lo, hi, "O", side_ranges("O"), None))
    gaps.sort()
    # The even and odd passes describe the SAME hole from two sides (1200-1298 and
    # 1201-1299); an analyst reads that as one gap, 1200-1299. Merge overlapping or
    # adjacent spans so the finding says what a person would say.
    merged = []
    for lo_i, hi_i in gaps:
        if merged and lo_i <= merged[-1][1] + 1:
            merged[-1] = (merged[-1][0], max(merged[-1][1], hi_i))
        else:
            merged.append((lo_i, hi_i))
    return merged[:max_spans] if max_spans else merged


def _group_key(rec):
    # Group by community + street name only. Parity is handled by COMPATIBILITY,
    # not exact grouping: MSAG records are overwhelmingly 'B' (both sides) while the
    # GIS rolls up to per-side 'E'/'O' records, so a 'B' MSAG range must be allowed
    # to be covered by the union of the GIS even+odd sides.
    return (rec.get("community", ""), rec.get("name_key", ""))


def _parity_compat(a, b):
    """True if two parity codes can address the same house numbers.
    'B'/'' (both) is compatible with anything; otherwise they must be equal."""
    a = (a or "").strip().upper()
    b = (b or "").strip().upper()
    if a in ("B", "") or b in ("B", ""):
        return True
    return a == b


def _index_by_group(records):
    groups = {}
    for r in records:
        groups.setdefault(_group_key(r), []).append(r)
    return groups


def build_msag_addr_index(addresses):
    """Index addressable house numbers by (community_upper, component name_key), so
    reconcile can tell a real coverage gap (an address actually occupies the range)
    from benign centerline/MSAG overshoot (no address there to misroute)."""
    idx = {}
    for a in addresses:
        if not is_addressable(a):
            continue
        try:
            h = int(a.get("Add_Number"))
        except (TypeError, ValueError):
            continue
        if h <= 0:
            continue
        comm = str(a.get("CITY") or a.get("INC_MUNI") or "").strip().upper()
        nk = name_key(a.get("PREFIX"), a.get("STREET_NA"), a.get("TYPE"), a.get("SUFFIX"))
        if not nk:
            continue
        idx.setdefault((comm, nk), []).append(h)
    return idx


def _has_uncovered_address(rec, other_ranges, addr_index):
    """True if a real addressable point of the record's (community, name) lies inside
    the record's range, on its parity, and is NOT covered by any other_range. A range
    with no such address is benign overshoot, not a reconcile defect."""
    nums = addr_index.get((rec.get("community", ""), rec.get("name_key", "")))
    if not nums:
        return False
    lo, hi = rec.get("low"), rec.get("high")
    if lo is None or hi is None:
        return False
    if lo > hi:
        lo, hi = hi, lo
    p = (rec.get("parity") or "").strip().upper()
    others = [(min(a, b), max(a, b)) for a, b in other_ranges if a is not None and b is not None]
    for h in nums:
        if h < lo or h > hi:
            continue
        if p in ("E", "O") and ((h % 2 == 0) != (p == "E")):
            continue
        if any(olo <= h <= ohi for olo, ohi in others):
            continue   # covered by the other side -> not an uncovered address
        return True
    return False


def reconcile(msag_records, gis_records, exceptions=None, addr_index=None):
    """Bidirectional NENA 71-501 reconcile by (community, name_key, parity).

    Returns dict with lists msag_not_gis, gis_not_msag, attr_mismatch, range_mismatch and
    counts + match_rate (fraction of eligible MSAG records covered) + exact_rate (fraction
    whose extent equals one whole GIS run). Pure-Python (dicts only).

    When addr_index (from build_msag_addr_index) is provided, a not-covered range is
    only reported when a real address actually occupies its uncovered portion -- benign
    overshoot with no occupying address is suppressed. The matched/excepted counts and
    match_rate are unaffected (the gate only filters the not-covered LISTS). addr_index
    None preserves legacy behavior.
    """
    gis_groups = _index_by_group(gis_records)

    msag_not_gis = []
    attr_mismatch = []
    range_mismatch = []
    matched = 0
    excepted = 0
    addr_gated = 0
    exact = 0
    runs = gis_runs(gis_records)

    for rec in msag_records:
        # Convention-excluded records (ESN-999 sentinels, 6+ digit pseudo-ESNs,
        # by-name/permanent exceptions) are neither matches nor misses and must not
        # produce attr_mismatch or inflate the match denominator -- test first.
        if is_excepted(rec, exceptions):
            excepted += 1
            continue
        if exact_tuple(rec, runs):
            exact += 1
        gis_in_group = [g for g in gis_groups.get(_group_key(rec), [])
                        if _parity_compat(rec.get("parity"), g.get("parity"))]
        covered = _covered_by(rec, gis_in_group)
        if covered:
            matched += 1
            # name+range match: flag ESN differences among overlapping GIS records.
            # Any overlapping side whose ESN differs is a mismatch -- a correct side
            # elsewhere must not mask a wrong ESN on the opposite side.
            overlap_esns = {g["esn"] for g in gis_in_group
                            if _overlaps(rec, g) and g["esn"]}
            mismatched = {e for e in overlap_esns if e != rec.get("esn")}
            if rec.get("esn") and mismatched:
                attr_mismatch.append({
                    "msag": rec,
                    "gis_esns": sorted(mismatched),
                    "reason": "ESN mismatch: MSAG %s vs GIS %s"
                              % (rec["esn"], ",".join(sorted(mismatched))),
                })
            continue
        # SAME ROAD, DIFFERENT EXTENT. The name/community/parity group matches and the
        # ranges OVERLAP, but an endpoint differs. It is its own class, and without it such
        # a record was not "covered", so it was not matched, and then the address gate below
        # usually dropped it entirely: it deflated the match rate while appearing in NO
        # bucket, so matched+excepted+msag_not_gis did not sum to the total. Reported
        # REGARDLESS of whether an address occupies the gap: the ranges disagreeing is the
        # finding.
        overlapping = [g for g in gis_in_group if _overlaps(rec, g)]
        differing = [g for g in overlapping
                     if g.get("low") != rec.get("low") or g.get("high") != rec.get("high")]
        if differing:
            range_mismatch.append({"msag": rec, "gis": differing,
                                   "group": list(gis_in_group)})
            continue
        # Address-evidence gate (symmetric with the GIS side): when an index is given
        # and the group has compatible GIS coverage, only report an MSAG range whose
        # uncovered portion actually holds an address. True orphan names (no compatible
        # GIS record at all) are always kept.
        if addr_index is not None and gis_in_group:
            gis_ranges = [(g["low"], g["high"]) for g in gis_in_group]
            if not _has_uncovered_address(rec, gis_ranges, addr_index):
                addr_gated += 1
                continue
        msag_not_gis.append(rec)

    # GIS-not-MSAG: a GIS side-range not covered by any MSAG record in its group.
    msag_groups = _index_by_group(msag_records)
    gis_not_msag = []
    # A GIS record already reported as the other half of a range_mismatch must not also be
    # reported as "GIS range not in MSAG" -- that is the same disagreement counted twice,
    # once from each side, which is what made the two buckets look inflated.
    paired_gis = {id(g) for rm in range_mismatch for g in rm["gis"]}
    for g in gis_records:
        if id(g) in paired_gis:
            continue
        msag_in_group = [m for m in msag_groups.get(_group_key(g), [])
                         if _parity_compat(g.get("parity"), m.get("parity"))]
        msag_ranges = [(m["low"], m["high"]) for m in msag_in_group]
        if not ranges_cover_parity(g["low"], g["high"], g.get("parity"),
                                   msag_ranges):
            if is_excepted(g, exceptions, convention_only=True):
                continue   # only structural sentinels suppress a GIS-side finding
            # Only a range whose uncovered portion holds a real address is a defect.
            if addr_index is not None and not _has_uncovered_address(g, msag_ranges, addr_index):
                continue
            gis_not_msag.append(g)

    total = len(msag_records)
    # Excepted records are authoritatively suppressed, not real misses; exclude them
    # from the denominator so the NENA KPI is not deflated by known exceptions.
    denom = total - excepted
    match_rate = (matched / denom) if denom else 1.0
    exact_rate = (exact / denom) if denom else 1.0
    accounted = matched + excepted + len(msag_not_gis) + len(range_mismatch) + addr_gated
    return {
        "msag_not_gis": msag_not_gis,
        "gis_not_msag": gis_not_msag,
        "attr_mismatch": attr_mismatch,
        "range_mismatch": range_mismatch,
        "counts": {
            "msag_total": total,
            "gis_total": len(gis_records),
            "matched": matched,
            "excepted": excepted,
            "msag_not_gis": len(msag_not_gis),
            "gis_not_msag": len(gis_not_msag),
            "attr_mismatch": len(attr_mismatch),
            "range_mismatch": len(range_mismatch),
            # Not-covered MSAG ranges suppressed because no address occupies the gap.
            # Counted so matched + excepted + msag_not_gis + range_mismatch + addr_gated
            # sums to msag_total -- the reconcile must add up or the KPI cannot be trusted.
            "addr_gated": addr_gated,
            # Records that landed in no bucket. Always 0; a non-zero value means a record was
            # lost and no rate printed beside it can be trusted.
            "unaccounted": total - accounted,
            "exact": exact,
            "eligible": denom,
        },
        "match_rate": match_rate,
        "exact_rate": exact_rate,
    }


def _overlaps(a, b):
    alo, ahi = a.get("low"), a.get("high")
    blo, bhi = b.get("low"), b.get("high")
    if None in (alo, ahi, blo, bhi):
        return False
    return alo <= bhi and blo <= ahi


# --- exact-tuple rate --------------------------------------------------------

def _parity_span(lo, hi, par):
    """The first and last house number of parity `par` ('E' or 'O') inside [lo, hi], or None
    when the range holds no number of that parity."""
    start = lo if (lo % 2 == 0) == (par == "E") else lo + 1
    end = hi if (hi % 2 == 0) == (par == "E") else hi - 1
    return (start, end) if start <= end else None


def _parities(parity):
    """The parities a record addresses. E and O address one; B and blank address both."""
    p = (parity or "").strip().upper()
    return (p,) if p in ("E", "O") else ("E", "O")


def gis_runs(gis_records):
    """Merge GIS side records into maximal runs.

    Returns {(community, name_key, esn, parity): [(lo, hi), ...]} where parity is 'E' or 'O'
    and each (lo, hi) is the first and last house number of that parity in a run. Two spans
    merge when they overlap or touch within one parity step (a gap of at most 2). A 'B' or
    blank side feeds both parities. This is what a single MSAG record would list if the
    two sources agreed to the letter."""
    spans = defaultdict(list)
    for g in gis_records:
        for par in _parities(g.get("parity")):
            span = _parity_span(g["low"], g["high"], par)
            if span:
                spans[(g["community"], g["name_key"], g["esn"], par)].append(span)
    runs = {}
    for key, items in spans.items():
        items.sort()
        merged = [items[0]]
        for lo, hi in items[1:]:
            if lo <= merged[-1][1] + 2:
                merged[-1] = (merged[-1][0], max(merged[-1][1], hi))
            else:
                merged.append((lo, hi))
        runs[key] = merged
    return runs


def exact_tuple(rec, runs):
    """True when the MSAG record equals GIS runs on community, street, ESN, parity and extent.

    An E or O record must equal one run of that parity. A B record must equal one even run
    and one odd run, because the two sources write the same street as one 'B' row or as two
    side rows. A record with no range, or an empty one, is never exact."""
    lo, hi = rec.get("low"), rec.get("high")
    if lo is None or hi is None:
        return False
    if lo > hi:
        lo, hi = hi, lo
    needed = [(par, _parity_span(lo, hi, par)) for par in _parities(rec.get("parity"))]
    needed = [(par, span) for par, span in needed if span]
    if not needed:
        return False
    return all(span in runs.get((rec.get("community", ""), rec.get("name_key", ""),
                                 rec.get("esn", ""), par), ())
               for par, span in needed)


# --- roll-up -----------------------------------------------------------------

ROLLUP_CLASSES = ("msag_not_gis", "gis_not_msag", "range_mismatch", "attr_mismatch")


def rollup(res):
    """Group a reconcile result by street.

    Returns a list of {community, name_key, total, msag_not_gis, gis_not_msag,
    range_mismatch, attr_mismatch}, largest total first, ties by community and name. A
    thousand findings across forty streets reads as forty rows."""
    rows = {}

    def bump(rec, cls):
        key = (rec.get("community", ""), rec.get("name_key", ""))
        row = rows.setdefault(key, dict({c: 0 for c in ROLLUP_CLASSES},
                                        community=key[0], name_key=key[1], total=0))
        row[cls] += 1
        row["total"] += 1

    for rec in res["msag_not_gis"]:
        bump(rec, "msag_not_gis")
    for rec in res["gis_not_msag"]:
        bump(rec, "gis_not_msag")
    for item in res["range_mismatch"]:
        bump(item["msag"], "range_mismatch")
    for item in res["attr_mismatch"]:
        bump(item["msag"], "attr_mismatch")
    return sorted(rows.values(), key=lambda r: (-r["total"], r["community"], r["name_key"]))
