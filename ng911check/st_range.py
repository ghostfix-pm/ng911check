"""Self-test: rangefit (STREET-14, XLAYER-17, XLAYER-18, XLAYER-19), its settings and its reader path.

Every line runs west to east at a fixed height y, in feet. North of the line is its left side and
south is its right side. The case helpers build the rows, and each assertion is a straight line.
"""
from . import engine, geometry, rangefit, reader, settings as settings_mod
from .selftest import Tmp
from .st_cli import INI, call, collection, feature
from .st_fix import A, S, found, geom_provider, line, run

GEO = {"geom_provider": geom_provider}
UPPER = dict(FROMLEFT=201, TOLEFT=299, FROMRIGHT=200, TORIGHT=298)
UNRANGED = dict(FROMLEFT=0, TOLEFT=0, FROMRIGHT=0, TORIGHT=0, Parity_L="Z", Parity_R="Z")
SWAP = [(101, 100.0), (103, 200.0), (107, 300.0), (105, 380.0), (109, 500.0)]


def _row(y, **kw):
    """A street whose line runs from x=0 to x=1000 at height y."""
    s = S(**kw)
    line(s, (0.0, y), (1000.0, y))
    return s


def _seg(first, last, **kw):
    """A street from `first` to `last`, a straight two-vertex line."""
    s = S(**kw)
    line(s, first, last)
    return s


def _num(number, x, y, **kw):
    return A(Add_Number=number, HOUSE_NU=str(number), _XY=(x, y), **kw)


def _north(pairs, y=30.0):
    return [_num(n, x, y) for n, x in pairs]


def _label(row):
    return "SEG %s" % row["SEGMENT_ID"]


