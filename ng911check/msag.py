"""MSAG load + reconciliation engine.

Treats the authoritative MSAG spreadsheet as READ-ONLY. The xlsx is parsed once
into a normalized in-memory list of records; reconciliation against GIS-derived
MSAG records follows NENA 71-501 (bidirectional, range-containment).

Pure Python + openpyxl only. The reconcile/build/normalize helpers operate on
plain dicts so they are unit-testable without arcpy or the big xlsx.
"""
import hashlib
import json
import os
from dataclasses import asdict, dataclass, field
from typing import Optional

from .common import normalize, is_addressable

# Canonical MSAG field keys the engine reasons about.
CANONICAL_FIELDS = ("prefix", "street_name", "type", "suffix",
                    "low", "high", "community", "parity", "esn")
# Fields that MUST resolve to a real column for the sheet to be usable.
REQUIRED_FIELDS = ("street_name", "low", "high", "community", "parity", "esn")

# Tokens used to auto-detect the real header row (DESIGN: row 3 in the live file).
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


@dataclass
class MsagConfig:
    source_path: str
    sheet: str = "Cleaned_up_Msag"
    header_row: int = 3                       # 1-based
    field_map: dict = field(default_factory=lambda: dict(DEFAULT_FIELD_MAP))
    esn_pad_width: int = 3
    exceptions_gdb: Optional[str] = None
    min_match_rate: float = 0.98
    source_hash: Optional[str] = None


def load_config(path):
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    fm = dict(DEFAULT_FIELD_MAP)
    fm.update(data.get("field_map") or {})
    data["field_map"] = fm
    unknown = set(data) - set(MsagConfig.__dataclass_fields__)
    if unknown:
        raise ValueError("Unknown MSAG config key(s): %s — check for typos"
                         % ", ".join(sorted(unknown)))
    cfg = MsagConfig(**data)
    # Resolve RELATIVE source/exceptions paths against the config file's own folder, so a
    # bundled config (with paths relative to the package) is portable across machines.
    base = os.path.dirname(os.path.abspath(path))
    if cfg.source_path and not os.path.isabs(cfg.source_path):
        cfg.source_path = os.path.normpath(os.path.join(base, cfg.source_path))
    if cfg.exceptions_gdb and not os.path.isabs(cfg.exceptions_gdb):
        cfg.exceptions_gdb = os.path.normpath(os.path.join(base, cfg.exceptions_gdb))
    return cfg


def save_config(cfg, path):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(asdict(cfg), f, indent=2)


