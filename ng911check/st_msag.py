"""Self-test: the MSAG reader, the reconcile, the exact-tuple rate, the roll-up and XLAYER-16."""
import os

from . import engine, msag
from . import cross_layer_checks as xl
from .selftest import Tmp
from .st_fix import A, S, ctx_for, found

HEADER = "PREFIX,STREET NAME,TYPE,SUFFIX,LOW,HIGH,COMMUNITY,SIDE,ESN\n"
ELM_B = ",ELM,ST,,100,199,TESTVILLE,B,100\n"


def g(lo, hi, par, esn="100", comm="TESTVILLE", name="ELM ST", **extra):
    """A rolled-up record, the shape of both an MSAG row and a GIS side."""
    rec = {"community": comm, "name_key": name, "low": lo, "high": hi, "parity": par, "esn": esn}
    rec.update(extra)
    return rec


def _xl16(msag_text, streets, addresses=(), tmp=None, **cfg_kw):
    """Run XLAYER-16 through the engine over a temporary MSAG file."""
    path = tmp.write("msag.csv", msag_text)
    cfg = msag.MsagConfig(source_path=path, **cfg_kw)
    ctx = ctx_for(list(addresses), streets)
    engine.build_msag_context(ctx, cfg)
    return engine.run_report(list(addresses), streets, ctx, ids=["XLAYER-16"]), ctx