def section(h):
    c, raises = h.check, h.raises

    # ---- the decisions, as plain functions over numbers
    c(not rangefit.clearly_farther(100.0, 250.0, 150.0, 2.0) and rangefit.clearly_farther(100.0, 250.1, 150.0, 2.0),
      "clearly_farther needs the gap to be more than the margin, not equal to it  <-- pinned defect")
    c(rangefit.clearly_farther(300.0, 600.0, 150.0, 2.0) and not rangefit.clearly_farther(300.0, 599.0, 150.0, 2.0),
      "clearly_farther accepts a ratio exactly at the limit and refuses one just under it  <-- pinned defect")
    c(rangefit.rank_correlation([1, 2, 3, 4]) == 1.0 and rangefit.rank_correlation([4, 3, 2, 1]) == -1.0
      and abs(rangefit.rank_correlation([1, 3, 2, 4]) - 0.8) < 1e-12 and rangefit.rank_correlation([2, 4, 1, 3]) == 0.0,
      "rank_correlation is 1 for rising numbers, -1 for falling and 0 for a scramble")
    along_swap = [(float(x), n) for n, x in SWAP]
    got = rangefit.find_out_of_sequence(along_swap, 0.0)
    c([(i, a, b) for i, a, b, _s in got] == [(2, 103, 105), (3, 107, 109)] and [s for _i, _a, _b, s in got] == [140.0, 130.0],
      "find_out_of_sequence names the two houses of a swap with their neighbours and their distance from where they belong")
    c([i for i, _a, _b, _s in rangefit.find_out_of_sequence(along_swap, 140.0)] == [2], "a displacement exactly at the limit is kept and one under it is dropped  <-- pinned defect")
    c(rangefit.find_out_of_sequence(along_swap, 150.0) == [], "find_out_of_sequence drops a swap of two houses side by side")
    c(rangefit.find_out_of_sequence(along_swap[:3], 0.0) == [], "find_out_of_sequence needs four positions")
    c(rangefit.find_out_of_sequence([(100.0, 103), (200.0, 101), (300.0, 105)], 0.0) == [], "find_out_of_sequence skips three positions even when one is out of order  <-- pinned defect")
    c([i for i, _a, _b, _s in rangefit.find_out_of_sequence([(100.0, 105), (200.0, 101), (300.0, 107), (400.0, 103), (500.0, 109)], 0.0)] == [1, 2, 3],
      "find_out_of_sequence accepts a rank correlation of exactly 0.5  <-- pinned defect")
    c([i for i, _a, _b, _s in rangefit.find_out_of_sequence([(100.0, 101), (200.0, 111), (300.0, 103), (400.0, 105), (500.0, 107), (600.0, 113), (700.0, 115), (800.0, 109)], 0.0)] == [1],
      "find_out_of_sequence never wraps round to compare the first position with the last  <-- pinned defect")
    c(rangefit.find_out_of_sequence([(100.0, 2), (200.0, 4), (300.0, 1), (400.0, 3)], 0.0) == [], "find_out_of_sequence gives nothing when the numbers show no direction")
    down = [(100.0, 109), (200.0, 105), (300.0, 107), (400.0, 103), (500.0, 101)]
    c([(i, a, b) for i, a, b, _s in rangefit.find_out_of_sequence(down, 0.0)] == [(1, 109, 107), (2, 105, 103)],
      "find_out_of_sequence reads falling numbers and reports the neighbours as written")
    c(rangefit.find_out_of_sequence([(100.0, 105), (200.0, 101), (300.0, 103), (400.0, 107), (500.0, 109)], 0.0) == [],
      "find_out_of_sequence never reports the first or last position, which has one neighbour")
    low = rangefit.find_out_of_sequence([(100.0, 103), (200.0, 105), (300.0, 101), (400.0, 107), (500.0, 109)], 0.0)
    high = rangefit.find_out_of_sequence([(100.0, 101), (200.0, 103), (300.0, 111), (400.0, 105), (500.0, 107)], 0.0)
    c(low == [(2, 105, 107, 200.0)] and high == [(2, 103, 105, 200.0)],
      "a number below every other belongs at the lowest end and one above every other at the highest end")
    c([i for i, _a, _b, _s in rangefit.find_out_of_sequence([(100.0, 101), (200.0, 109), (300.0, 105), (400.0, 103), (500.0, 111)], 0.0)] == [1, 3],
      "a position whose two neighbours disagree about the direction is not reported")

    # ---- XLAYER-18 an address nearer a block whose range excludes its number
    lower, upper = _row(0.0), _row(900.0, **UPPER)
    r = run([_num(105, 500.0, 800.0)], [lower, upper], ["XLAYER-18"], **GEO)
    c(found(r, "XLAYER-18", "WARNING", "house number 105 is 800 ft from %s, whose range covers it, and 100 ft from %s, whose range does not"
            % (_label(lower), _label(upper))) == 1, "xlayer-18 flags a number whose covering block is far and whose nearest block excludes it")
    r = run([_num(105, 500.0, 60.0)], [lower, upper], ["XLAYER-18"], **GEO)
    c(r == [], "xlayer-18 passes an address nearest the block that covers its number")
    r = run([_num(105, 500.0, 600.0)], [lower, upper], ["XLAYER-18"], **GEO)
    c(found(r, "XLAYER-18") == 1, "xlayer-18 flags a covering block exactly twice as far as the nearest block  <-- pinned defect")
    r = run([_num(105, 500.0, 599.0)], [lower, upper], ["XLAYER-18"], **GEO)
    c(r == [], "xlayer-18 keeps a corner lot, under twice as far, out of the report  <-- pinned defect")
    near_lower, near_upper = _row(0.0), _row(450.0, **UPPER)
    r = run([_num(105, 500.0, 300.0)], [near_lower, near_upper], ["XLAYER-18"], **GEO)
    c(r == [], "xlayer-18 needs the gap to be more than the margin, not equal to it  <-- pinned defect")
    r = run([_num(105, 500.0, 301.0)], [near_lower, near_upper], ["XLAYER-18"], **GEO)
    c(found(r, "XLAYER-18") == 1, "xlayer-18 reports a gap one foot over the margin")
    r = run([_num(105, 500.0, 800.0)], [lower, upper], ["XLAYER-18"], wb_min_margin_ft=800.0, **GEO)
    c(r == [], "xlayer-18 reads wb_min_margin_ft")
    r = run([_num(105, 500.0, 800.0)], [lower, upper], ["XLAYER-18"], wb_min_ratio=10.0, **GEO)
    c(r == [], "xlayer-18 reads wb_min_ratio")
    r = run([_num(301, 500.0, 800.0)], [lower, upper], ["XLAYER-18"], **GEO)
    c(r == [], "xlayer-18 leaves a number that no block covers to xlayer-02")
    r = run([_num(105, 500.0, 800.0)], [lower], ["XLAYER-18"], **GEO)
    c(r == [], "xlayer-18 needs a second block of the same street to compare with")
    r = run([A(Add_Number=105, HOUSE_NU="105", _XY=None), _num(0, 500.0, 800.0)], [lower, upper], ["XLAYER-18"], **GEO)
    c(r == [], "xlayer-18 skips a point with no position and a point with no house number")
    r = run([_num(105, 500.0, 800.0)], [lower, upper], ["XLAYER-18"], street_names_ignored=frozenset({"ELM"}), **GEO)
    c(r == [], "xlayer-18 skips an ignored street name")
    bare_cover, bare_other = S(), S(**UPPER)
    line(bare_other, (0.0, 900.0), (1000.0, 900.0))
    r = run([_num(105, 500.0, 800.0)], [bare_cover, bare_other], ["XLAYER-18"], **GEO)
    c(r == [], "xlayer-18 skips a number whose covering segment has no line")
    bare_other = S(**UPPER)
    r = run([_num(105, 500.0, 800.0)], [lower, bare_other], ["XLAYER-18"], **GEO)
    c(r == [], "xlayer-18 skips an address whose only other block has no line")

    # ---- XLAYER-19 an address nearer a ranged street of another name
    own, rival = _row(0.0), _row(300.0, NAME="OAK")
    margin = dict(nm_min_margin_ft=100.0, nm_min_ratio=2.0)
    r = run([_num(105, 500.0, 201.0)], [own, rival], ["XLAYER-19"], **margin, **GEO)
    c(found(r, "XLAYER-19", "WARNING", "house number 105 on 'ELM ST' is 201 ft from its street (%s) and 99 ft from 'OAK ST' (%s)"
            % (_label(own), _label(rival))) == 1, "xlayer-19 flags an address clearly nearer a ranged street of another name")
    r = run([_num(105, 500.0, 200.0)], [own, rival], ["XLAYER-19"], **margin, **GEO)
    c(r == [], "xlayer-19 needs the gap to be more than the margin, not equal to it  <-- pinned defect")
    far_rival = _row(900.0, NAME="OAK")
    r = run([_num(105, 500.0, 600.0)], [own, far_rival], ["XLAYER-19"], **margin, **GEO)
    c(found(r, "XLAYER-19") == 1, "xlayer-19 flags an own street exactly twice as far as the other street")
    r = run([_num(105, 500.0, 599.0)], [own, far_rival], ["XLAYER-19"], **margin, **GEO)
    c(r == [], "xlayer-19 keeps a point under twice as far out of the report  <-- pinned defect")
    r = run([_num(105, 500.0, 50.0)], [own, _row(60.0, NAME="OAK")], ["XLAYER-19"], **margin, **GEO)
    c(r == [], "xlayer-19 never reports a point within the margin of its own street")
    wide_own, wide_rival = _row(0.0), _row(10000.0, NAME="OAK")
    r = run([_num(105, 500.0, 8000.0), _num(107, 500.0, 4000.0)], [wide_own, wide_rival], ["XLAYER-19"], **GEO)
    c(found(r, "XLAYER-19") == 1 and found(r, "XLAYER-19", text="house number 105") == 1, "xlayer-19 defaults to a margin of 5,000 ft: 8,000 ft is reported and 4,000 ft is not")
    r = run([_num(105, 500.0, 201.0)], [own, _row(300.0, NAME="OAK", **UNRANGED)], ["XLAYER-19"], **margin, **GEO)
    c(r == [], "xlayer-19 ignores a nearer centerline that has no address range  <-- pinned defect")
    r = run([_num(105, 500.0, 201.0)], [own, rival], ["XLAYER-19"], street_names_ignored=frozenset({"OAK"}), **margin, **GEO)
    c(r == [], "xlayer-19 ignores a nearer centerline whose name the settings ignore")
    r = run([_num(105, 500.0, 201.0)], [own], ["XLAYER-19"], **margin, **GEO)
    c(r == [], "xlayer-19 does not report an address against its own street")
    r = run([_num(105, 500.0, 201.0)], [_row(0.0, **UNRANGED)], ["XLAYER-19"], **margin, **GEO)
    c(r == [], "xlayer-19 needs at least one ranged centerline to compare with")
    r = run([_num(105, 500.0, 201.0)], [S(), rival], ["XLAYER-19"], **margin, **GEO)
    c(r == [], "xlayer-19 skips an address whose own street has no line")
    r = run([_num(105, 500.0, 201.0)], [own, S(NAME="OAK")], ["XLAYER-19"], **margin, **GEO)
    c(r == [], "xlayer-19 skips a rival street that has no line")
    r = run([A(Add_Number=105, HOUSE_NU="105", _XY=None)], [own, rival], ["XLAYER-19"], **margin, **GEO)
    c(r == [], "xlayer-19 skips a point with no position")

    # ---- XLAYER-17 a number out of order along its street
    spine = _row(0.0)
    r = run(_north(SWAP), [spine], ["XLAYER-17"], **GEO)
    c(r == [], "xlayer-17 leaves two houses that swapped side by side alone")
    r = run(_north(SWAP), [spine], ["XLAYER-17"], oo_min_displacement_ft=0.0, **GEO)
    c(found(r, "XLAYER-17", "WARNING") == 2 and found(r, "XLAYER-17", text="house number 107 is out of sequence on the left side of %s: its neighbours are 103 and 105, and it sits 140 ft from where its number belongs" % _label(spine)) == 1,
      "xlayer-17 with a displacement of 0 reports both houses of a swap")
    r = run(_north(SWAP), [spine], ["XLAYER-17"], oo_min_displacement_ft=140.0, **GEO)
    c(found(r, "XLAYER-17") == 1 and found(r, "XLAYER-17", text="house number 107") == 1, "xlayer-17 reads oo_min_displacement_ft and keeps a point exactly at the limit")
    far_out = [(101, 100.0), (103, 200.0), (121, 300.0), (107, 400.0), (109, 500.0), (111, 600.0)]
    r = run(_north(far_out), [spine], ["XLAYER-17"], **GEO)
    c(found(r, "XLAYER-17", "WARNING", "house number 121 is out of sequence on the left side of %s: its neighbours are 103 and 107, and it sits 300 ft" % _label(spine)) == 1 and found(r, "XLAYER-17") == 1,
      "xlayer-17 flags a number far from where it belongs, by default")
    complex_units = _north(far_out) + [_num(121, 320.0, 30.0)]
    r = run(complex_units, [spine], ["XLAYER-17"], **GEO)
    c(found(r, "XLAYER-17", text="house number 121") == 2 and found(r, "XLAYER-17") == 2, "xlayer-17 counts the points of a complex as one position and reports each point")
    clean_north = _north([(101, 100.0), (103, 200.0), (105, 300.0), (107, 400.0)])
    south = [_num(n, x, -30.0) for n, x in [(100, 100.0), (102, 200.0), (120, 300.0), (106, 400.0), (108, 500.0), (110, 600.0)]]
    r = run(clean_north + south, [spine], ["XLAYER-17"], **GEO)
    c(found(r, "XLAYER-17", text="house number 120 is out of sequence on the right side") == 1 and found(r, "XLAYER-17") == 1,
      "xlayer-17 orders each side of the line on its own")
    falling = [_num(n, x, 30.0) for n, x in [(119, 100.0), (117, 200.0), (101, 300.0), (113, 400.0), (111, 500.0), (109, 600.0)]]
    r = run(falling, [spine], ["XLAYER-17"], **GEO)
    c(found(r, "XLAYER-17", text="house number 101") == 1 and found(r, "XLAYER-17") == 1, "xlayer-17 reads numbers that fall along the line")
    r = run(_north(far_out[:2] + far_out[3:]), [spine], ["XLAYER-17"], **GEO)
    c(r == [], "xlayer-17 passes a side whose numbers are in order")
    r = run(_north(far_out[:3]), [spine], ["XLAYER-17"], **GEO)
    c(r == [], "xlayer-17 skips a side with fewer than four numbers")
    four = [(105, 100.0), (103, 200.0), (107, 300.0), (109, 400.0)]
    r = run([_num(101, -10.0, 30.0)] + _north(four), [spine], ["XLAYER-17"], oo_min_displacement_ft=0.0, **GEO)
    c(found(r, "XLAYER-17") == 1 and found(r, "XLAYER-17", text="house number 103") == 1, "xlayer-17 leaves out a point whose nearest spot is the start of the line  <-- pinned defect")
    tail = [(101, 100.0), (103, 200.0), (109, 300.0), (105, 400.0)]
    r = run([_num(111, 1010.0, 30.0)] + _north(tail), [spine], ["XLAYER-17"], oo_min_displacement_ft=0.0, **GEO)
    c(found(r, "XLAYER-17") == 1 and found(r, "XLAYER-17", text="house number 109") == 1, "xlayer-17 leaves out a point whose nearest spot is the end of the line  <-- pinned defect")
    r = run(_north(far_out) + [A(Add_Number=125, HOUSE_NU="125", _XY=None), A(Add_Number=127, HOUSE_NU="127", STREET_NA="NOPE", _XY=(300.0, 30.0))], [spine], ["XLAYER-17"], **GEO)
    c(found(r, "XLAYER-17") == 1, "xlayer-17 skips a point with no position and a point on a street with no line")
    r = run(_north(far_out), [spine], ["XLAYER-17"], street_names_ignored=frozenset({"ELM"}), **GEO)
    c(r == [], "xlayer-17 skips an ignored street name")
    r = run(_north(far_out), [S()], ["XLAYER-17"], **GEO)
    c(r == [], "xlayer-17 skips a street that has no line")

    # ---- STREET-14 two same-name lines drawn against each other
    west, east = _seg((0.0, 0.0), (100.0, 0.0)), _seg((200.0, 0.0), (100.0, 0.0), **UPPER)
    r = run([], [west, east], ["STREET-14"], **GEO)
    c(found(r, "STREET-14", "WARNING", "%s and %s of 'ELM ST' meet head-to-head, so one is drawn against the street" % (_label(west), _label(east))) == 1
      and r[0].xy == (100.0, 0.0) and r[0].source_oid == west["_OID"], "street-14 flags two lines that both end at one point")
    out_west, out_east = _seg((100.0, 0.0), (0.0, 0.0)), _seg((100.0, 0.0), (200.0, 0.0), **UPPER)
    r = run([], [out_west, out_east], ["STREET-14"], **GEO)
    c(found(r, "STREET-14", text="meet tail-to-tail") == 1, "street-14 flags two lines that both start at one point")
    r = run([], [_seg((0.0, 0.0), (100.0, 0.0)), _seg((100.0, 0.0), (200.0, 0.0), **UPPER)], ["STREET-14"], **GEO)
    c(r == [], "street-14 passes two lines that follow each other")
    r = run([], [_seg((0.0, 0.0), (100.0, 0.0)), _seg((200.0, 0.0), (100.0, 0.0))], ["STREET-14"], **GEO)
    c(r == [], "street-14 passes two lines that carry the same block, a divided road  <-- pinned defect")
    r = run([], [_seg((0.0, 0.0), (100.0, 0.0)), _seg((200.0, 0.0), (100.0, 0.0), **UNRANGED)], ["STREET-14"], **GEO)
    c(r == [], "street-14 skips a line with no address range, a private drive  <-- pinned defect")
    ring = S(FROMLEFT=301, TOLEFT=399, FROMRIGHT=300, TORIGHT=398)
    line(ring, (100.0, 0.0), (100.0, 50.0), (150.0, 50.0), (100.0, 0.5))
    r = run([], [_seg((0.0, 0.0), (100.0, 0.0)), ring], ["STREET-14"], **GEO)
    c(r == [], "street-14 skips a closed loop, which meets its feeder head-to-head whichever way it was drawn  <-- pinned defect")
    r = run([], [_seg((0.0, 0.0), (100.0, 0.0)), _seg((200.0, 0.0), (100.0, 0.0), NAME="OAK", **UPPER)], ["STREET-14"], **GEO)
    c(r == [], "street-14 compares lines of one name only")
    r = run([], [_seg((0.0, 0.0), (100.0, 0.0)), _seg((200.0, 0.0), (100.5, 0.5), **UPPER)], ["STREET-14"], **GEO)
    c(found(r, "STREET-14") == 1, "street-14 treats two ends within a foot as one point")
    r = run([], [_seg((0.0, 0.0), (100.0, 0.0)), _seg((200.0, 0.0), (102.0, 0.0), **UPPER), _seg((200.0, 0.0), (100.0, 5.0), **UPPER)], ["STREET-14"], **GEO)
    c(r == [], "street-14 does not join ends more than a foot apart, along the line or across it")
    twin_a, twin_b = _seg((0.0, 0.0), (100.0, 0.0)), _seg((0.0, 0.0), (100.0, 0.0), **UPPER)
    r = run([], [twin_a, twin_b], ["STREET-14"], **GEO)
    c(found(r, "STREET-14") == 1, "street-14 reports a pair that meets at both ends once  <-- pinned defect")
    r = run([], [west, S(**UPPER)], ["STREET-14"], **GEO)
    c(r == [], "street-14 skips a segment that has no line")

    # ---- the line reader that feeds STREET-14
    multi = geometry.Polyline([[(0.0, 0.0), (10.0, 0.0)], [(50.0, 5.0), (60.0, 6.0)]])
    c(multi.ends() == ((0.0, 0.0), (60.0, 6.0)), "ends takes the first vertex of the first part and the last vertex of the last part")
    with Tmp() as tmp:
        path = tmp.write("multi.geojson", collection(feature("MultiLineString", [[[0.0, 0.0], [10.0, 0.0]], [[50.0, 5.0], [60.0, 6.0]]], S())))
        lay = reader.read_layer(path, "streets")
        geoms = reader.finalize_layer(lay, geometry.Frame.fit("feet", list(lay.raw_coords())))
        c(geoms[1].ends() == ((0.0, 0.0), (60.0, 6.0)), "the GeoJSON reader keeps every vertex of a MultiLineString in order")

        # ---- the settings
        st = settings_mod.load(tmp.write("t.ini", INI + "[thresholds]\noo_min_displacement_ft = 0\nwb_min_margin_ft = 10\nwb_min_ratio = 1.5\nnm_min_margin_ft = 0\nnm_min_ratio = 1\n"))
        ctx = engine.build_context([], [], settings=st)
        c((ctx.oo_min_displacement_ft, ctx.wb_min_margin_ft, ctx.wb_min_ratio, ctx.nm_min_margin_ft, ctx.nm_min_ratio) == (0.0, 10.0, 1.5, 0.0, 1.0),
          "the five rangefit thresholds load from [thresholds]")
        base = engine.build_context([], [])
        c((base.oo_min_displacement_ft, base.wb_min_margin_ft, base.wb_min_ratio, base.nm_min_margin_ft, base.nm_min_ratio) == (150.0, 150.0, 2.0, 5000.0, 2.0),
          "the rangefit thresholds default to 150 ft, 150 ft, 2.0, 5,000 ft and 2.0")
        for key, value in (("oo_min_displacement_ft", "-1"), ("wb_min_margin_ft", "-0.5"), ("nm_min_margin_ft", "-1"), ("wb_min_ratio", "0.5"), ("nm_min_ratio", "0.99")):
            raises(lambda k=key, v=value: settings_mod.load(tmp.write("bad.ini", INI + "[thresholds]\n%s = %s\n" % (k, v))),
                   "a %s of %s is refused  <-- pinned defect" % (key, value))

        # ---- from GeoJSON files through the command line
        streets = [
            feature("LineString", [[0.0, 0.0], [1000.0, 0.0]], S(SEGMENT_ID=1)),
            feature("LineString", [[0.0, 900.0], [1000.0, 900.0]], S(SEGMENT_ID=2, **UPPER)),
            feature("LineString", [[2000.0, 0.0], [1000.0, 0.0]], S(SEGMENT_ID=3, FROMLEFT=301, TOLEFT=399, FROMRIGHT=300, TORIGHT=398)),
            feature("LineString", [[0.0, 20000.0], [1000.0, 20000.0]], S(SEGMENT_ID=4, NAME="OAK", FROMLEFT=1, TOLEFT=99, FROMRIGHT=2, TORIGHT=98)),
        ]
        points = [feature("Point", [x, 30.0], A(Add_Number=n, HOUSE_NU=str(n))) for n, x in far_out]
        points.append(feature("Point", [500.0, 800.0], A(Add_Number=105, HOUSE_NU="105")))
        points.append(feature("Point", [500.0, 19000.0], A(Add_Number=107, HOUSE_NU="107")))
        base_args = ["--addresses", tmp.write("a.geojson", collection(*points)), "--streets", tmp.write("s.geojson", collection(*streets)),
                     "--settings", tmp.write("agency.ini", INI), "--units", "feet", "--show", "200"]
        code, out, err = call(base_args)
        lines = [l.split(None, 2) for l in out.splitlines() if l.startswith("  WARNING ") or l.startswith("  ERROR ")]
        got = sorted(set((l[1], l[2].split(":")[0]) for l in lines if l[1] in ("STREET-14", "XLAYER-17", "XLAYER-18", "XLAYER-19")))
        c(err == "" and got == [("STREET-14", "street row 1"), ("XLAYER-17", "address row 3"), ("XLAYER-18", "address row 7"), ("XLAYER-19", "address row 8")],
          "a GeoJSON run reports STREET-14, XLAYER-17, XLAYER-18 and XLAYER-19 on the rows that hold the defects")
        code, out, err = call(["--addresses", base_args[1], "--streets", tmp.write("s.csv", "NAME,TYPE,FROMLEFT,TOLEFT,FROMRIGHT,TORIGHT\nELM,ST,101,199,100,198\n"),
                               "--settings", base_args[5], "--units", "feet"])
        c(all("%s was skipped: it needs street geometry" % cid in out for cid in ("STREET-14", "XLAYER-17", "XLAYER-18", "XLAYER-19")),
          "a street file without geometry skips all four checks and says why")
