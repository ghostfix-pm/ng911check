"""cross_layer checks. See spec docs/superpowers/specs/2026-06-02-911-validation-toolbox-design.md."""
from .model import ErrorRecord, SEVERITY, FAMILY
from .common import (normalize, get_parity, esn_eq, nguid_partition,
                     p_distance, addr_name_key, street_name_key, _clean,
                     is_addressable, seg_label)
from . import registry
from . import msag
import re

_FQDN_RE = re.compile(
    r"^(?=.{1,253}$)([A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,}$")


def arcpy_point(xy):
    import arcpy
    return arcpy.PointGeometry(arcpy.Point(xy[0], xy[1]))


def _covering_side(hno, s):
    """Return 'Left'/'Right'/'BOTH'/None for which side's range+parity covers hno."""
    p = "E" if hno % 2 == 0 else "O"

    def side_ok(frm, to, par):
        if frm is None or to is None:
            return False
        lo, hi = min(frm, to), max(frm, to)
        if lo <= 0 or hi <= 0:   # house numbers are >=1; a 0 endpoint is a broken range,
            return False          # not coverage of [0, hi] (would mask XLAYER-02/01/06)
        pv = _clean(par).upper()   # NULL/lowercase/padded parity -> normalized
        return lo <= hno <= hi and (pv in ("B", "") or pv == p)
    left = side_ok(s.get("FROMLEFT"), s.get("TOLEFT"), s.get("Parity_L"))
    right = side_ok(s.get("FROMRIGHT"), s.get("TORIGHT"), s.get("Parity_R"))
    if left and not right:
        return "Left"
    if right and not left:
        return "Right"
    if left and right:
        return "BOTH"
    return None


def _candidate_segments(a, ctx):
    """Same-name segments for address a, keyed by BOTH its COMPARE-derived _NAMEKEY
    and its raw component name (PREFIX/STREET_NA/TYPE/SUFFIX), de-duped by SEGMENT_ID.

    Mirrors engine.build_context's street raw_key index: when an address's COMPARE
    is stale its _NAMEKEY points at the wrong name, so the raw component key recovers
    the segment that truly carries the address's name. Only ever ADDS candidates.
    """
    keys = [a["_NAMEKEY"]]
    raw = normalize(a.get("PREFIX"), a.get("STREET_NA"), a.get("TYPE"), a.get("SUFFIX"))
    if raw and raw != a["_NAMEKEY"]:
        keys.append(raw)
    out = []
    seen = set()
    for key in keys:
        for s in ctx.streets_by_name.get(key, ()):
            sid = s.get("SEGMENT_ID")
            dedup = sid if sid is not None else id(s)
            if dedup in seen:
                continue
            seen.add(dedup)
            out.append(s)
    return out


def _covering_segments(a, ctx):
    """List of (segment, side) covering address a, by name + range + parity."""
    try:
        hno = int(a.get("Add_Number"))
    except (TypeError, ValueError):
        return []
    out = []
    for s in _candidate_segments(a, ctx):
        side = _covering_side(hno, s)
        if side:
            out.append((s, side))
    return out


def _range_only_sides(hno, s):
    """Return the list of sides ('Left'/'Right') whose range covers hno, parity ignored.

    Matches min(FROM,TO)<=hno<=max(FROM,TO); 0-0 sides are skipped.
    """
    def covers(frm, to):
        if frm is None or to is None:
            return False
        lo, hi = min(frm, to), max(frm, to)
        if lo <= 0 or hi <= 0:   # broken (0/negative-endpoint) range is not coverage
            return False
        return lo <= hno <= hi
    sides = []
    if covers(s.get("FROMLEFT"), s.get("TOLEFT")):
        sides.append("Left")
    if covers(s.get("FROMRIGHT"), s.get("TORIGHT")):
        sides.append("Right")
    return sides


def _range_only_segments(a, ctx):
    """List of (segment, side) covering address a by name + range only (parity ignored)."""
    try:
        hno = int(a.get("Add_Number"))
    except (TypeError, ValueError):
        return []
    out = []
    for s in _candidate_segments(a, ctx):
        for side in _range_only_sides(hno, s):
            out.append((s, side))
    return out


@registry.check(id="XLAYER-01", family=FAMILY.CROSS, severity=SEVERITY.ERROR,
                priority="v1-core", target="both")
def check_xlayer_01(addresses, streets, ctx):
    out = []
    for a in addresses:
        if not is_addressable(a):
            continue
        covering = _covering_segments(a, ctx)
        if not covering:
            continue  # name/range failures handled by XLAYER-02/04
        def _side_esns(seg, sd):
            sd = (sd or "").lower()
            if sd.startswith("l"):
                return [seg.get("LESN")]
            if sd.startswith("r"):
                return [seg.get("RESN")]
            return [seg.get("LESN"), seg.get("RESN")]   # 'both'/blank covers either side
        # Compare against every covering side ESN: OK if any side agrees; skip if
        # nothing is comparable (all sides blank); flag only when every comparable
        # side disagrees.
        pairs = [(seg, sd, e) for seg, sd in covering for e in _side_esns(seg, sd)]
        cov_esns = [e for _, _, e in pairs]
        results = [esn_eq(a.get("ESN"), e) for e in cov_esns]
        if any(r is True for r in results):
            continue
        if all(r is None for r in results):
            continue
        # Report a side that actually disagreed (result False), not just covering[0]
        # (whose ESN may be blank and never drove the flag).
        off = next(((seg, sd) for (seg, sd, _), r in zip(pairs, results) if r is False), None)
        s, side = off if off else covering[0]
        out.append(ErrorRecord(
            "XLAYER-01", "Address ESN vs covering segment side ESN", FAMILY.CROSS,
            SEVERITY.ERROR, "address", a["_OID"], a.get("Site_NGUID", "") or "",
            "ESN %s != covering side ESN(s) %s (SEG %s %s)"
            % (a.get("ESN"), sorted({str(e) for e in cov_esns if e not in (None, "")}),
               seg_label(s), side),
            a.get("_XY")))
    return out


