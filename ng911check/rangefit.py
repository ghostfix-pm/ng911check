"""rangefit: address points against the range and the line of the segment they front.

STREET-14 finds two same-name centerlines drawn against each other. XLAYER-17, XLAYER-18 and
XLAYER-19 compare where an address point sits with where its house number says it belongs. All
four need street geometry, so they run on a GeoJSON street layer. The decisions are plain
functions over numbers (rank_correlation, find_out_of_sequence, clearly_farther). The checks
only gather the inputs and word the findings.
"""
from .model import ErrorRecord, SEVERITY, FAMILY
from .common import is_addressable, normalize, seg_label
from .cross_layer_checks import _candidate_segments, _covering_segments, _side_ranges
from . import registry

JOIN_TOLERANCE_FT = 1.0      # STREET-14: two line ends this close share one point
MIN_POSITIONS = 4            # XLAYER-17: fewer house numbers on a side say nothing about order
MIN_CORRELATION = 0.5        # XLAYER-17: a weaker rank correlation means no clear direction
END_MARGIN_FT = 0.5          # XLAYER-17: a foot this close to a line end has no side


def clearly_farther(near, far, margin, ratio):
    """True when `far` is more than `margin` beyond `near` and at least `ratio` times as far."""
    return far - near > margin and far >= ratio * near


def rank_correlation(numbers):
    """Spearman correlation between list order and value order. Values must all differ.

    1.0 means the numbers rise along the list, -1.0 means they fall."""
    n = len(numbers)
    order = sorted(range(n), key=lambda i: numbers[i])
    rank = [0] * n
    for r, i in enumerate(order):
        rank[i] = r
    spread = sum((i - rank[i]) ** 2 for i in range(n))
    return 1.0 - 6.0 * spread / (n * (n * n - 1))


def _belongs_at(positions, nums, i):
    """Where along the line the number at index i would sit among its neighbours' numbers.

    It sits half way between the two other positions whose numbers surround it, or at the
    nearest end when its number is beyond all of them."""
    others = sorted((nums[j], positions[j][0]) for j in range(len(nums)) if j != i)
    below = sum(1 for number, _along in others if number < nums[i])
    if below == 0:
        return others[0][1]
    if below == len(others):
        return others[-1][1]
    return (others[below - 1][1] + others[below][1]) / 2.0


def find_out_of_sequence(positions, min_displacement):
    """The positions whose number is out of order with the numbers on both sides of them.

    `positions` is [(distance along the line, house number)] in order along the line, every
    number different. The direction of the numbering is read from the numbers themselves. A side
    with fewer than MIN_POSITIONS numbers, or no clear direction, gives nothing. A position is
    out of sequence when its two neighbours agree with the direction and its number lies
    outside them. It is kept when it sits at least `min_displacement` feet from where its
    number belongs. Returns [(index, previous number, next number, displacement)]."""
    n = len(positions)
    if n < MIN_POSITIONS:
        return []
    rho = rank_correlation([p[1] for p in positions])
    if abs(rho) < MIN_CORRELATION:
        return []
    sign = 1 if rho > 0 else -1
    nums = [sign * p[1] for p in positions]
    found = []
    for i in range(1, n - 1):
        lo, hi = nums[i - 1], nums[i + 1]
        if lo < hi and not lo < nums[i] < hi:
            shift = abs(positions[i][0] - _belongs_at(positions, nums, i))
            if shift >= min_displacement:
                found.append((i, positions[i - 1][1], positions[i + 1][1], shift))
    return found


def _address_keys(a):
    """The street names an address answers to: its _NAMEKEY and its rebuilt component name."""
    raw = normalize(a.get("PREFIX"), a.get("STREET_NA"), a.get("TYPE"), a.get("SUFFIX"))
    return {a["_NAMEKEY"], raw} - {""}


def _usable(a, ctx):
    """A real address with a position, on a street name the settings do not ignore."""
    return (is_addressable(a) and a.get("_XY") is not None
            and not all(ctx.name_ignored(k) for k in _address_keys(a)))


def _distances(a, segments, ctx):
    """[(distance in feet, segment)] from the address to each segment that has a line."""
    out = []
    for s in segments:
        geom = ctx.geom("street", s["_OID"])
        if geom is not None:
            out.append((geom.distance_to(*a["_XY"]), s))
    return out


def _nearest(pairs):
    return min(pairs, key=lambda p: p[0])


def _record(check_id, title, family, sev, layer, row, nguid, text, xy):
    return ErrorRecord(check_id, title, family, sev, layer, row["_OID"], nguid or "", text, xy)


