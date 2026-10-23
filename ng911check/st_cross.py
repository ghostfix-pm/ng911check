"""Self-test: the cross_layer checks except the MSAG one (XLAYER-01 to XLAYER-15)."""
from . import cross_layer_checks as xl
from .crosswalks import load_crosswalks
from .st_fix import A, AG, S, ctx_for, found, geom_provider, line, run

GEO = {"geom_provider": geom_provider}
BOTH = dict(Parity_L="B", Parity_R="B", FROMRIGHT=101, TORIGHT=199)
LEFT_ONLY = dict(FROMRIGHT=0, TORIGHT=0, Parity_R="Z")


def _street_on_line(y=0.0, **kw):
    """A street with a west-to-east line at height y (feet)."""
    s = S(**kw)
    line(s, (0.0, y), (1000.0, y))
    return s


def section(h):
    c = h.check

    # ---- XLAYER-01 address ESN against the covering side
    r = run([A(ESN="200")], [S()], ["XLAYER-01"])
    c(found(r, "XLAYER-01", "ERROR", "ESN 200 != covering side ESN(s) ['100']") == 1, "xlayer-01 flags an address ESN that differs from its covering side")
    r = run([A(), A(ESN=""), A(Add_Number=301, HOUSE_NU="301", ESN="999")], [S()], ["XLAYER-01"])
    c(len(r) == 0, "xlayer-01 passes a match, skips a blank ESN and skips an address no segment covers")
    r = run([A(Add_Number=100, HOUSE_NU="100", ESN="100")], [S(RESN="300")], ["XLAYER-01"])
    c(found(r, "XLAYER-01", text="Right") == 1, "xlayer-01 compares an even number with the right side")
    r = run([A(Add_Number=105, HOUSE_NU="105", ESN="200")], [S(LESN="100", RESN="200", **BOTH)], ["XLAYER-01"])
    c(len(r) == 0, "xlayer-01 accepts a match with either side when both sides cover the number")
    r = run([A(Add_Number=105, HOUSE_NU="105", ESN="300")], [S(LESN="100", RESN="200", **BOTH)], ["XLAYER-01"])
    c(found(r, "XLAYER-01", text="BOTH") == 1, "xlayer-01 flags a number that matches neither of two covering sides")
    r = run([A()], [S(LESN="")], ["XLAYER-01"])
    c(len(r) == 0, "xlayer-01 does not flag when the covering side has no ESN to compare")

    # ---- XLAYER-02 number outside every range
    r = run([A(Add_Number=301, HOUSE_NU="301")], [S()], ["XLAYER-02"])
    c(found(r, "XLAYER-02", "ERROR", "house number 301 on ELM ST") == 1, "xlayer-02 flags a number outside every range of its street")
    r = run([A(), A(STREET_NA="NOPE", Add_Number=301)], [S()], ["XLAYER-02"])
    c(len(r) == 0, "xlayer-02 leaves an absent street name to xlayer-04")
    r = run([A(Add_Number=301, HOUSE_NU="301")], [S()], ["XLAYER-02"], street_names_ignored=frozenset({"ELM"}))
    c(len(r) == 0, "xlayer-02 skips an ignored street name")
    r = run([A(STREET_NA="", TYPE="", _NAMEKEY="ELM ST", Add_Number=301, HOUSE_NU="301")], [S()], ["XLAYER-02"])
    c(found(r, "XLAYER-02") == 1, "xlayer-02 still checks a point named only by its _NAMEKEY")

    # ---- XLAYER-12 ties
    r = run([A()], [S(), S()], ["XLAYER-12"])
    c(found(r, "XLAYER-12", "ERROR", "covered by segments") == 1, "xlayer-12 flags a number two segments of one street cover")
    r = run([A()], [S(SEGMENT_ID=None), S(SEGMENT_ID=None)], ["XLAYER-12"])
    c(found(r, "XLAYER-12") == 1, "xlayer-12 tells two segments with no SEGMENT_ID apart  <-- pinned defect")
    r = run([A(), A(Add_Number=301, HOUSE_NU="301")], [S()], ["XLAYER-12"])
    c(len(r) == 0, "xlayer-12 passes a number one segment covers or none covers")

    # ---- XLAYER-03 parity against the side
    r = run([A()], [S(Parity_L="E")], ["XLAYER-03"])
    c(found(r, "XLAYER-03", "WARNING", "parity O vs side E") == 1, "xlayer-03 flags an odd number on a side declared even")
    r = run([A(), A(Add_Number=100, HOUSE_NU="100"), A(Add_Number=301, HOUSE_NU="301")], [S()], ["XLAYER-03"])
    c(len(r) == 0, "xlayer-03 passes agreeing parity and a number no range covers")
    r = run([A()], [S(Parity_L="B"), S(Parity_L="")], ["XLAYER-03"])
    c(len(r) == 0, "xlayer-03 accepts B and a blank parity")
    r = run([A()], [S(Parity_L="E"), S(Parity_L="O")], ["XLAYER-03"])
    c(len(r) == 0, "xlayer-03 is clean when any covering side agrees")

    # ---- XLAYER-13 geometric side
    s = _street_on_line()
    r = run([A(_XY=(500.0, 50.0)), A(_XY=(500.0, -50.0))], [s], ["XLAYER-13"], **GEO)
    c(found(r, "XLAYER-13", "WARNING", "geometric side Right != parity side Left") == 1 and found(r, "XLAYER-13") == 1,
      "xlayer-13 flags an odd number south of an eastbound line and passes one north of it")
    r = run([A(_XY=(-50.0, 10.0)), A(_XY=(1050.0, 10.0)), A(_XY=None)], [s], ["XLAYER-13"], **GEO)
    c(len(r) == 0, "xlayer-13 ignores a foot at a line end and a point with no position")
    r = run([A(_XY=(500.0, -50.0))], [S()], ["XLAYER-13"], **GEO)
    c(len(r) == 0, "xlayer-13 ignores a segment that has no geometry")
    far, near = _street_on_line(0.0), _street_on_line(100.0)
    r = run([A(_XY=(500.0, 60.0))], [far, near], ["XLAYER-13"], **GEO)
    c(found(r, "XLAYER-13") == 1, "xlayer-13 judges the nearest covering segment, far one first")
    r = run([A(_XY=(500.0, 60.0))], [near, far], ["XLAYER-13"], **GEO)
    c(found(r, "XLAYER-13") == 1, "xlayer-13 judges the nearest covering segment, near one first")
    both = _street_on_line(**BOTH)
    r = run([A(Add_Number=105, HOUSE_NU="105", _XY=(500.0, -50.0))], [both], ["XLAYER-13"], **GEO)
    c(len(r) == 0, "xlayer-13 does not judge a number that both sides cover")
    c(xl.check_xlayer_13([], [], ctx_for([], [])) == [], "xlayer-13 returns nothing when the context has no geometry")

    # ---- XLAYER-05 distance to the same-name segment
    s = _street_on_line()
    r = run([A(_XY=(500.0, 2000.0)), A(Add_Number=301, HOUSE_NU="301", _XY=(500.0, 2000.0)), A(_XY=(500.0, 50.0))], [s],
            ["XLAYER-05"], **GEO)
    c(found(r, "XLAYER-05", "INFO", "(> 1000 ft)") == 1 and found(r, "XLAYER-05", "WARNING", "(> 1000 ft)") == 1 and found(r, "XLAYER-05") == 2,
      "xlayer-05 reports a far point at INFO when its number is in range and at WARNING when it is not")
    r = run([A(_XY=(500.0, 2000.0))], [s], ["XLAYER-05"], distance_tolerance_ft=5000.0, **GEO)
    c(len(r) == 0, "xlayer-05 reads distance_tolerance_ft from the context")
    r = run([A(STREET_NA="NOPE", _XY=(500.0, 9000.0)), A(Add_Number=0, _XY=(500.0, 9000.0)), A(_XY=None)], [s],
            ["XLAYER-05"], **GEO)
    c(len(r) == 0, "xlayer-05 skips an absent name, a placeholder and a point with no position")
    r = run([A(_XY=(500.0, 9000.0))], [S()], ["XLAYER-05"], **GEO)
    c(len(r) == 0, "xlayer-05 skips a name whose segments have no geometry")
    c(xl.check_xlayer_05([], [], ctx_for([], [])) == [], "xlayer-05 returns nothing when the context has no geometry")

    # ---- XLAYER-10 abbreviations against St_ fields
    r = run([A(PREFIX="N", St_PreDir="")], [S(PREFIX="N", St_PreDir="")], ["XLAYER-10"])
    c(found(r, "XLAYER-10", text="PREFIX 'N' vs St_PreDir", layer="address") == 1 and found(r, "XLAYER-10", text="one blank", layer="street") == 1,
      "xlayer-10 flags a PREFIX with no St_PreDir on both layers")
    r = run([A(PREFIX="XX", St_PreDir="NORTH")], [], ["XLAYER-10"])
    c(found(r, "XLAYER-10", text="PREFIX 'XX' unmapped") == 1, "xlayer-10 flags an unmapped PREFIX")
    r = run([A(PREFIX="N", St_PreDir="SOUTH")], [], ["XLAYER-10"])
    c(found(r, "XLAYER-10", text="PREFIX 'N' != St_PreDir") == 1, "xlayer-10 flags a PREFIX that disagrees with St_PreDir")
    r = run([A(PREFIX="N", St_PreDir="NORTH", ADDRESS="101 N ELM ST")], [], ["XLAYER-10"])
    c(len(r) == 0, "xlayer-10 accepts an abbreviation that cross-walks")
    r = run([A(TYPE="", St_PosTyp="STREET")], [], ["XLAYER-10"])
    c(found(r, "XLAYER-10", text="TYPE '' vs St_PosTyp") == 1, "xlayer-10 flags a St_PosTyp with no TYPE")
    r = run([A(TYPE="ZZZ", St_PosTyp="STREET")], [], ["XLAYER-10"])
    c(found(r, "XLAYER-10", text="TYPE 'ZZZ' unmapped") == 1, "xlayer-10 flags an unmapped TYPE")
    r = run([A(TYPE="", St_PosTyp="")], [], ["XLAYER-10"])
    c(len(r) == 0, "xlayer-10 accepts a point with neither TYPE nor St_PosTyp")
    r = run([A(TYPE="ST", St_PosTyp="AVENUE")], [], ["XLAYER-10"])
    c(found(r, "XLAYER-10", text="TYPE 'ST' != St_PosTyp") == 1, "xlayer-10 flags a TYPE that disagrees with St_PosTyp")
    r = run([A(STREET_NA="OAK")], [], ["XLAYER-10"])
    c(found(r, "XLAYER-10", text="STREET_NA 'OAK' != St_Name") == 1, "xlayer-10 flags a name that differs from St_Name")
    names = [("NB I75", "Northbound Interstate 75", ""), ("ST BENEDICT", "SAINT BENEDICT", ""),
             ("HWY 99", "99", "Highway"), ("", "", "")]
    r = run([A(STREET_NA=n, St_Name=s_, St_PreTyp=p, _NAMEKEY="ELM ST") for n, s_, p in names], [], ["XLAYER-10"])
    c(len(r) == 0, "xlayer-10 expands bound directionals, interstates and a listed saint, and takes a trailing route number")
    bad = [("OAK ST", "OAK STREET", ""), ("HWY 99", "99", ""), ("HWY 99", "", "Highway"), ("HWY 99", "98", "Highway"),
           ("99", "HWY 99", "Highway"), ("ST ELM", "SAINT ELM", "")]
    r = run([A(STREET_NA=n, St_Name=s_, St_PreTyp=p, _NAMEKEY="ELM ST") for n, s_, p in bad], [], ["XLAYER-10"])
    c(found(r, "XLAYER-10", text="!= St_Name") == 6, "xlayer-10 flags six name pairs that do not agree")

    # ---- XLAYER-06 city and ZIP against the side
    r = run([A(CITY="OTHERVILLE")], [S()], ["XLAYER-06"])
    c(found(r, "XLAYER-06", "WARNING", "CITY 'OTHERVILLE' != side Left CITY") == 1, "xlayer-06 flags a CITY that differs from the left side")
    r = run([A(ZIP_CODE="32111")], [S()], ["XLAYER-06"])
    c(found(r, "XLAYER-06", "WARNING", "ZIP 32111 != side Left ZIP") == 1, "xlayer-06 flags a ZIP that differs from the left side")
    r = run([A(Add_Number=100, HOUSE_NU="100", CITY="OTHERVILLE")], [S()], ["XLAYER-06"])
    c(found(r, "XLAYER-06", text="side Right") == 1, "xlayer-06 compares an even number with the right side")
    r = run([A(Add_Number=105, HOUSE_NU="105", CITY="ALPHA")], [S(RCITY="ALPHA", **BOTH)], ["XLAYER-06"])
    c(len(r) == 0, "xlayer-06 accepts a CITY that matches either of two covering sides")
    r = run([A(Add_Number=105, HOUSE_NU="105", CITY="BETA")], [S(RCITY="ALPHA", **BOTH)], ["XLAYER-06"])
    c(found(r, "XLAYER-06") == 1, "xlayer-06 flags a CITY that matches neither of two covering sides")
    r = run([A(STREET_NA="OAK", _NAMEKEY="ELM ST", CITY="OTHERVILLE")], [S()], ["XLAYER-06"])
    c(len(r) == 0, "xlayer-06 never compares a segment of another street that shares a stale key  <-- pinned defect")
    r = run([A(CITY=""), A(Add_Number=301, HOUSE_NU="301", CITY="OTHERVILLE")], [S()], ["XLAYER-06"])
    c(len(r) == 0, "xlayer-06 skips a blank CITY and a number no segment covers")
    r = run([A(CITY="OTHERVILLE", ZIP_CODE="99999")], [S(LCITY="", LEFTZIP="")], ["XLAYER-06"])
    c(len(r) == 0, "xlayer-06 skips a side that has no city and no ZIP")

    # ---- XLAYER-04 street name present
    r = run([A(STREET_NA="NOPE")], [S()], ["XLAYER-04"])
    c(found(r, "XLAYER-04", "ERROR", "no centerline named 'NOPE ST'") == 1, "xlayer-04 flags a name that no centerline carries")
    r = run([A(), A(STREET_NA="", TYPE="", _NAMEKEY="NOPE ST"), A(STREET_NA="IGN", _NAMEKEY="IGN ST")], [S()], ["XLAYER-04"],
            street_names_ignored=frozenset({"IGN"}))
    c(len(r) == 0, "xlayer-04 passes a present name and skips a blank or ignored one")

    # ---- XLAYER-04b COMPARE cache
    r = run([A(COMPARE="OAK ST")], [S(COMPARE="OAK ST")], ["XLAYER-04b"])
    c(found(r, "XLAYER-04b", "WARNING", "COMPARE 'OAK ST' != 'ELM ST'") == 1 and found(r, "XLAYER-04b", "WARNING", "norm mismatch") == 1,
      "xlayer-04b warns on a COMPARE that differs from the recomputed name, on both layers")
    r = run([A(COMPARE=""), A(COMPARE=""), A(Add_Number=0, COMPARE="")], [S(COMPARE=""), S(COMPARE=" ELM ST "), S()], ["XLAYER-04b"])
    c(found(r, "XLAYER-04b", "INFO", "2 address points have an empty COMPARE") == 1 and found(r, "XLAYER-04b", "INFO", "1 segments have an empty COMPARE") == 1
      and found(r, "XLAYER-04b", "INFO", "surrounding whitespace") == 1 and found(r, "XLAYER-04b", "WARNING") == 0,
      "xlayer-04b summarises empty and padded COMPARE values at INFO and does not warn per row")

    # ---- XLAYER-07 duplicate NGUID
    r = run([A(Site_NGUID="D@" + AG), A(Site_NGUID="D@" + AG), A(Site_NGUID=" "), A(Site_NGUID="")],
            [S(RCL_NGUID="E@" + AG), S(RCL_NGUID="E@" + AG), S(RCL_NGUID="")], ["XLAYER-07"])
    c(found(r, "XLAYER-07", "ERROR", layer="address") == 2 and found(r, "XLAYER-07", layer="street") == 2,
      "xlayer-07 flags both rows of a duplicate NGUID on each layer and ignores blanks")

    # ---- XLAYER-08 DiscrpAgID
    r = run([A(DiscrpAgID=""), A(DiscrpAgID=None), A(DiscrpAgID=" x"), A(DiscrpAgID="a b")], [S(DiscrpAgID="")], ["XLAYER-08"])
    c(found(r, "XLAYER-08", "ERROR", "invalid (blank/whitespace)") == 5, "xlayer-08 flags a blank, missing, padded or spaced DiscrpAgID")
    r = run([A(DiscrpAgID="other.example.net")], [S(DiscrpAgID="other.example.net")], ["XLAYER-08"])
    c(found(r, "XLAYER-08", "ERROR", "!= expected") == 2, "xlayer-08 flags a DiscrpAgID other than the expected agency")
    r = run([A(DiscrpAgID="badagency")], [], ["XLAYER-08"], expected_agid="badagency", strict_fqdn=True)
    c(found(r, "XLAYER-08", "WARNING", "strict NENA bare-FQDN", layer="dataset") == 1, "xlayer-08 warns when strict mode finds a DiscrpAgID that is not a bare FQDN")
    r = run([A(DiscrpAgID="badagency")], [], ["XLAYER-08"], expected_agid="badagency")
    c(len(r) == 0, "xlayer-08 leaves the FQDN format alone unless strict mode is on")
    r = run([A(DiscrpAgID="x@agency.example.org")], [S(DiscrpAgID="x@agency.example.org")], ["XLAYER-08"],
            expected_agid="x@agency.example.org", strict_fqdn=True)
    c(len(r) == 0, "xlayer-08 checks the domain part of a localid@domain agency in strict mode")
    r = run([A()], [S()], ["XLAYER-08"], strict_fqdn=True)
    c(len(r) == 0, "xlayer-08 passes a conforming agency in strict mode")

    # ---- XLAYER-09 state, country, county
    kw = dict(expected_state="FL", counties=frozenset({"EXAMPLE"}))
    r = run([A(STATE="ZZ"), A(STATE="GA"), A(Country=""), A(Country="CANADA"), A(COUNTY=""), A(COUNTY="OTHER COUNTY"),
             A(COUNTY="Example County", STATE="fl", Country="us"), A(STATE="")], [], ["XLAYER-09"], **kw)
    c(found(r, "XLAYER-09", "ERROR", "STATE 'ZZ' invalid") == 1 and found(r, "XLAYER-09", "WARNING", "STATE 'GA' != FL") == 1,
      "xlayer-09 errors on a state that is not a USPS code and warns on one that is not the expected state")
    c(found(r, "XLAYER-09", "ERROR", "Country blank") == 1 and found(r, "XLAYER-09", "WARNING", "Country 'CANADA' not canonical") == 1,
      "xlayer-09 errors on a blank country and warns on a country that is not canonical")
    c(found(r, "XLAYER-09", "ERROR", "COUNTY blank") == 1 and found(r, "XLAYER-09", "WARNING", "COUNTY 'OTHER COUNTY' not in the configured set") == 1
      and found(r, "XLAYER-09") == 6, "xlayer-09 errors on a blank county, warns on one outside the set and accepts a county written with COUNTY")
    r = run([A(STATE="GA", COUNTY="ANYWHERE")], [], ["XLAYER-09"])
    c(len(r) == 0, "xlayer-09 assumes no state and no county set when the settings name none")
    r = run([], [S(State_L="ZZ", State_R="GA", County_L="", County_R="OTHER"), S(County_L="EXAMPLE", County_R="ELSEWHERE"),
                 S(State_L="FL", State_R="fl")], ["XLAYER-09"], **kw)
    c(found(r, "XLAYER-09", "ERROR", "State_L 'ZZ' invalid") == 1 and found(r, "XLAYER-09", "WARNING", "State_R 'GA' != FL") == 1
      and found(r, "XLAYER-09", "ERROR", "County_L blank") == 1 and found(r, "XLAYER-09", "WARNING", "County_R 'OTHER' not in") == 1
      and found(r, "XLAYER-09", "INFO", "County_L 'EXAMPLE' != County_R 'ELSEWHERE'") == 1,
      "xlayer-09 checks both street sides for state and county and reports County_L differing from County_R at INFO")
    r = run([], [S()], ["XLAYER-09"])
    c(len(r) == 0, "xlayer-09 passes a clean segment")

    # ---- XLAYER-14 ranges with no address point
    r = run([], [S()], ["XLAYER-14"])
    c(found(r, "XLAYER-14", "INFO", "no active address covers") == 1, "xlayer-14 reports a segment no address point covers")
    r = run([A()], [S()], ["XLAYER-14"])
    c(len(r) == 0, "xlayer-14 passes a segment an address point covers")
    r = run([A()], [S(FROMLEFT=0, TOLEFT=0, Parity_L="Z")], ["XLAYER-14"])
    c(found(r, "XLAYER-14") == 1, "xlayer-14 does not let an odd point cover an even-only side")
    r = run([A(Add_Number=100, HOUSE_NU="100")], [S()], ["XLAYER-14"])
    c(len(r) == 0, "xlayer-14 accepts a point on the second side when the first side has none")
    r = run([A()], [S(Parity_L="Z", FROMRIGHT=0, TORIGHT=0, Parity_R="Z"), S(Parity_L="Q", **LEFT_ONLY)], ["XLAYER-14"])
    c(len(r) == 0, "xlayer-14 matches an unknown parity code by range alone and a bad code does not hide coverage")
    r = run([A()], [S(**dict(FROMLEFT=None, TOLEFT=199, FROMRIGHT=-5, TORIGHT=0, Parity_R="Z")), S(**dict(FROMLEFT=0, TOLEFT=0, FROMRIGHT=0, TORIGHT=0))],
            ["XLAYER-14"])
    c(len(r) == 0, "xlayer-14 skips a side with a missing end, a negative end or no range")
    r = run([A(Add_Number=0), A()], [S(_NAMEKEY="STALE KEY")], ["XLAYER-14"])
    c(len(r) == 0, "xlayer-14 finds points under the true name when the segment key is stale, and skips a placeholder")

    # ---- XLAYER-11 sync metric
    r = run([A(), A(ESN="200")], [S()], ["XLAYER-11"])
    c(found(r, "XLAYER-11", "INFO", "sync_rate 50.0% (1/2 active reconcile)") == 1 and found(r, "XLAYER-11", "WARNING", "< target 98.0%") == 1,
      "xlayer-11 reports the sync rate and warns when it is under the target")
    r = run([A()], [S()], ["XLAYER-11"])
    c(found(r, "XLAYER-11", "INFO", "100.0%") == 1 and found(r, "XLAYER-11", "WARNING") == 0, "xlayer-11 stays at INFO when every point reconciles")
    r = run([], [], ["XLAYER-11"])
    c(found(r, "XLAYER-11", "INFO", "100.0% (0/0") == 1, "xlayer-11 reports 100 percent for a layer with no addressable point")
    r = run([A(), A(ESN="200")], [S()], ["XLAYER-11"], sync_threshold=40.0)
    c(found(r, "XLAYER-11", "WARNING") == 0, "xlayer-11 reads sync_threshold from the context")

    # ---- XLAYER-15 modifier domains
    cw = load_crosswalks([("premod", "ALT", ""), ("postmod", "BIS", ""), ("pretypesep", "OF", "")])
    r = run([A(St_PreMod="BAD", St_PosMod="BAD", St_PreSep="BAD"), A(St_PreMod="ALT", St_PosMod="bis", St_PreSep="OF"), A()],
            [S(St_PreMod="BAD")], ["XLAYER-15"], crosswalks=cw)
    c(found(r, "XLAYER-15", "WARNING", "St_PreMod 'BAD' not in domain") == 2 and found(r, "XLAYER-15", text="St_PosMod 'BAD'") == 1
      and found(r, "XLAYER-15", text="St_PreSep 'BAD'") == 1 and found(r, "XLAYER-15", layer="street") == 1,
      "xlayer-15 flags a modifier or separator outside its domain on both layers and skips blanks and valid values")