@registry.check(id="XLAYER-02", family=FAMILY.CROSS, severity=SEVERITY.ERROR,
                priority="v1-core", target="both")
def check_xlayer_02(addresses, streets, ctx):
    out = []
    for a in addresses:
        if not is_addressable(a):
            continue
        # Consider BOTH the COMPARE-derived _NAMEKEY and the raw components: skip only
        # when EVERY candidate name is blank or ignored. A stale COMPARE naming an
        # ignored street must not suppress a real range-coverage failure on the
        # address's actual street (and an address whose name lives only in COMPARE
        # must still be checked). Matches the dual-key lookup in _covering_segments.
        akey = normalize(a.get("PREFIX"), a.get("STREET_NA"), a.get("TYPE"), a.get("SUFFIX"))
        names = [n for n in (a["_NAMEKEY"], akey) if n]
        if not names or all(ctx.name_ignored(n) for n in names):
            continue
        # XLAYER-02 is the RANGE check: the street name exists but the house number is
        # outside every matching segment's range. The name-ABSENT case is XLAYER-04's
        # (it fires when the address's true component name `akey` is not in any
        # centerline). Defer exactly that case so the same address is not reported under
        # both checks -- a "not within any range" message is meaningless when the road
        # name does not exist. (akey blank = COMPARE-only address; XLAYER-04 skips those,
        # so XLAYER-02 still checks them via _NAMEKEY -- no overlap either way.)
        if akey and akey not in ctx.streets_by_name:
            continue
        try:
            num = int(a.get("Add_Number"))
        except (TypeError, ValueError):
            continue
        if num <= 0:   # is_addressable already requires a non-blank name
            continue
        if not _covering_segments(a, ctx):
            out.append(ErrorRecord(
                "XLAYER-02", "Address number not within any matching road range",
                FAMILY.CROSS, SEVERITY.ERROR, "address", a["_OID"],
                a.get("Site_NGUID", "") or "",
                "house number %s on %s not within any matching segment range"
                % (a.get("Add_Number"), names[0]),
                a.get("_XY")))
    return out


@registry.check(id="XLAYER-12", family=FAMILY.CROSS, severity=SEVERITY.ERROR,
                priority="v1-core", target="both")
def check_xlayer_12(addresses, streets, ctx):
    out = []
    for a in addresses:
        if not is_addressable(a):
            continue
        covering = _covering_segments(a, ctx)
        # A genuine tie means two distinct segments of the SAME street cover the
        # address. Group covering segments by their intrinsic name (PREFIX+NAME+
        # TYPE+SUFFIX) rather than counting across the COMPARE-keyed set: a stale
        # COMPARE lands physically-distinct roads in one bucket, producing false
        # ties between segments that are actually different streets.
        by_name = {}
        for s, _ in covering:
            key = normalize(s.get("PREFIX"), s.get("NAME"),
                            s.get("TYPE"), s.get("SUFFIX"))
            # Distinct identity per segment so two NULL-SEGMENT_ID segments do not
            # collapse to one set member and hide a real tie.
            sid = s.get("SEGMENT_ID")
            by_name.setdefault(key, set()).add(sid if sid is not None else ("_oid", s["_OID"]))
        for key, ids in by_name.items():
            if len(ids) > 1:
                seg_ids = sorted(ids, key=str)
                out.append(ErrorRecord(
                    "XLAYER-12", "Address geocodes to multiple segments (ties)", FAMILY.CROSS,
                    SEVERITY.ERROR, "address", a["_OID"], a.get("Site_NGUID", "") or "",
                    "address covered by segments %s on '%s'" % (seg_ids, key),
                    a.get("_XY")))
    return out


@registry.check(id="XLAYER-03", family=FAMILY.CROSS, severity=SEVERITY.WARNING,
                priority="v1-core", target="address")
def check_xlayer_03(addresses, streets, ctx):
    out = []
    for a in addresses:
        if not is_addressable(a):
            continue
        # Find covering sides by RANGE ONLY (parity ignored) so we can detect parity
        # disagreements that the parity-gated _covering_segments would silently hide.
        covering = _range_only_segments(a, ctx)
        if not covering:
            continue
        eo = "E" if int(a["Add_Number"]) % 2 == 0 else "O"

        def declared(seg, side):
            return seg.get("Parity_L") if side == "Left" else seg.get("Parity_R")

        # Clean if ANY range-covering side declares a parity consistent with eo
        # (matching, 'B' both, or blank). Flag only when every covering side contradicts.
        if any(_clean(declared(s, side)).upper() in ("B", "", eo) for s, side in covering):
            continue
        s, side = covering[0]
        decl = declared(s, side)
        out.append(ErrorRecord(
            "XLAYER-03", "Address parity disagrees with segment side parity",
            FAMILY.CROSS, SEVERITY.WARNING, "address", a["_OID"],
            a.get("Site_NGUID", "") or "",
            "parity %s vs side %s (SEG %s)" % (eo, decl, seg_label(s)), a.get("_XY")))
    return out


@registry.check(id="XLAYER-13", family=FAMILY.CROSS, severity=SEVERITY.WARNING,
                priority="v1", target="address")
