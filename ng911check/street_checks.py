"""street_attr checks: one centerline segment at a time, plus the range and name tests."""
import re
from .model import ErrorRecord, SEVERITY, FAMILY
from .common import normalize, get_parity, esn_eq, nguid_partition, _clean, seg_label
from . import registry


def _side_parity(frm, to):
    """Per-side parity. Exactly one null endpoint = incomplete range (defer to
    STREET-10) -> None; both null -> '0-0'. Evaluating per side so a fully-null
    opposite side no longer blocks a real parity defect on the populated side."""
    if (frm is None) != (to is None):
        return None
    return get_parity(frm, to)


@registry.check(id="STREET-01", family=FAMILY.STREET, severity=SEVERITY.ERROR,
                priority="v1-core", target="street",
                emits=(SEVERITY.ERROR,), summary="Flag a street side whose range ends mix parity, or two sides that share one parity.",
                fields=("FROMLEFT", "FROMRIGHT", "RCL_NGUID", "TOLEFT", "TORIGHT",), requires=())
def check_street_01(addresses, streets, ctx):
    out = []
    for s in streets:
        pL = _side_parity(s.get("FROMLEFT"), s.get("TOLEFT"))
        pR = _side_parity(s.get("FROMRIGHT"), s.get("TORIGHT"))
        msg = None
        if pL in ("Error", "Both") or pR in ("Error", "Both"):
            msg = "invalid/mixed parity L=%s R=%s" % (pL, pR)
        elif pL is not None and pL == pR and pL != "0-0":
            msg = "both sides parity %s" % pL
        if msg:
            out.append(ErrorRecord("STREET-01", "Invalid address range", FAMILY.STREET,
                                   SEVERITY.ERROR, "street", s["_OID"], s.get("RCL_NGUID", "") or "",
                                   msg, s.get("_XY")))
    return out


def _par(n):
    return "E" if abs(n) % 2 == 0 else "O"


@registry.check(id="STREET-02", family=FAMILY.STREET, severity=SEVERITY.ERROR,
                priority="v1-core", target="street",
                emits=(SEVERITY.ERROR, SEVERITY.WARNING,), summary="Flag a declared side parity that the range does not support.",
                fields=("FROMLEFT", "FROMRIGHT", "Parity_L", "Parity_R", "RCL_NGUID",
                        "TOLEFT", "TORIGHT",), requires=())
def check_street_02(addresses, streets, ctx):
    out = []
    for s in streets:
        for frm, to, dec, nm in ((s.get("FROMLEFT"), s.get("TOLEFT"), s.get("Parity_L"), "L"),
                                 (s.get("FROMRIGHT"), s.get("TORIGHT"), s.get("Parity_R"), "R")):
            dec = _clean(dec).upper()   # normalize lowercase/padded parity like STREET-09
            if (frm or 0) == 0 and (to or 0) == 0:   # NULL treated as 0 (unused side)
                if dec != "Z":
                    out.append(ErrorRecord("STREET-02", "Side parity inconsistent", FAMILY.STREET,
                                           SEVERITY.WARNING, "street", s["_OID"], s.get("RCL_NGUID", "") or "",
                                           "%s 0-0 but parity=%s (expect Z)" % (nm, dec), s.get("_XY")))
            elif dec == "Z":
                out.append(ErrorRecord("STREET-02", "Side parity inconsistent", FAMILY.STREET,
                                       SEVERITY.ERROR, "street", s["_OID"], s.get("RCL_NGUID", "") or "",
                                       "%s parity Z but range %s-%s not 0-0"
                                       % (nm, _clean(frm), _clean(to)), s.get("_XY")))
            elif dec in ("E", "O") and frm is not None and to is not None:
                if not (_par(frm) == _par(to) == dec):
                    out.append(ErrorRecord("STREET-02", "Side parity inconsistent", FAMILY.STREET,
                                           SEVERITY.ERROR, "street", s["_OID"], s.get("RCL_NGUID", "") or "",
                                           "%s parity %s vs ends %s/%s"
                                           % (nm, dec, _clean(frm), _clean(to)), s.get("_XY")))
    return out


