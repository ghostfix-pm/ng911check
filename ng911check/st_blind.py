"""Self-test: cases that earlier fixtures could not reach, and the notices that stop a zero reading as clean.

The first sections of the range fit test use level lines that start at the origin. A sign slip in the
line arithmetic, a wrong vertex index or a segment identity mix-up gives the same verdict there.
These cases use a vertical line, a sloped line, a bent line and lines far from the origin.
"""
import io
import json

from . import cli, cross_layer_checks, engine, geometry, msag, rangefit, reader, report
from .selftest import Tmp
from .st_cli import INI, LINE, call, collection, csv_file, feature, props, text_of
from .st_fix import A, POOL_A, POOL_S, S, ctx_for, found, line, run
from .st_range import GEO, UNRANGED, UPPER, _north, _num, _row, _seg

THREE = ("XLAYER-17", "XLAYER-18", "XLAYER-19")
FOUR = THREE + ("STREET-14",)
MARGIN = dict(nm_min_margin_ft=100.0, nm_min_ratio=2.0)


def _notices(addresses, streets, ids):
    return engine.run_report(addresses, streets, ctx_for(addresses, streets, **GEO), ids=list(ids)).notices


def _nopos(number):
    return A(Add_Number=number, HOUSE_NU=str(number), _XY=None)


def _groups(point, streets):
    return list(rangefit._sides([point], ctx_for([point], streets, **GEO)))


def _bare(geometry_value, props):
    return {"type": "Feature", "properties": props, "geometry": geometry_value}


