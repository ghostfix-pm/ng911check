"""Self-test: geometry, the shared value helpers, severity remapping and the crosswalks."""
import math

from . import common, crosswalks, geometry, model
from .selftest import Tmp


def section(h):
    c, raises = h.check, h.raises

    # ---- the frame
    raises(lambda: geometry.Frame("furlongs"), "a unit that is not degrees, feet or meters is refused")
    f = geometry.Frame.fit("feet", [(1.0, 2.0)])
    c(f.forward(3.0, 4.0) == (3.0, 4.0) and f.inverse(3.0, 4.0) == (3.0, 4.0), "the feet frame passes coordinates through")
    m = geometry.Frame.fit("meters", [])
    x, y = m.forward(0.3048, 0.6096)
    c(abs(x - 1.0) < 1e-12 and abs(y - 2.0) < 1e-12 and m.inverse(x, y) == (0.3048, 0.6096), "the meters frame uses the international foot, exactly 0.3048 m")
    d = geometry.Frame.fit("degrees", [])
    c(d.units == "degrees" and d.lon0 == 0.0, "the degrees frame with no coordinates centres on 0, 0")
    d = geometry.Frame.fit("degrees", [(-82.0, 29.0), (-81.8, 29.2)])
    c(abs(d.lon0 + 81.9) < 1e-9 and abs(d.lat0 - 29.1) < 1e-9, "the degrees frame centres on the middle of the data")
    fx, fy = d.forward(-81.9, 29.2)
    c(abs(fx) < 1e-6 and abs(fy - 0.1 * geometry.FEET_PER_DEGREE) < 1e-6, "a point 0.1 degrees north of the centre is 0.1 degrees of latitude away")
    bx, by = d.inverse(fx, fy)
    c(abs(bx + 81.9) < 1e-9 and abs(by - 29.2) < 1e-9, "forward then inverse returns the same degrees")
    c(abs(geometry.FEET_PER_DEGREE - 364814.0) < 1.0, "one degree of latitude is about 364,814 feet on the mean-radius sphere")
    ex, _ = d.forward(-81.8, 29.1)
    c(abs(ex - 0.1 * geometry.FEET_PER_DEGREE * math.cos(math.radians(29.1))) < 1e-6, "a degree of longitude is shortened by the cosine of the centre latitude")
    for bad in ([(-181.0, 0.0)], [(181.0, 0.0)], [(0.0, -91.0)], [(0.0, 91.0)]):
        raises(lambda b=bad: geometry.Frame.fit("degrees", b), "coordinates outside the degree range are refused when the unit is degrees, %r" % (bad,))
    c(geometry.Frame.fit("feet", [(2.0e6, 3.0e5)]).units == "feet", "projected coordinates are accepted as feet")

    # ---- polylines
    raises(lambda: geometry.Polyline([[(0.0, 0.0)]]), "a line with no part of two vertices is refused")
    pl = geometry.Polyline([[(0.0, 0.0), (100.0, 0.0)]])
    along, dist, right = pl.query(30.0, 40.0)
    c(abs(along - 30.0) < 1e-9 and abs(dist - 40.0) < 1e-9 and right is False and pl.length == 100.0, "query returns the distance along, the distance off and the side of a point left of travel")
    c(pl.query(30.0, -40.0)[2] is True and pl.distance_to(30.0, -40.0) == 40.0, "query puts a point south of an eastbound line on the right")
    c(pl.query(30.0, 0.0)[2] is False, "a point exactly on the line is on neither side")
    multi = geometry.Polyline([[(0.0, 0.0), (100.0, 0.0), (100.0, 100.0)], [(500.0, 0.0), (600.0, 0.0)], [(1.0, 1.0)]])
    c(multi.length == 300.0 and len(multi.parts) == 2, "a polyline sums its parts and drops a one-vertex part")
    c(abs(multi.query(550.0, 5.0)[0] - 250.0) < 1e-9 and multi.query(100.0, 40.0)[0] == 140.0, "the distance along counts the parts before the nearest one")
    c(multi.midpoint() == (100.0, 0.0), "the midpoint is half way along the first part")
    bent = geometry.Polyline([[(0.0, 0.0), (100.0, 0.0), (100.0, 300.0)]])
    c(tuple(round(v, 6) for v in bent.midpoint()) == (100.0, 100.0), "the midpoint can fall on a later segment of the part")
    c(pl.midpoint() == (50.0, 0.0), "the midpoint of a one-segment part is its middle")
    zero = geometry.Polyline([[(5.0, 5.0), (5.0, 5.0)]])
    c(zero.midpoint() == (5.0, 5.0) and zero.length == 0.0, "the midpoint of a zero-length part is its first vertex")
    c(geometry.point_in_ring(5.0, 5.0, [(0, 0), (10, 0), (10, 10), (0, 10), (0, 0)]) and not geometry.point_in_ring(15.0, 5.0, [(0, 0), (10, 0), (10, 10), (0, 10), (0, 0)]),
      "point_in_ring is true inside a ring and false outside")
    outer = [(0, 0), (10, 0), (10, 10), (0, 10), (0, 0)]
    hole = [(4, 4), (6, 4), (6, 6), (4, 6), (4, 4)]
    c(geometry.point_in_polygon(1, 1, [outer, hole]) and not geometry.point_in_polygon(5, 5, [outer, hole]) and not geometry.point_in_polygon(20, 5, [outer, hole]),
      "point_in_polygon is false inside a hole and outside the outer ring")

    # ---- value helpers
    c([common._clean(v) for v in (None, "", " a ", 13.0, 1.5, 7)] == ["", "", "a", "13", "1.5", "7"], "_clean renders none as blank, 13.0 as 13 and strips text")
    c(common.seg_label({"SEGMENT_ID": 36247.0, "_OID": 9}) == "36247" and common.seg_label({"SEGMENT_ID": None, "_OID": 9}) == "OID 9",
      "seg_label prints a numeric id without .0 and falls back to the OID  <-- pinned defect")
    ok = {"Add_Number": 5, "_NAMEKEY": "ELM ST"}
    c(common.is_addressable(ok) and not common.is_addressable({"Add_Number": 0, "_NAMEKEY": "X"}) and not common.is_addressable({"Add_Number": 5, "_NAMEKEY": " "})
      and not common.is_addressable({"Add_Number": "x", "_NAMEKEY": "X"}) and not common.is_addressable({"Add_Number": None, "_NAMEKEY": "X"}) and not common.is_addressable({"Add_Number": 5}),
      "is_addressable needs a positive whole number and a name")
    c(common.normalize(" n ", None, "O'Brien", "  elm   st ") == "N OBRIEN ELM ST", "normalize upper-cases, drops apostrophes and blanks and collapses spaces")
    c([common.get_parity(a, b) for a, b in ((0, 0), (None, None), (0, 5), (2, 8), (3, 9), (2, 9))] == ["0-0", "0-0", "Error", "Even", "Odd", "Both"],
      "get_parity names a zero range, a broken range and the three parities")
    c(common.esn_eq("6", "006") is True and common.esn_eq("6", "7") is False and common.esn_eq("", "7") is None and common.esn_eq("A", "a") is True and common.esn_eq("A", "B") is False and common.esn_eq(None, None) is None,
      "esn_eq compares numbers as numbers, text without case and returns None when a side is blank")
    c(common.nguid_partition("a@b@c") == ("a", "b@c") and common.nguid_partition("nope") == (None, None) and common.nguid_partition("@x") == (None, None) and common.nguid_partition(None) == (None, None),
      "nguid_partition splits at the first @ and refuses a value with no localid")
    c(common.side_of_line(0, 1, 0, 0, 10, 0) == "Left" and common.side_of_line(0, -1, 0, 0, 10, 0) == "Right" and common.side_of_line(5, 0, 0, 0, 10, 0) is None,
      "side_of_line names left, right and on the line")
    dd, foot = common.p_distance(5, 3, 0, 0, 10, 0)
    c(dd == 3.0 and foot == (5.0, 0.0), "p_distance finds the foot inside a segment")
    c(common.p_distance(-4, 3, 0, 0, 10, 0) == (5.0, (0, 0)) and common.p_distance(14, 3, 0, 0, 10, 0)[1] == (10, 0) and common.p_distance(3, 4, 0, 0, 0, 0) == (5.0, (0, 0)),
      "p_distance clamps to an end and handles a zero-length segment")
    row = {"PREFIX": "n", "STREET_NA": "elm", "TYPE": "st", "SUFFIX": "", "NAME": "oak"}
    c(common.addr_name_key(row) == "N ELM ST" and common.street_name_key(row) == "N OAK ST", "the name keys join the component fields")

    # ---- severity remapping
    rs = model.remap_severity
    c(rs("WARNING", None) == "WARNING" and rs("WARNING", "ERROR") == "ERROR" and rs("WARNING", "INFO") == "INFO", "an override raises or lowers a WARNING")
    c(rs("ERROR", "INFO") == "ERROR" and rs("ERROR", "WARNING") == "ERROR" and rs("ERROR", "ERROR") == "ERROR",
      "an override can never lower an ERROR  <-- pinned defect")
    c(rs("INFO", "ERROR") == "INFO" and rs("INFO", "ERROR", classed=True) == "ERROR" and rs("ERROR", "INFO", classed=True) == "ERROR",
      "an INFO metric line is left alone unless it is a classed record, and a classed ERROR is still held  <-- pinned defect")

    # ---- crosswalks
    cw = crosswalks.load_crosswalks()
    c(cw.dir_full("ne") == "NORTHEAST" and cw.type_full("ave") == "AVENUE" and cw.type_full("zzz") is None and cw.dir_full(None) is None, "the built-in tables map an abbreviation to its full name")
    c(cw.type_full("PARK") == "PARK" and cw.type_full("TRL") == "TRAIL" and cw.type_full("SPUR") == "SPUR", "the shortest full name represents an abbreviation shared by two names")
    c(cw.valid_dir_abbrev("N") and cw.valid_dir_abbrev("northwest") and not cw.valid_dir_abbrev("X") and cw.valid_type_abbrev("VW") and cw.valid_type_abbrev("view") and not cw.valid_type_abbrev("QQ"),
      "a direction or type is valid as an abbreviation or spelled out")
    c(cw.dir_ok("N", "NORTH") and cw.dir_ok("NORTH", "N") and cw.dir_ok("NE", "NE") and not cw.dir_ok("N", "SOUTH") and not cw.dir_ok("", ""),
      "dir_ok accepts either order and identical tokens and refuses a mismatch or two blanks")
    c(cw.type_ok("AVE", "AVENUE") and cw.type_ok("AVENUE", "AVE") and cw.type_ok("XX", "XX") and not cw.type_ok("AVE", "STREET") and not cw.type_ok("", ""),
      "type_ok accepts either order and identical tokens and refuses a mismatch or two blanks")
    c(not cw.has_modifier_domains() and not cw.valid_premod("X") and not cw.valid_postmod("X") and not cw.valid_pretypesep("X"), "no modifier domain ships with the package")
    c(cw.county_canonical("Example County") == "EXAMPLE" and cw.county_canonical(None) == "" and crosswalks.county_canonical(" x county ") == "X" and cw.county_canonical("COUNTY") == "COUNTY",
      "county_canonical drops a trailing COUNTY word and only a trailing one")
    c("FL" in cw.states and "US" in cw.countries and len(crosswalks.STREET_TYPES) > 150 and len(crosswalks.DIRECTIONS) == 8, "the built-in sets hold the Pub 28 suffixes, eight directions, states and countries")

    with Tmp() as tmp:
        ok = tmp.write("dom.csv", chr(0xFEFF) + "domain,full,abbrev\ndirection,UPPER,UP\ntype,TRAILHEAD,TH\npremod,OLD,\npostmod,BYPASS,\npretypesep,OF,\n,,\npremod,SHORT\n")
        rows = crosswalks.load_domain_csv(ok)
        c(len(rows) == 6 and rows[0] == ("direction", "UPPER", "UP") and rows[5] == ("premod", "SHORT", ""), "load_domain_csv reads a BOM file, skips a blank row and pads a short row")
        good = tmp.write("dom2.csv", "domain,full,abbrev\ndirection,UPPER,UP\ntype,TRAILHEAD,TH\npremod,OLD,\npostmod,BYPASS,\npretypesep,OF,\n")
        cw2 = crosswalks.load_crosswalks(crosswalks.load_domain_csv(good))
        c(cw2.valid_dir_abbrev("UP") and cw2.type_ok("TH", "TRAILHEAD") and cw2.valid_premod("old") and cw2.valid_postmod("BYPASS") and cw2.valid_pretypesep("OF") and cw2.has_modifier_domains(),
          "a domain file adds to the built-in tables")
        raises(lambda: crosswalks.load_domain_csv(tmp.write("d3.csv", "kind,full\nx,y\n")), "load_domain_csv refuses a wrong header")
        raises(lambda: crosswalks.load_domain_csv(tmp.write("d4.csv", "")), "load_domain_csv refuses an empty file")
        raises(lambda: crosswalks.load_domain_csv(tmp.write("d5.csv", "domain,full,abbrev\nsideways,X,Y\n")), "load_domain_csv refuses an unknown domain with its line number")
        raises(lambda: crosswalks.load_domain_csv(tmp.write("d6.csv", "domain,full,abbrev\npremod,,\n")), "load_domain_csv refuses a blank full value")
        raises(lambda: crosswalks.load_domain_csv(tmp.write("d7.csv", "domain,full,abbrev\ntype,TRAILHEAD,\n")), "load_domain_csv refuses a type with no abbreviation")

    # ---- the degree approximation against the WGS 84 ellipsoid
    phi = math.radians(29.1)
    lat_m = 111132.95255 - 559.84957 * math.cos(2 * phi) + 1.17514 * math.cos(4 * phi) - 0.0023 * math.cos(6 * phi)
    lon_m = 111412.877331 * math.cos(phi) - 93.504117 * math.cos(3 * phi) + 0.117744 * math.cos(5 * phi)
    fr = geometry.Frame.fit("degrees", [(-82.0, 29.0), (-81.8, 29.2)])
    ex, ey = fr.forward(fr.lon0 + 1.0, fr.lat0 + 1.0)
    c(abs(ey - lat_m / 0.3048) / (lat_m / 0.3048) < 0.005 and abs(ex - lon_m / 0.3048) / (lon_m / 0.3048) < 0.005,
      "a degree of latitude and of longitude near 29 degrees north is within half a percent of the WGS 84 length")