def _side_intervals(streets):
    """Yield (name_key, parity_class, lo, hi, seg) per addressable side. parity_class in {'E','O'}."""
    for s in streets:
        truename = normalize(s.get("PREFIX"), s.get("NAME"), s.get("TYPE"), s.get("SUFFIX"))
        for frm, to, par in ((s.get("FROMLEFT"), s.get("TOLEFT"), s.get("Parity_L")),
                             (s.get("FROMRIGHT"), s.get("TORIGHT"), s.get("Parity_R"))):
            if frm is None or to is None:
                continue
            lo, hi = min(frm, to), max(frm, to)
            if lo == 0 and hi == 0:
                continue
            pv = _clean(par).upper()   # NULL/lowercase/padded parity -> normalized
            # A blank OR an invalid/unknown parity code (e.g. 'Z' or a typo) on a real
            # nonzero range is expanded to BOTH E and O, so a bad parity value can't hide
            # the side's overlap/gap from STREET-04/12 (the only consumers of _side_intervals;
            # STREET-13 builds its own side buckets and does not use parity). The parity error
            # itself is reported separately by STREET-02/09. (0-0 sides are already skipped.)
            classes = (pv,) if pv in ("E", "O") else ("E", "O")
            for pc in classes:
                yield (truename, pc, lo, hi, s)


# Max centroid separation (feet) for two same-name segments to be treated as a physically
# continuous run. The same street name repeats across a grid; for STREET-12 (range
# GAP) this guard is essential - a "gap" between two distinct same-name grid streets is not
# a defect. (STREET-13 deliberately does NOT use this: an ESN/ZIP change is compared only
# between range-ADJACENT segments, and a per-segment-centroid test there hid real mid-street
# boundaries on long roads, so STREET-13 suppresses only confirmed community crossings.)
_SAME_ROAD_MAX_FT = 600.0


def _shared_city(a, b):
    ca = {a.get("LCITY"), a.get("RCITY")} - {None, ""}
    cb = {b.get("LCITY"), b.get("RCITY")} - {None, ""}
    return bool(ca & cb)


def _same_physical_run(a, b):
    """True if two same-name segments are plausibly one continuous stretch of road
    (centroid proximity AND shared community). If either centroid is unknown, do not
    suppress. Used by STREET-12 (range-gap FP control)."""
    pa, pb = a.get("_XY"), b.get("_XY")
    if pa is None or pb is None:
        return True
    import math
    if math.hypot(pa[0] - pb[0], pa[1] - pb[1]) > _SAME_ROAD_MAX_FT:
        return False
    return _shared_city(a, b)


def _confirmed_different_community(a, b):
    """True only when BOTH segments have a known community and they do NOT overlap.
    Unknown/blank community returns False (do not suppress on missing data -- never
    hide a potential same-road defect)."""
    ca = {str(v).strip().upper() for v in (a.get("LCITY"), a.get("RCITY")) if v not in (None, "")}
    cb = {str(v).strip().upper() for v in (b.get("LCITY"), b.get("RCITY")) if v not in (None, "")}
    return bool(ca) and bool(cb) and not (ca & cb)


@registry.check(id="STREET-04", family=FAMILY.STREET, severity=SEVERITY.ERROR,
                priority="v1-core", target="street",
                emits=(SEVERITY.ERROR,), summary="Flag two segments of one street whose address ranges overlap on one parity.",
                fields=("FROMLEFT", "FROMRIGHT", "NAME", "PREFIX", "Parity_L", "Parity_R",
                        "RCL_NGUID", "SEGMENT_ID", "SUFFIX", "TOLEFT",
                        "TORIGHT", "TYPE",), requires=())