@registry.check(id="XLAYER-18", family=FAMILY.CROSS, severity=SEVERITY.WARNING,
                priority="v1", target="address",
                emits=(SEVERITY.WARNING,),
                summary="Flag an address that sits clearly nearer a block of its street whose range excludes its number.",
                fields=("Add_Number", "FROMLEFT", "FROMRIGHT", "PREFIX", "Parity_L", "Parity_R",
                        "SEGMENT_ID", "STREET_NA", "SUFFIX", "Site_NGUID", "TOLEFT", "TORIGHT",
                        "TYPE"),
                requires=("geometry",))
def check_xlayer_18(addresses, streets, ctx):
    """The segment whose range covers the number is far from the point; another same-name one is near."""
    out = []
    for a in addresses:
        if not _usable(a, ctx):
            continue
        covering = {id(s) for s, _side in _covering_segments(a, ctx)}
        dists = _distances(a, _candidate_segments(a, ctx), ctx)
        cover = [d for d in dists if id(d[1]) in covering]
        other = [d for d in dists if id(d[1]) not in covering]
        if not cover or not other:
            continue
        d_cover, s_cover = _nearest(cover)
        d_other, s_other = _nearest(other)
        if clearly_farther(d_other, d_cover, ctx.wb_min_margin_ft, ctx.wb_min_ratio):
            out.append(_record(
                "XLAYER-18", "Address on wrong block", FAMILY.CROSS, SEVERITY.WARNING,
                "address", a, a.get("Site_NGUID"),
                "house number %s is %.0f ft from SEG %s, whose range covers it, and %.0f ft "
                "from SEG %s, whose range does not" % (a.get("Add_Number"), d_cover,
                                                       seg_label(s_cover), d_other,
                                                       seg_label(s_other)),
                a["_XY"]))
    return out


@registry.check(id="XLAYER-19", family=FAMILY.CROSS, severity=SEVERITY.WARNING,
                priority="v1", target="address",
                emits=(SEVERITY.WARNING,),
                summary="Flag an address that sits clearly nearer a ranged street of another name than its own street.",
                fields=("Add_Number", "FROMLEFT", "FROMRIGHT", "PREFIX", "Parity_L", "Parity_R",
                        "SEGMENT_ID", "STREET_NA", "SUFFIX", "Site_NGUID", "TOLEFT", "TORIGHT",
                        "TYPE"),
                requires=("geometry",))
def check_xlayer_19(addresses, streets, ctx):
    """The nearest ranged centerline of another name is much nearer than the address's own street."""
    ranged = [s for s in streets if any(True for _r in _side_ranges(s))
              and not ctx.name_ignored(s["_NAMEKEY"])]
    out = []
    for a in addresses:
        if not _usable(a, ctx):
            continue
        owned = _distances(a, _candidate_segments(a, ctx), ctx)
        # The margin is never negative (settings refuse it), so a point nearer than the margin to
        # its own street cannot be reported. That skips the scan over every other street.
        if not owned:
            continue
        d_own, s_own = _nearest(owned)
        if d_own <= ctx.nm_min_margin_ft:
            continue
        # shortcut: one scan of every ranged segment per far point, so a layer with a million far
        # points and tens of thousands of segments is slow. Build a grid index when that matters.
        rivals = _distances(a, ranged, ctx)
        if not rivals:
            continue
        d_other, s_other = _nearest(rivals)
        if clearly_farther(d_other, d_own, ctx.nm_min_margin_ft, ctx.nm_min_ratio):
            out.append(_record(
                "XLAYER-19", "Nearest street has another name", FAMILY.CROSS, SEVERITY.WARNING,
                "address", a, a.get("Site_NGUID"),
                "house number %s on '%s' is %.0f ft from its street (SEG %s) and %.0f ft from "
                "'%s' (SEG %s)" % (a.get("Add_Number"), a["_NAMEKEY"], d_own, seg_label(s_own),
                                   d_other, s_other["_NAMEKEY"], seg_label(s_other)),
                a["_XY"]))
    return out


def _sides(addresses, ctx):
    """{(segment OID, on right): (segment, [(distance along, number, address)])}.

    Each usable point joins its nearest same-name line. A point whose nearest spot is a line end
    is left out, because it has no side."""
    groups = {}
    for a in addresses:
        if not _usable(a, ctx):
            continue
        best = None
        for s in _candidate_segments(a, ctx):
            geom = ctx.geom("street", s["_OID"])
            if geom is None:
                continue
            along, dist, right = geom.query(*a["_XY"])
            if best is None or dist < best[0]:
                best = (dist, along, right, s, geom)
        if best is None or not END_MARGIN_FT < best[1] < best[4].length - END_MARGIN_FT:
            continue
        _dist, along, right, s, _geom = best
        groups.setdefault((s["_OID"], right), (s, []))[1].append(
            (along, int(a.get("Add_Number")), a))
    return groups


