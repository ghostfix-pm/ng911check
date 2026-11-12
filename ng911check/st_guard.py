"""Self-test: a null polygon key, a reference layer with no hit, and the CSV formula guard."""
import ast
import csv
import io
import os

from . import geometry, reader, report, response_area_checks as ra
from .geometry import Frame
from .selftest import Tmp
from .st_cli import HEADER, INI, LINE, call, collection, csv_file, feature, props
from .st_fix import A, AG, S
from .st_io import SQUARE

BOX = [[-30.501, 29.099], [-30.498, 29.099], [-30.498, 29.101], [-30.501, 29.101], [-30.501, 29.099]]
FAR = [[-20.501, 29.099], [-20.498, 29.099], [-20.498, 29.101], [-20.501, 29.101], [-20.501, 29.099]]
STARTS = (("=", "equals"), ("+", "plus"), ("-", "minus"), ("@", "at sign"), (chr(9), "tab"), (chr(13), "cr"))
TEXT_COLUMNS = ("check_id", "check_name", "family", "severity", "layer", "nguid", "description")
BASE_ROW = {"check_id": "ADDR-05", "check_name": "name", "family": "address_attr", "severity": "ERROR",
            "layer": "address", "row": 7, "nguid": "ADR7@" + AG, "description": "text",
            "x": "-30.0000000", "y": "29.0000000"}


def _in(key, cid="RA-08", **kw):
    row = A(**kw)
    row["_XY"] = (0.0, 0.0)
    row[ra.annotation_key(cid)] = key
    return row


def _parse(text):
    return list(csv.reader(io.StringIO(text, newline="")))


def _read(path):
    with open(path, encoding="utf-8", newline="") as fh:
        return fh.read()


def _areas(tmp, name, key, ring=BOX):
    return tmp.write(name, collection({"type": "Feature", "properties": {"ESN": key}, "geometry": {"type": "Polygon", "coordinates": [ring]}}))


def _addresses(tmp, name, **kw):
    return tmp.write(name, collection(feature("Point", [-30.4995, 29.10015], A(Add_Number=101, HOUSE_NU="101", **kw))))


def section(h):
    c = h.check
    _null_key(c)
    _zero_hits(h)
    _unplaced(c)
    _guard(c)
    with Tmp() as tmp:
        _cli(c, tmp)


def _null_key(c):
    # ---- the comparison: a null key is its own finding, never a mismatch
    r = ra.check_ra_08([_in("", ESN="20")])
    c(len(r) == 1 and r[0].severity == "ERROR" and r[0].check_name.endswith(ra.NULL_KEY_SUFFIX) and "whose key is null or blank" in r[0].description
      and "ESN cannot be checked" in r[0].description and "!=" not in r[0].description,
      "a point inside a polygon with a null key is reported as its own finding, not as a mismatch  <-- pinned defect")
    r = ra.check_ra_08([_in("", ESN=""), _in("  ", ESN="20")])
    c(len(r) == 2, "a null key is reported whether the stored ESN is blank or filled, and a key of spaces counts as null")
    c(ra.check_ra_08([_in("30", ESN="20")])[0].check_name == ra.DEFAULT_RULES["RA-08"].name, "a mismatch keeps the plain check name")
    two = ra.check_ra_01([_in("", "RA-01", RA_1="B2", RA_2="B3")])
    city = ra.check_ra_09([_in("", "RA-09", CITY="")])
    c(len(two) == 1 and two[0].description.endswith("RA_1, RA_2 cannot be checked") and city[0].severity == "ERROR" and city[0].severity_id is None,
      "a null key reports once per row for a two-field rule and stays ERROR for ra-09 even when the CITY is blank  <-- pinned defect")
    rows = ra.rollup([_in("", ESN="20"), _in("", ESN="21"), _in("30", ESN="20")], ["RA-08"])
    c(sorted((r_["containing"], r_["count"]) for r_ in rows) == [("(null key)", 2), ("30", 1)] and ra.NULL_KEY_LABEL == "(null key)",
      "rollup groups every point of a null-keyed polygon under (null key)")

    # ---- the annotation
    frame = Frame.fit("feet", [])
    for key, want in ((None, ""), ("", ""), ("   ", ""), (0, 0), ("A", "A")):
        rows = [{"_OID": 1, "_XY": (5.0, 5.0)}]
        reader.annotate_areas(rows, [(key, [SQUARE])], "_k", frame)
        c(rows[0]["_k"] == want and type(rows[0]["_k"]) is type(want), "annotate_areas stores %r for a polygon keyed %r  <-- pinned defect" % (want, key))
    rows = [{"_OID": 1, "_XY": (5.0, 5.0)}]
    reader.annotate_areas(rows, [("", [SQUARE]), ("B", [SQUARE])], "_k", frame)
    first = rows[0]["_k"]
    reader.annotate_areas(rows, [("B", [SQUARE]), ("", [SQUARE])], "_k", frame)
    c(first == "" and rows[0]["_k"] == "", "a point inside a null-keyed and a keyed polygon is a null key whichever comes first in the file  <-- pinned defect")
    reader.annotate_areas(rows, [("B", [SQUARE]), ("C", [SQUARE])], "_k", frame)
    c(rows[0]["_k"] == "B", "a point inside two keyed polygons takes the first in the file")