def check_street_04(addresses, streets, ctx):
    from collections import defaultdict
    buckets = defaultdict(list)
    for name, pc, lo, hi, s in _side_intervals(streets):
        buckets[(name, pc)].append((lo, hi, s["_OID"], s.get("SEGMENT_ID"), s))
    out, seen = [], set()
    for key, ivals in buckets.items():
        ivals.sort(key=lambda t: (t[0], t[1], t[2]))   # _OID identity, never None
        # Sweep: compare each interval against EVERY still-open predecessor (hi >= lo),
        # not just the running max-hi baseline, so two narrow ranges nested in a wider
        # one are still compared to each other.
        active = []   # (hi, oid, seg, s) intervals not yet closed
        for lo, hi, oid, seg, s in ivals:
            active = [x for x in active if x[0] >= lo]
            for ahi, aoid, aseg, a_s in active:
                if aoid == oid:
                    continue
                pair = tuple(sorted((aoid, oid)))
                if pair not in seen:
                    seen.add(pair)
                    out.append(ErrorRecord("STREET-04", "Overlapping address ranges", FAMILY.STREET,
                                           SEVERITY.ERROR, "street", s["_OID"], s.get("RCL_NGUID", "") or "",
                                           "ranges overlap with SEG %s on %s"
                                           % (_clean(aseg) or aseg, key[0]), s.get("_XY")))
            active.append((hi, oid, seg, s))
    return out


@registry.check(id="STREET-12", family=FAMILY.STREET, severity=SEVERITY.WARNING,
                priority="v1", target="street",
                emits=(SEVERITY.WARNING,), summary="Flag a gap in the address numbering between two segments of one street.",
                fields=("FROMLEFT", "FROMRIGHT", "NAME", "PREFIX", "Parity_L", "Parity_R",
                        "RCL_NGUID", "SUFFIX", "TOLEFT", "TORIGHT", "TYPE",), requires=())
def check_street_12(addresses, streets, ctx):
    from collections import defaultdict
    buckets = defaultdict(list)
    for name, pc, lo, hi, s in _side_intervals(streets):
        buckets[(name, pc)].append((lo, hi, s))
    out, seen = [], set()
    for key, ivals in buckets.items():
        ivals.sort(key=lambda t: (t[0], t[1]))  # never compare the dict on ties
        cur_hi, cur_seg = None, None
        for lo, hi, s in ivals:
            if cur_hi is not None and lo > cur_hi + ctx.max_range_gap + 2 \
                    and _same_physical_run(cur_seg, s):   # +2 = odd/even step; physical-run FP guard
                # Dedup across the E and O buckets: a blank/invalid-parity segment is now
                # expanded into BOTH, so the same physical gap can reach here twice.
                sig = (s["_OID"], cur_hi, lo, key[0])
                if sig not in seen:
                    seen.add(sig)
                    out.append(ErrorRecord("STREET-12", "Address-range gap", FAMILY.STREET,
                                           SEVERITY.WARNING, "street", s["_OID"], s.get("RCL_NGUID", "") or "",
                                           "gap %s-%s on %s"
                                           % (_clean(cur_hi), _clean(lo), key[0]), s.get("_XY")))
            if cur_hi is None or hi > cur_hi:
                cur_hi, cur_seg = hi, s
    return out


def _sign(n):
    return (n > 0) - (n < 0)


@registry.check(id="STREET-03", family=FAMILY.STREET, severity=SEVERITY.WARNING,
                priority="v1", target="street",
                emits=(SEVERITY.ERROR, SEVERITY.WARNING,), summary="Flag a negative range end, a half-zero range or two sides that run in opposite directions.",
                fields=("FROMLEFT", "FROMRIGHT", "Parity_L", "Parity_R", "RCL_NGUID",
                        "TOLEFT", "TORIGHT",), requires=())