def check_xlayer_13(addresses, streets, ctx):
    """Geometric side (from geom) disagrees with parity-implied side. Needs geometry."""
    if ctx.geom_provider is None:
        return []
    out = []
    for a in addresses:
        covering = _covering_segments(a, ctx)
        if not covering or a.get("_XY") is None:
            continue
        pt = arcpy_point(a["_XY"])
        # Pick the NEAREST covering segment whose perpendicular foot is INTERIOR.
        # A foot at a segment endpoint gives an undefined left/right side (the point
        # is off the end, not beside the line), which produced spurious wrong-side
        # findings under covering[0]. Among interior-foot covering segments take the
        # closest; if none have an interior foot the geometric side is undefined.
        best = None  # (dist, seg, parity_side, right_side)
        for s, parity_side in covering:
            seg_geom = ctx.geom("street", s["_OID"])
            if seg_geom is None:
                continue
            res = seg_geom.queryPointAndDistance(pt)
            along, dist, right = res[1], res[2], res[3]
            if along <= 0.5 or along >= seg_geom.length - 0.5:
                continue  # foot at an endpoint -> side undefined
            if best is None or dist < best[0]:
                best = (dist, s, parity_side, right)
        if best is None:
            continue
        _, s, parity_side, right = best
        geom_side = "Right" if right else "Left"
        if parity_side in ("Left", "Right") and geom_side != parity_side:
            out.append(ErrorRecord(
                "XLAYER-13", "Address on wrong side of centerline for its parity",
                FAMILY.CROSS, SEVERITY.WARNING, "address", a["_OID"],
                a.get("Site_NGUID", "") or "",
                "geometric side %s != parity side %s (SEG %s)" % (geom_side, parity_side, seg_label(s)),
                a.get("_XY")))
    return out


@registry.check(id="XLAYER-05", family=FAMILY.CROSS, severity=SEVERITY.WARNING,
                priority="v1", target="address", default_on=False)
def check_xlayer_05(addresses, streets, ctx):
    """Address within distance of nearest same-name centerline segment."""
    if ctx.geom_provider is None:
        return []
    out = []
    tol = ctx.distance_tolerance_ft
    for a in addresses:
        if not is_addressable(a):
            continue   # placeholder points are reported once by ADDR-08
        if a.get("_XY") is None:
            continue
        candidates = ctx.streets_by_name.get(a["_NAMEKEY"], ())
        if not candidates:
            continue  # no same-name segment -> XLAYER-02's job
        pt = arcpy_point(a["_XY"])
        dists = []
        for s in candidates:
            seg_geom = ctx.geom("street", s["_OID"])
            if seg_geom is None:
                continue
            dists.append(seg_geom.distanceTo(pt))
        if not dists:
            continue
        d = min(dists)
        if d > tol:
            # A far address whose number nonetheless falls within a same-name
            # segment's L/R range is a benign large-lot / deep-setback case, not a
            # geocoding defect. Downgrade those to INFO; reserve WARNING for the
            # genuinely unserved tail (far AND out of every same-name range).
            in_range = bool(_range_only_segments(a, ctx))
            sev = SEVERITY.INFO if in_range else SEVERITY.WARNING
            title = ("Address far from nearest same-name segment (in-range setback)"
                     if in_range else "Address far from nearest same-name segment")
            out.append(ErrorRecord(
                "XLAYER-05", title, FAMILY.CROSS,
                sev, "address", a["_OID"], a.get("Site_NGUID", "") or "",
                "%.1f ft from nearest '%s' segment (> %.0f ft)" % (d, a["_NAMEKEY"], tol),
                a.get("_XY")))
        # Only the outlier tail (d > tolerance) is reported. The sub-tolerance band is
        # the rural-setback norm, not a defect, so it is intentionally not emitted
        # (per NENA practice: distance is a plausibility heuristic, not a conformance
        # failure; report only outliers). Calibrate the tail via distance_tolerance_ft.
    return out


_NAME_DIR_EXPAND = {"NB": "NORTHBOUND", "SB": "SOUTHBOUND",
                    "EB": "EASTBOUND", "WB": "WESTBOUND"}
_INTERSTATE_RE = re.compile(r"^I-?(\d+)$")   # I75 / I-75 -> INTERSTATE 75

# A leading "ST" in the legacy name is expanded to SAINT only in front of one of these.
# "ST" is overwhelmingly the STREET type abbreviation, so a blanket ST->SAINT rule would
# wreck every ordinary road; this is the closed set of local road names where the county
# confirmed the ST means Saint (St_Name spells them "Saint Augustine" etc.). Add a name here
# if a new Saint road is created -- nothing infers it from the data.
_SAINT_NAMES = frozenset({"AUGUSTINE", "BENEDICT", "GEORGE", "LAWRENCE", "PATRICK", "PETER"})


def _expand_name_tokens(tokens):
    """Expand abbreviations the legacy STREET_NA/NAME carries but the NENA St_Name spells
    out: bound-directionals (NB->NORTHBOUND ...), interstates (I75/I-75 -> INTERSTATE 75) and
    a leading Saint (ST BENEDICT -> SAINT BENEDICT, only for _SAINT_NAMES). Lets 'NB I75'
    agree with 'Northbound Interstate 75' instead of false-flagging XLAYER-10."""
    out = []
    for idx, t in enumerate(tokens):
        m = _INTERSTATE_RE.match(t)
        if m:
            out.extend(("INTERSTATE", m.group(1)))
        elif t == "ST" and idx + 1 < len(tokens) and tokens[idx + 1] in _SAINT_NAMES:
            out.append("SAINT")
        else:
            out.append(_NAME_DIR_EXPAND.get(t, t))
    return out


def _name_matches_stname(legacy, stname, pretyp):
    """True if the legacy combined name agrees with the NENA St_Name. Exact match; or the
    legacy name's directional/interstate abbreviations expand to St_Name ('NB I75' ==
    'Northbound Interstate 75'); or (when a route pre-type is present) St_Name is the
    trailing token-run of the legacy name -- so 'HWY 318' / St_Name '318' / St_PreTyp
    'Highway' agrees."""
    nl, ns = normalize(legacy), normalize(stname)
    if nl == ns:
        return True
    if not ns:
        return False
    st = ns.split()
    elt = _expand_name_tokens(nl.split())
    if elt == st:
        return True
    if _clean(pretyp) == "":
        return False
    return len(st) <= len(elt) and elt[-len(st):] == st


