"""Self-test: the CSV and GeoJSON readers, the settings file, the engine and the report."""
import json
import os

from . import engine, reader, report, settings
from .geometry import Frame
from .model import ErrorRecord
from .selftest import Tmp
from .st_fix import A, AG, S, ctx_for


def fc(*features):
    return json.dumps({"type": "FeatureCollection", "features": list(features)})


def pt(x, y, **props):
    return {"type": "Feature", "properties": props, "geometry": {"type": "Point", "coordinates": [x, y]}}


def ln(coords, kind="LineString", **props):
    return {"type": "Feature", "properties": props, "geometry": {"type": kind, "coordinates": coords}}


def poly(rings, kind="Polygon", **props):
    return {"type": "Feature", "properties": props, "geometry": {"type": kind, "coordinates": rings}}


SQUARE = [[0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [0.0, 10.0], [0.0, 0.0]]

INI = """[thresholds]
min_address = 1
max_address = 9999
max_range_gap = 4
distance_tolerance_ft = 500
sync_threshold = 90
[agency]
expected_agid = agency.example.org
strict_fqdn = yes
expected_state = fl
counties = Example, Other County
[names]
ignored = Alpha, beta
[checks]
ADDR-07 = off
XLAYER-05 = on
RA-04 = off
[severity]
ADDR-05 = INFO
XLAYER-14 = ERROR
RA-09-BLANK = WARNING
RA-04 = ERROR
ADDR-01 = INFO
ADDR-03 = WARNING
XLAYER-09 = ERROR
[areas]
RA-08 = %s|ESN
RA-03 = esn.geojson|KEY|MYZONE, OTHER|none
"""


def section(h):
    with Tmp() as tmp:
        _reader(h, tmp)
        _settings(h, tmp)
    _engine(h)
    _report(h)


def _reader(h, tmp):
    c, raises = h.check, h.raises
    # ---- renames
    c(reader.parse_renames(["addresses:Num=Add_Number", "streets: A = B "]) == {"addresses": {"Num": "Add_Number"}, "streets": {"A": "B"}}
      and reader.parse_renames(None) == {"addresses": {}, "streets": {}}, "parse_renames reads LAYER:ACTUAL=CANONICAL")
    for bad in ("Num=Add_Number", "addresses:Num", "roads:A=B", "addresses:=B", "addresses:A="):
        raises(lambda b=bad: reader.parse_renames([b]), "parse_renames refuses %r" % bad)

    # ---- CSV addresses
    p = tmp.write("a1.csv", chr(0xFEFF) + "Add_Number , STREET_NA,TYPE,CITY,X,Y\n12.0,ELM,ST, TESTVILLE ,-30.5,29.1\n\n12A,OAK,AVE,X,,\n,PINE,RD,Y,-30.4,29.2\n13\n")
    lay = reader.read_layer(p, "addresses")
    c(len(lay.rows) == 4 and lay.rows[0]["Add_Number"] == 12 and lay.rows[1]["Add_Number"] == "12A" and lay.rows[2]["Add_Number"] is None,
      "read_layer turns a whole number into an int, keeps text as text and a blank as None")
    c(lay.rows[0]["CITY"] == " TESTVILLE " and lay.rows[0]["_NAMEKEY"] == "ELM ST" and lay.rows[0]["_OID"] == 1 and lay.rows[2]["_OID"] == 3,
      "read_layer does not strip values (addr-07 needs them) and numbers the data rows")
    c(lay.rows[0]["_RAW"] == (-30.5, 29.1) and lay.rows[1]["_RAW"] is None and lay.rows[3]["CITY"] == "" and "X" in lay.columns,
      "read_layer reads X and Y, leaves blank coordinates empty and pads a short row")
    c(sorted(lay.raw_coords()) == [(-30.5, 29.1), (-30.4, 29.2)] and "ZIP_CODE" in lay.missing_columns() and "Add_Number" not in lay.missing_columns(),
      "a layer lists its raw coordinates and the columns the file lacks")

    q = tmp.write("a2.csv", "Num,STREET_NA,Lon,Lat\n5,ELM,-30.5,29.1\n")
    lay = reader.read_layer(q, "addresses", {"Num": "Add_Number"}, "Lon", "Lat")
    c(lay.rows[0]["Add_Number"] == 5 and lay.rows[0]["_RAW"] == (-30.5, 29.1), "read_layer renames a column and reads named coordinate columns")
    lay = reader.read_layer(tmp.write("a3.csv", "Add_Number,STREET_NA\n5,ELM\n"), "addresses")
    c(lay.rows[0]["_RAW"] is None, "a CSV without coordinate columns has no positions")
    raises(lambda: reader.read_layer(tmp.write("a4.csv", ""), "addresses"), "read_layer refuses a CSV with no header row")
    raises(lambda: reader.read_layer(tmp.write("a5.csv", "A,A\n1,2\n"), "addresses"), "read_layer refuses duplicate column names")
    raises(lambda: reader.read_layer(q, "addresses", {"Num": "STREET_NA"}), "read_layer refuses a rename that makes two columns share a name")
    raises(lambda: reader.read_layer(tmp.write("a6.csv", "Add_Number,X,Y\n1,abc,2\n"), "addresses"), "read_layer refuses a coordinate that is not a number")
    raises(lambda: reader.read_layer(tmp.write("a7.csv", "Add_Number,X,Y\n1,5,\n"), "addresses"), "read_layer refuses one coordinate without the other")
    raises(lambda: reader.read_layer(tmp.write("a8.csv", "Add_Number,X,Y\n1,nan,2\n"), "addresses"), "read_layer refuses a coordinate that is not finite")
    raises(lambda: reader.read_layer(tmp.write("a9.txt", "x"), "addresses"), "read_layer refuses a file type it does not know")

    # ---- CSV streets
    s1 = tmp.write("s1.csv", "NAME,TYPE,FROMLEFT,TOLEFT,FROMRIGHT,TORIGHT\nELM,ST,101,199,100,198\n")
    lay = reader.read_layer(s1, "streets")
    c(lay.rows[0]["FROMLEFT"] == 101 and lay.rows[0]["_NAMEKEY"] == "ELM ST" and lay.lines == {}, "read_layer reads a street range as whole numbers")
    raises(lambda: reader.read_layer(tmp.write("s2.csv", "NAME,FROMLEFT\nELM,10A\n"), "streets"), "read_layer refuses a street range that is not a whole number")
    raises(lambda: reader.read_layer(tmp.write("s3.csv", "NAME,FROMLEFT\nELM,1.5\n"), "streets"), "read_layer refuses a street range with a fraction")
    raises(lambda: reader.read_layer(tmp.write("s4.csv", "NAME,FROMLEFT\nELM,inf\n"), "streets"), "read_layer refuses an infinite street range")

    # ---- GeoJSON addresses
    g1 = tmp.write("a1.geojson", fc(pt(-30.5, 29.1, Add_Number=7, STREET_NA="ELM", TYPE="ST"), {"type": "Feature", "properties": None, "geometry": None},
                                    {"type": "Feature", "properties": {"Add_Number": "9"}}, "not a feature"))
    lay = reader.read_layer(g1, "addresses")
    c(len(lay.rows) == 4 and lay.rows[0]["_RAW"] == (-30.5, 29.1) and lay.rows[1]["_RAW"] is None and lay.rows[2]["Add_Number"] == 9 and lay.rows[3]["_NAMEKEY"] == "",
      "read_layer reads GeoJSON points, a null geometry, a missing properties object and a non-feature")
    lay = reader.read_layer(tmp.write("a2.geojson", fc(pt(1.0, 2.0, Num=3))), "addresses", {"Num": "Add_Number"})
    c(lay.rows[0]["Add_Number"] == 3, "read_layer renames a GeoJSON property")
    lay = reader.read_layer(tmp.write("a2b.geojson", fc(pt(1.0, 2.0, Num=3), pt(3.0, 4.0))), "addresses", {"Num": "Add_Number"})
    c(lay.rows[0]["Add_Number"] == 3 and lay.rows[1].get("Add_Number") is None, "read_layer applies a rename only to the features that have the property")
    raises(lambda: reader.read_layer(tmp.write("a3.geojson", fc(pt(1.0, 2.0, Num=3, Add_Number=4))), "addresses", {"Num": "Add_Number"}), "read_layer refuses a rename onto a property that exists")
    raises(lambda: reader.read_layer(tmp.write("a4.geojson", "{not json"), "addresses"), "read_layer refuses text that is not JSON")
    raises(lambda: reader.read_layer(tmp.write("a5.geojson", json.dumps({"type": "Feature"})), "addresses"), "read_layer refuses JSON that is not a FeatureCollection")
    raises(lambda: reader.read_layer(tmp.write("a6.geojson", json.dumps([1])), "addresses"), "read_layer refuses a JSON list")
    raises(lambda: reader.read_layer(tmp.write("a7.geojson", fc(ln([[0, 0], [1, 1]]))), "addresses"), "read_layer refuses a line in an address layer")
    raises(lambda: reader.read_layer(tmp.write("a8.geojson", fc({"type": "Feature", "properties": {}, "geometry": {"type": "Point"}})), "addresses"), "read_layer refuses a geometry with no coordinates")
    raises(lambda: reader.read_layer(tmp.write("a9.geojson", fc({"type": "Feature", "properties": {}, "geometry": "x"})), "addresses"), "read_layer refuses a geometry that is not an object")
    for badpos in ([1.0], "ab", [1.0, "x"], [True, 2.0], [float("nan"), 2.0]):
        raises(lambda b=badpos: reader.read_layer(tmp.write("a10.geojson", json.dumps({"type": "FeatureCollection", "features": [pt(0, 0)]}).replace("[0, 0]", json.dumps(b).replace("NaN", "NaN"))), "addresses"),
               "read_layer refuses the position %s" % json.dumps(badpos))

    # ---- GeoJSON streets
    st = tmp.write("s1.geojson", fc(ln([[0, 0], [1, 0]], NAME="ELM", FROMLEFT=1), ln([[[0, 0], [1, 0]], [[5, 5], [6, 5]]], "MultiLineString", NAME="OAK"), {"type": "Feature", "properties": {}, "geometry": None}))
    lay = reader.read_layer(st, "streets")
    c(sorted(lay.lines) == [1, 2] and len(lay.lines[2]) == 2 and lay.rows[2]["_RAW"] is None and len(list(lay.raw_coords())) == 6,
      "read_layer reads a line and a multi-line into parts and keeps a street with no geometry")
    raises(lambda: reader.read_layer(tmp.write("s5.geojson", fc(pt(0, 0))), "streets"), "read_layer refuses a point in a street layer")
    raises(lambda: reader.read_layer(tmp.write("s6.geojson", fc(ln([[0, 0]]))), "streets"), "read_layer refuses a line with one position")
    raises(lambda: reader.read_layer(tmp.write("s7.geojson", fc(ln([[[0, 0]], [[1, 1], [2, 2]]], "MultiLineString"))), "streets"), "read_layer refuses a multi-line part with one position")

    # ---- areas
    ar = tmp.write("ar1.geojson", fc(poly([SQUARE], KEY=1), poly([[SQUARE], [SQUARE]], "MultiPolygon", KEY=2)))
    areas = reader.read_areas(ar, "KEY")
    c(len(areas) == 3 and areas[0][0] == 1 and areas[2][0] == 2 and len(areas[0][1]) == 1, "read_areas returns one entry per polygon, with the key of its feature")
    raises(lambda: reader.read_areas(tmp.write("ar2.geojson", fc(poly([SQUARE], OTHER=1))), "KEY"), "read_areas refuses a feature without the key property")
    raises(lambda: reader.read_areas(tmp.write("ar3.geojson", fc({"type": "Feature", "properties": None, "geometry": None})), "KEY"), "read_areas refuses a feature with no properties")
    raises(lambda: reader.read_areas(tmp.write("ar4.geojson", fc(pt(0, 0, KEY=1))), "KEY"), "read_areas refuses a point")
    raises(lambda: reader.read_areas(tmp.write("ar5.geojson", fc(poly([SQUARE[:-1] + [[1.0, 1.0]]], KEY=1))), "KEY"), "read_areas refuses a ring that does not close")
    raises(lambda: reader.read_areas(tmp.write("ar6.geojson", fc(poly([SQUARE[:3]], KEY=1))), "KEY"), "read_areas refuses a ring of fewer than four positions")
    raises(lambda: reader.read_areas(tmp.write("ar7.geojson", fc(poly([], KEY=1))), "KEY"), "read_areas refuses a polygon with no ring")

    # ---- planar feet and the area annotation
    frame = Frame.fit("feet", [])
    lay = reader.read_layer(tmp.write("a11.geojson", fc(pt(5.0, 5.0, Add_Number=1, STREET_NA="X"), pt(50.0, 50.0, Add_Number=2, STREET_NA="X"), {"type": "Feature", "properties": {"Add_Number": 3}, "geometry": None})), "addresses")
    geoms = reader.finalize_layer(lay, frame)
    c(geoms == {} and lay.rows[0]["_XY"] == (5.0, 5.0) and lay.rows[2]["_XY"] is None and "_RAW" not in lay.rows[0], "finalize_layer gives each row a position and removes the raw one")
    reader.annotate_areas(lay.rows, [("A", [SQUARE]), ("B", [SQUARE])], "_k", frame)
    c([r["_k"] for r in lay.rows] == ["A", None, None], "annotate_areas names the first polygon that holds a point, and None for a point outside or with no position")
    lay = reader.read_layer(st, "streets")
    geoms = reader.finalize_layer(lay, frame)
    c(sorted(geoms) == [1, 2] and lay.rows[0]["_XY"] == (0.5, 0.0) and lay.rows[2]["_XY"] is None, "finalize_layer gives a street the midpoint of its line")


def _settings(h, tmp):
    c, raises = h.check, h.raises
    base = tmp.write("esn.geojson", fc(poly([SQUARE], KEY=1)))
    path = tmp.write("ok.ini", INI % base.replace("\\", "/"))
    st = settings.load(path)
    c(st.ctx_overrides["min_address"] == 1 and st.ctx_overrides["distance_tolerance_ft"] == 500.0 and st.ctx_overrides["strict_fqdn"] is True
      and st.ctx_overrides["expected_state"] == "FL" and st.ctx_overrides["counties"] == frozenset({"EXAMPLE", "OTHER COUNTY"}) and st.ctx_overrides["expected_agid"] == "agency.example.org",
      "settings.load reads thresholds and agency values with their types")
    c(st.names_ignored == frozenset({"ALPHA", "BETA"}) and st.checks == {"ADDR-07": False, "XLAYER-05": True, "RA-04": False}
      and st.severity["ADDR-05"] == "INFO" and st.severity["RA-09-BLANK"] == "WARNING", "settings.load reads names, check switches and severities")
    c(st.areas["RA-08"].path == base.replace("\\", "/") and st.areas["RA-08"].fields is None and st.areas["RA-03"].path == os.path.normpath(os.path.join(tmp.root, "esn.geojson"))
      and st.areas["RA-03"].fields == ("MYZONE", "OTHER") and st.areas["RA-03"].sentinel == "NONE", "settings.load resolves a relative area path against the settings folder")
    c(settings.load(tmp.write("bom.ini", chr(0xFEFF) + "[thresholds]\nmin_address = 2\n")).ctx_overrides["min_address"] == 2, "settings.load tolerates a UTF-8 byte order mark")
    c(settings.load(tmp.write("names.ini", "[names]\nignored =\n")).names_ignored is None, "an empty ignored list keeps the default and does not switch every name off")
    c(settings.load(tmp.write("case.ini", "[Checks]\nADDR-01 = yes\n")).checks == {"ADDR-01": True}, "settings.load matches a section name without regard to case")

    def bad(label, text, raw=None):
        p = tmp.write("bad.ini", text) if raw is None else _raw(tmp, "bad.ini", raw)
        raises(lambda: settings.load(p), label)

    raises(lambda: settings.load(tmp.path("missing.ini")), "settings.load refuses a file that does not exist")
    c(settings.load(tmp.write("empty.ini", "")).ctx_overrides == {}, "settings.load reads an empty file as no overrides")
    bad("settings.load refuses text with no section", "key = 1\n")
    bad("settings.load refuses a file that is not UTF-8", None, b"\xff\xfe\x00[x]")
    bad("settings.load refuses a DEFAULT section", "[DEFAULT]\na = 1\n")
    bad("settings.load refuses two sections that differ only in case", "[checks]\nADDR-01 = on\n[Checks]\nADDR-02 = on\n")
    bad("settings.load refuses an unknown section", "[colours]\na = 1\n")
    bad("settings.load refuses an unknown threshold", "[thresholds]\nbogus = 1\n")
    bad("settings.load refuses a threshold that is not a number", "[thresholds]\nmin_address = many\n")
    bad("settings.load refuses a threshold that is not finite", "[thresholds]\nsync_threshold = nan\n")
    bad("settings.load refuses an unknown agency key", "[agency]\nbogus = 1\n")
    bad("settings.load refuses a true or false value that is neither", "[agency]\nstrict_fqdn = maybe\n")
    bad("settings.load refuses an unknown names key", "[names]\nbogus = 1\n")
    bad("settings.load refuses a check id that does not exist", "[checks]\nADDR-99 = on\n")
    bad("settings.load refuses to switch a severity-only id on or off", "[checks]\nRA-09-BLANK = off\n")
    bad("settings.load refuses a severity for an id that does not exist", "[severity]\nADDR-99 = INFO\n")
    bad("settings.load refuses a severity that is not ERROR, WARNING or INFO", "[severity]\nADDR-01 = LOUD\n")
    bad("settings.load refuses an area id that is not an area check", "[areas]\nADDR-01 = a.geojson|KEY\n")
    bad("settings.load refuses an area line with one part", "[areas]\nRA-08 = a.geojson\n")
    bad("settings.load refuses an area line with a blank key", "[areas]\nRA-08 = a.geojson| \n")
    bad("settings.load refuses an area line with five parts", "[areas]\nRA-08 = a|b|c|d|e\n")
    for word, want in (("1", True), ("T", True), ("On", True), ("0", False), ("no", False), ("F", False)):
        c(settings.load(tmp.write("b.ini", "[agency]\nstrict_fqdn = %s\n" % word)).ctx_overrides["strict_fqdn"] is want, "settings reads %r as %s" % (word, want))

    # ---- apply and print
    ctx = ctx_for([], [], settings=path)
    c(ctx.min_address == 1 and ctx.street_names_ignored == frozenset({"ALPHA", "BETA"}) and ctx.settings.source == path and ctx.expected_agid == "agency.example.org",
      "build_context applies a settings file given by path, and the settings override the default agency")
    st2 = settings.Settings()
    st2.ctx_overrides["bogus"] = 1
    raises(lambda: settings.apply_to_context(ctx, st2), "apply_to_context refuses a setting that targets no context field")
    lines = settings.effective_lines(st)
    text = "\n".join(lines)
    c("Settings source: " in text and "min_address" in text and "EXAMPLE, OTHER COUNTY" in text and "Ignored street names: ALPHA, BETA" in text and "ADDR-07      off" in text
      and "RA-04" in text and "RA-08" in text and "Severity overrides:" in text, "effective_lines prints every section of the settings")
    c("(no effect: RA-04 is not run by this package)" in text and "(ERROR findings stay ERROR; the others become INFO)" in text, "effective_lines says when a line has no effect or leaves ERRORs in place  <-- pinned defect")
    c(settings.effective_lines(settings.Settings()) == ["Settings source: (built-in defaults)", "(no overrides - every check uses its built-in default)"], "effective_lines says plainly when there are no overrides")
    n = settings.override_note
    c(n("ADDR-01", "INFO") == "  (no effect: emits only ERROR findings; the engine never lowers an ERROR)", "override_note: a check that emits only ERROR is unchanged by a lower line")
    c(n("XLAYER-14", "ERROR") == "  (no effect: emits only INFO findings; cannot be escalated)", "override_note: an INFO metric cannot be escalated")
    c(n("ADDR-03", "WARNING") == "  (no effect: every finding it emits stays where it is)", "override_note: a line equal to the check's own severity changes nothing")
    c(n("ADDR-05", "INFO") == "  (ERROR findings stay ERROR; the others become INFO)", "override_note: a mixed check keeps its ERRORs  <-- pinned defect")
    c(n("ADDR-05", "ERROR") == "" and n("RA-09-BLANK", "ERROR") == "", "override_note: raising says nothing")
    c(n("RA-09-BLANK", "INFO") == "  (no effect: every finding it emits stays where it is)" and n("NOPE-1", "INFO").startswith("  (no effect: NOPE-1 is not run"),
      "override_note: a class that is already INFO, and an unknown id")
    c(settings.override_lines([{"id": "ADDR-05", "override": "INFO", "changed": 1, "held": 2, "info": 0, "same": 3}]) == [
        "  ADDR-05        INFO: 1 raised or lowered, 2 held at ERROR, 0 INFO untouched, 3 already INFO"], "override_lines prints what each line did on the run")


def _raw(tmp, name, data):
    with open(tmp.path(name), "wb") as fh:
        fh.write(data)
    return tmp.path(name)


def _engine(h):
    c, raises = h.check, h.raises

    # ---- the override tally
    def rec(cid, sev, sid=None):
        return ErrorRecord(cid, "n", "f", sev, "address", 1, "", "d", None, sid)
    recs = [rec("ADDR-05", "ERROR"), rec("ADDR-05", "WARNING"), rec("ADDR-05", "INFO"), rec("ADDR-05", "INFO"), rec("RA-09", "INFO", "RA-09-BLANK"), rec("ADDR-01", "ERROR"), rec("XLAYER-01", "ERROR"), rec("ADDR-06", "ERROR")]
    tally = engine.apply_overrides(recs, {"ADDR-05": "INFO", "RA-09-BLANK": "WARNING", "ADDR-01": "ERROR", "ADDR-99": "ERROR"})
    by = dict((t["id"], t) for t in tally)
    c(by["ADDR-05"] == {"id": "ADDR-05", "override": "INFO", "changed": 1, "held": 1, "info": 2, "same": 0}, "apply_overrides holds an ERROR, lowers a WARNING and leaves INFO metrics alone")
    c(by["RA-09-BLANK"]["changed"] == 1 and by["ADDR-01"]["same"] == 1 and by["ADDR-99"]["changed"] == 0 and [t["id"] for t in tally] == sorted(by),
      "apply_overrides re-severities a classed record, counts an unchanged one and lists a line that matched nothing")
    c([r.severity for r in recs] == ["ERROR", "INFO", "INFO", "INFO", "WARNING", "ERROR", "ERROR", "ERROR"], "apply_overrides changes the records in place and never lowers an ERROR")

    # ---- the pipeline keeps the rule
    st = settings.Settings()
    st.severity["ADDR-05"] = "INFO"
    st.ctx_overrides["expected_agid"] = AG
    adds = [A(ESN="ABC"), A(STATUS="RETIRED")]
    ctx = ctx_for(adds, [], settings=st)
    res = engine.run_report(adds, [], ctx, ids=["ADDR-05"])
    sev = sorted(r.severity for r in res.records)
    c(sev == ["ERROR", "INFO"] and res.tally[0]["held"] == 1 and res.tally[0]["changed"] == 1,
      "a settings line ADDR-05 = INFO lowers the WARNING and leaves the invalid-ESN ERROR  <-- pinned defect")
    c(report.exit_status(res.records) == 1, "the held ERROR still makes the run exit 1  <-- pinned defect")

    # ---- context
    raises(lambda: engine.build_context([], [], bogus=1), "build_context refuses an override that names no context field")
    s_a, s_b = S(_NAMEKEY="STALE"), S()
    ctx = ctx_for([], [s_a, s_b])
    c(ctx.streets_by_name["STALE"] == [s_a] and ctx.streets_by_name["ELM ST"] == [s_a, s_b], "build_context also indexes a street under its true component name")
    a_one = A()
    ctx = ctx_for([a_one], [S()])
    c(ctx.addresses_by_name["ELM ST"] == [a_one], "build_context indexes addresses by name")

    # ---- which checks run
    st = settings.Settings()
    st.checks = {"ADDR-01": False, "XLAYER-05": True, "XLAYER-16": False}
    adds = [A(STATE="")]
    ctx = ctx_for(adds, [], settings=st)
    c("ADDR-01" not in {r.check_id for r in engine.run_report(adds, [], ctx, family="address_attr").records}, "run_report honours a switch-off")
    ids = {r.check_id for r in engine.run_report(adds, [], ctx, ids=["ADDR-01", "ADDR-08", "NOPE-9"]).records}
    c("ADDR-01" not in ids, "an explicit switch-off wins even when the check is named by id")
    ctx = ctx_for([A(STATE="")], [])
    c({r.check_id for r in engine.run_report([A(STATE="")], [], ctx, priority="v1", target="address").records} >= {"ADDR-01"}, "run_report filters by priority and target")
    c({r.check_id for r in engine.run_report([A(STATE="")], [], ctx, family="street_attr").records} == set(), "run_report filters by family")
    res = engine.run_report([A(STATE="")], [], ctx, ids=["ADDR-01"])
    c(len(res.records) == 1 and res.notices == [], "run_report with ids runs only those checks")
    seen = []
    res = engine.run_report([], [S()], ctx_for([], [S()]), ids=["XLAYER-13", "XLAYER-15", "STREET-11"], warn=seen.append)
    c(len(res.notices) == 3 and "XLAYER-13 was skipped: it needs street geometry" in res.notices[0] and "XLAYER-15 was skipped: it needs modifier domains" in res.notices[1]
      and seen == res.notices[:2] + res.notices[2:] and "DEGRADED" in res.notices[2], "run_report skips a check whose input is missing, says why, and names the degraded STREET-11 mode")
    res = engine.run_report([], [S()], ctx_for([], [S()], area_layers=frozenset()), ids=["RA-08"])
    c("a polygon layer for RA-08 (an [areas] line)" in res.notices[0], "run_report names the polygon layer a skipped area check needs")
    res = engine.run_report([], [S()], ctx_for([], [S()], authoritative_names=frozenset()), ids=["STREET-11"])
    c(res.notices == [], "run_report does not call STREET-11 degraded when a name list is loaded")
    c(engine.run_checks([A(STATE="")], [], ctx_for([A(STATE="")], []), ids=["ADDR-01"])[0].check_id == "ADDR-01", "run_checks returns the records alone")
    optional = engine.run_report([A()], [S()], ctx_for([A()], [S()]), include_optional=True).records
    c(report.exit_status(optional) == 0 and any(r.check_id == "XLAYER-11" for r in optional) and len(engine.run_report([], [], ctx_for([], [])).records) == 0,
      "run_report with the optional checks on adds the opt-in metric, and an empty world has no finding")


def _report(h):
    c = h.check
    r1 = ErrorRecord("B-1", "n", "f", "WARNING", "street", 2, "g", "second", (10.0, 20.0))
    r2 = ErrorRecord("A-1", "n", "f", "ERROR", "address", 1, "g2", "first, with a comma", None)
    r3 = ErrorRecord("A-2", "n", "f", "INFO", "dataset", 0, "", "third", (1.0, 2.0))
    recs = [r1, r2, r3]
    c([r.check_id for r in report.ordered(recs)] == ["A-1", "B-1", "A-2"], "ordered puts ERROR first, then WARNING, then INFO")
    c(report.counts(recs) == {"ERROR": 1, "WARNING": 1, "INFO": 1} and report.counts([]) == {"ERROR": 0, "WARNING": 0, "INFO": 0}, "counts gives all three severities, zeros included")
    c(report.by_check(recs + [r1]) == [("A-1", "ERROR", 1), ("B-1", "WARNING", 2), ("A-2", "INFO", 1)], "by_check counts each check and severity, most severe first")
    c(report.exit_status(recs) == 1 and report.exit_status([r1, r3]) == 0 and report.exit_status([]) == 0, "exit_status is 1 only when an ERROR remains")
    rows = report.to_rows(recs, Frame("feet"))
    c(rows[0]["x"] == "" and rows[1]["x"] == "10.000" and rows[1]["y"] == "20.000" and rows[0]["row"] == 1, "to_rows writes feet with three decimals and a blank for no position")
    deg = Frame("degrees", -30.0, 29.0)
    r4 = ErrorRecord("A-3", "n", "f", "INFO", "dataset", 0, "", "fourth", (0.0, 0.0))
    c(report.to_rows([r4], deg)[0]["x"] == "-30.0000000" and report.to_rows([r4], deg)[0]["y"] == "29.0000000", "to_rows writes degrees with seven decimals")
    text = report.to_csv_text(rows)
    c(text.splitlines()[0] == ",".join(report.CSV_COLUMNS) and '"first, with a comma"' in text and "\r" not in text and text.endswith("\n"), "to_csv_text quotes a comma, writes LF and starts with the header")
    doc = json.loads(report.to_json(rows, ["n1"], {"ERROR": 1}))
    c(doc["summary"] == {"ERROR": 1} and doc["notices"] == ["n1"] and len(doc["findings"]) == 3, "to_json carries the summary, the notices and every finding")
    out = report.format_text(recs, ["note"], ["Settings source: x"], ["  tally"], ["addresses: a.csv (1 rows)"], [("Roll-up:", ["  line"])], 2)
    c("NOTICE: note" in out and "Override effects on this run:" in out and "Findings: 1 ERROR, 1 WARNING, 1 INFO" in out and "Roll-up:" in out and "... 1 more. Write them all with --out FILE --apply." in out,
      "format_text prints the settings, the notices, the override effects, the counts, the roll-ups and how many findings it left out")
    out = report.format_text([], [], ["s"], [], [], [], 20)
    c("Findings: 0 ERROR, 0 WARNING, 0 INFO" in out and "First" not in out and "NOTICE" not in out and "Override effects" not in out, "format_text with no findings prints no list and no notice")
    out = report.format_text(recs, [], ["s"], [], [], [], 20)
    c("more." not in out and "First 3 finding(s)" in out, "format_text prints all findings when they fit under the limit")