def _one_position_per_number(items):
    """[(mean distance along, number, [addresses])] in order along the line.

    Points that share a number, a complex, count as one position."""
    by_number = {}
    for along, number, a in items:
        by_number.setdefault(number, []).append((along, a))
    merged = [(sum(al for al, _a in pts) / len(pts), number, [a for _al, a in pts])
              for number, pts in by_number.items()]
    return sorted(merged, key=lambda p: p[0])


@registry.check(id="XLAYER-17", family=FAMILY.CROSS, severity=SEVERITY.WARNING,
                priority="v1", target="address",
                emits=(SEVERITY.WARNING,),
                summary="Flag an address whose house number is out of order with its neighbours along its street.",
                fields=("Add_Number", "PREFIX", "STREET_NA", "SEGMENT_ID", "SUFFIX", "Site_NGUID",
                        "TYPE"),
                requires=("geometry",))
def check_xlayer_17(addresses, streets, ctx):
    """Order the points on one side of one line; flag a number that breaks the order."""
    out = []
    for (_oid, right), (s, items) in _sides(addresses, ctx).items():
        positions = _one_position_per_number(items)
        for i, before, after, shift in find_out_of_sequence(
                [(p[0], p[1]) for p in positions], ctx.oo_min_displacement_ft):
            for a in positions[i][2]:
                out.append(_record(
                    "XLAYER-17", "Address out of sequence along its street", FAMILY.CROSS,
                    SEVERITY.WARNING, "address", a, a.get("Site_NGUID"),
                    "house number %s is out of sequence on the %s side of SEG %s: its "
                    "neighbours are %s and %s, and it sits %.0f ft from where its number "
                    "belongs" % (a.get("Add_Number"), "right" if right else "left",
                                 seg_label(s), before, after, shift),
                    a["_XY"]))
    return out


def _closed(first, last):
    return abs(first[0] - last[0]) <= JOIN_TOLERANCE_FT and abs(first[1] - last[1]) <= JOIN_TOLERANCE_FT


def _end_points(streets, ctx):
    """{street name: [(segment, (low, high), first vertex, last vertex)]} for the segments STREET-14 compares.

    A segment with no address range (a private drive, a ramp) is left out, and so is a
    closed loop: its first and last vertex are one point, so any neighbour at that point is
    head-to-head or tail-to-tail with it whichever way the loop was drawn."""
    by_name = {}
    for s in streets:
        spans = list(_side_ranges(s))
        geom = ctx.geom("street", s["_OID"])
        if not spans or geom is None:
            continue
        first, last = geom.ends()
        if _closed(first, last):
            continue
        low = min(lo for lo, _hi, _par in spans)
        high = max(hi for _lo, hi, _par in spans)
        by_name.setdefault(s["_NAMEKEY"], []).append((s, (low, high), first, last))
    return by_name


@registry.check(id="STREET-14", family=FAMILY.STREET, severity=SEVERITY.WARNING,
                priority="v1", target="street",
                emits=(SEVERITY.WARNING,),
                summary="Flag two same-name centerlines that meet head-to-head or tail-to-tail, so one is drawn against the street.",
                fields=("FROMLEFT", "FROMRIGHT", "Parity_L", "Parity_R", "RCL_NGUID",
                        "SEGMENT_ID", "TOLEFT", "TORIGHT"),
                requires=("geometry",))
def check_street_14(addresses, streets, ctx):
    """Two same-name segments that both end, or both start, at one point, with different blocks."""
    out = []
    for segs in _end_points(streets, ctx).values():
        ends = sorted((p[0], p[1], kind, i) for i, seg in enumerate(segs)
                      for kind, p in (("start", seg[2]), ("end", seg[3])))
        seen = set()
        for j, (x, y, kind, i) in enumerate(ends):
            for x2, y2, kind2, i2 in ends[j + 1:]:
                if x2 - x > JOIN_TOLERANCE_FT:
                    break
                if kind2 != kind or abs(y2 - y) > JOIN_TOLERANCE_FT:
                    continue
                pair = (min(i, i2), max(i, i2))
                s1, span1 = segs[pair[0]][:2]
                s2, span2 = segs[pair[1]][:2]
                if pair in seen or (span1[0] <= span2[1] and span2[0] <= span1[1]):
                    continue
                seen.add(pair)
                out.append(_record(
                    "STREET-14", "Street pointing wrong direction", FAMILY.STREET,
                    SEVERITY.WARNING, "street", s1, s1.get("RCL_NGUID"),
                    "SEG %s and SEG %s of '%s' meet %s, so one is drawn against the street"
                    % (seg_label(s1), seg_label(s2), s1["_NAMEKEY"],
                       "head-to-head" if kind == "end" else "tail-to-tail"),
                    (x, y)))
    return out
