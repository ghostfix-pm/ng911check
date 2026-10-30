"""Self-test: verdicts that a mutation sweep showed no other assertion pinned.

Each case changes one boundary or one operator in the code under test and checks that the
verdict changes with it. The cases are straight lines, as in every other section.
"""
from . import msag, reader, response_area_checks as ra
from .common import is_addressable
from .selftest import Tmp
from .st_fix import A, S, ctx_for, found, run
from .st_msag import ELM_B, HEADER, _xl16, g


def section(h):
    c = h.check

    # ---- the MSAG coverage rule
    res = msag.reconcile([g(100, 199, "B")], [g(100, 198, "E")])
    c(res["match_rate"] == 0.0 and res["counts"]["matched"] == 0,
      "a lone even GIS side does not cover a B record whose odd numbers have no side  <-- pinned defect")
    exc = msag.Exceptions(by_name_any_esn={"ALPHA ST"})
    res = msag.reconcile([], [g(100, 198, "E", name="ALPHA ST")], exceptions=exc, addr_index={("TESTVILLE", "ALPHA ST"): [150]})
    c(len(res["gis_not_msag"]) == 1, "an MSAG-side exception does not hide a GIS range that the MSAG lacks  <-- pinned defect")
    res = msag.reconcile([g(100, 198, "E", esn="100")], [g(100, 198, "E", esn="100")])
    c(res["attr_mismatch"] == [] and res["counts"]["matched"] == 1, "equal ESNs on a covered range give no ESN mismatch  <-- pinned defect")

    with Tmp() as tmp:
        rep, ctx = _xl16(HEADER + ELM_B + ",OAK,AVE,,10,20,TESTVILLE,B,100\n", [S()], tmp=tmp, min_match_rate=0.5)
        kpi = [r.description for r in rep.records if r.check_name == "MSAG match-rate KPI"][0]
        c("50.00%" in kpi and "-> OK" in kpi, "a match rate exactly at the floor is OK, not BELOW FLOOR  <-- pinned defect")
        rep, ctx = _xl16(HEADER + ELM_B + ",PINE,ST,,100,199,TESTVILLE,B,1001\n,PINE,ST,,100,199,TESTVILLE,B,12345\n", [S()], tmp=tmp)
        kpi = [r.description for r in rep.records if r.check_name == "MSAG match-rate KPI"][0]
        c("matched 1/3 eligible" in kpi and "33.33%" in kpi, "a four or five digit MSAG ESN is compared with the GIS, not dropped from the rate  <-- pinned defect")

    # ---- response-area sentinel
    c("!= containing" in ra._describe("ESN", "200", "100", True, "ESN area", "999")[0]
      and "means outside" in ra._describe("ESN", "999", "100", True, "ESN area", "999")[0],
      "a configured sentinel hides only its own value inside a polygon  <-- pinned defect")
    c("not inside any" in ra._describe("ESN", "200", "", False, "ESN area", "999")[0]
      and ra._describe("ESN", "999", "", False, "ESN area", "999")[0] is None,
      "a configured sentinel hides only its own value outside every polygon  <-- pinned defect")

    # ---- ADDR-05 domain and bounds
    r = run([A(ESN="0"), A(ESN="00"), A(ESN="123456")], [], ["ADDR-05"])
    c(found(r, "ADDR-05", "ERROR", "not a valid 1-5 digit ESN") == 3, "ADDR-05 flags ESN 0, 00 and a six digit ESN  <-- pinned defect")
    r = run([A(ESN="1"), A(ESN="7"), A(ESN="12345")], [], ["ADDR-05"])
    c(len(r) == 0, "ADDR-05 accepts a one digit ESN, ESN 1 and a five digit ESN  <-- pinned defect")
    r = run([A(Add_Number=100), A(Add_Number=200), A(Add_Number=150)], [], ["ADDR-05"], min_address=100, max_address=200)
    c(len(r) == 0, "ADDR-05 accepts a number equal to the minimum or the maximum  <-- pinned defect")
    r = run([A(Add_Number=99), A(Add_Number=201)], [], ["ADDR-05"], min_address=100, max_address=200)
    c(found(r, "ADDR-05", "ERROR", "out of bounds (100-200)") == 2, "ADDR-05 flags a number one below the minimum and one above the maximum  <-- pinned defect")
    c(is_addressable({"Add_Number": 1, "_NAMEKEY": "ELM ST"}) and not is_addressable({"Add_Number": 0, "_NAMEKEY": "ELM ST"}),
      "house number 1 is addressable and house number 0 is not  <-- pinned defect")

    # ---- XLAYER-02 range ends and STREET-04 shared end number
    r = run([A(Add_Number=101), A(Add_Number=199), A(Add_Number=100), A(Add_Number=198)], [S()], ["XLAYER-02"])
    c(len(r) == 0, "xlayer-02 accepts a number on either end of a range  <-- pinned defect")
    r = run([], [S(), S(FROMLEFT=199, TOLEFT=299, FROMRIGHT=200, TORIGHT=298)], ["STREET-04"])
    c(found(r, "STREET-04", "ERROR", "ranges overlap") == 1, "street-04 flags two segments that share an end number  <-- pinned defect")

    # ---- ignored street names match whole words
    ctx = ctx_for([], [], street_names_ignored=frozenset({"ELM"}))
    c(ctx.name_ignored("ELM ST") and ctx.name_ignored("n elm ave") and not ctx.name_ignored("ELMWOOD DR") and not ctx.name_ignored("HELM ST"),
      "an ignored name ELM skips ELM ST and N ELM AVE, never ELMWOOD DR  <-- pinned defect")
    r = run([A(STREET_NA="ELMWOOD")], [S()], ["XLAYER-04"], street_names_ignored=frozenset({"ELM"}))
    c(found(r, "XLAYER-04", "ERROR", "no centerline named 'ELMWOOD ST'") == 1, "an ignored name does not hide the routing ERROR of a longer name  <-- pinned defect")

    # ---- GeoJSON values
    row = {"COUNTY": 12083.0, "ZIP_CODE": 1.5, "STATE": 12, "Add_Number": 7, "CITY": None, "ESN": "100"}
    reader._plain_values(row, "addresses", "where")
    c(row == {"COUNTY": "12083", "ZIP_CODE": "1.5", "STATE": "12", "Add_Number": 7, "CITY": None, "ESN": "100"},
      "a GeoJSON number in a text column becomes the text a CSV would hold and a numeric column keeps its number")