def _unplaced(c):
    # ---- an address with no position is not judged against a polygon
    nowhere = A(ESN="7")
    nowhere["_XY"] = None
    nowhere[ra.annotation_key("RA-08")] = None
    r = ra.check_ra_08([nowhere, _in("30", ESN="30")])
    c(r == [], "ra-08 does not call an address with no position outside every polygon  <-- pinned defect")
    c(ra.rollup([nowhere], ["RA-08"]) == [], "the roll-up leaves an address with no position out too  <-- pinned defect")
    c(ra.coverage_notice([nowhere, _in("30", ESN="30")], {"RA-08"}).startswith("RA-08 left out 1 of 2 addresses that have no position, so ")
      and ra.coverage_notice([nowhere], {"RA-10", "RA-08"}).startswith("RA-08 and RA-10 left out 1 of 1 addresses"),
      "the notice names the running checks and counts the addresses that have no position")
    c(ra.coverage_notice([nowhere], {"ADDR-05"}) is None and ra.coverage_notice([_in("30", ESN="30")], {"RA-08"}) is None, "no notice when no RA check runs or every address has a position")


def _zero_hits(h):
    c = h.check
    inside = _in("30", ESN="20")
    outside = _in(None, ESN="")
    c(ra.require_hits("RA-08", [inside, outside], "esn.geojson") == 1, "require_hits counts the points inside the layer")
    c(ra.require_hits("RA-08", [_in("", ESN="")], "esn.geojson") == 1, "a point inside a null-keyed polygon is a hit")
    c(ra.require_hits("RA-08", [_in(0, ESN="")], "esn.geojson") == 1, "a polygon keyed 0 is a hit")
    for label, rows in (("no point inside", [outside]), ("no address row", []), ("no position", [A()])):
        h.raises(lambda r=rows: ra.require_hits("RA-08", r, "esn.geojson"), "require_hits refuses a layer with %s  <-- pinned defect" % label)
    c(geometry.require_street_overlap([(5.0, 5.0)], [geometry.Polyline([[(0.0, 0.0), (10.0, 0.0)]])], "s") == 1
      and geometry.require_street_overlap([], [geometry.Polyline([[(0.0, 0.0), (10.0, 0.0)]])], "s") == 0,
      "require_street_overlap counts a point near the street and has nothing to refuse when there is no point")
    h.raises(lambda: geometry.require_street_overlap([None, None], [geometry.Polyline([[(0.0, 0.0), (10.0, 0.0)]])], "s"),
             "require_street_overlap refuses addresses that all lack a position  <-- pinned defect")
    h.raises(lambda: geometry.require_street_overlap([(9000.0, 0.0)], [geometry.Polyline([[(0.0, 0.0), (10.0, 0.0)]])], "s"),
                 "require_street_overlap refuses a point more than a mile from the street extent  <-- pinned defect")
    c(geometry.require_street_overlap([(5280.0, 5280.0)], [geometry.Polyline([[(0.0, 0.0), (10.0, 0.0)]])], "s") == 1, "a point exactly a mile from the street extent counts as a hit")