@registry.check(id="XLAYER-10", family=FAMILY.CROSS, severity=SEVERITY.WARNING,
                priority="v1", target="both")
def check_xlayer_10(addresses, streets, ctx):
    """Abbrev PREFIX/TYPE must cross-walk to full-name St_PreDir/St_PosTyp."""
    cw = ctx.crosswalks
    out = []

    def _blank(v):
        return (v or "").strip() == ""

    def _up(v):
        return (v or "").strip().upper()

    def _check(rows, name_fld, layer, nguid_fld):
        for r in rows:
            oid, nguid, xy = r["_OID"], r.get(nguid_fld, "") or "", r.get("_XY")
            # PREFIX <-> St_PreDir
            pre, full = r.get("PREFIX"), r.get("St_PreDir")
            if _blank(pre) and _blank(full):
                pass
            elif _blank(pre) != _blank(full):
                out.append(ErrorRecord(
                    "XLAYER-10", "Prefix vs St_PreDir presence mismatch", FAMILY.CROSS,
                    SEVERITY.WARNING, layer, oid, nguid,
                    "PREFIX %r vs St_PreDir %r (one blank)" % (pre, full), xy))
            else:
                if not cw.valid_dir_abbrev(pre):
                    out.append(ErrorRecord(
                        "XLAYER-10", "Prefix abbrev unmapped", FAMILY.CROSS,
                        SEVERITY.WARNING, layer, oid, nguid,
                        "PREFIX %r unmapped" % pre, xy))
                elif not cw.dir_ok(pre, full):
                    out.append(ErrorRecord(
                        "XLAYER-10", "Prefix does not cross-walk to St_PreDir", FAMILY.CROSS,
                        SEVERITY.WARNING, layer, oid, nguid,
                        "PREFIX %r != St_PreDir %r" % (pre, full), xy))
            # TYPE <-> St_PosTyp
            typ, tfull = r.get("TYPE"), r.get("St_PosTyp")
            if _blank(typ) and _blank(tfull):
                pass
            elif _blank(typ) != _blank(tfull):
                out.append(ErrorRecord(
                    "XLAYER-10", "Type vs St_PosTyp presence mismatch", FAMILY.CROSS,
                    SEVERITY.WARNING, layer, oid, nguid,
                    "TYPE %r vs St_PosTyp %r (one blank)" % (typ, tfull), xy))
            else:
                if not cw.valid_type_abbrev(typ):
                    out.append(ErrorRecord(
                        "XLAYER-10", "Type abbrev unmapped", FAMILY.CROSS,
                        SEVERITY.WARNING, layer, oid, nguid,
                        "TYPE %r unmapped" % typ, xy))
                elif not cw.type_ok(typ, tfull):
                    out.append(ErrorRecord(
                        "XLAYER-10", "Type does not cross-walk to St_PosTyp", FAMILY.CROSS,
                        SEVERITY.WARNING, layer, oid, nguid,
                        "TYPE %r != St_PosTyp %r" % (typ, tfull), xy))
            # name <-> St_Name. The legacy combined name embeds a route pre-type
            # ("HWY 318", "NFR 38") that NENA splits into St_PreTyp ("Highway") +
            # St_Name ("318"). So accept when St_Name's tokens are the TRAILING tokens
            # of the legacy name (i.e. legacy = <pre-type> + St_Name); flag otherwise.
            if not _name_matches_stname(r.get(name_fld), r.get("St_Name"), r.get("St_PreTyp")):
                out.append(ErrorRecord(
                    "XLAYER-10", "Name does not match St_Name", FAMILY.CROSS,
                    SEVERITY.WARNING, layer, oid, nguid,
                    "%s %r != St_Name %r" % (name_fld, r.get(name_fld), r.get("St_Name")), xy))

    _check(addresses, "STREET_NA", "address", "Site_NGUID")
    _check(streets, "NAME", "street", "RCL_NGUID")
    return out


@registry.check(id="XLAYER-06", family=FAMILY.CROSS, severity=SEVERITY.WARNING,
                priority="v1", target="address", default_on=False)
def check_xlayer_06(addresses, streets, ctx):
    """Address city/ZIP must match the covering segment side's city/ZIP."""
    out = []
    for a in addresses:
        if not is_addressable(a):
            continue
        covering = _covering_segments(a, ctx)
        if not covering:
            continue
        # Compare only against a segment that truly carries the address's name.
        # _candidate_segments can surface a same-COMPARE segment of a different
        # real street; its city/ZIP must not be asserted against this address.
        addr_comp = normalize(a.get("PREFIX"), a.get("STREET_NA"),
                              a.get("TYPE"), a.get("SUFFIX"))
        name_matched = [(s, side) for (s, side) in covering
                        if normalize(s.get("PREFIX"), s.get("NAME"),
                                     s.get("TYPE"), s.get("SUFFIX")) == addr_comp]
        if not name_matched:
            continue
        s, side = name_matched[0]
        # A BOTH-covering segment (overlapping L/R ranges) could legitimately put the
        # address on either side, so check both and flag only if it matches NEITHER.
        if side == "Left":
            cands = [("Left", s.get("LCITY"), s.get("LEFTZIP"))]
        elif side == "Right":
            cands = [("Right", s.get("RCITY"), s.get("RIGHTZIP"))]
        else:
            cands = [("Left", s.get("LCITY"), s.get("LEFTZIP")),
                     ("Right", s.get("RCITY"), s.get("RIGHTZIP"))]
        a_city = a.get("CITY")
        side_cities = [normalize(c) for (_sd, c, _z) in cands if normalize(c)]
        if normalize(a_city) and side_cities and normalize(a_city) not in side_cities:
            out.append(ErrorRecord(
                "XLAYER-06", "Address city does not match covering segment side city",
                FAMILY.CROSS, SEVERITY.WARNING, "address", a["_OID"],
                a.get("Site_NGUID", "") or "",
                "CITY %r != side %s CITY %r (SEG %s)"
                % (a_city, side, [c for (_sd, c, _z) in cands], seg_label(s)),
                a.get("_XY")))
        a_zip = _clean(a.get("ZIP_CODE"))[:5]
        side_zips = [_clean(z)[:5] for (_sd, _c, z) in cands if _clean(z)[:5]]
        if a_zip and side_zips and a_zip not in side_zips:
            out.append(ErrorRecord(
                "XLAYER-06", "Address ZIP does not match covering segment side ZIP",
                FAMILY.CROSS, SEVERITY.WARNING, "address", a["_OID"],
                a.get("Site_NGUID", "") or "",
                "ZIP %s != side %s ZIP %s (SEG %s)" % (a_zip, side, side_zips, seg_label(s)),
                a.get("_XY")))
    return out


