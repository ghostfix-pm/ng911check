"""Self-test: the command line, end to end, on synthetic files in a temporary folder."""
import csv
import io
import json
import os

from . import __version__, catalog, cli, reader
from .selftest import Quiet, Tmp
from .st_fix import A, AG, S

INI = "[agency]\nexpected_agid = %s\n" % AG
HEADER = "PREFIX,STREET NAME,TYPE,SUFFIX,LOW,HIGH,COMMUNITY,SIDE,ESN\n"
LINE = [[-81.5, 29.1], [-81.499, 29.1]]


def csv_file(tmp, name, columns, rows):
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(columns)
    for row in rows:
        w.writerow([row.get(col, "") for col in columns])
    return tmp.write(name, buf.getvalue())


def text_of(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def props(row):
    return dict((k, v) for k, v in row.items() if not k.startswith("_"))


def feature(geom_type, coords, row):
    return {"type": "Feature", "properties": props(row), "geometry": {"type": geom_type, "coordinates": coords}}


def collection(*features):
    return json.dumps({"type": "FeatureCollection", "features": list(features)})


def call(args):
    """Run cli.main. Returns (exit code, stdout, stderr). A SystemExit becomes its code."""
    q = Quiet()
    with q:
        try:
            code = cli.main(args)
        except SystemExit as exc:
            code = exc.code
    return code, q.out.getvalue(), q.err.getvalue()


def listing(tmp):
    return sorted(os.listdir(tmp.root))


def section(h):
    c = h.check
    c(__version__ == "0.2.0", "the package version is 0.2.0")

    # ---- the quiet commands
    code, out, err = call(["--version"])
    c(code == 0 and out == "ng911check 0.2.0\n", "--version prints the version and exits 0")
    code, out, err = call(["--catalog"])
    c(code == 0 and out.startswith("| Check |") and "XLAYER-16" in out and "ADDR-01" in out, "--catalog prints the check table and exits 0")

    with Tmp() as tmp:
        good = tmp.write("good.md", "intro\n" + catalog.START + "\n" + catalog.render_markdown() + "\n" + catalog.END + "\nend\n")
        stale = tmp.write("stale.md", catalog.START + "\n| Check | Target |\n| OLD-1 | x |\n" + catalog.END + "\n")
        none = tmp.write("none.md", "no markers here\n")
        code, out, err = call(["--catalog-check", good])
        c(code == 0 and "matches the registry" in out, "--catalog-check exits 0 when the README block equals the registry")
        code, out, err = call(["--catalog-check", stale])
        c(code == 1 and "out of date" in out, "--catalog-check exits 1 when the block is stale")
        code, out, err = call(["--catalog-check", none])
        c(code == 1 and "has no" in out, "--catalog-check exits 1 when the markers are missing")
        code, out, err = call(["--catalog-check", tmp.path("absent.md")])
        c(code == 2 and "ng911check:" in err, "--catalog-check exits 2 when the file cannot be read")

        # ---- usage errors
        ini = tmp.write("agency.ini", INI)
        rows = [A(X=1000.0, Y=1000.0), A(ESN="ABC", X=1100.0, Y=1000.0)]
        addr = csv_file(tmp, "addresses.csv", reader.ADDRESS_COLUMNS + ("X", "Y"), rows)
        strt = csv_file(tmp, "streets.csv", reader.STREET_COLUMNS, [S()])
        base = ["--addresses", addr, "--streets", strt, "--settings", ini, "--units", "feet"]
        before = listing(tmp)
        for flag in ("--ap", "--app", "--appl"):
            code, out, err = call(base + ["--out", tmp.path("o.csv"), flag])
            c(code == 64 and "unrecognized arguments" in err and listing(tmp) == before,
              "a prefix %s of --apply is REFUSED by the parser and writes nothing  <-- pinned defect" % flag)
        code, out, err = call(base + ["--ou", tmp.path("o.csv"), "--apply"])
        c(code == 64 and listing(tmp) == before, "a prefix --ou of --out is REFUSED by the parser  <-- pinned defect")
        code, out, err = call(["--cata"])
        c(code == 64, "a prefix --cata of --catalog is REFUSED because it is ambiguous with --catalog-check")
        code, out, err = call(base + ["--apply"])
        c(code == 64 and "--apply needs --out FILE" in err, "--apply without --out is a usage error")
        code, out, err = call(base + ["--out", os.path.join(tmp.root, ".", "addresses.csv"), "--apply"])
        c(code == 64 and "would overwrite an input file" in err and text_of(addr).startswith("Add_Number"),
          "--out onto an input file is refused and the input is untouched  <-- pinned defect")
        code, out, err = call(["--settings", ini])
        c(code == 2 and "give --addresses, --streets or both" in err, "a run with no layer exits 2")
        code, out, err = call(["--addresses", addr, "--units", "feet"])
        c(code == 2 and "no agency is named" in err, "a run with no agency exits 2 and does not fall back to a default agency  <-- pinned defect")
        code, out, err = call(["--addresses", tmp.path("nope.csv"), "--settings", ini])
        c(code == 2 and "ng911check:" in err, "a missing input file exits 2")
        code, out, err = call(base + ["--format", "xml"])
        c(code == 64 and "invalid choice" in err, "--format takes csv or json only")

        # ---- a run with findings
        code, out, err = call(base)
        c(code == 1 and "ng911check report" in out and "Findings:" in out and "ERROR" in out and "ADDR-05" in out and err == "",
          "a run with an ERROR exits 1 and prints the report")
        c("Override effects" not in out and "expected_agid" in out and "addresses: " in out and "units: feet" in out, "the report lists the inputs, the units and the settings, and no override effects when none is set")
        code, out, err = call(base + ["--out", tmp.path("o.csv")])
        c(code == 1 and "Would write the findings to" in out and "o.csv" in out and listing(tmp) == before,
          "--out without --apply says what it would write and writes nothing  <-- pinned defect")
        code, out, err = call(base + ["--out", tmp.path("o.csv"), "--apply"])
        body = text_of(tmp.path("o.csv"))
        c(code == 1 and "Wrote " in out and body.splitlines()[0] == ",".join(("check_id", "check_name", "family", "severity", "layer", "row", "nguid", "description", "x", "y"))
          and "ADDR-05" in body and listing(tmp) == sorted(before + ["o.csv"]), "--out with --apply writes the findings as CSV and leaves no temporary file")
        code, out, err = call(base + ["--out", tmp.path("o.json"), "--apply", "--format", "json"])
        doc = json.loads(text_of(tmp.path("o.json")))
        c(code == 1 and doc["summary"]["ERROR"] >= 1 and any(f["check_id"] == "ADDR-05" for f in doc["findings"]), "--format json writes a document with the summary and the findings")
        code, out, err = call(base + ["--show", "1"])
        c("... " in out and "more. Write them all with --out FILE --apply." in out, "--show limits the printed findings and says how to get the rest")
        clean = csv_file(tmp, "clean.csv", reader.ADDRESS_COLUMNS, [A()])
        code, out, err = call(["--addresses", clean, "--streets", strt, "--settings", ini])
        c(code == 0 and "Findings: 0 ERROR" in out, "a run with no ERROR exits 0")
        code, out, err = call(["--addresses", clean, "--settings", ini])
        c(code == 0 and "XLAYER-04 was skipped: it needs a street file (--streets)" in out and "no centerline named" not in out,
          "a clean address file given alone exits 0 and says XLAYER-04 was skipped  <-- pinned defect")
        code, out, err = call(["--streets", strt, "--settings", ini])
        c("XLAYER-14 was skipped: it needs an address file (--addresses)" in out and "no active address covers" not in out,
          "a street file given alone skips XLAYER-14 instead of calling every segment uncovered  <-- pinned defect")
        header_only = tmp.write("header_only.csv", ",".join(reader.ADDRESS_COLUMNS) + "\n")
        code, out, err = call(["--addresses", header_only, "--settings", ini])
        c(code == 2 and "the addresses file has no rows, so nothing was checked" in err and out == "",
          "a header-only CSV exits 2 instead of passing as clean  <-- pinned defect")
        empty_gj = tmp.write("empty.geojson", collection())
        code, out, err = call(["--streets", empty_gj, "--settings", ini])
        c(code == 2 and "the streets file has no rows" in err, "an empty FeatureCollection exits 2 instead of passing as clean  <-- pinned defect")
        num_gj = tmp.write("num.geojson", collection(feature("Point", [-81.4995, 29.10015], dict(A(), COUNTY=12083, STATE=12, ESN=100, Site_NGUID=7))))
        code, out, err = call(["--addresses", num_gj, "--settings", ini])
        c(code == 1 and err == "" and "Findings:" in out, "a GeoJSON number in a text column is read as text and the run gives a verdict, not exit 70  <-- pinned defect")
        list_gj = tmp.write("list.geojson", collection(feature("Point", [-81.4995, 29.10015], dict(A(), COUNTY=["a"]))))
        code, out, err = call(["--addresses", list_gj, "--settings", ini])
        c(code == 2 and "property COUNTY must be a string, a number or null" in err, "a GeoJSON list in a property exits 2, not 70  <-- pinned defect")
        bool_gj = tmp.write("bool.geojson", collection(feature("Point", [-81.4995, 29.10015], dict(A(), STATE=True))))
        code, out, err = call(["--addresses", bool_gj, "--settings", ini])
        c(code == 2 and "property STATE must be a string, a number or null" in err, "a GeoJSON boolean in a property exits 2, not 70")
        off_ini = tmp.write("off.ini", INI + "[checks]\nADDR-05 = off\nXLAYER-01 = off\nADDR-07 = off\n")
        off_addr = csv_file(tmp, "off_addr.csv", reader.ADDRESS_COLUMNS, [A(ESN="ABC")])
        code, out, err = call(["--addresses", off_addr, "--streets", strt, "--settings", ini])
        c(code == 1 and "ESN 'ABC' not a valid 1-5 digit ESN" in out, "the same address file with the ESN checks left on exits 1")
        code, out, err = call(["--addresses", off_addr, "--streets", strt, "--settings", off_ini])
        c(code == 0 and "ADDR-05" in out and "(can emit ERROR: its findings are NOT in this report)" in out and "ESN 'ABC'" not in out,
          "a [checks] off line removes the ERRORs and the report says the check can emit ERROR  <-- pinned defect")
        c(out.count("can emit ERROR") == 2, "the off note is written only for a check that can emit ERROR")

        # ---- the rule, through the command line
        rule_ini = tmp.write("rule.ini", INI + "[severity]\nADDR-05 = INFO\nADDR-01 = INFO\n")
        code, out, err = call(["--addresses", addr, "--streets", strt, "--settings", rule_ini, "--units", "feet"])
        c(code == 1 and "1 held at ERROR" in out and "Override effects on this run:" in out and "(ERROR findings stay ERROR; the others become INFO)" in out,
          "ADDR-05 = INFO leaves the ESN ERROR in place, exits 1 and prints what the line did  <-- pinned defect")
        code, out, err = call(base + ["--agency", " other.example.net "])
        c("!= expected 'other.example.net'" in out, "--agency replaces the agency of the settings file and is stripped")

        # ---- missing columns and renames
        small = csv_file(tmp, "small.csv", ("Num", "STREET_NA", "TYPE"), [{"Num": 101, "STREET_NA": "ELM", "TYPE": "ST"}])
        code, out, err = call(["--addresses", small, "--settings", ini, "--rename", "addresses:Num=Add_Number"])
        c("The addresses file has no column(s) named:" in out and "ZIP_CODE" in out and "Add_Number" not in out.split("no column(s) named:")[1].split("\n")[0],
          "a file that lacks columns gets a notice and --rename supplies a column")
        code, out, err = call(["--addresses", small, "--settings", ini, "--rename", "addresses:Num"])
        c(code == 2 and "--rename" in err, "a --rename that is not LAYER:ACTUAL=CANONICAL exits 2")

        # ---- a domain file adds modifier domains
        dom = tmp.write("dom.csv", "domain,full,abbrev\npremod,ALT,\n")
        mods = csv_file(tmp, "mods.csv", reader.ADDRESS_COLUMNS, [A(St_PreMod="BAD")])
        code, out, err = call(["--addresses", mods, "--settings", ini, "--domains", dom])
        c("XLAYER-15" in out, "--domains turns on the modifier check and flags a value outside it")
        code, out, err = call(["--addresses", mods, "--settings", ini])
        c("XLAYER-15 was skipped: it needs modifier domains" in out, "without --domains the modifier check is skipped and says so")

        # ---- an unexpected crash is not a finding
        real = cli.run

        def boom(args):
            raise RuntimeError("boom")
        cli.run = boom
        try:
            code, out, err = call(base)
        finally:
            cli.run = real
        c(code == 70 and "RuntimeError: boom" in err, "an unexpected exception exits 70, never the 1 that means a finding  <-- pinned defect")

        # ---- GeoJSON, areas, MSAG and the rollups
        _geojson(h, tmp, ini)


def _geojson(h, tmp, ini):
    c = h.check
    street = S(SEGMENT_ID=1, RCL_NGUID="RCL1@" + AG)
    odd_north = A(Add_Number=101, HOUSE_NU="101", ADDRESS="101 ELM ST", ESN="100")
    odd_south = A(Add_Number=103, HOUSE_NU="103", ADDRESS="103 ELM ST", ESN="200")
    blank_city = A(Add_Number=105, HOUSE_NU="105", ADDRESS="105 ELM ST", CITY="", ESN="100")
    outside = A(Add_Number=107, HOUSE_NU="107", ADDRESS="107 ELM ST", ESN="100")
    addr = tmp.write("addr.geojson", collection(
        feature("Point", [-81.4995, 29.10015], odd_north), feature("Point", [-81.4995, 29.09985], odd_south),
        feature("Point", [-81.4994, 29.10015], blank_city), feature("Point", [-81.0, 29.5], outside)))
    strt = tmp.write("street.geojson", collection(feature("LineString", LINE, street)))
    box = [[-81.501, 29.099], [-81.498, 29.099], [-81.498, 29.101], [-81.501, 29.101], [-81.501, 29.099]]
    tmp.write("esn.geojson", collection({"type": "Feature", "properties": {"ESN": 100}, "geometry": {"type": "Polygon", "coordinates": [box]}}))
    tmp.write("city.geojson", collection({"type": "Feature", "properties": {"NAME": "TESTVILLE"}, "geometry": {"type": "Polygon", "coordinates": [box]}}))
    ini2 = tmp.write("areas.ini", INI + "[areas]\nRA-08 = esn.geojson|ESN\nRA-09 = city.geojson|NAME\n[checks]\nXLAYER-05 = on\nXLAYER-11 = on\n")
    msag_csv = tmp.write("msag.csv", HEADER + ",ELM,ST,,100,199,TESTVILLE,B,100\n,OAK,AVE,,10,20,TESTVILLE,B,100\n")
    exc = tmp.write("exc.csv", "kind,community,prefix,street,type,suffix,esn\nname,,,NOWHERE,ST,,\n")
    names = tmp.write("names.csv", "community,street_name\nTESTVILLE,PINE ST\n")
    cfg = tmp.write("msag.json", json.dumps({"source_path": "msag.csv", "min_match_rate": 0.5}))
    args = ["--addresses", addr, "--streets", strt, "--settings", ini2, "--msag", msag_csv, "--msag-exceptions", exc, "--street-names", names, "--optional"]
    code, out, err = call(args)
    c(code == 1 and err == "", "a GeoJSON run with areas, an MSAG, exceptions and a name list completes")
    c("MSAG reconciliation:" in out and "MSAG match rate" in out and "MSAG exact-tuple rate" in out and "MSAG source is " in out, "the report prints the match rate, the exact-tuple rate and the source age together")
    c("MSAG roll-up by street (top 1 of 1):" in out and "OAK AVE" in out and "1 not in GIS" in out, "the report prints the MSAG roll-up by street")
    c("Response-area roll-up (top " in out and "RA-08" in out and "inside 100" in out and "stored 200" in out, "the report prints the response-area roll-up")
    code, out, err = call([a for a in args if a != "--optional"])
    lines = [l.split()[:2] for l in out.splitlines()]
    c(["RA-08", "ERROR"] in lines and ["RA-09", "ERROR"] in lines, "an [areas] line switches its check on without --optional  <-- pinned defect")
    c("XLAYER-13" in out and "geometric side Right != parity side Left" in out and "XLAYER-05" in out, "the geometry checks run on GeoJSON lines and flag the point on the wrong side")
    c("RA-09" in out and "RA-09-BLANK" not in out and "INFO" in out, "the blank-CITY class is reported inside RA-09 at INFO")
    msag_ok = tmp.write("msag_ok.csv", HEADER + ",ELM,ST,,100,199,TESTVILLE,B,100\n")
    code, out, err = call(["--addresses", addr, "--streets", strt, "--settings", ini2, "--msag", msag_ok])
    c("MSAG match rate 100.00%" in out and "MSAG exact-tuple rate 100.00%" in out and "MSAG roll-up" not in out,
      "a run whose MSAG agrees with the GIS prints the rates and no roll-up")
    code, out, err = call(["--addresses", addr, "--streets", strt, "--settings", ini2, "--msag-config", cfg])
    c(code == 1 and "MSAG match rate" in out, "--msag-config alone names the MSAG file and the floor")
    code, out, err = call(["--addresses", addr, "--streets", strt, "--settings", ini2, "--msag-config", cfg, "--msag", msag_csv])
    c(code == 1 and "MSAG match rate" in out, "--msag overrides the file named in --msag-config")
    code, out, err = call(["--addresses", addr, "--streets", strt, "--settings", ini2, "--msag-exceptions", exc])
    c(code == 2 and "--msag-exceptions and --street-names need --msag or --msag-config" in err, "--msag-exceptions without an MSAG exits 2")
    code, out, err = call(["--addresses", addr, "--streets", strt, "--settings", ini2, "--street-names", names])
    c(code == 2 and "need --msag" in err, "--street-names without an MSAG exits 2")
    code, out, err = call(["--addresses", addr, "--streets", strt, "--settings", ini2, "--msag", tmp.path("nope.csv")])
    c(code == 2, "an MSAG file that cannot be read exits 2")

    code, out, err = call(["--streets", strt, "--settings", ini2])
    c(code == 2 and "needs an --addresses file" in err, "an [areas] line without an addresses file exits 2")
    nofield = csv_file(tmp, "noesn.csv", ("Add_Number", "STREET_NA", "CITY", "X", "Y"), [{"Add_Number": 1, "STREET_NA": "ELM", "CITY": "X", "X": -81.4995, "Y": 29.10015}])
    code, out, err = call(["--addresses", nofield, "--settings", ini2])
    c(code == 2 and "compares ESN but the addresses file has no such column" in err, "an area check whose address column is missing exits 2 instead of flagging every point")
    code, out, err = call(["--addresses", addr, "--streets", strt, "--settings", ini2, "--units", "feet"])
    c(code == 1 and err == "", "a GeoJSON run in feet reads the same coordinates as feet")
    code, out, err = call(["--addresses", addr, "--settings", ini2, "--units", "feet"])
    c(code == 1, "a GeoJSON address layer needs no street layer")
    far = tmp.write("far.geojson", collection(feature("Point", [500000.0, 200000.0], A())))
    code, out, err = call(["--addresses", far, "--settings", ini])
    c(code == 2 and "not degrees" in err, "coordinates that are not degrees are refused unless --units says otherwise  <-- pinned defect")
    code, out, err = call(["--addresses", far, "--settings", ini, "--units", "feet"])
    c(code == 0 and "ng911check" in out, "the same file runs with --units feet")
    badesn = tmp.write("badesn.geojson", collection(feature("Point", [-81.4995, 29.10015], A(Add_Number=101, HOUSE_NU="101", ESN="ABC"))))
    code, out, err = call(["--addresses", badesn, "--settings", ini, "--units", "meters"])
    c(code == 1 and err == "", "--units meters runs")
    code, out, err = call(["--addresses", badesn, "--settings", ini, "--units", "degrees", "--out", tmp.path("g.csv"), "--apply"])
    row = [r for r in csv.reader(io.StringIO(text_of(tmp.path("g.csv"))))][1]
    c(code == 1 and len(row[-2].split(".")[1]) == 7 and row[-2].startswith("-81."), "findings on a degrees layer are written back in degrees with seven decimals")

    # ---- --out may not overwrite any file the run read, including files only the settings name
    code, out, err = call(["--addresses", addr, "--streets", strt, "--settings", ini2, "--out", tmp.path("esn.geojson"), "--apply"])
    c(code == 64 and "would overwrite an input file" in err and json.loads(text_of(tmp.path("esn.geojson")))["type"] == "FeatureCollection",
      "--out onto a polygon file named in the settings is refused and the file is untouched  <-- pinned defect")
    code, out, err = call(["--addresses", addr, "--streets", strt, "--settings", ini2, "--msag-config", cfg, "--out", tmp.path("msag.csv"), "--apply"])
    c(code == 64 and text_of(tmp.path("msag.csv")).startswith("PREFIX"),
      "--out onto the MSAG file named in the MSAG config is refused and the file is untouched  <-- pinned defect")
    cfg_exc = tmp.write("msag_exc.json", json.dumps({"source_path": "msag.csv", "exceptions_path": "exc.csv"}))
    code, out, err = call(["--addresses", addr, "--streets", strt, "--settings", ini2, "--msag-config", cfg_exc, "--out", tmp.path("exc.csv"), "--apply"])
    c(code == 64 and text_of(tmp.path("exc.csv")).startswith("kind"),
      "--out onto the exceptions file named only in the MSAG config is refused and the file is untouched")

    # ---- named coordinate columns and a pinned MSAG hash, through the command line
    lonlat = csv_file(tmp, "lonlat.csv", reader.ADDRESS_COLUMNS + ("Lon", "Lat"), [dict(A(Add_Number=101, HOUSE_NU="101", ESN="ABC"), Lon=-81.4995, Lat=29.10015)])
    code, out, err = call(["--addresses", lonlat, "--settings", ini, "--x-field", "Lon", "--y-field", "Lat", "--out", tmp.path("ll.csv"), "--apply"])
    ll_row = [r for r in csv.reader(io.StringIO(text_of(tmp.path("ll.csv"))))][1]
    c(code == 1 and err == "" and ll_row[-2] == "-81.4995000" and ll_row[-1] == "29.1001500", "--x-field and --y-field name the coordinate columns of a CSV layer")
    bad = tmp.write("pin.json", json.dumps({"source_path": "msag.csv", "source_hash": "0" * 64}))
    code, out, err = call(["--addresses", addr, "--settings", ini2, "--msag-config", bad])
    c(code == 2 and "changed: its SHA-256 is" in err, "a pinned MSAG hash that no longer matches exits 2 and names both hashes  <-- pinned defect")