def check_street_03(addresses, streets, ctx):
    out = []
    for s in streets:
        fl, tl = s.get("FROMLEFT"), s.get("TOLEFT")
        fr, tr = s.get("FROMRIGHT"), s.get("TORIGHT")
        for frm, to, par, nm in ((fl, tl, s.get("Parity_L"), "L"),
                                 (fr, tr, s.get("Parity_R"), "R")):
            par = _clean(par).upper()   # normalize lowercase/padded parity like STREET-02/09
            for v in (frm, to):
                if v is not None and v < 0:
                    out.append(ErrorRecord("STREET-03", "Range directionality invalid", FAMILY.STREET,
                                           SEVERITY.ERROR, "street", s["_OID"], s.get("RCL_NGUID", "") or "",
                                           "%s range value %s < 0" % (nm, _clean(v)), s.get("_XY")))
            if par != "Z" and frm is not None and to is not None:
                if (frm == 0) != (to == 0):
                    out.append(ErrorRecord("STREET-03", "Range directionality invalid", FAMILY.STREET,
                                           SEVERITY.ERROR, "street", s["_OID"], s.get("RCL_NGUID", "") or "",
                                           "%s partial range %s-%s with parity %s"
                                           % (nm, _clean(frm), _clean(to), par), s.get("_XY")))
        if None not in (fl, tl, fr, tr):
            dirL = _sign(tl - fl)
            dirR = _sign(tr - fr)
            if dirL != 0 and dirR != 0 and dirL != dirR:
                out.append(ErrorRecord("STREET-03", "Range directionality invalid", FAMILY.STREET,
                                       SEVERITY.WARNING, "street", s["_OID"], s.get("RCL_NGUID", "") or "",
                                       "left/right ranges run opposite directions", s.get("_XY")))
    return out


@registry.check(id="STREET-06", family=FAMILY.STREET, severity=SEVERITY.WARNING,
                priority="v1", target="street",
                emits=(SEVERITY.WARNING,), summary="Flag two segments of one street that carry an identical range tuple.",
                fields=("FROMLEFT", "FROMRIGHT", "NAME", "PREFIX", "RCL_NGUID", "SEGMENT_ID",
                        "SUFFIX", "TOLEFT", "TORIGHT", "TYPE",), requires=())
def check_street_06(addresses, streets, ctx):
    from collections import defaultdict
    buckets = defaultdict(list)
    for s in streets:
        fl, tl = s.get("FROMLEFT"), s.get("TOLEFT")
        fr, tr = s.get("FROMRIGHT"), s.get("TORIGHT")
        if (fl or 0) == 0 and (tl or 0) == 0 and (fr or 0) == 0 and (tr or 0) == 0:
            continue
        name = normalize(s.get("PREFIX"), s.get("NAME"), s.get("TYPE"), s.get("SUFFIX"))
        key = (fl, tl, fr, tr, name)
        buckets[key].append(s)
    out = []
    for key, segs in buckets.items():
        if len(segs) > 1:
            ids = ",".join(seg_label(s) for s in segs)
            for s in segs:
                out.append(ErrorRecord("STREET-06", "Duplicate address-range tuple", FAMILY.STREET,
                                       SEVERITY.WARNING, "street", s["_OID"], s.get("RCL_NGUID", "") or "",
                                       "identical range tuple on SEGMENT_IDs %s for %s" % (ids, key[4]), s.get("_XY")))
    return out


@registry.check(id="STREET-05", family=FAMILY.STREET, severity=SEVERITY.ERROR,
                priority="v1-core", target="street",
                emits=(SEVERITY.ERROR,), summary="Flag a SEGMENT_ID or RCL_NGUID that appears on more than one segment.",
                fields=("RCL_NGUID", "SEGMENT_ID",), requires=())
def check_street_05(addresses, streets, ctx):
    from collections import Counter
    out = []
    for fld, label in (("SEGMENT_ID", "SEGMENT_ID"), ("RCL_NGUID", "RCL_NGUID")):
        counts = Counter(s.get(fld) for s in streets if s.get(fld) not in (None, "", " "))
        dup = {k for k, n in counts.items() if n > 1}
        for s in streets:
            if s.get(fld) in dup:
                out.append(ErrorRecord("STREET-05", "Duplicate %s" % label, FAMILY.STREET,
                                       SEVERITY.ERROR, "street", s["_OID"], s.get("RCL_NGUID", "") or "",
                                       "%s %s not unique" % (label, _clean(s.get(fld))), s.get("_XY")))
    return out


@registry.check(id="STREET-07", family=FAMILY.STREET, severity=SEVERITY.ERROR,
                priority="v1", target="street",
                emits=(SEVERITY.ERROR,), summary="Flag a segment that has an address range and no street name.",
                fields=("FROMLEFT", "FROMRIGHT", "NAME", "RCL_NGUID", "SEGMENT_ID", "TOLEFT",
                                        "TORIGHT",), requires=())