def section(h):
    c, raises = h.check, h.raises

    # ---- value helpers
    c(msag.pad_esn("6") == "006" and msag.pad_esn(13.0) == "013" and msag.pad_esn(" ab ") == "AB" and msag.pad_esn(None) == "" and msag.pad_esn("  ") == "",
      "pad_esn zero-pads digits, reads 13.0 as 13, upper-cases text and keeps blank blank")
    c(msag.pad_esn("6", 4) == "0006", "pad_esn takes the width as a parameter")
    c([msag.norm_parity(v) for v in ("o", "ODD", "e", "Even", "b", "BOTH", "x", None)] == ["O", "O", "E", "E", "B", "B", "", ""],
      "norm_parity maps odd, even and both words and refuses anything else")
    c([msag._to_int(v) for v in (None, 5, " 7 ", "", "x", "inf", "12.0")] == [None, 5, 7, None, None, None, 12],
      "to_int reads numbers, blanks, text and infinity without raising")
    c(msag.name_key("N", "ELM", "ST", "") == "N ELM ST", "name_key joins prefix, name, type and suffix")

    # ---- header detection and schema
    rows = [["banner"], ["PREFIX", "STREET NAME", "TYPE", "SUFFIX", "LOW", "HIGH", "COMMUNITY", "SIDE", "ESN"], ["", "ELM"]]
    c(msag.detect_header_row(rows) == 2 and msag.detect_header_row([]) == 1, "detect_header_row finds the header under a banner and defaults to row 1")
    c(msag.detect_header_row([["a"], ["b"]]) == 1, "detect_header_row resolves a tie to the earliest row")
    ok, errs = msag.validate_msag_schema(["STREET NAME", None, "LOW"], msag.DEFAULT_FIELD_MAP)
    c(not ok and any("'high'" in e for e in errs) and any("not found" in e for e in errs), "validate_msag_schema names each missing required column")
    ok, errs = msag.validate_msag_schema(msag.HEADER_TOKENS, dict(msag.DEFAULT_FIELD_MAP, esn=""))
    c(not ok and any("not mapped" in e for e in errs), "validate_msag_schema names a required field that is not mapped")
    ok, errs = msag.validate_msag_schema(["STREET NAME", "LOW", "HIGH", "COMMUNITY", "SIDE", "ESN"], msag.DEFAULT_FIELD_MAP)
    c(ok and errs == [], "validate_msag_schema accepts the six required columns")

    with Tmp() as tmp:
        # ---- load_msag_csv
        path = tmp.write("m1.csv", "Banner line\n\n" + HEADER + ELM_B + "\n,OAK, AVE ,,10,20,TESTVILLE,odd,6\n,SHORT,,\n")
        recs = msag.load_msag_csv(msag.MsagConfig(source_path=path))
        c(len(recs) == 3 and recs[0]["low"] == 100 and recs[1]["type"] == "AVE" and recs[1]["esn"] == "006" and recs[1]["parity"] == "O",
          "load_msag_csv finds the header under a banner, skips blank rows and normalises the values")
        c(recs[2]["low"] is None and recs[2]["esn"] == "" and recs[2]["community"] == "", "load_msag_csv keeps a short row with empty values")
        recs = msag.load_msag_csv(msag.MsagConfig(source_path=path, header_row=3))
        c(len(recs) == 3, "load_msag_csv honours an explicit header_row")
        raises(lambda: msag.load_msag_csv(msag.MsagConfig(source_path=path, header_row=99)), "load_msag_csv refuses a header_row past the end of the file")
        bad = tmp.write("m2.csv", "STREET NAME,LOW\nELM,1\n")
        raises(lambda: msag.load_msag_csv(msag.MsagConfig(source_path=bad)), "load_msag_csv refuses a file that lacks the required columns")
        empty = tmp.write("m3.csv", "")
        raises(lambda: msag.load_msag_csv(msag.MsagConfig(source_path=empty)), "load_msag_csv refuses an empty file")

        # ---- the hash pin and the age
        pinned = msag.MsagConfig(source_path=path, source_hash=msag.file_hash(path))
        c(len(msag.load_msag_csv(pinned)) == 3, "a source that hashes to the pinned value loads")
        raises(lambda: msag.load_msag_csv(msag.MsagConfig(source_path=path, source_hash="0" * 64)),
               "a source that no longer hashes to the pinned value is refused  <-- pinned defect")
        mtime = os.path.getmtime(path)
        c(msag.source_age_days(path, now=mtime + 10 * 86400 + 5) == 10 and msag.source_age_days(path, now=mtime - 500) == 0,
          "source_age_days counts whole days and never goes below zero")
        c(msag.source_age_days(path) <= 1, "source_age_days reads the clock when no time is given")

        # ---- config files
        cfgpath = tmp.write("cfg.json", '{"source_path": "m1.csv", "field_map": {"esn": "ESN"}, "exceptions_path": "exc.csv", "min_match_rate": 0.9}')
        cfg = msag.load_config(cfgpath)
        c(cfg.source_path == os.path.normpath(os.path.join(tmp.root, "m1.csv")) and cfg.min_match_rate == 0.9 and cfg.field_map["low"] == "LOW",
          "load_config resolves relative paths against the config folder and merges the field map")
        absolute = tmp.write("cfg2.json", '{"source_path": "%s", "names_path": ""}' % path.replace("\\", "/"))
        c(msag.load_config(absolute).source_path == path.replace("\\", "/"), "load_config leaves an absolute path alone")
        raises(lambda: msag.load_config(tmp.write("cfg3.json", '{"source_path": "x", "bogus": 1}')), "load_config refuses an unknown key")
        out = os.path.join(tmp.root, "saved.json")
        msag.save_config(cfg, out)
        c(msag.load_config(out).min_match_rate == 0.9, "save_config writes a file that load_config reads back")

        # ---- exceptions and name lists
        exc_path = tmp.write("exc.csv", "kind,community,prefix,street,type,suffix,esn\nname,,,ALPHA,ST,,\nname,,,BETA,ST,,200\npermanent,testville,,GAMMA,ST,,300\nname,,,,,,\n\n")
        exc = msag.load_exceptions(exc_path)
        c(exc.by_name_any_esn == {"ALPHA ST"} and exc.by_name_esn == {("BETA ST", "200")} and exc.permanent == {("TESTVILLE", "GAMMA ST", "300")},
          "load_exceptions reads name, name-and-ESN and permanent rows and skips a blank name")
        raises(lambda: msag.load_exceptions(tmp.write("exc2.csv", "kind,community,prefix,street,type,suffix,esn\nweird,,,X,,,\n")), "load_exceptions refuses an unknown kind")
        raises(lambda: msag.load_exceptions(tmp.write("exc3.csv", "kind,street\nname,X\n")), "load_exceptions refuses a file without the expected header")
        raises(lambda: msag.load_exceptions(tmp.write("exc4.csv", "")), "load_exceptions refuses an empty file")
        names = msag.load_authoritative_names(tmp.write("names.csv", "community,street_name\ntestville,ELM ST\ntestville,\n"))
        c(names == {("TESTVILLE", "ELM ST")}, "load_authoritative_names reads community and name and skips a blank name")
        auth = msag.authoritative_names_from_msag([g(1, 2, "B", name="N ELM ST", street_name="ELM", type="ST", suffix=""), g(1, 2, "B", name="", street_name="", type="", suffix="")])
        c(("TESTVILLE", "ELM ST") in auth and ("TESTVILLE", "ELM") in auth and len(auth) == 2, "authoritative_names_from_msag emits the full and the bare name without the prefix")

        # ---- is_excepted
        exc = msag.Exceptions(by_name_any_esn={"ALPHA ST"}, by_name_esn={("BETA ST", "200")}, permanent={("TESTVILLE", "GAMMA ST", "300")})
        c(msag.is_excepted(g(1, 9, "B", esn="999"), None) and msag.is_excepted(g(1, 9, "B", esn="999"), exc), "is_excepted drops the ESN 999 convention with or without an exceptions file")
        c(msag.is_excepted(g(0, 0, "B"), None) and msag.is_excepted(g(None, 0, "B"), None) and not msag.is_excepted(g(None, None, "B"), None),
          "is_excepted drops an explicit 0-0 range and keeps a record with no range at all")
        c(msag.is_excepted(g(1, 9, "B", esn="123456"), None) and not msag.is_excepted(g(1, 9, "B", esn="123"), None), "is_excepted drops a numeric ESN longer than five digits")
        c(not msag.is_excepted(g(1, 9, "B", esn="1234"), None) and not msag.is_excepted(g(1, 9, "B", esn="12345"), None),
          "is_excepted keeps a four or five digit ESN, which ADDR-05 accepts  <-- pinned defect")
        c(msag.is_excepted(g(1, 9, "B", name="ALPHA ST"), exc) and msag.is_excepted(g(1, 9, "B", name="BETA ST", esn="200"), exc)
          and msag.is_excepted(g(1, 9, "B", name="GAMMA ST", esn="300"), exc) and not msag.is_excepted(g(1, 9, "B", name="DELTA ST"), exc),
          "is_excepted applies name, name-and-ESN and permanent rows and keeps anything else")
        c(not msag.is_excepted(g(1, 9, "B", name="ALPHA ST"), exc, convention_only=True) and not msag.is_excepted(g(1, 9, "B", name="ALPHA ST"), None),
          "the data-driven exceptions never hide a GIS-side finding")
        c(not msag.is_excepted(g(1, 9, "B", esn="ABC"), None), "is_excepted keeps a non-numeric ESN")

    # ---- the GIS side
    sides = msag.build_gis_msag([S(), S(FROMLEFT=0, TOLEFT=0), S(FROMLEFT=199, TOLEFT=101, FROMRIGHT=None)])
    c(len(sides) == 4 and sides[0]["low"] == 101 and sides[3]["low"] == 101 and sides[0]["parity"] == "O" and sides[0]["esn"] == "100",
      "build_gis_msag emits one record per populated side, swaps a reversed range and skips 0-0 and missing ends")

    # ---- coverage helpers
    cover = msag.ranges_cover
    c(not cover(None, 5, [(1, 9)]) and cover(5, 1, [(1, 9)]) and not cover(1, 9, [(1, 4), (6, 9)]) and cover(1, 9, [(1, 4), (5, 9)]) and not cover(1, 9, [(1, 4), (None, 3)]) and cover(1, 9, [(9, 1)]),
      "ranges_cover takes the union of adjacent ranges, in either order, and refuses a gap or a missing end")
    c(not cover(1, 9, []) and cover(1, 3, [(1, 9), (2, 4)]) and not cover(5, 9, [(1, 4)]), "ranges_cover handles no ranges, an early finish and a range that stops short")
    par = msag.ranges_cover_parity
    c(par(100, 110, "E", [(100, 110)]) and not par(100, 110, "E", [(100, 108)]) and par(101, 109, "O", [(101, 109)]) and par(110, 100, "E", [(100, 110)]),
      "ranges_cover_parity covers only the numbers of the stated parity, in either order")
    c(par(100, 110, "E", [(100, 110)]) and par(100, 110, "E", [(100, 101), (102, 110)]) is True, "ranges_cover_parity unions several ranges")
    c(not par(None, 5, "E", [(1, 9)]) and par(1, 9, "B", [(1, 9)]) and par(1, 9, "", [(1, 9)]) and not par(1, 9, "B", [(1, 4)]),
      "ranges_cover_parity defers B and blank to the full union and refuses a missing end")
    c(not par(101, 101, "E", [(5, 9)]) and par(101, 101, "E", [(101, 101)]), "ranges_cover_parity falls back to integer cover when the range holds no number of its parity  <-- pinned defect")
    span = msag.uncovered_spans
    c(span(100, 110, "E", [(100, 104), (108, 110)]) == [(106, 106)] and span(101, 109, "O", []) == [(101, 109)] and span(None, 5, "E", []) == [],
      "uncovered_spans names the missing numbers of the stated parity")
    c(span(110, 100, "E", [(100, 110)]) == [] and span(100, 110, "B", [(100, 101), (104, 110)]) == [(102, 103)] and span(99, 105, "E", [(100, 100)]) == [(102, 104)],
      "uncovered_spans accepts a reversed range, steps by one for B and starts on the right parity")
    many = span(100, 130, "E", [(102, 102), (106, 106), (110, 110), (114, 114), (118, 118)])
    c(len(many) == 3 and len(span(100, 130, "E", [(102, 102), (106, 106), (110, 110), (114, 114), (118, 118)], max_spans=0)) == 6,
      "uncovered_spans stops at max_spans, and 0 means no limit")
    rec_b = g(1200, 1300, "B")
    sides = [g(1200, 1208, "E"), g(1216, 1300, "E"), g(1201, 1209, "O"), g(1217, 1299, "O")]
    c(msag.uncovered_for_record(rec_b, sides) == [(1210, 1215)] and msag.uncovered_for_record(rec_b, [g(1202, 1298, "B")]) == [(1200, 1201), (1299, 1300)],
      "uncovered_for_record merges the even and odd holes of a B record into one span, and keeps two separate holes apart  <-- pinned defect")
    c(msag.uncovered_for_record(g(100, 110, "E"), [g(100, 104, "E")]) == [(106, 110)] and msag.uncovered_for_record(g(100, 110, "E"), [g(100, 104, "E")], 0) == [(106, 110)],
      "uncovered_for_record reads an E record against its own parity")
    c(msag.uncovered_for_record(g(100, 110, "B"), [g(100, 104, "E"), g(101, 109, "O"), g(106, 110, "E")], 5) == [] and msag.uncovered_for_record(g(100, 110, "B"), [], 0) == [(100, 110)] ,
      "uncovered_for_record has no gap when the sides cover a B record, and one span when nothing covers it")

    # ---- reconcile
    res = msag.reconcile([g(100, 199, "B")], [g(101, 199, "O"), g(100, 198, "E")])
    c(res["counts"]["matched"] == 1 and res["counts"]["exact"] == 1 and res["match_rate"] == 1.0 and res["exact_rate"] == 1.0,
      "reconcile matches a B record against an odd side and an even side and counts it exact")
    res = msag.reconcile([g(100, 150, "E")], [g(100, 198, "E")])
    c(res["match_rate"] == 1.0 and res["exact_rate"] == 0.0 and res["counts"]["exact"] == 0,
      "reconcile reports 100 percent coverage and 0 percent exact when the GIS run is wider than the MSAG record  <-- pinned defect")
    res = msag.reconcile([g(100, 198, "E", esn="200")], [g(100, 198, "E", esn="100")])
    c(len(res["attr_mismatch"]) == 1 and res["attr_mismatch"][0]["gis_esns"] == ["100"] and "ESN mismatch: MSAG 200 vs GIS 100" in res["attr_mismatch"][0]["reason"] and res["counts"]["matched"] == 1,
      "reconcile matches the range and reports the ESN difference")
    res = msag.reconcile([g(100, 198, "E", esn="")], [g(100, 198, "E", esn="100")])
    c(res["attr_mismatch"] == [], "reconcile does not report an ESN difference when the MSAG ESN is blank")
    res = msag.reconcile([g(100, 200, "E")], [g(100, 150, "E")])
    c(len(res["range_mismatch"]) == 1 and len(res["gis_not_msag"]) == 0 and res["counts"]["unaccounted"] == 0,
      "reconcile reports an endpoint that moved once, from the MSAG side only")
    res = msag.reconcile([g(100, 198, "E")], [g(100, 198, "E", name="OAK ST")])
    c(len(res["msag_not_gis"]) == 1 and len(res["gis_not_msag"]) == 1 and res["match_rate"] == 0.0, "reconcile reports a street that only one source has, in both directions")
    res = msag.reconcile([g(300, 400, "E")], [g(100, 198, "E")])
    c(len(res["msag_not_gis"]) == 1, "reconcile reports an MSAG range with no GIS overlap when no address index is given")
    idx = msag.build_msag_addr_index([A(Add_Number=350, HOUSE_NU="350", CITY="testville"), A(Add_Number=0), A(Add_Number="x"), A(STREET_NA="", TYPE="", _NAMEKEY="X"), A(Add_Number=-3), A(Add_Number=-3.0)])
    c(idx == {("TESTVILLE", "ELM ST"): [350]}, "build_msag_addr_index keeps only addressable points with a positive number and a name")
    res = msag.reconcile([g(300, 400, "E")], [g(100, 198, "E")], addr_index={})
    c(res["counts"]["addr_gated"] == 1 and res["msag_not_gis"] == [] and res["counts"]["unaccounted"] == 0,
      "reconcile counts an MSAG range as address-gated when no point lies in the gap")
    res = msag.reconcile([g(300, 400, "E")], [g(100, 198, "E")], addr_index=idx)
    c(len(res["msag_not_gis"]) == 1, "reconcile keeps an MSAG range when an address point lies in the gap")
    res = msag.reconcile([g(300, 400, "E")], [g(100, 198, "E"), g(302, 399, "E", name="OAK ST")], addr_index={("TESTVILLE", "ELM ST"): [351, 360]})
    c(len(res["msag_not_gis"]) == 1, "reconcile ignores an address point of the wrong parity when it gates a gap")
    res = msag.reconcile([g(100, 198, "E")], [g(100, 198, "E"), g(300, 400, "E", name="OAK ST")], addr_index={})
    c(res["gis_not_msag"] == [], "reconcile drops a GIS range with no MSAG record when no point lies in it")
    res = msag.reconcile([], [g(100, 198, "E", name="OAK ST")], addr_index={("TESTVILLE", "OAK ST"): [150]})
    c(len(res["gis_not_msag"]) == 1 and res["counts"]["eligible"] == 0 and res["match_rate"] == 1.0 and res["exact_rate"] == 1.0,
      "reconcile keeps a GIS range with an address point, and reports 100 percent of nothing when no MSAG record is eligible")
    res = msag.reconcile([g(100, 198, "E", esn="999")], [g(100, 198, "E", esn="999", name="OAK ST")])
    c(res["counts"]["excepted"] == 1 and res["counts"]["eligible"] == 0 and res["gis_not_msag"] == [], "reconcile excludes excepted records from the denominator and from the GIS-side findings")
    res = msag.reconcile([g(100, 198, "E")], [g(100, 198, "E")], addr_index={("TESTVILLE", "ELM ST"): [150]})
    c(res["counts"]["matched"] == 1 and res["gis_not_msag"] == [], "reconcile with an address index still matches a covered range")
    res = msag.reconcile([g(None, 198, "E"), g(100, None, "E")], [g(100, 198, "E")])
    c(res["counts"]["unaccounted"] == 0 and res["counts"]["msag_total"] == 2, "reconcile accounts for a record that has no range")
    c(msag._overlaps({"low": None, "high": 1}, {"low": 1, "high": 2}) is False, "overlaps is false when an end is missing")
    c(msag._has_uncovered_address(g(None, 5, "E"), [], {("TESTVILLE", "ELM ST"): [3]}) is False and msag._has_uncovered_address(g(5, 1, "E"), [], {("TESTVILLE", "ELM ST"): [3]}) is False
      and msag._has_uncovered_address(g(1, 5, "O"), [(3, 9)], {("TESTVILLE", "ELM ST"): [3, 4, 9]}) is False,
      "the address gate treats a missing end, an odd point against an even range and a covered point as no gap")
    c(msag._has_uncovered_address(g(5, 1, "B"), [], {("TESTVILLE", "ELM ST"): [3]}) is True, "the address gate reads a reversed range in either order")

    # ---- exact-tuple rate
    runs = msag.gis_runs([g(100, 110, "E"), g(112, 120, "E"), g(130, 140, "E"), g(101, 109, "B"), g(111, 111, "E")])
    c(runs[("TESTVILLE", "ELM ST", "100", "E")] == [(100, 120), (130, 140)], "gis_runs merges spans within one parity step and keeps a larger gap apart")
    c(runs[("TESTVILLE", "ELM ST", "100", "O")] == [(101, 109)] and ("TESTVILLE", "ELM ST", "100", "E") in runs, "gis_runs feeds a B side to both parities")
    runs = msag.gis_runs([g(100, 198, "E"), g(101, 199, "O")])
    et = msag.exact_tuple
    c(et(g(100, 198, "E"), runs) and et(g(101, 199, "O"), runs) and et(g(100, 199, "B"), runs) and et(g(199, 100, "B"), runs),
      "exact_tuple accepts an E, an O and a B record that equal whole GIS runs, in either order")
    c(not et(g(100, 150, "E"), runs) and not et(g(100, 198, "E", esn="200"), runs) and not et(g(None, 5, "E"), runs) and not et(g(5, None, "E"), runs),
      "exact_tuple refuses a shorter span, another ESN and a missing end")
    c(not et(g(101, 101, "E"), runs) and not et(g(100, 199, "B", comm="OTHER"), runs), "exact_tuple refuses a range with no number of its parity and another community")
    c(msag._parity_span(101, 101, "E") is None and msag._parity_span(100, 101, "E") == (100, 100) and msag._parities("o") == ("O",) and msag._parities(None) == ("E", "O"),
      "the parity helpers find the first and last number of a parity")

    # ---- roll-up
    res = {"msag_not_gis": [g(1, 2, "B"), g(3, 4, "B")], "gis_not_msag": [g(1, 2, "B", name="OAK ST")],
           "range_mismatch": [{"msag": g(1, 2, "B"), "gis": [], "group": []}], "attr_mismatch": [{"msag": g(1, 2, "B", name="OAK ST"), "gis_esns": [], "reason": ""}]}
    rows = msag.rollup(res)
    c(rows[0]["name_key"] == "ELM ST" and rows[0]["total"] == 3 and rows[0]["msag_not_gis"] == 2 and rows[0]["range_mismatch"] == 1
      and rows[1]["name_key"] == "OAK ST" and rows[1]["total"] == 2 and rows[1]["gis_not_msag"] == 1 and rows[1]["attr_mismatch"] == 1 and len(rows) == 2,
      "rollup turns findings on two streets into two rows, the larger first")
    c(msag.rollup({"msag_not_gis": [], "gis_not_msag": [], "range_mismatch": [], "attr_mismatch": []}) == [], "rollup of no findings is empty")

    # ---- XLAYER-16 through the engine
    with Tmp() as tmp:
        rep, ctx = _xl16(HEADER + ELM_B, [S()], tmp=tmp)
        r = rep.records
        c(found(r, "XLAYER-16", "INFO", "MSAG match rate 100.00% (matched 1/1 eligible)") == 1 and found(r, "XLAYER-16", "INFO", "MSAG exact-tuple rate 100.00% (1/1 eligible") == 1,
          "xlayer-16 reports the match rate and the exact-tuple rate")
        c(found(r, "XLAYER-16", "INFO", "MSAG source is 0 day(s) old (no limit set)") == 1 and ctx.msag_match_rate == 1.0 and ctx.msag_result is not None,
          "xlayer-16 reports the age of the MSAG file and leaves the result on the context")
        c(found(r, "XLAYER-16", "WARNING") == 0 and found(r, "XLAYER-16", "ERROR") == 0, "xlayer-16 is quiet when the MSAG and the GIS agree")

        rep, ctx = _xl16(HEADER + ",ELM,ST,,100,150,TESTVILLE,E,100\n", [S()], tmp=tmp)
        r = rep.records
        c(found(r, "XLAYER-16", "INFO", "MSAG match rate 100.00%") == 1 and found(r, "XLAYER-16", "INFO", "MSAG exact-tuple rate 0.00% (0/1 eligible") == 1,
          "xlayer-16 shows a perfect match rate beside a 0 percent exact-tuple rate  <-- pinned defect")

        rep, ctx = _xl16(HEADER + ",ELM,ST,,100,150,TESTVILLE,E,100\n,ELM,ST,,101,199,TESTVILLE,O,200\n,OAK,AVE,,10,20,TESTVILLE,B,100\n,DUP,ST,,1,5,TESTVILLE,O,100\n",
                         [S(), S(FROMLEFT=301, TOLEFT=399, FROMRIGHT=0, TORIGHT=0, Parity_R="Z"), S(NAME="PINE", _NAMEKEY="PINE ST")],
                         addresses=[A(Add_Number=351, HOUSE_NU="351")], tmp=tmp)
        r = rep.records
        c(found(r, "XLAYER-16", "WARNING", "MSAG record has no GIS coverage") == 2 and found(r, "XLAYER-16", "WARNING", "ESN mismatch: MSAG 200 vs GIS 100") == 1,
          "xlayer-16 warns for an MSAG record no GIS side covers and for an ESN that differs")
        c(found(r, "XLAYER-16", "ERROR", "GIS centerline range has no MSAG coverage") >= 1, "xlayer-16 reports a GIS range with no MSAG coverage as an ERROR")

        rep, ctx = _xl16(HEADER + ",ELM,ST,,100,200,TESTVILLE,E,100\n", [S()], tmp=tmp)
        r = rep.records
        c(found(r, "XLAYER-16", "WARNING", "GIS 100-198 vs MSAG 100-200") == 1 and found(r, "XLAYER-16", "WARNING", "not covered by GIS: 200") == 1,
          "xlayer-16 states which endpoint moved and which numbers are missing")
        rep, ctx = _xl16(HEADER + ",ELM,ST,,100,198,TESTVILLE,E,100\n", [S(FROMRIGHT=100, TORIGHT=130), S(FROMRIGHT=140, TORIGHT=198, FROMLEFT=0, TOLEFT=0, Parity_L="Z")], tmp=tmp)
        r = rep.records
        c(found(r, "XLAYER-16", "WARNING", "GIS and MSAG both 100-198, but GIS coverage has gaps") == 1 and found(r, "XLAYER-16", text="2 GIS segments") == 1 and found(r, "XLAYER-16", text="132-138") == 1,
          "xlayer-16 reports a hole inside agreeing endpoints once, with the segment count")
        rep, ctx = _xl16(HEADER + ",ELM,ST,,100,198,TESTVILLE,E,200\n", [S()], tmp=tmp)
        r = rep.records
        c(found(r, "XLAYER-16", "WARNING", "ESN mismatch: MSAG 200 vs GIS 100") == 1, "xlayer-16 warns on an ESN mismatch")

        rep, ctx = _xl16(HEADER + ",ELM,ST,,100,198,TESTVILLE,E,999\n", [S()], tmp=tmp)
        r = rep.records
        c(found(r, "XLAYER-16", "WARNING", "compared nothing") == 1 and found(r, "XLAYER-16", "INFO", "MSAG match rate 100.00% (matched 0/0 eligible)") == 1,
          "xlayer-16 warns that a 100 percent rate over no eligible record compared nothing  <-- pinned defect")

        # age against the limit
        path = tmp.path("msag.csv")
        mt = os.path.getmtime(path)
        cfg = msag.MsagConfig(source_path=path, max_source_age_days=30, min_match_rate=0.5)
        ctx = ctx_for([], [S()])
        engine.build_msag_context(ctx, cfg, now=mt + 40 * 86400)
        r = engine.run_report([], [S()], ctx, ids=["XLAYER-16"]).records
        c(found(r, "XLAYER-16", "WARNING", "MSAG source is 40 day(s) old (limit 30)") == 1, "xlayer-16 warns when the MSAG file is older than the limit")
        ctx = ctx_for([], [S()])
        engine.build_msag_context(ctx, cfg, now=mt + 3 * 86400)
        r = engine.run_report([], [S()], ctx, ids=["XLAYER-16"]).records
        c(found(r, "XLAYER-16", "INFO", "MSAG source is 3 day(s) old (limit 30)") == 1 and found(r, "XLAYER-16", "WARNING", "source") == 0,
          "xlayer-16 reports the age at INFO inside the limit")
        c(ctx.min_match_rate == 0.5 and ctx.max_source_age_days == 30, "build_msag_context copies the floor and the age limit onto the context")
        ctx.msag_source_age_days = None
        r = engine.run_report([], [S()], ctx, ids=["XLAYER-16"]).records
        c(found(r, "XLAYER-16", text="day(s) old") == 0, "xlayer-16 reports no age when none was measured")

        # below the floor
        ctx = ctx_for([], [S()])
        engine.build_msag_context(ctx, msag.MsagConfig(source_path=path, min_match_rate=1.1))
        r = engine.run_report([], [S()], ctx, ids=["XLAYER-16"]).records
        c(found(r, "XLAYER-16", "INFO", "BELOW FLOOR") == 1, "xlayer-16 says BELOW FLOOR when the rate is under the floor")

        # a record in no bucket is a WARNING
        real = msag.reconcile
        ctx = ctx_for([], [S()])
        engine.build_msag_context(ctx, msag.MsagConfig(source_path=path))

        def lossy(*a, **k):
            res = real(*a, **k)
            res["counts"]["unaccounted"] = 1
            return res
        msag.reconcile = lossy
        try:
            r = engine.run_report([], [S()], ctx, ids=["XLAYER-16"]).records
        finally:
            msag.reconcile = real
        c(found(r, "XLAYER-16", "WARNING", "1 MSAG record(s) are in no bucket") == 1, "xlayer-16 warns when a record falls between buckets")

        # the context loaders
        ctx = ctx_for([A()], [S()])
        exc_p = tmp.write("e.csv", "kind,community,prefix,street,type,suffix,esn\nname,,,ELM,ST,,\n")
        nam_p = tmp.write("n.csv", "community,street_name\nTESTVILLE,OAK AVE\n")
        engine.build_msag_context(ctx, msag.MsagConfig(source_path=path, exceptions_path=exc_p, names_path=nam_p))
        c(ctx.msag_exceptions.by_name_any_esn == {"ELM ST"} and ("TESTVILLE", "OAK AVE") in ctx.authoritative_names and ("TESTVILLE", "ELM ST") in ctx.authoritative_names,
          "build_msag_context unions the name list with the names in the MSAG file")
        c(engine.build_msag_context(ctx_for([], []), None).msag_records is None, "build_msag_context with no config leaves the MSAG fields empty")
        blank = tmp.write("blank.csv", HEADER)
        ctx = ctx_for([], [S()])
        engine.build_msag_context(ctx, msag.MsagConfig(source_path=blank))
        c(ctx.authoritative_names is None, "build_msag_context leaves STREET-11 on its fallback when the MSAG has no names")

    c(xl._msag_rec_label(g(1, 2, "")) == "TESTVILLE | ELM ST | 1..2 | parity ? | ESN 100" and xl._msag_rec_label({}) == " |  | None..None | parity ? | ESN ?",
      "the record label shows a question mark for a blank parity or ESN")