def file_hash(path):
    """SHA-256 of a file's bytes; used to detect that the source xlsx changed."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


# --- normalization helpers ---------------------------------------------------

def pad_esn(value, width=3):
    """Zero-pad an ESN to a fixed width for comparison. Non-numeric -> upper/trim.
    Blank -> ''. '6' and '006' compare equal at width 3."""
    if isinstance(value, float) and value.is_integer():
        value = int(value)   # arcpy numeric ESN 13.0 -> '13', not '13.0'
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

def detect_header_row(ws, expected_tokens=HEADER_TOKENS, scan_rows=10):
    """Return the 1-based row whose cells best match the core MSAG tokens.

    Scans the first ~scan_rows rows; the row with the most token hits wins.
    Ties resolve to the earliest row.
    """
    wanted = {normalize(t) for t in expected_tokens}
    best_row, best_score = 1, -1
    for row_idx, row in enumerate(ws.iter_rows(min_row=1, max_row=scan_rows), start=1):
        cells = {normalize(c.value) for c in row if c.value is not None}
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
                          "'%s'). Fix the column name in field_map or the sheet."
                          % (canonical, actual))
    return (not errors, errors)


# --- xlsx loading ------------------------------------------------------------

def _row_is_blank(values):
    return all(v is None or str(v).strip() == "" for v in values)


def load_msag_xlsx(config):
    """Parse the MSAG xlsx into normalized record dicts.

    Returns a list of {community, name_key, prefix, street_name, type, suffix,
    low(int|None), high(int|None), parity('O'/'E'/'B'/''), esn(zero-padded str)}.
    Skips fully-blank rows; tolerates banner/legend rows via header_row.
    """
    import openpyxl
    wb = openpyxl.load_workbook(config.source_path, read_only=True, data_only=True)
    try:
        ws = wb[config.sheet]
        header_idx = config.header_row
        headers = []
        for row in ws.iter_rows(min_row=header_idx, max_row=header_idx):
            headers = [("" if c.value is None else str(c.value).strip()) for c in row]
            break
        col_of = {h: i for i, h in enumerate(headers) if h}

        def idx(canonical):
            actual = config.field_map.get(canonical)
            return col_of.get(actual)

        cols = {c: idx(c) for c in CANONICAL_FIELDS}
        records = []
        for row in ws.iter_rows(min_row=header_idx + 1):
            values = [c.value for c in row]
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
    finally:
        wb.close()


# --- exceptions --------------------------------------------------------------

@dataclass
class Exceptions:
    """MSAG-not-GIS suppression rules loaded from the reference geodatabase."""
    # (normalized street name, padded ESN) -> True ; ESN '' means any-ESN for that name
    by_name_esn: set = field(default_factory=set)
    by_name_any_esn: set = field(default_factory=set)     # normalized street name
    permanent: set = field(default_factory=set)           # (community, name_key, padded ESN)
    esn_pad_width: int = 3


ESN_999 = "999"  # convention: any record on ESN 999 is excluded


def load_exceptions(gdb, esn_pad_width=3):
    """Build an Exceptions structure from MSAG_EXCEPTIONS + MSAG_PERMANENT."""
    import arcpy
    exc = Exceptions(esn_pad_width=esn_pad_width)

    exc_tbl = gdb + "\\MSAG_EXCEPTIONS"
    if arcpy.Exists(exc_tbl):
        fields = ["Direction", "PrefixType", "Street", "SuffixType",
                  "SuffixDirection", "ESN"]
        with arcpy.da.SearchCursor(exc_tbl, fields) as cur:
            for direction, pretype, street, suftype, sufdir, esn in cur:
                nk = name_key(_first(direction, pretype), street, suftype, sufdir)
                if not nk:
                    continue
                padded = pad_esn(esn, esn_pad_width)
                if padded == "":
                    exc.by_name_any_esn.add(nk)
                else:
                    exc.by_name_esn.add((nk, padded))

    perm_tbl = gdb + "\\MSAG_PERMANENT"
    if arcpy.Exists(perm_tbl):
        fields = ["Community", "Direction", "Street", "SuffixType",
                  "SuffixDirection", "ESN"]
        with arcpy.da.SearchCursor(perm_tbl, fields) as cur:
            for community, direction, street, suftype, sufdir, esn in cur:
                nk = name_key(direction, street, suftype, sufdir)
                comm = "" if community is None else str(community).strip().upper()
                exc.permanent.add((comm, nk, pad_esn(esn, esn_pad_width)))
    return exc


def load_authoritative_names(gdb):
    """Build the authoritative {(community_upper, name_key)} set from DOMAINSTREETNAMES.

    Returns None if the table is absent so STREET-11 stays in degraded mode.
    """
    import arcpy
    tbl = gdb + "\\DOMAINSTREETNAMES"
    if not arcpy.Exists(tbl):
        return None
    names = set()
    with arcpy.da.SearchCursor(tbl, ["Community", "StreetName"]) as cur:
        for community, street in cur:
            nk = normalize(street)
            if not nk:
                continue
            comm = "" if community is None else str(community).strip().upper()
            names.add((comm, nk))
    return names


def authoritative_names_from_msag(records):
    """Build {(community_upper, name_key)} from the parsed MSAG rows themselves.

    DOMAINSTREETNAMES is a frozen MapSAG-era table: it is not rebuilt from anything, has no
    Source populated, and has drifted from the MSAG it is supposed to mirror -- GRANADA WAY
    (RIVERTON) and eight other names are in the spreadsheet but not the table, so STREET-11 warns
    on names the authoritative MSAG says are valid. The MSAG spreadsheet IS the authority these
    tools follow, and it is the artifact the analyst actually maintains, so its names count as
    authoritative too. Unioning the two means adding a road to the MSAG is enough -- no
    geodatabase edit, in any of the shipped copies.

    Keys are emitted PREFIX-STRIPPED to match street_checks._street_name_candidates, which
    compares prefix-stripped forms because DOMAINSTREETNAMES stores '147TH', not 'SE 147TH PL'.
    Emitting the MSAG's own 'SE 147TH PL' would add an entry nothing can ever match. Both the
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