def check_street_07(addresses, streets, ctx):
    out = []
    for s in streets:
        addressable = any(s.get(f) not in (None, 0) for f in
                          ("FROMLEFT", "TOLEFT", "FROMRIGHT", "TORIGHT"))
        if addressable and _clean(s.get("NAME")) == "":
            out.append(ErrorRecord("STREET-07", "Street name missing", FAMILY.STREET,
                                   SEVERITY.ERROR, "street", s["_OID"], s.get("RCL_NGUID", "") or "",
                                   "addressable segment SEGMENT_ID %s has blank NAME" % seg_label(s),
                                   s.get("_XY")))
    return out


@registry.check(id="STREET-08", family=FAMILY.STREET, severity=SEVERITY.ERROR,
                priority="v1", target="street",
                emits=(SEVERITY.ERROR, SEVERITY.WARNING,), summary="Flag an RCL_NGUID that is not RCL plus SEGMENT_ID at the expected agency.",
                fields=("DiscrpAgID", "RCL_NGUID", "SEGMENT_ID",), requires=())
def check_street_08(addresses, streets, ctx):
    out = []
    for s in streets:
        nguid = s.get("RCL_NGUID", "") or ""
        xy = s.get("_XY")

        def emit(sev, desc):
            out.append(ErrorRecord("STREET-08", "RCL_NGUID format/agency mismatch", FAMILY.STREET,
                                   sev, "street", s["_OID"], nguid, desc, xy))

        loc, auth = nguid_partition(nguid)
        if loc is None:
            emit(SEVERITY.ERROR, "RCL_NGUID '%s' is not '<localid>@<authority>'" % nguid)
            continue
        agid = _clean(s.get("DiscrpAgID"))
        if not re.match(r"^[A-Za-z0-9_.-]+$", loc):
            emit(SEVERITY.ERROR, "RCL_NGUID localid '%s' has invalid characters" % loc)
        # Case-insensitive: the authority is a domain (case-insensitive by RFC); matches ADDR-06.
        if not (auth.casefold() == agid.casefold() == ctx.expected_agid.casefold()):
            emit(SEVERITY.ERROR, "authority '%s' / DiscrpAgID '%s' != expected '%s'" % (auth, agid, ctx.expected_agid))
        # _clean, not str: a numeric SEGMENT_ID can arrive as 12345.0, which would make
        # every conforming 'RCL12345' localid mismatch. A genuinely non-integral or null id
        # still renders visibly and still fires.
        if loc != "RCL" + _clean(s.get("SEGMENT_ID")):
            emit(SEVERITY.WARNING, "localid '%s' != 'RCL'+SEGMENT_ID" % loc)
    return out


_ONEWAY_OK = {"B", "F", "T", "FT", "TF", "FROM-TO", "TO-FROM", "BOTH", "UNKNOWN"}


@registry.check(id="STREET-09", family=FAMILY.STREET, severity=SEVERITY.ERROR,
                priority="v1", target="street",
                emits=(SEVERITY.ERROR, SEVERITY.WARNING,), summary="Flag a parity or ONEWAY value outside its domain.",
                fields=("FROMLEFT", "FROMRIGHT", "ONEWAY", "Parity_L", "Parity_R",
                        "RCL_NGUID", "TOLEFT", "TORIGHT",), requires=())