def section(h):
    c, raises = h.check, h.raises
    pooled = (len(POOL_A), len(POOL_S))

    # ---- segments told apart by identity, never by SEGMENT_ID
    for sid in ("", 0, 7):
        low, up = _row(0.0, SEGMENT_ID=sid), _row(900.0, SEGMENT_ID=sid, **UPPER)
        r = run([_num(205, 500.0, 860.0)], [low, up], THREE[1:], **MARGIN, **GEO)
        c(r == [], "a correct address on a street whose segments share SEGMENT_ID %r is not flagged  <-- pinned defect" % (sid,))
        r = run([_num(105, 500.0, 800.0)], [low, up], THREE[1:], **MARGIN, **GEO)
        c(found(r, "XLAYER-18") == 1 and found(r, "XLAYER-19") == 0,
          "a wrong-block address on a street whose segments share SEGMENT_ID %r is still XLAYER-18  <-- pinned defect" % (sid,))

    both = S(_NAMEKEY="OLD ST")
    asked = A(_NAMEKEY="OLD ST")
    c(cross_layer_checks._candidate_segments(asked, ctx_for([asked], [both])) == [both], "a segment indexed under both of an address's name keys is one candidate, not two")

    # ---- the line arithmetic away from the origin and off the level
    north = _seg((5000.0, 7000.0), (5000.0, 8000.0))
    ys = [(101, 7100.0), (103, 7200.0), (121, 7300.0), (107, 7400.0), (109, 7500.0), (111, 7600.0)]
    r = run([_num(n, 4970.0, y) for n, y in ys], [north], ["XLAYER-17"], **GEO)
    c(found(r, "XLAYER-17", "WARNING", "house number 121 is out of sequence on the left side of SEG %s" % north["SEGMENT_ID"]) == 1 and found(r, "XLAYER-17") == 1,
      "xlayer-17 finds the left side and the break on a due-north street far from the origin  <-- pinned defect")
    r = run([_num(n, 5030.0, y) for n, y in ys], [north], ["XLAYER-17"], **GEO)
    c(found(r, "XLAYER-17", text="on the right side") == 1, "xlayer-17 finds the right side of a due-north street  <-- pinned defect")
    sloped = geometry.Polyline([[(5000.0, 7000.0), (5600.0, 7800.0)]])
    along, dist, right = sloped.query(5276.0, 7418.0)
    c(abs(along - 500.0) < 1e-9 and abs(dist - 30.0) < 1e-9 and right is False and sloped.query(5324.0, 7382.0)[2] is True,
      "query measures along, off and side on a sloped line far from the origin  <-- pinned defect")
    bent = geometry.Polyline([[(5000.0, 7000.0), (5000.0, 8000.0), (6000.0, 8000.0)]])
    along, dist, right = bent.query(5500.0, 8030.0)
    c(abs(along - 1500.0) < 1e-9 and abs(dist - 30.0) < 1e-9 and right is False,
      "query adds the true length of every earlier segment of a bent line  <-- pinned defect")
    c(abs(geometry.Polyline([[(5000.0, 7000.0), (5000.0, 8000.0)]]).distance_to(5030.0, 7500.0) - 30.0) < 1e-9,
      "the distance to a due-north line far from the origin is the plain offset  <-- pinned defect")
    three = geometry.Polyline([[(0.0, 0.0), (10.0, 0.0), (20.0, 0.0)]])
    c(three.ends() == ((0.0, 0.0), (20.0, 0.0)), "ends names the last vertex of a line with three vertices  <-- pinned defect")
    west = _seg((0.0, 0.0), (100.0, 0.0))
    east3 = S(**UPPER)
    line(east3, (200.0, 0.0), (150.0, 0.0), (100.0, 0.0))
    r = run([], [west, east3], ["STREET-14"], **GEO)
    c(found(r, "STREET-14", text="meet head-to-head") == 1, "street-14 reads the last vertex of a line with three vertices  <-- pinned defect")

    # ---- STREET-14 loops, joins and ranges at their limits
    feeder = _seg((0.0, 5000.0), (100.0, 5000.0))
    ring = S(FROMLEFT=301, TOLEFT=399, FROMRIGHT=300, TORIGHT=398)
    line(ring, (100.0, 5000.0), (100.0, 5050.0), (150.0, 5050.0), (100.0, 5001.0))
    r = run([], [feeder, ring], ["STREET-14"], **GEO)
    c(r == [], "street-14 treats a loop whose ends are exactly a foot apart as closed, at any height  <-- pinned defect")
    r = run([], [west, _seg((200.0, 0.0), (101.0, 0.0), **UPPER)], ["STREET-14"], **GEO)
    c(found(r, "STREET-14") == 1, "street-14 joins two ends exactly a foot apart along the line  <-- pinned defect")
    r = run([], [west, _seg((200.0, 0.0), (100.0, 1.0), **UPPER)], ["STREET-14"], **GEO)
    c(found(r, "STREET-14") == 1, "street-14 joins two ends exactly a foot apart across the line  <-- pinned defect")
    touching = _seg((200.0, 0.0), (100.0, 0.0), FROMLEFT=199, TOLEFT=299, FROMRIGHT=200, TORIGHT=298)
    r = run([], [west, touching], ["STREET-14"], **GEO)
    c(r == [], "street-14 treats ranges that touch at one number as overlapping, a divided road  <-- pinned defect")
    r = run([], [west, _seg((200.0, 0.0), (100.0, 0.0), **UPPER)], ["STREET-14"], **GEO)
    c(r[0].source_nguid == west["RCL_NGUID"], "a street-14 finding carries the RCL_NGUID of its first segment")

    # ---- XLAYER-17 sides, line ends and the direction limit
    spine = _row(0.0)
    c(_groups(_num(101, 500.0, 0.0), [spine]) == [] and _groups(_num(101, 500.0, 0.4), [spine]) == [] and _groups(_num(101, 500.0, -0.4), [spine]) == [] and _groups(_num(101, 500.0, 0.5), [spine]) == [],
      "a point on the centerline, or within half a foot of it, has no side and joins neither group  <-- pinned defect")
    c(_groups(_num(101, 500.0, 0.6), [spine]) == [(spine["_OID"], False)] and _groups(_num(101, 500.0, -0.6), [spine]) == [(spine["_OID"], True)],
      "a point more than half a foot off the centerline joins the left or the right group")
    c(_groups(_num(101, 0.5, 30.0), [spine]) == [] and _groups(_num(101, 0.2, 30.0), [spine]) == [] and _groups(_num(101, 0.6, 30.0), [spine]) == [(spine["_OID"], False)],
      "a point exactly half a foot from the start of the line has no side  <-- pinned defect")
    c(_groups(_num(101, 999.5, 30.0), [spine]) == [] and _groups(_num(101, 999.8, 30.0), [spine]) == [] and _groups(_num(101, 999.4, 30.0), [spine]) == [(spine["_OID"], False)],
      "a point exactly half a foot from the end of the line has no side  <-- pinned defect")
    snapped = [_num(n, x, 0.0) for n, x in ((101, 100.0), (100, 150.0), (103, 200.0), (102, 250.0), (105, 300.0), (104, 350.0), (107, 400.0))]
    r = run(snapped, [spine], ["XLAYER-17"], oo_min_displacement_ft=0.0, **GEO)
    c(r == [], "xlayer-17 never mixes the two sides' numbers when the points are snapped onto the centerline  <-- pinned defect")
    c(rangefit.find_out_of_sequence([(100.0 * (k + 1), n) for k, n in enumerate([101, 103, 111, 107, 109, 105])], 0.0) == [],
      "find_out_of_sequence refuses a rank correlation of 0.49  <-- pinned defect")
    pair = rangefit.find_out_of_sequence([(100.0 * (k + 1), n) for k, n in enumerate([101, 103, 105, 107, 121, 125, 109, 111, 113, 115])], 0.0)
    lone = rangefit.find_out_of_sequence([(100.0 * (k + 1), n) for k, n in enumerate([101, 103, 105, 107, 121, 109, 111, 113, 115])], 0.0)
    c(pair == [] and [i for i, _a, _b, _s in lone] == [4], "find_out_of_sequence reports one mis-numbered house and misses two side by side, whose neighbours disagree")
    near_a, near_b = _row(0.0), _row(900.0, **UPPER)
    ctx = ctx_for([], [near_a, near_b], **GEO)
    groups = list(rangefit._sides([_num(105, 10.0, 500.0)], ctx))
    c(groups == [(near_b["_OID"], True)], "a point joins the nearer of two same-name lines, not the one it is first checked against  <-- pinned defect")

    stray = A(Add_Number=105, HOUSE_NU="105", STREET_NA="NOPE", _XY=(500.0, 3000.0))
    c(run([stray], [_row(0.0), _row(300.0, NAME="OAK")], ["XLAYER-19"], **MARGIN, **GEO) == [], "xlayer-19 reports nothing for a point whose street name matches no segment")

    # ---- XLAYER-18 and a stub whose range covers nothing
    lower, upper = _row(0.0), _row(900.0, **UPPER)
    zero_stub = _row(9000.0, FROMLEFT=0, TOLEFT=399, FROMRIGHT=None, TORIGHT=None, Parity_L="B")
    blank_stub = _row(9000.0, FROMLEFT=None, TOLEFT=None, FROMRIGHT=None, TORIGHT=None)
    r = run([_num(305, 500.0, 800.0)], [lower, upper, zero_stub], ["XLAYER-18"], **GEO)
    c(r == [], "xlayer-18 does not let a stub with a 0 range end cover a number  <-- pinned defect")
    r = run([_num(305, 500.0, 800.0)], [lower, upper, blank_stub], ["XLAYER-18"], **GEO)
    c(r == [], "xlayer-18 does not let a stub with a blank range cover a number  <-- pinned defect")

    # ---- findings carry the NGUID of their row
    wrong = run([_num(105, 500.0, 800.0)], [lower, upper], ["XLAYER-18"], **GEO)
    c(wrong[0].source_nguid.startswith("ADR") and wrong[0].source_nguid.endswith("@agency.example.org"), "an xlayer-18 finding carries the Site_NGUID of its address")
    own, rival = _row(0.0), _row(300.0, NAME="OAK")
    wrong = run([_num(105, 500.0, 201.0)], [own, rival], ["XLAYER-19"], **MARGIN, **GEO)
    c(wrong[0].source_nguid.startswith("ADR"), "an xlayer-19 finding carries the Site_NGUID of its address")
    far_out = [(101, 100.0), (103, 200.0), (121, 300.0), (107, 400.0), (109, 500.0), (111, 600.0)]
    wrong = run(_north(far_out), [spine], ["XLAYER-17"], **GEO)
    c(wrong[0].source_nguid.startswith("ADR"), "an xlayer-17 finding carries the Site_NGUID of its address")

    # ---- the readers
    c(reader._pair([1.0, 2.0, "up"], "w") == (1.0, 2.0) and reader._pair([1.0, 2.0, float("nan")], "w") == (1.0, 2.0),
      "a position keeps its first two numbers and ignores a third")
    raises(lambda: reader._pair([10 ** 400, 1.0], "w"), "a position with a huge integer is refused as a ValueError, not an OverflowError  <-- pinned defect")
    c(geometry.Frame.fit("degrees", [(180.0, 90.0), (-180.0, -90.0)]).lon0 == 0.0, "coordinates exactly at +/-180 and +/-90 are degrees")
    c(geometry.Frame.fit("degrees", [(0.0, 0.0)]).lon0 == 0.0, "a degrees frame fitted to nothing but 0, 0 centres on 0, 0")
    base = geometry.Frame.fit("degrees", [(-31.0, 29.0), (-30.8, 29.2)])
    lost = geometry.Frame.fit("degrees", [(0.0, 0.0), (-31.0, 29.0), (-30.8, 29.2)])
    c((base.lon0, base.lat0) == (lost.lon0, lost.lat0), "a position of 0, 0 does not move the centre of a degrees frame  <-- pinned defect")
    c(geometry.Frame.fit("feet", [(0.0, 0.0), (10.0, 10.0)]).units == "feet" and geometry.fits_degrees([(1.0, 2.0)]) and not geometry.fits_degrees([]) and not geometry.fits_degrees([(1.0, 2.0), (500.0, 2.0)]),
      "fits_degrees needs at least one pair and every pair inside the degree range")

    with Tmp() as tmp:
        ini = tmp.write("agency.ini", INI)
        streets_gj = tmp.write("s.geojson", collection(feature("LineString", [[0.0, 0.0], [1000.0, 0.0]], S(SEGMENT_ID=1)),
                                                       _bare(None, props(S(SEGMENT_ID=2, **UPPER)))))
        args = ["--streets", streets_gj, "--settings", ini, "--units", "feet"]
        no_xy = csv_file(tmp, "noxy.csv", ("Add_Number", "STREET_NA", "TYPE", "POINT_X", "POINT_Y"),
                         [{"Add_Number": 105, "STREET_NA": "ELM", "TYPE": "ST", "POINT_X": 500, "POINT_Y": 30}, {"Add_Number": 107, "STREET_NA": "ELM", "TYPE": "ST", "POINT_X": 600, "POINT_Y": 30}])
        code, out, err = call(["--addresses", no_xy] + args)
        c(code == 2 and out == "" and "none of the 2 address(es) has a position" in err and "--x-field and --y-field" in err,
          "an address file with no X and Y columns beside a street layer exits 2 and prints no report, not a clean pass  <-- pinned defect")
        allnull = tmp.write("allnull.geojson", collection(_bare(None, props(A(Add_Number=105, HOUSE_NU="105"))), _bare(None, props(A(Add_Number=107, HOUSE_NU="107")))))
        code, out, err = call(["--addresses", allnull] + args)
        c(code == 2 and out == "" and "none of the 2 address(es) has a position" in err,
          "a GeoJSON address file whose geometries are all null beside a street layer exits 2  <-- pinned defect")
        code, out, err = call(["--addresses", no_xy, "--x-field", "POINT_X", "--y-field", "POINT_Y"] + args)
        c("judged no address" not in out and "left out" in out and "1 of 2 street segments that have an address range and no line" in out,
          "naming the coordinate columns lifts the notice, and a ranged street with a null geometry is counted  <-- pinned defect")
        half = tmp.write("half.geojson", collection(feature("Point", [500.0, 30.0], A(Add_Number=105, HOUSE_NU="105")), _bare(None, props(A(Add_Number=107, HOUSE_NU="107")))))
        code, out, err = call(["--addresses", half] + args)
        c("XLAYER-17, XLAYER-18 and XLAYER-19 left out 1 of 2 addresses that have no position." in out, "a GeoJSON address with a null geometry is counted in a notice  <-- pinned defect")
        code, out, err = call(["--addresses", half, "--streets", tmp.write("s.csv", "NAME,TYPE,FROMLEFT,TOLEFT,FROMRIGHT,TORIGHT\nELM,ST,101,199,100,198\n"), "--settings", ini, "--units", "feet"])
        c("Notices: " in out and "STREET-14 was skipped: it needs street geometry" in out, "a run that skipped the four checks prints the notices line beside a zero count  <-- pinned defect")

        csv_streets = tmp.write("s2.csv", "NAME,TYPE,FROMLEFT,TOLEFT,FROMRIGHT,TORIGHT\nELM,ST,101,199,100,198\n")
        call(["--addresses", half, "--streets", csv_streets, "--settings", ini, "--units", "feet", "--out", tmp.path("n.csv"), "--apply"])
        call(["--addresses", half, "--streets", csv_streets, "--settings", ini, "--units", "feet", "--out", tmp.path("n.json"), "--apply", "--format", "json"])
        c("skipped" not in text_of(tmp.path("n.csv")) and any("STREET-14 was skipped" in n for n in json.loads(text_of(tmp.path("n.json")))["notices"]),
          "the --out csv holds findings only and the json file holds the notices")
        with_crs = json.loads(collection(feature("Point", [5.0, 6.0], A(Add_Number=105, HOUSE_NU="105"))))
        with_crs["crs"] = {"type": "name", "properties": {"name": "urn:ogc:def:crs:EPSG::3857"}}
        lay = reader.read_layer(tmp.write("crs.geojson", json.dumps(with_crs)), "addresses")
        c(lay.rows[0]["_RAW"] == (5.0, 6.0), "a GeoJSON crs member is ignored, so the coordinates are read as they are")

        # ---- units that could be degrees
        deg_addr = tmp.write("deg.geojson", collection(feature("Point", [-30.4995, 29.10015], A(Add_Number=105, HOUSE_NU="105"))))
        deg_street = tmp.write("degs.geojson", collection(feature("LineString", LINE, S())))
        for unit in ("feet", "meters"):
            code, out, err = call(["--addresses", deg_addr, "--streets", deg_street, "--settings", ini, "--units", unit])
            c("Every coordinate fits longitude -180..180 and latitude -90..90, yet --units is %s." % unit in out, "--units %s over a degree-sized layer says the file may be degrees  <-- pinned defect" % unit)
        code, out, err = call(["--addresses", deg_addr, "--streets", deg_street, "--settings", ini])
        c("yet --units is" not in out, "--units degrees over a degree-sized layer prints no such notice")

        # ---- a position of 0, 0 in a degrees file
        zero_addr = tmp.write("zero.geojson", collection(feature("Point", [-30.4995, 29.10015], A(Add_Number=105, HOUSE_NU="105")), feature("Point", [0.0, 0.0], A(Add_Number=107, HOUSE_NU="107"))))
        code, out, err = call(["--addresses", zero_addr, "--streets", deg_street, "--settings", ini])
        c("XLAYER-17, XLAYER-18 and XLAYER-19 left out 1 of 2 addresses that have no position." in out and "counts as none" in out,
          "an address at 0, 0 in a degrees run counts as having no position  <-- pinned defect")
        zero_line = tmp.write("zero_line.geojson", collection(feature("LineString", [[0.0, 0.0], [-30.499, 29.1]], S())))
        code, out, err = call(["--addresses", deg_addr, "--streets", zero_line, "--settings", ini])
        c(code == 2 and "zero_line.geojson feature 1: a street vertex is at 0, 0" in err, "a street vertex at 0, 0 in a degrees run refuses the file  <-- pinned defect")
        code, out, err = call(["--addresses", tmp.write("zf.geojson", collection(feature("Point", [0.0, 0.0], A(Add_Number=105, HOUSE_NU="105")))), "--streets", zero_line, "--settings", ini, "--units", "feet"])
        c("a street vertex is at 0, 0" not in err and "judged no address" not in out, "a position of 0, 0 is a real position in a feet run")

        # ---- input errors that name their file
        huge = tmp.write("huge.geojson", '{"type":"FeatureCollection","features":[{"type":"Feature","properties":{"Add_Number":1},"geometry":{"type":"Point","coordinates":[1%s,0]}}]}' % ("0" * 400))
        code, out, err = call(["--addresses", huge, "--settings", ini, "--units", "feet"])
        c(code == 2 and "huge.geojson feature 1: a position must be [x, y] with two finite numbers" in err, "a GeoJSON position with a huge integer exits 2 with a message, not 70  <-- pinned defect")
        empty_multi = tmp.write("multi0.geojson", collection(_bare({"type": "MultiLineString", "coordinates": []}, props(S()))))
        code, out, err = call(["--streets", empty_multi, "--settings", ini, "--units", "feet"])
        c(code == 2 and "multi0.geojson feature 1: a line part needs at least two positions" in err, "an empty MultiLineString exits 2 and names its file and feature  <-- pinned defect")

        # ---- --show
        for bad in ("-1", "x"):
            code, out, err = call(["--show", bad, "--version"])
            c(code == 64 and ("%r is not a number of zero or more" % bad) in err, "--show %s is refused with exit 64  <-- pinned defect" % bad)
        code, out, err = call(["--addresses", no_xy, "--x-field", "POINT_X", "--y-field", "POINT_Y", "--show", "0", "--settings", ini, "--units", "feet"])
        c("First " not in out and "Findings:" in out, "--show 0 prints the counts and no finding")

        # ---- MSAG config errors name the file and the key
        addr_only = csv_file(tmp, "plain.csv", ("Add_Number", "STREET_NA", "TYPE"), [{"Add_Number": 105, "STREET_NA": "ELM", "TYPE": "ST"}])
        table = (
            ("quoted.json", '{"source_path": "m.csv", "max_source_age_days": "30"}', "quoted.json: max_source_age_days must be a whole number of days, or null"),
            ("rate.json", '{"source_path": "m.csv", "min_match_rate": 98}', "rate.json: min_match_rate must be a fraction from 0 to 1"),
            ("flag.json", '{"source_path": "m.csv", "header_row": true}', "flag.json: header_row must be a whole number"),
            ("map.json", '{"source_path": "m.csv", "field_map": ["ESN"]}', "map.json: field_map must be an object of column names"),
            ("pad.json", '{"source_path": "m.csv", "esn_pad_width": -1}', "pad.json: esn_pad_width must be a whole number"),
            ("text.json", '{"source_path": 5}', "text.json: source_path must be text or null"),
            ("array.json", '[]', "array.json: expected a JSON object"),
            ("broken.json", '{"source_path": ', "broken.json: not valid JSON"),
            ("typo.json", '{"source_path": "m.csv", "min_match": 0.9}', "typo.json: unknown MSAG config key(s): min_match"),
            ("nosrc.json", '{"min_match_rate": 0.9}', "nosrc.json names no source_path and --msag was not given"),
        )
        for name, text, want in table:
            code, out, err = call(["--addresses", addr_only, "--settings", ini, "--units", "feet", "--msag-config", tmp.write(name, text)])
            c(code == 2 and want in err, "an MSAG config error is exit 2 and reads: %s  <-- pinned defect" % want)
        bom = tmp.write("bom.json", chr(0xFEFF) + '{"source_path": "m.csv", "min_match_rate": 0.9}')
        c(msag.load_config(bom).min_match_rate == 0.9, "an MSAG config saved with a byte order mark loads  <-- pinned defect")
        c(msag.load_config(tmp.write("whole.json", '{"source_path": "m.csv", "min_match_rate": 1, "max_source_age_days": 0, "source_hash": null}')).max_source_age_days == 0,
          "an MSAG config accepts a rate of 1 and an age limit of 0")

    # ---- the notices, one case at a time
    spine = _row(0.0)
    placed = _num(105, 500.0, 60.0)
    n = _notices([_nopos(105), _nopos(107)], [spine], THREE)
    c(len(n) == 1 and "XLAYER-17, XLAYER-18 and XLAYER-19 judged no address: none of the 2 addresses has a position." in n[0], "every address without a position gives one notice naming the three checks")
    n = _notices([placed, _nopos(107), _nopos(109)], [spine], THREE)
    c(len(n) == 1 and "left out 2 of 3 addresses that have no position." in n[0], "some addresses without a position give a notice with the count")
    c(_notices([placed, A(Add_Number=0, HOUSE_NU="0", _XY=None)], [spine], THREE) == [], "a placeholder address with no number is not counted as a lost position")
    c(_notices([placed], [spine], THREE) == [], "a run that judged every address gives no notice")
    n = _notices([_nopos(105)], [spine], ["XLAYER-18"])
    c(len(n) == 1 and n[0].startswith("XLAYER-18 judged no address: none of the 1 addresses"), "a single check is named alone")
    c(_notices([_nopos(105)], [spine], ["XLAYER-13"]) == [], "a check outside the range fit gives no position notice")
    bare = S(**UPPER)
    n = _notices([placed], [spine, bare], FOUR)
    c(n == ["XLAYER-17, XLAYER-18, XLAYER-19 and STREET-14 left out 1 of 2 street segments that have an address range and no line."], "a ranged segment with no line is counted and the four checks are named")
    n = _notices([], [spine, bare], ["STREET-14"])
    c(n == ["STREET-14 left out 1 of 2 street segments that have an address range and no line."], "STREET-14 alone is named when a ranged segment has no line")
    c(_notices([], [spine, S(**UNRANGED)], ["STREET-14"]) == [], "a segment with no address range and no line is not counted")
    res = engine.run_report([], [spine], ctx_for([], [spine], **GEO), ids=["XLAYER-17"])
    c(res.records == [] and res.notices == ["XLAYER-17 was skipped: it needs an address file (--addresses)."], "xlayer-17 on a street-only run is skipped with a notice  <-- pinned defect")

    # ---- the notices line and the console encoding
    c("Notices:" not in report.format_text([], [], [], [], [], [], 20) and "Notices: 1." in report.format_text([], ["a notice"], [], [], [], [], 20),
      "the report prints a notices line only when there are notices")
    raw = io.BytesIO()
    wrapper = io.TextIOWrapper(raw, encoding="cp1252", newline="")
    raises(lambda: wrapper.write("a" + chr(0x2603) + "b"), "a console on a legacy code page fails on a character it lacks  <-- pinned defect", UnicodeEncodeError)
    raw = io.BytesIO()
    wrapper = io.TextIOWrapper(raw, encoding="cp1252", newline="")
    cli._tolerate_encoding(wrapper, io.StringIO())
    wrapper.write("a" + chr(0x2603) + "b")
    wrapper.flush()
    c(raw.getvalue() == b"a\\u2603b", "the report prints a character the code page lacks as a backslash escape, so the run keeps its report  <-- pinned defect")
    c(json.loads(report.to_json([], ["n"], {}))["notices"] == ["n"], "the json report carries the notices")

    # These rows were made for their own cases. The catalog test runs every check over the pool, so leave it as it was.
    del POOL_A[pooled[0]:]
    del POOL_S[pooled[1]:]