def _first(*vals):
    """First non-blank of the candidates (PREFIX may live in Direction or PrefixType)."""
    for v in vals:
        s = "" if v is None else str(v).strip()
        if s:
            return s
    return ""


def is_excepted(rec, exceptions, convention_only=False):
    """True if a reconcile finding for `rec` should be suppressed.

    `convention_only=True` applies ONLY the symmetric structural sentinels (ESN-999,
    0-0 placeholder range, out-of-domain pseudo-ESN) — used for the GIS-not-MSAG
    direction. The data-driven by_name/permanent exceptions are MSAG-side authoritative
    omissions and must NOT suppress a real GIS-side defect, so they apply only when
    convention_only is False (the MSAG-not-GIS direction).
    """
    # The pure-convention sentinel suppressions (ESN-999, 0-0 placeholder range,
    # out-of-domain >3-digit pseudo-ESN) do NOT depend on a loaded exceptions GDB,
    # which is Optional; fall back to the standard 3-digit pad when it is absent.
    pad = exceptions.esn_pad_width if exceptions is not None else 3
    if rec.get("esn") == pad_esn(ESN_999, pad):
        return True
    # Sentinel placeholder rows carry a structurally non-coverable 0-0 range
    # (Example's MSAG uses ESN 099 / LOW=0 HIGH=0 for these). build_gis_msag can
    # never emit such a range, so they are guaranteed-flagged noise, not a real
    # reconciliation defect. Require an explicit 0 on at least one side so a
    # record carrying no range info at all is not silently suppressed.
    _lo, _hi = rec.get("low"), rec.get("high")
    if _lo in (None, 0) and _hi in (None, 0) and (_lo == 0 or _hi == 0):
        return True
    # Non-geographic PSAP service pseudo-records (VOIP/WIRELESS 911 CALLER routing
    # rows) carry out-of-domain 4+ digit ESNs. Every real MSAG and every GIS-derived
    # ESN is a 3-digit numeric, so a non-3-digit numeric ESN can never match a GIS
    # range and is not a coverable centerline defect.
    esn = rec.get("esn", "")
    if esn.isdigit() and len(esn) != pad:
        return True
    if exceptions is None or convention_only:
        return False   # data-driven suppressions need the GDB and are MSAG-direction only
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
    by union of overlapping/adjacent ranges (Spatial Pro "Inclusive Range").
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
    Without it the finding could read "GIS 7512-7736 vs MSAG 7512-7736" -- true (the spans
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
    # The even and odd passes describe the SAME hole from two sides (5890-5988 and
    # 5891-5989); an analyst reads that as one gap, 5890-5989. Merge overlapping or
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

    Returns dict with lists msag_not_gis, gis_not_msag, attr_mismatch and counts
    + match_rate (fraction of MSAG records matched). Pure-Python (dicts only).

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

    for rec in msag_records:
        # Convention-excluded records (ESN-999 sentinels, 4+ digit pseudo-ESNs,
        # by-name/permanent exceptions) are neither matches nor misses and must not
        # produce attr_mismatch or inflate the match denominator -- test first.
        if is_excepted(rec, exceptions):
            excepted += 1
            continue
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
        # ranges OVERLAP, but an endpoint differs -- MapSAG reports this as its own class
        # and it is the single largest thing this reconcile used to lose. Before this
        # bucket existed such a record was not "covered", so it was not matched, and then
        # the address gate below usually dropped it entirely: it deflated the NENA match
        # rate while appearing in NO bucket (measured 2026-08-27: 75 of 15,163 records
        # unaccounted for, which is why matched+excepted+msag_not_gis did not sum to the
        # total). Reported REGARDLESS of whether an address occupies the gap: the ranges
        # disagreeing is the finding, and MapSAG shows it either way.
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
        },
        "match_rate": match_rate,
    }


def _overlaps(a, b):
    alo, ahi = a.get("low"), a.get("high")
    blo, bhi = b.get("low"), b.get("high")
    if None in (alo, ahi, blo, bhi):
        return False
    return alo <= bhi and blo <= ahi