def check_street_09(addresses, streets, ctx):
    out = []
    for s in streets:
        nguid = s.get("RCL_NGUID", "") or ""
        xy = s.get("_XY")
        for frm, to, par, nm in ((s.get("FROMLEFT"), s.get("TOLEFT"), s.get("Parity_L"), "L"),
                                 (s.get("FROMRIGHT"), s.get("TORIGHT"), s.get("Parity_R"), "R")):
            pv = _clean(par).upper()
            nonzero = (frm not in (None, 0)) or (to not in (None, 0))
            if pv != "" and pv not in ("O", "E", "B", "Z"):
                out.append(ErrorRecord("STREET-09", "Invalid parity/ONEWAY domain", FAMILY.STREET,
                                       SEVERITY.ERROR, "street", s["_OID"], nguid,
                                       "%s parity '%s' not in {O,E,B,Z}" % (nm, par), xy))
            elif pv == "" and nonzero:
                out.append(ErrorRecord("STREET-09", "Invalid parity/ONEWAY domain", FAMILY.STREET,
                                       SEVERITY.ERROR, "street", s["_OID"], nguid,
                                       "%s parity blank on non-zero range" % nm, xy))
        ow = _clean(s.get("ONEWAY")).upper()
        if ow not in _ONEWAY_OK:
            out.append(ErrorRecord("STREET-09", "Invalid parity/ONEWAY domain", FAMILY.STREET,
                                   SEVERITY.WARNING, "street", s["_OID"], nguid,
                                   "ONEWAY '%s' not a recognized value" % (s.get("ONEWAY")), xy))
    return out


_STREET10_NUMERIC = ("FROMLEFT", "TOLEFT", "FROMRIGHT", "TORIGHT")
_STREET10_REQUIRED = ("SEGMENT_ID", "RCL_NGUID", "NAME", "St_Name", "DiscrpAgID",
                      "State_L", "State_R", "County_L", "County_R", "IncMuni_L",
                      "IncMuni_R", "FROMLEFT", "TOLEFT", "FROMRIGHT", "TORIGHT",
                      "Parity_L", "Parity_R", "RESN", "LESN", "ONEWAY")


def _name_tokens(key):
    return {t for t in re.split(r"\s+", key or "") if len(t) >= 3}


def _authoritative_has(names, community, name_key):
    """True if name_key is authoritative. `names` is a set of (community, name_key)
    tuples or plain name_key strings; tuple form matches on either community."""
    if name_key in names:
        return True
    comm = (community or "").strip().upper()
    return (comm, name_key) in names


def _street_name_candidates(s, cw=None):
    """Candidate name keys for matching a centerline against the authoritative list.
    An authoritative name table often stores names WITHOUT the prefix directional
    (e.g. '12TH AVE', '30TH LANE', '40TH'), so we compare prefix-stripped forms and
    tolerate type/suffix being present or absent in either source."""
    name, typ, suf = s.get("NAME"), s.get("TYPE"), s.get("SUFFIX")
    cands = {normalize(name, typ, suf), normalize(name, typ),
             normalize(name, suf), normalize(name)}
    # A name table may store grid roads as the bare ordinal ('20TH') while a centerline NAME
    # may embed a type word ('20TH PLACE', NAME='20TH PLACE' TYPE='RD'). Strip a trailing
    # type word from NAME so the bare-ordinal candidate matches the authoritative list.
    if cw is not None:
        toks = normalize(name).split()
        if len(toks) >= 2 and cw.valid_type_abbrev(toks[-1]):
            cands.add(" ".join(toks[:-1]))
    nk = (s.get("_NAMEKEY") or "").strip()
    if nk:
        cands.add(nk)   # COMPARE-only-named centerline (NAME blank) still has a candidate
    return {c for c in cands if c}


def _is_county_wide_name(c):
    """A single numeric-leading token ('20TH', '99', '12B') is a grid or route
    name, valid anywhere regardless of which communities the master list enumerates."""
    return bool(c) and len(c.split()) == 1 and c[0].isdigit()


@registry.check(id="STREET-11", family=FAMILY.STREET, severity=SEVERITY.WARNING,
                priority="v2", target="street",
                emits=(SEVERITY.WARNING, SEVERITY.INFO,), summary="Flag a street name that is not in the authoritative list, or that shares no word with any other name.",
                fields=("LCITY", "NAME", "PREFIX", "RCITY", "RCL_NGUID", "SUFFIX", "TYPE",), requires=())