def _imports_report(src):
    """True when the source imports the report module in any form."""
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Import) and any(a.name.split(".")[-1] == "report" for a in node.names):
            return True
        if isinstance(node, ast.ImportFrom) and ((node.module or "").split(".")[-1] == "report"
                                                 or any(a.name == "report" for a in node.names)):
            return True
    return False


def _guard(c):
    # ---- cell(): every text column, every starting character
    for column in TEXT_COLUMNS:
        for start, name in STARTS:
            value = start + "payload"
            rows = _parse(report.to_csv_text([dict(BASE_ROW, **{column: value})]))
            got = rows[1][report.CSV_COLUMNS.index(column)]
            c(got == "'" + value and got[1:] == value and len(rows) == 2,
              "to_csv_text prefixes one apostrophe to the %s column when it starts with %s  <-- pinned defect" % (column, name))
    clean = _parse(report.to_csv_text([BASE_ROW]))[1]
    c(clean == ["ADDR-05", "name", "address_attr", "ERROR", "address", "7", "ADR7@" + AG, "text", "-30.0000000", "29.0000000"],
      "to_csv_text leaves clean text alone and keeps the row, x and y columns numeric  <-- pinned defect")
    odd = _parse(report.to_csv_text([dict(BASE_ROW, description="a=b, +c", nguid="'quoted", layer="")]))[1]
    c(odd[7] == "a=b, +c" and odd[6] == "'quoted" and odd[4] == "", "a leading character that is not a formula start, an inner sign and an empty cell are left alone")
    inner = _parse(report.to_csv_text([dict(BASE_ROW, description="a" + chr(13) + "b"), BASE_ROW]))
    c(len(inner) == 3 and inner[1][7] == "a" + chr(13) + "b" and inner[2][5] == "7", "a CR inside a cell keeps its row whole on every Python version, because the row is written fully quoted  <-- pinned defect")
    c(report.cell(5) == "5" and report.cell("") == "" and report.cell("-") == "'-", "cell accepts a number and guards a lone sign")
    both = report.to_csv_text([dict(BASE_ROW, nguid="=1+1", description=chr(9) + "t")]).splitlines()
    c(len(both) == 2 and "'=1+1" in both[1] and "'" + chr(9) + "t" in both[1], "a guarded row stays one line of CSV")
    c(report.cell(report.cell("=x")) == "'=x" and report.cell("'=x") == "'=x", "a cell that already starts with an apostrophe is not prefixed again")

    # ---- this package never reads its own findings file back, so there is no prefix to strip
    here = os.path.dirname(os.path.abspath(__file__))
    for name in ("reader.py", "msag.py", "crosswalks.py", "settings.py"):
        src = _read(os.path.join(here, name))
        c("CSV_COLUMNS" not in src and "to_csv_text" not in src and not _imports_report(src),
          "%s does not read the findings file, so a read-back strip is not needed" % name)
    for form in ("import report", "from . import report", "from . import cli, report", "from .report import cell",
                 "from . import (" + chr(10) + "    cli," + chr(10) + "    report," + chr(10) + ")", "import ng911check.report", "from ng911check import report as rep"):
        c(_imports_report(form + chr(10)), "the reader guard sees the import form %r  <-- pinned defect" % form)
    c(not _imports_report("from . import reporting, common" + chr(10) + "x = 'import report'  # .report" + chr(10)), "the reader guard ignores a word that only looks like the report module")