@registry.check(id="XLAYER-04", family=FAMILY.CROSS, severity=SEVERITY.ERROR,
                priority="v1-core", target="both")
def check_xlayer_04(addresses, streets, ctx):
    out = []
    for a in addresses:
        if not is_addressable(a):
            continue
        # Key name-presence on the address's TRUE components, not the
        # COMPARE-derived _NAMEKEY: a stale COMPARE can name a road that does not
        # carry this address while masking the absence of its real street name.
        # (Same stale-COMPARE calibration as engine.build_context's raw_key index.)
        akey = normalize(a.get("PREFIX"), a.get("STREET_NA"), a.get("TYPE"), a.get("SUFFIX"))
        if not akey or ctx.name_ignored(akey):
            continue
        # Case (1) "name mismatch with matched road" is structurally impossible
        # here: covering segments are looked up by the address's own name key, so
        # a covering segment's name always equals the address name. Without a
        # name-independent (geometric) covering lookup there is nothing to compare,
        # so XLAYER-04 enforces only case (2): the name must exist in centerlines.
        if akey not in ctx.streets_by_name:
            out.append(ErrorRecord(
                "XLAYER-04", "Street name not present in centerlines", FAMILY.CROSS,
                SEVERITY.ERROR, "address", a["_OID"], a.get("Site_NGUID", "") or "",
                "no centerline named '%s'" % akey, a.get("_XY")))
    return out


@registry.check(id="XLAYER-04b", family=FAMILY.CROSS, severity=SEVERITY.WARNING,
                priority="v1", target="both")
def check_xlayer_04b(addresses, streets, ctx):
    """COMPARE integrity: stored COMPARE should equal recomputed (pre-normalization)."""
    out = []
    addr_blank = 0
    for a in addresses:
        # Placeholders (Add_Number 0 / blank name) are reported once by ADDR-08;
        # peer address-content checks all gate on is_addressable, so do the same
        # here rather than re-flagging their (legitimately blank) COMPARE.
        if not is_addressable(a):
            continue
        want = normalize(a.get("PREFIX"), a.get("STREET_NA"), a.get("TYPE"), a.get("SUFFIX"))
        if _clean(a.get("COMPARE")) == "":
            addr_blank += 1   # cache simply not populated — uniform, summarized below
            continue
        if normalize(a.get("COMPARE")) != want:
            out.append(ErrorRecord("XLAYER-04b", "Address COMPARE inconsistent", FAMILY.CROSS,
                                   SEVERITY.WARNING, "address", a["_OID"], a.get("Site_NGUID", "") or "",
                                   "COMPARE %r != %r" % (a.get("COMPARE"), want), a.get("_XY")))
    whitespace_count = 0
    street_blank = 0
    for s in streets:
        raw = s.get("COMPARE")
        want = normalize(s.get("PREFIX"), s.get("NAME"), s.get("TYPE"), s.get("SUFFIX"))
        if _clean(raw) == "":
            street_blank += 1
            continue
        if normalize(raw) != want:
            out.append(ErrorRecord("XLAYER-04b", "Street COMPARE inconsistent", FAMILY.CROSS,
                                   SEVERITY.WARNING, "street", s["_OID"], s.get("RCL_NGUID", "") or "",
                                   "COMPARE norm mismatch", s.get("_XY")))
        elif raw != raw.strip():
            whitespace_count += 1
    # A blank COMPARE cache is a uniform "not populated" condition, not a per-row defect;
    # summarize it (one INFO per layer) instead of emitting thousands of WARNINGs. Genuine
    # drift (COMPARE present but != recomputed) still WARNs per row above.
    for cnt, layer, label in ((addr_blank, "address", "address points"),
                              (street_blank, "street", "segments")):
        if cnt:
            out.append(ErrorRecord("XLAYER-04b", "COMPARE cache empty", FAMILY.CROSS,
                                   SEVERITY.INFO, layer, 0, "",
                                   "%d %s have an empty COMPARE cache (not populated)"
                                   % (cnt, label), None))
    if whitespace_count:
        out.append(ErrorRecord("XLAYER-04b", "Street COMPARE has surrounding whitespace",
                               FAMILY.CROSS, SEVERITY.INFO, "street", 0, "",
                               "%d segments have surrounding whitespace in COMPARE "
                               "(uniform convention)" % whitespace_count, None))
    return out


from collections import Counter


@registry.check(id="XLAYER-07", family=FAMILY.CROSS, severity=SEVERITY.ERROR,
                priority="v1-core", target="both")