def check_street_11(addresses, streets, ctx):
    """If an authoritative name set is on ctx, flag any street whose name is not
    in it. Otherwise fall back to a degraded fuzzy self-check (no master list)."""
    if ctx.authoritative_names is not None:
        out = []
        names = ctx.authoritative_names
        cw = ctx.crosswalks
        bare = {e[1] if isinstance(e, tuple) else e for e in names}   # name_keys, any community
        for s in streets:
            key = s["_NAMEKEY"]
            if not _clean(key) or ctx.name_ignored(key):
                continue
            lcity, rcity = s.get("LCITY"), s.get("RCITY")
            cands = _street_name_candidates(s, cw)
            # Match on either side's community, OR (for county-wide grid/route ordinals
            # like '20TH'/'99') accept membership under any community.
            if any(_authoritative_has(names, lcity, c) or _authoritative_has(names, rcity, c)
                   or (_is_county_wide_name(c) and c in bare)
                   for c in cands):
                continue
            # Report the COMPONENT name actually tested (PREFIX+NAME+TYPE+SUFFIX), not
            # the COMPARE-derived _NAMEKEY which can be a stale/typo'd cache.
            shown = normalize(s.get("PREFIX"), s.get("NAME"), s.get("TYPE"), s.get("SUFFIX")) or key
            out.append(ErrorRecord("STREET-11", "Invalid road name", FAMILY.STREET,
                                   SEVERITY.WARNING, "street", s["_OID"], s.get("RCL_NGUID", "") or "",
                                   "name '%s' not in authoritative street-name list" % shown,
                                   s.get("_XY")))
        return out
    from collections import Counter
    counts = Counter(s["_NAMEKEY"] for s in streets if _clean(s.get("_NAMEKEY")))
    all_tokens = {}
    for key in counts:
        all_tokens[key] = _name_tokens(key)
    out = []
    for s in streets:
        key = s["_NAMEKEY"]
        if not _clean(key) or counts.get(key, 0) != 1 or ctx.name_ignored(key):
            continue
        mine = all_tokens.get(key, set())
        if not mine:
            continue   # no >=3-char token (e.g. 'US 27', 'CR 25') -> nothing to fuzzy-match on
        overlaps = any(other != key and (mine & all_tokens[other]) for other in all_tokens)
        if not overlaps:
            # Degraded fuzzy mode (no authoritative list) is a heuristic that false-positives
            # on legitimate one-off names, so it emits INFO. The AUTHORITATIVE branch above
            # stays WARNING, so a run with --msag (which loads a name list) still surfaces
            # real 'name not in master list' findings. (This replaces the blanket
            # [severity] STREET-11 = INFO, which had muted the authoritative branch too.)
            out.append(ErrorRecord("STREET-11", "Invalid road name", FAMILY.STREET,
                                   SEVERITY.INFO, "street", s["_OID"], s.get("RCL_NGUID", "") or "",
                                   "name '%s' unmatched in degraded fuzzy check (no master list)" % key,
                                   s.get("_XY")))
    return out


@registry.check(id="STREET-13", family=FAMILY.STREET, severity=SEVERITY.WARNING,
                priority="v2", target="street",
                emits=(SEVERITY.WARNING,), summary="Flag an ESN or ZIP change between two range-adjacent segments of one street side.",
                fields=("FROMLEFT", "FROMRIGHT", "LCITY", "LEFTZIP", "LESN", "NAME", "PREFIX",
                        "RCITY", "RCL_NGUID", "RESN", "RIGHTZIP",
                        "SEGMENT_ID", "SUFFIX", "TOLEFT", "TORIGHT", "TYPE",), requires=())