def _cli(c, tmp):
    ini = tmp.write("agency.ini", INI + "[areas]\nRA-08 = esn.geojson|ESN\n")
    addr_blank = _addresses(tmp, "a_blank.geojson", ESN="")
    addr_100 = _addresses(tmp, "a_100.geojson", ESN="100")

    # ---- a null key through the command line
    _areas(tmp, "esn.geojson", None)
    code, out, err = call(["--addresses", addr_100, "--settings", ini, "--out", tmp.path("n.csv"), "--apply"])
    hit = [r for r in _parse(_read(tmp.path("n.csv"))) if r[0] == "RA-08"]
    c(code == 1 and err == "" and len(hit) == 1 and hit[0][1].endswith(ra.NULL_KEY_SUFFIX) and "whose key is null or blank" in hit[0][7],
      "a point inside a null-keyed polygon exits 1 with a finding of its own  <-- pinned defect")
    c("Response-area roll-up" in out and "inside (null key)" in out, "the roll-up names the null key")
    code, out, err = call(["--addresses", addr_blank, "--settings", ini])
    c(code == 1 and "RA-08" in out, "a null key with a blank stored ESN is still not a clean run  <-- pinned defect")
    _areas(tmp, "esn.geojson", "   ")
    code, out, err = call(["--addresses", addr_100, "--settings", ini])
    c(code == 1 and "whose key is null or blank" in out, "a polygon key of spaces is a null key")

    # ---- a reference layer with no hit is refused, and nothing is written
    _areas(tmp, "esn.geojson", 100, FAR)
    target = tmp.path("z.csv")
    before = sorted(os.listdir(tmp.root))
    code, out, err = call(["--addresses", addr_blank, "--settings", ini, "--out", target, "--apply"])
    c(code == 2 and "RA-08: none of the 1 address point(s) with a position falls inside a polygon of " in err and "esn.geojson" in err and out == ""
      and sorted(os.listdir(tmp.root)) == before, "a polygon layer that no address falls inside exits 2, prints no report and writes nothing  <-- pinned defect")
    code, out, err = call(["--addresses", addr_100, "--settings", ini])
    c(code == 2 and "falls inside a polygon" in err, "the same refusal holds when the stored ESN is filled, where it would have been one finding per point")
    tmp.write("esn.geojson", collection())
    code, out, err = call(["--addresses", addr_blank, "--settings", ini])
    c(code == 2 and "none of the 1 address point(s)" in err, "an empty polygon layer is refused")
    nopos = csv_file(tmp, "nopos.csv", ("Add_Number", "STREET_NA", "ESN"), [{"Add_Number": 1, "STREET_NA": "ELM", "ESN": ""}])
    _areas(tmp, "esn.geojson", 100)
    code, out, err = call(["--addresses", nopos, "--settings", ini])
    c(code == 2 and "none of the 0 address point(s) with a position" in err, "addresses with no position cannot be placed in a layer, so the run is refused")
    code, out, err = call(["--addresses", addr_100, "--settings", ini])
    c(code == 0 and err == "", "a polygon layer with a hit and a matching ESN is a clean run")

    # ---- an address with a null geometry is left out of the area check, with a notice
    _areas(tmp, "esn.geojson", 100)
    placed = feature("Point", [-30.4995, 29.10015], A(Add_Number=101, HOUSE_NU="101", ESN="100"))
    lost = {"type": "Feature", "properties": props(A(Add_Number=103, HOUSE_NU="103", ESN="7")), "geometry": None}
    half = tmp.write("half.geojson", collection(placed, lost))
    code, out, err = call(["--addresses", half, "--settings", ini])
    c(code == 0 and err == "" and "not inside any" not in out and "RA-08 left out 1 of 2 addresses that have no position" in out,
      "an address with a null geometry is no finding, and the run says it left that row out  <-- pinned defect")

    # ---- the formula guard, through --out
    rows = [A(Site_NGUID=start + "id@" + AG, ESN="ABC", X=1000.0 + 10 * i, Y=1000.0) for i, (start, _n) in enumerate(STARTS)]
    plain = tmp.write("plain.ini", INI)
    columns = reader.ADDRESS_COLUMNS + ("X", "Y")
    buf = io.StringIO()
    # fully quoted, because the csv module of Python 3.9 and 3.10 leaves a bare CR unquoted
    feed = csv.writer(buf, lineterminator="\n", quoting=csv.QUOTE_ALL)
    feed.writerow(columns)
    for row in rows:
        feed.writerow([row.get(col, "") for col in columns])
    addr = tmp.write("inj.csv", buf.getvalue())
    code, out, err = call(["--addresses", addr, "--settings", plain, "--units", "feet", "--out", tmp.path("inj.out"), "--apply"])
    body = _parse(_read(tmp.path("inj.out")))
    got = set(r[6] for r in body[1:] if r[0] == "ADDR-05")
    c(code == 1 and err == "" and got == set("'" + s + "id@" + AG for s, _n in STARTS),
      "a Site_NGUID that starts with = + - @ tab or CR reaches the findings file with one apostrophe in front  <-- pinned defect")
    c(all(not r[5].startswith("'") and not r[8].startswith("'") and not r[9].startswith("'") for r in body[1:]), "row, x and y stay unprefixed in the findings file")
    code, out, err = call(["--addresses", addr, "--settings", plain, "--units", "feet", "--out", tmp.path("inj.json"), "--apply", "--format", "json"])
    c(code == 1 and "\"=id@" in _read(tmp.path("inj.json")), "the json findings file keeps the raw value, because json is not opened as a spreadsheet")

    # ---- a street layer that no address is near is refused, and so is an MSAG with nothing to compare
    near = tmp.write("near.geojson", collection(feature("LineString", LINE, S(SEGMENT_ID=1, RCL_NGUID="RCL1@" + AG))))
    far = tmp.write("far.geojson", collection(feature("LineString", [[-20.5, 29.1], [-20.499, 29.1]], S(SEGMENT_ID=1, RCL_NGUID="RCL1@" + AG))))
    plain = tmp.write("plain.ini", INI)
    code, out, err = call(["--addresses", addr_100, "--streets", near, "--settings", plain])
    c(err == "" and code in (0, 1), "a street layer next to the address points runs")
    before = sorted(os.listdir(tmp.root))
    code, out, err = call(["--addresses", addr_100, "--streets", far, "--settings", plain, "--out", tmp.path("s.csv"), "--apply"])
    c(code == 2 and "none of the 1 address point(s) with a position lies within the extent of the street geometry in " in err and "far.geojson" in err
      and out == "" and sorted(os.listdir(tmp.root)) == before,
      "a street layer that no address is near exits 2, prints no report and writes nothing  <-- pinned defect")
    exc_all = tmp.write("exc_all.csv", "kind,community,prefix,street,type,suffix,esn\nname,,,ELM,ST,,\n")
    msag_one = tmp.write("msag_one.csv", HEADER + ",ELM,ST,,100,199,TESTVILLE,B,100\n")
    msag_none = tmp.write("msag_none.csv", HEADER)
    for label, extra in (("a header-only file", ["--msag", msag_none]), ("every record excepted", ["--msag", msag_one, "--msag-exceptions", exc_all])):
        before = sorted(os.listdir(tmp.root))
        code, out, err = call(["--addresses", addr_100, "--streets", near, "--settings", plain, "--out", tmp.path("m.csv"), "--apply"] + extra)
        c(code == 2 and "no MSAG record is eligible (" in err and "would read as clean" in err and out == "" and sorted(os.listdir(tmp.root)) == before,
          "an MSAG with %s and so no eligible record exits 2, prints no report and writes nothing  <-- pinned defect" % label)
    code, out, err = call(["--addresses", addr_100, "--streets", near, "--settings", plain, "--msag", msag_one])
    c(err == "" and "MSAG match rate 100.00% (matched 1/1 eligible)" in out, "an MSAG with an eligible record still runs")