def check_xlayer_07(addresses, streets, ctx):
    out = []
    for rows, fld, layer in ((addresses, "Site_NGUID", "address"), (streets, "RCL_NGUID", "street")):
        counts = Counter((r.get(fld) or "").strip() for r in rows if (r.get(fld) or "").strip())
        dup = {k for k, n in counts.items() if n > 1}
        for r in rows:
            v = (r.get(fld) or "").strip()
            if v in dup:
                out.append(ErrorRecord("XLAYER-07", "Duplicate NGUID", FAMILY.CROSS,
                                       SEVERITY.ERROR, layer, r["_OID"], v,
                                       "NGUID %s not unique" % v, r.get("_XY")))
    return out


@registry.check(id="XLAYER-08", family=FAMILY.CROSS, severity=SEVERITY.ERROR,
                priority="v1", target="both")
def check_xlayer_08(addresses, streets, ctx):
    out = []
    fqdn_failed = False
    for rows, fld, layer in ((addresses, "Site_NGUID", "address"),
                             (streets, "RCL_NGUID", "street")):
        for r in rows:
            raw = r.get("DiscrpAgID")
            nguid = (r.get(fld) or "")
            xy = r.get("_XY")
            # Tier 1: presence / no internal whitespace
            if raw is None or str(raw).strip() == "" or str(raw) != str(raw).strip() \
                    or any(c.isspace() for c in str(raw)):
                out.append(ErrorRecord(
                    "XLAYER-08", "DiscrpAgID blank or contains whitespace", FAMILY.CROSS,
                    SEVERITY.ERROR, layer, r["_OID"], nguid,
                    "DiscrpAgID %r invalid (blank/whitespace)" % raw, xy))
                continue
            agid = _clean(raw)
            # Tier 2: consistency with expected modal value (case-insensitive domain; matches ADDR-06)
            if agid.casefold() != ctx.expected_agid.casefold():
                out.append(ErrorRecord(
                    "XLAYER-08", "DiscrpAgID inconsistent with expected value", FAMILY.CROSS,
                    SEVERITY.ERROR, layer, r["_OID"], nguid,
                    "DiscrpAgID '%s' != expected '%s'" % (agid, ctx.expected_agid), xy))
                continue
            # Tier 3: strict NENA bare-FQDN format (suppressible). Validate the
            # domain part of a localid@domain value, not the whole '@' string.
            domain = agid.split("@", 1)[-1] if "@" in agid else agid
            if not _FQDN_RE.match(domain):
                fqdn_failed = True
    if ctx.strict_fqdn and fqdn_failed:
        out.append(ErrorRecord(
            "XLAYER-08", "DiscrpAgID not a strict NENA FQDN", FAMILY.CROSS,
            SEVERITY.WARNING, "dataset", 0, "",
            "DiscrpAgID '%s' fails strict NENA bare-FQDN format" % ctx.expected_agid, None))
    return out


@registry.check(id="XLAYER-09", family=FAMILY.CROSS, severity=SEVERITY.WARNING,
                priority="v1", target="both")
def check_xlayer_09(addresses, streets, ctx):
    """State/country/county validity for addresses and street sides."""
    cw = ctx.crosswalks
    out = []

    def _v(val):
        return (val or "").strip().upper()

    for a in addresses:
        oid, nguid, xy = a["_OID"], a.get("Site_NGUID", "") or "", a.get("_XY")
        state = _v(a.get("STATE"))
        if state and state not in cw.states:
            out.append(ErrorRecord("XLAYER-09", "Address STATE not a valid USPS code",
                                   FAMILY.CROSS, SEVERITY.ERROR, "address", oid, nguid,
                                   "STATE %r invalid" % a.get("STATE"), xy))
        elif state and state != "FL":
            out.append(ErrorRecord("XLAYER-09", "Address STATE not FL", FAMILY.CROSS,
                                   SEVERITY.WARNING, "address", oid, nguid,
                                   "STATE %r != FL" % a.get("STATE"), xy))
        country = _v(a.get("Country"))
        if not country:
            out.append(ErrorRecord("XLAYER-09", "Address Country blank", FAMILY.CROSS,
                                   SEVERITY.ERROR, "address", oid, nguid,
                                   "Country blank", xy))
        elif country not in cw.countries:
            out.append(ErrorRecord("XLAYER-09", "Address Country not canonical", FAMILY.CROSS,
                                   SEVERITY.WARNING, "address", oid, nguid,
                                   "Country %r not canonical" % a.get("Country"), xy))
        county = _v(a.get("COUNTY"))
        if not county:
            out.append(ErrorRecord("XLAYER-09", "Address COUNTY blank", FAMILY.CROSS,
                                   SEVERITY.ERROR, "address", oid, nguid,
                                   "COUNTY blank", xy))
        elif cw.county_canonical(a.get("COUNTY")) not in cw.fl_counties:
            out.append(ErrorRecord("XLAYER-09", "Address COUNTY not in FL set", FAMILY.CROSS,
                                   SEVERITY.WARNING, "address", oid, nguid,
                                   "COUNTY %r not in FL set" % a.get("COUNTY"), xy))

    for s in streets:
        oid, nguid, xy = s["_OID"], s.get("RCL_NGUID", "") or "", s.get("_XY")
        for fld in ("State_L", "State_R"):
            state = _v(s.get(fld))
            if state and state not in cw.states:
                out.append(ErrorRecord("XLAYER-09", "Street %s not a valid USPS code" % fld,
                                       FAMILY.CROSS, SEVERITY.ERROR, "street", oid, nguid,
                                       "%s %r invalid" % (fld, s.get(fld)), xy))
            elif state and state != "FL":
                out.append(ErrorRecord("XLAYER-09", "Street %s not FL" % fld, FAMILY.CROSS,
                                       SEVERITY.WARNING, "street", oid, nguid,
                                       "%s %r != FL" % (fld, s.get(fld)), xy))
        for fld in ("County_L", "County_R"):
            county = _v(s.get(fld))
            if not county:
                out.append(ErrorRecord("XLAYER-09", "Street %s blank" % fld, FAMILY.CROSS,
                                       SEVERITY.ERROR, "street", oid, nguid,
                                       "%s blank" % fld, xy))
            elif cw.county_canonical(s.get(fld)) not in cw.fl_counties:
                out.append(ErrorRecord("XLAYER-09", "Street %s not in FL set" % fld, FAMILY.CROSS,
                                       SEVERITY.WARNING, "street", oid, nguid,
                                       "%s %r not in FL set" % (fld, s.get(fld)), xy))
        cl, cr = cw.county_canonical(s.get("County_L")), cw.county_canonical(s.get("County_R"))
        if cl and cr and cl != cr:   # a blank side is already an ERROR above; don't double-fire
            out.append(ErrorRecord("XLAYER-09", "Street County_L != County_R", FAMILY.CROSS,
                                   SEVERITY.INFO, "street", oid, nguid,
                                   "County_L %r != County_R %r" % (s.get("County_L"), s.get("County_R")), xy))
    return out