def check_street_13(addresses, streets, ctx):
    """Boundary-QA surrogate: ESN/ZIP changes between range-adjacent same-side
    segments of the same street name (manual review; may be a true boundary)."""
    from collections import defaultdict
    sides = (("L", "FROMLEFT", "TOLEFT", "LESN", "LEFTZIP"),
             ("R", "FROMRIGHT", "TORIGHT", "RESN", "RIGHTZIP"))
    buckets = defaultdict(list)
    for s in streets:
        for nm, ff, tf, esnf, zipf in sides:
            frm, to = s.get(ff), s.get(tf)
            if frm is None or to is None:
                continue
            lo, hi = min(frm, to), max(frm, to)
            if lo == 0 and hi == 0:
                continue
            truename = normalize(s.get("PREFIX"), s.get("NAME"), s.get("TYPE"), s.get("SUFFIX"))
            buckets[(truename, nm)].append((lo, hi, s, esnf, zipf))   # component name, not stale COMPARE
    out = []
    for key, chain in buckets.items():
        chain.sort(key=lambda t: (t[0], t[1]))
        run_hi = chain[0][1]   # running max hi over chain[0..i-1]
        for i in range(1, len(chain)):
            plo, phi, ps, pesnf, pzipf = chain[i - 1]
            lo, hi, s, esnf, zipf = chain[i]
            # Only compare range-contiguous neighbors. A large numbering gap means
            # the next stretch is a separate run of the same-named road (a normal
            # ESZ/ZIP boundary crossing per NENA), not a mid-street inconsistency.
            # Gate on the RUNNING max hi (not just the prior element), so a short
            # segment contained within a longer one does not break the run.
            # Allow the normal odd/even step of 2 plus the configured MaxRangeGap.
            contiguous = lo - run_hi <= ctx.max_range_gap + 2   # +2 = odd/even step (matches STREET-12)
            run_hi = max(run_hi, hi)
            if not contiguous:
                continue
            # Suppress ONLY a confirmed community-boundary crossing: an ESN/ZIP change
            # where the two segments are in provably different communities is an expected
            # boundary, not a mid-street defect. A same-community (or unknown-community)
            # change on one continuous road is the real defect this check exists to find,
            # so it is always kept. (Do NOT gate on segment-centroid distance - _XY is a
            # per-segment centroid, so abutting segments of one long road sit far apart and
            # would be wrongly suppressed, hiding real boundaries.)
            if _confirmed_different_community(ps, s):
                continue
            side = key[1]   # 'L' or 'R' - label so left/right findings are distinct
            if esn_eq(ps.get(pesnf), s.get(esnf)) is False:
                out.append(ErrorRecord("STREET-13", "Adjacent ESN/ZIP inconsistent", FAMILY.STREET,
                                       SEVERITY.WARNING, "street", s["_OID"], s.get("RCL_NGUID", "") or "",
                                       "ESN changes mid-street %s-side (SEG %s->%s) on %s"
                                       % (side, seg_label(ps), seg_label(s), key[0]), s.get("_XY")))
            if esn_eq(ps.get(pzipf), s.get(zipf)) is False:
                out.append(ErrorRecord("STREET-13", "Adjacent ESN/ZIP inconsistent", FAMILY.STREET,
                                       SEVERITY.WARNING, "street", s["_OID"], s.get("RCL_NGUID", "") or "",
                                       "ZIP changes mid-street %s-side (SEG %s->%s) on %s"
                                       % (side, seg_label(ps), seg_label(s), key[0]), s.get("_XY")))
    return out


@registry.check(id="STREET-10", family=FAMILY.STREET, severity=SEVERITY.ERROR,
                priority="v1", target="street",
                emits=(SEVERITY.ERROR,), summary="Flag a street segment that has an empty required field.",
                fields=("County_L", "County_R", "DiscrpAgID", "FROMLEFT", "FROMRIGHT",
                        "IncMuni_L", "IncMuni_R", "LESN", "NAME", "ONEWAY",
                        "Parity_L", "Parity_R", "RCL_NGUID", "RESN",
                        "SEGMENT_ID", "St_Name", "State_L", "State_R",
                        "TOLEFT", "TORIGHT",), requires=())
def check_street_10(addresses, streets, ctx):
    out = []
    for s in streets:
        nguid = s.get("RCL_NGUID", "") or ""
        xy = s.get("_XY")
        for fld in _STREET10_REQUIRED:
            v = s.get(fld)
            if fld in _STREET10_NUMERIC:
                missing = v is None
            else:
                missing = _clean(v) == ""
            if missing:
                out.append(ErrorRecord("STREET-10", "Required street field missing", FAMILY.STREET,
                                       SEVERITY.ERROR, "street", s["_OID"], nguid,
                                       "required field %s is empty" % fld, xy))
    return out