def _side_ranges(s):
    """Yield (frm, to, parity) for each addressable side of a segment."""
    for frm_f, to_f, par_f in (("FROMLEFT", "TOLEFT", "Parity_L"),
                               ("FROMRIGHT", "TORIGHT", "Parity_R")):
        frm, to = s.get(frm_f), s.get(to_f)
        if frm is None or to is None:
            continue
        lo, hi = min(frm, to), max(frm, to)
        if lo <= 0 or hi <= 0:   # skip broken (0/negative-endpoint) ranges, not just 0-0
            continue
        yield lo, hi, s.get(par_f)


@registry.check(id="XLAYER-14", family=FAMILY.CROSS, severity=SEVERITY.INFO,
                priority="v1", target="street")
def check_xlayer_14(addresses, streets, ctx):
    """Addressable side range with no covering active address points."""
    out = []
    for s in streets:
        ranges = list(_side_ranges(s))
        if not ranges:
            continue
        # Look up covering addresses under BOTH the segment's COMPARE-derived
        # _NAMEKEY and its true component name: a stale COMPARE otherwise hides the
        # address points that actually carry the segment's name. Widening candidates
        # can only reveal real coverage, never mask a true coverage gap.
        raw = normalize(s.get("PREFIX"), s.get("NAME"), s.get("TYPE"), s.get("SUFFIX"))
        cands = list(ctx.addresses_by_name.get(s["_NAMEKEY"], ()))
        if raw and raw != s["_NAMEKEY"]:
            cands += ctx.addresses_by_name.get(raw, ())
        any_covered = False
        for lo, hi, par in ranges:
            for a in cands:
                if not is_addressable(a):
                    continue
                try:
                    hno = int(a.get("Add_Number"))
                except (TypeError, ValueError):
                    continue
                p = "E" if hno % 2 == 0 else "O"
                pv = _clean(par).upper()   # NULL/lowercase parity -> normalized
                # Only an explicit E/O gates by parity; B/blank/Z/mislabeled match by
                # range alone (a bad parity code is STREET-02/09's defect, not a reason
                # to falsely report this real range as having no covering address).
                if lo <= hno <= hi and (pv not in ("E", "O") or pv == p):
                    any_covered = True
                    break
            if any_covered:
                break
        if not any_covered:
            out.append(ErrorRecord(
                "XLAYER-14", "Addressable range with no covering address points",
                FAMILY.CROSS, SEVERITY.INFO, "street", s["_OID"],
                s.get("RCL_NGUID", "") or "",
                "no active address covers any side range of SEG %s ('%s')"
                % (seg_label(s), s["_NAMEKEY"]), s.get("_XY")))
    return out


@registry.check(id="XLAYER-11", family=FAMILY.CROSS, severity=SEVERITY.INFO,
                priority="v1", target="both", default_on=False)
def check_xlayer_11(addresses, streets, ctx):
    """ALI/MSAG-to-GIS sync metric: % of addressable addresses fully reconciling."""
    active = [a for a in addresses if is_addressable(a)]
    failing_oids = set()
    for check in (check_xlayer_01, check_xlayer_02, check_xlayer_03, check_xlayer_04):
        for r in check(addresses, streets, ctx):
            if r.source_layer == "address":
                failing_oids.add(r.source_oid)
    total = len(active)
    reconciling = sum(1 for a in active if a["_OID"] not in failing_oids)
    sync_rate = 100.0 * reconciling / total if total else 100.0
    out = [ErrorRecord(
        "XLAYER-11", "ALI/MSAG-to-GIS synchronization metric", FAMILY.CROSS,
        SEVERITY.INFO, "dataset", 0, "",
        "sync_rate %.1f%% (%d/%d active reconcile); %d not reconciling "
        "(see XLAYER-01/02/03/04 for the per-address findings)"
        % (sync_rate, reconciling, total, len(failing_oids)), None)]
    if sync_rate < ctx.sync_threshold:
        out.append(ErrorRecord(
            "XLAYER-11", "ALI/MSAG-to-GIS sync below target", FAMILY.CROSS,
            SEVERITY.WARNING, "dataset", 0, "",
            "sync_rate %.1f%% < target %.1f%%" % (sync_rate, ctx.sync_threshold), None))
    return out


@registry.check(id="XLAYER-15", family=FAMILY.CROSS, severity=SEVERITY.WARNING,
                priority="v1", target="both")
def check_xlayer_15(addresses, streets, ctx):
    """NENA modifier/separator domain conformance (MapSAG parity): populated
    St_PreMod / St_PosMod / St_PreSep must be valid domain values. Blank skipped."""
    cw = ctx.crosswalks
    checks = (("St_PreMod", cw.valid_premod, "pre-modifier"),
              ("St_PosMod", cw.valid_postmod, "post-modifier"),
              ("St_PreSep", cw.valid_pretypesep, "pre-type separator"))
    out = []
    for rows, layer, nguid_fld in ((addresses, "address", "Site_NGUID"),
                                   (streets, "street", "RCL_NGUID")):
        for r in rows:
            for fld, is_valid, label in checks:
                v = _clean(r.get(fld))
                if v and not is_valid(v):
                    out.append(ErrorRecord(
                        "XLAYER-15", "Invalid %s value" % label, FAMILY.CROSS,
                        SEVERITY.WARNING, layer, r["_OID"], r.get(nguid_fld, "") or "",
                        "%s %r not in domain" % (fld, r.get(fld)), r.get("_XY")))
    return out


def _msag_rec_label(rec):
    """Human-readable identity for an MSAG/GIS rolled-up record dict."""
    return "%s | %s | %s..%s | parity %s | ESN %s" % (
        rec.get("community", ""), rec.get("name_key", ""),
        rec.get("low"), rec.get("high"),
        rec.get("parity", "") or "?", rec.get("esn", "") or "?")


@registry.check(id="XLAYER-16", family=FAMILY.CROSS, severity=SEVERITY.WARNING,
                priority="v2", target="both", default_on=False)
def check_xlayer_16(addresses, streets, ctx):
    """MSAG <-> GIS reconciliation (NENA 71-501, opt-in).

    No-ops unless an MSAG source has been loaded onto the context
    (engine.build_msag_context). Emits one ERROR per GIS range with no MSAG
    coverage, one WARNING per MSAG record with no GIS coverage (after
    exceptions), one WARNING per ESN attribute mismatch, one WARNING per RANGE mismatch (same road in
    both sources, different low/high), and one INFO summary
    carrying the match-rate KPI vs the NENA floor.
    """
    if ctx.msag_records is None:
        return []
    res = msag.reconcile(ctx.msag_records, ctx.gis_msag or [], ctx.msag_exceptions,
                         addr_index=getattr(ctx, "msag_addr_index", None))
    ctx.msag_match_rate = res["match_rate"]
    out = []
    for g in res["gis_not_msag"]:
        # Attribute/locate to the originating centerline so the finding is mappable.
        out.append(ErrorRecord(
            "XLAYER-16", "GIS range not in MSAG", FAMILY.CROSS, SEVERITY.ERROR,
            "street", g.get("_oid", 0), "",
            "GIS centerline range has no MSAG coverage: %s" % _msag_rec_label(g),
            g.get("_xy")))
    for m in res["msag_not_gis"]:
        out.append(ErrorRecord(
            "XLAYER-16", "MSAG record not in GIS", FAMILY.CROSS, SEVERITY.WARNING,
            "street", 0, "",
            "MSAG record has no GIS coverage: %s" % _msag_rec_label(m),
            None))
    for rm in res.get("range_mismatch", []):
        # Report it the way MapSAG does: the same road stated once per source, so the analyst
        # sees WHICH endpoint moved without cross-referencing two other buckets.
        # ONE finding per MSAG record, against the AGGREGATE GIS extent -- Example splits a
        # road into many short centerline segments, so emitting one finding per overlapping
        # segment turned 72 real disagreements into 800 lines that all restated the same MSAG
        # range. The span plus the segment count is the actionable form.
        m = rm["msag"]
        lows = [g.get("low") for g in rm["gis"] if g.get("low") is not None]
        highs = [g.get("high") for g in rm["gis"] if g.get("high") is not None]
        anchor = rm["gis"][0]
        g_lo = min(lows) if lows else None
        g_hi = max(highs) if highs else None
        gaps = msag.uncovered_for_record(m, rm.get("group") or rm["gis"])
        gap_txt = ", ".join("%s-%s" % (a, b) if a != b else str(a) for a, b in gaps)
        if (g_lo, g_hi) != (m.get("low"), m.get("high")):
            what = ("GIS %s-%s vs INHOUSE_MSAG %s-%s" % (g_lo, g_hi, m.get("low"), m.get("high")))
        else:
            # Endpoints agree; the disagreement is a hole inside the span.
            what = ("GIS and INHOUSE_MSAG both %s-%s, but GIS coverage has gaps"
                    % (m.get("low"), m.get("high")))
        out.append(ErrorRecord(
            "XLAYER-16", "MSAG/GIS range mismatch", FAMILY.CROSS, SEVERITY.WARNING,
            "street", anchor.get("_oid", 0), "",
            "Range differs for the same road: %s (%d GIS segment%s%s)  (%s)"
            % (what, len(rm["gis"]), "" if len(rm["gis"]) == 1 else "s",
               ("; not covered by GIS: " + gap_txt) if gap_txt else "",
               _msag_rec_label(m)),
            anchor.get("_xy")))
    for mm in res["attr_mismatch"]:
        out.append(ErrorRecord(
            "XLAYER-16", "MSAG/GIS ESN mismatch", FAMILY.CROSS, SEVERITY.WARNING,
            "street", 0, "",
            "%s (%s)" % (mm["reason"], _msag_rec_label(mm["msag"])),
            None))
    rate = res["match_rate"]
    floor = ctx.min_match_rate
    out.append(ErrorRecord(
        "XLAYER-16", "MSAG match-rate KPI", FAMILY.CROSS, SEVERITY.INFO,
        "street", 0, "",
        "MSAG match rate %.2f%% (matched %d/%d eligible); NENA floor %.2f%% -> %s "
        "[unmatched: %d range mismatch, %d not in GIS, %d gap-with-no-address]" % (
            rate * 100.0, res["counts"]["matched"],
            res["counts"]["msag_total"] - res["counts"]["excepted"],
            floor * 100.0, "OK" if rate >= floor else "BELOW FLOOR",
            res["counts"].get("range_mismatch", 0), res["counts"]["msag_not_gis"],
            res["counts"].get("addr_gated", 0)),
        None))
    return out
