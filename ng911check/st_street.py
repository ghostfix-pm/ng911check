"""Self-test: the street_attr checks (STREET-01 to STREET-13)."""
from .st_fix import AG, S, found, line, run

ZERO = dict(FROMLEFT=0, TOLEFT=0, FROMRIGHT=0, TORIGHT=0, Parity_L="Z", Parity_R="Z")
LEFT_ONLY = dict(FROMRIGHT=0, TORIGHT=0, Parity_R="Z")


def section(h):
    c = h.check

    # ---- STREET-01 range parity
    r = run([], [S()], ["STREET-01"])
    c(len(r) == 0, "street-01 passes an odd left side and an even right side")
    r = run([], [S(FROMRIGHT=101, TORIGHT=199, Parity_R="O")], ["STREET-01"])
    c(found(r, "STREET-01", "ERROR", "both sides parity Odd") == 1, "street-01 flags two odd sides")
    r = run([], [S(FROMLEFT=101, TOLEFT=198)], ["STREET-01"])
    c(found(r, "STREET-01", "ERROR", "invalid/mixed parity L=Both") == 1, "street-01 flags a side that mixes odd and even ends")
    r = run([], [S(FROMLEFT=0, TOLEFT=199)], ["STREET-01"])
    c(found(r, "STREET-01", "ERROR", "L=Error") == 1, "street-01 flags a side with one zero end")
    r = run([], [S(FROMLEFT=None, TOLEFT=199)], ["STREET-01"])
    c(len(r) == 0, "street-01 defers a side with one missing end to street-10")
    r = run([], [S(**ZERO)], ["STREET-01"])
    c(len(r) == 0, "street-01 accepts two unused sides")

    # ---- STREET-02 declared parity against the range
    r = run([], [S(FROMRIGHT=0, TORIGHT=0, Parity_R="E")], ["STREET-02"])
    c(found(r, "STREET-02", "WARNING", "R 0-0 but parity=E") == 1, "street-02 warns on a 0-0 side that does not declare Z")
    r = run([], [S(FROMRIGHT=None, TORIGHT=None, Parity_R="Z")], ["STREET-02"])
    c(len(r) == 0, "street-02 reads missing ends as 0-0 and accepts Z")
    r = run([], [S(Parity_L="Z")], ["STREET-02"])
    c(found(r, "STREET-02", "ERROR", "L parity Z but range 101-199") == 1, "street-02 flags Z on a side that has a range")
    r = run([], [S(Parity_L="E")], ["STREET-02"])
    c(found(r, "STREET-02", "ERROR", "L parity E vs ends 101/199") == 1, "street-02 flags a declared parity the ends contradict")
    r = run([], [S(FROMLEFT=None, TOLEFT=199, Parity_L="O"), S(Parity_L="B", Parity_R="b")], ["STREET-02"])
    c(len(r) == 0, "street-02 skips an incomplete range and accepts B")

    # ---- STREET-03 range direction
    r = run([], [S(FROMLEFT=-5)], ["STREET-03"])
    c(found(r, "STREET-03", "ERROR", "L range value -5 < 0") == 1, "street-03 flags a negative range end")
    r = run([], [S(TORIGHT=-4)], ["STREET-03"])
    c(found(r, "STREET-03", "ERROR", "R range value -4 < 0") == 1, "street-03 flags a negative end on the right side")
    r = run([], [S(FROMLEFT=0, TOLEFT=199), S(FROMLEFT=0, TOLEFT=199, Parity_L="Z")], ["STREET-03"])
    c(found(r, "STREET-03", "ERROR", "partial range 0-199 with parity O") == 1, "street-03 flags a half-zero range, and accepts it when parity is Z")
    r = run([], [S(FROMRIGHT=198, TORIGHT=100)], ["STREET-03"])
    c(found(r, "STREET-03", "WARNING", "opposite directions") == 1, "street-03 warns when the two sides run in opposite directions")
    r = run([], [S(FROMLEFT=101, TOLEFT=101), S(FROMLEFT=None)], ["STREET-03"])
    c(len(r) == 0, "street-03 accepts a one-number side and a missing end")

    # ---- STREET-04 overlap
    r = run([], [S(), S(FROMLEFT=151, TOLEFT=249)], ["STREET-04"])
    c(found(r, "STREET-04", "ERROR") == 1, "street-04 reports one overlapping pair once, not once per parity")
    r = run([], [S(FROMLEFT=101, TOLEFT=399, **{"FROMRIGHT": 0, "TORIGHT": 0, "Parity_R": "Z"}),
                 S(FROMLEFT=111, TOLEFT=121, **{"FROMRIGHT": 0, "TORIGHT": 0, "Parity_R": "Z"}),
                 S(FROMLEFT=131, TOLEFT=141, **{"FROMRIGHT": 0, "TORIGHT": 0, "Parity_R": "Z"})],
        ["STREET-04"])
    c(found(r, "STREET-04") == 2, "street-04 compares each narrow range with the wide one and not with each other")
    r = run([], [S(FROMRIGHT=101, TORIGHT=199, Parity_R="O", SEGMENT_ID=None)], ["STREET-04"])
    c(len(r) == 0, "street-04 never overlaps a segment with itself")
    r = run([], [S(SEGMENT_ID=None, **LEFT_ONLY), S(FROMLEFT=111, TOLEFT=121, **LEFT_ONLY)], ["STREET-04"])
    c(found(r, "STREET-04", text="SEG None") == 1, "street-04 names a missing SEGMENT_ID as None")
    r = run([], [S(FROMLEFT=101, TOLEFT=199, Parity_L="Q", **LEFT_ONLY), S(FROMLEFT=151, TOLEFT=249, **LEFT_ONLY)], ["STREET-04"])
    c(found(r, "STREET-04") == 1, "street-04 expands an unknown parity to both so a typo cannot hide an overlap")

    # ---- STREET-05 duplicate ids
    r = run([], [S(SEGMENT_ID=7), S(SEGMENT_ID=7), S(SEGMENT_ID=8)], ["STREET-05"])
    c(found(r, "STREET-05", "ERROR", "SEGMENT_ID 7 not unique") == 2, "street-05 flags both rows of a duplicate SEGMENT_ID")
    r = run([], [S(RCL_NGUID="D@" + AG), S(RCL_NGUID="D@" + AG), S(RCL_NGUID="")], ["STREET-05"])
    c(found(r, "STREET-05", text="RCL_NGUID") == 2, "street-05 flags a duplicate RCL_NGUID and ignores a blank one")

    # ---- STREET-06 duplicate tuple
    r = run([], [S(), S(), S(FROMLEFT=201, TOLEFT=299), S(**ZERO), S(**ZERO)], ["STREET-06"])
    c(found(r, "STREET-06", "WARNING") == 2, "street-06 flags two segments with one name and one range tuple, and skips unused segments")
    r = run([], [S(SEGMENT_ID=None), S(SEGMENT_ID=None)], ["STREET-06"])
    c(found(r, "STREET-06", text="OID") == 2, "street-06 names a segment by OID when it has no SEGMENT_ID")

    # ---- STREET-07 name missing
    r = run([], [S(NAME=""), S(NAME="", **ZERO)], ["STREET-07"])
    c(found(r, "STREET-07", "ERROR") == 1, "street-07 flags an addressable segment with no NAME and not an unused one")

    # ---- STREET-08 RCL_NGUID
    r = run([], [S()], ["STREET-08"])
    c(len(r) == 0, "street-08 passes a conforming RCL_NGUID")
    r = run([], [S(RCL_NGUID="NOAT")], ["STREET-08"])
    c(found(r, "STREET-08", "ERROR", "not '<localid>@<authority>'") == 1, "street-08 flags an RCL_NGUID with no @")
    r = run([], [S(RCL_NGUID="RCL 1@" + AG)], ["STREET-08"])
    c(found(r, "STREET-08", "ERROR", "invalid characters") == 1, "street-08 flags a localid with a space")
    r = run([], [S(DiscrpAgID="other.example.net")], ["STREET-08"])
    c(found(r, "STREET-08", "ERROR", "!= expected") == 1, "street-08 flags a DiscrpAgID that is not the authority")
    r = run([], [S(RCL_NGUID="X9@" + AG)], ["STREET-08"])
    c(found(r, "STREET-08", "WARNING", "!= 'RCL'+SEGMENT_ID") == 1, "street-08 warns when the localid is not RCL plus SEGMENT_ID")
    r = run([], [S(SEGMENT_ID=12345.0, RCL_NGUID="RCL12345@" + AG.upper())], ["STREET-08"])
    c(len(r) == 0, "street-08 reads a numeric SEGMENT_ID 12345.0 as 36247 and the authority without regard to case  <-- pinned defect")

    # ---- STREET-09 domains
    r = run([], [S(Parity_L="Q")], ["STREET-09"])
    c(found(r, "STREET-09", "ERROR", "L parity 'Q' not in") == 1, "street-09 flags a parity outside O, E, B, Z")
    r = run([], [S(Parity_R=""), S(Parity_R="", FROMRIGHT=0, TORIGHT=0)], ["STREET-09"])
    c(found(r, "STREET-09", "ERROR", "R parity blank on non-zero range") == 1, "street-09 flags a blank parity on a real range and not on an empty one")
    r = run([], [S(ONEWAY="X"), S(ONEWAY="")], ["STREET-09"])
    c(found(r, "STREET-09", "WARNING", "ONEWAY") == 2, "street-09 warns on an unknown or blank ONEWAY")
    r = run([], [S(ONEWAY="ft")], ["STREET-09"])
    c(len(r) == 0, "street-09 accepts ONEWAY without regard to case")

    # ---- STREET-10 required fields
    r = run([], [S(NAME="", FROMLEFT=None, State_L="")], ["STREET-10"])
    c(found(r, "STREET-10", "ERROR") == 3 and found(r, "STREET-10", text="FROMLEFT") == 1,
      "street-10 reports each empty required field and counts a missing number as empty")
    r = run([], [S(FROMLEFT=0)], ["STREET-10"])
    c(len(r) == 0, "street-10 accepts a zero range end")

    # ---- STREET-11 road names
    names = frozenset({("TESTVILLE", "ELM ST"), ("OTHERVILLE", "20TH")})
    r = run([], [S()], ["STREET-11"], authoritative_names=names)
    c(len(r) == 0, "street-11 passes a name in the list for the segment's community")
    r = run([], [S(NAME="OAK", _NAMEKEY="OAK ST")], ["STREET-11"], authoritative_names=names)
    c(found(r, "STREET-11", "WARNING", "'OAK ST' not in authoritative") == 1, "street-11 warns on a name that is not in the list")
    r = run([], [S(NAME="20TH", TYPE="", _NAMEKEY="20TH")], ["STREET-11"], authoritative_names=names)
    c(len(r) == 0, "street-11 accepts a grid ordinal listed under any community")
    r = run([], [S(NAME="20TH PLACE", TYPE="RD", _NAMEKEY="20TH PLACE RD")], ["STREET-11"], authoritative_names=names)
    c(len(r) == 0, "street-11 strips a type word embedded in NAME before it looks the name up")
    r = run([], [S(NAME="", TYPE="", _NAMEKEY="ELM ST")], ["STREET-11"], authoritative_names=frozenset({"ELM ST"}))
    c(len(r) == 0, "street-11 accepts a plain-name list and a segment named only by _NAMEKEY")
    r = run([], [S(NAME="", TYPE="", _NAMEKEY="XYZ")], ["STREET-11"], authoritative_names=names)
    c(found(r, "STREET-11", text="'XYZ'") == 1, "street-11 shows _NAMEKEY when the name parts are blank")
    r = run([], [S(_NAMEKEY=""), S(NAME="IGNORED", _NAMEKEY="IGNORED ST")], ["STREET-11"],
            authoritative_names=names, street_names_ignored=frozenset({"IGNORED"}))
    c(len(r) == 0, "street-11 skips a blank key and an ignored name")
    r = run([], [S(LCITY=None, RCITY=None)], ["STREET-11"], authoritative_names=names)
    c(found(r, "STREET-11") == 1, "street-11 cannot match a named road that has no community unless the list holds a bare key")
    deg = [S(NAME="ELM", _NAMEKEY="ELM ST"), S(NAME="ELM", TYPE="CT", _NAMEKEY="ELM CT"),
           S(NAME="PINE", TYPE="RD", _NAMEKEY="PINE RD"), S(NAME="US", TYPE="", _NAMEKEY="US 27"),
           S(NAME="DUP", _NAMEKEY="DUP ST"), S(NAME="DUP", _NAMEKEY="DUP ST"), S(_NAMEKEY=""),
           S(NAME="ZZZ", _NAMEKEY="ZZZ ST")]
    r = run([], deg, ["STREET-11"])
    c(found(r, "STREET-11", "INFO", "PINE RD") == 1 and found(r, "STREET-11", "INFO", "ZZZ ST") == 1 and found(r, "STREET-11") == 2,
      "street-11 without a list flags only a unique name that shares no word with another, at INFO")
    r = run([], [S(NAME="IGN", _NAMEKEY="IGN ST"), S(NAME="OTHER", _NAMEKEY="OTHER ST")], ["STREET-11"],
            street_names_ignored=frozenset({"IGN"}))
    c(found(r, "STREET-11", text="IGN") == 0, "street-11 without a list skips an ignored name")

    # ---- STREET-12 gaps
    r = run([], [S(**LEFT_ONLY), S(FROMLEFT=301, TOLEFT=399, **LEFT_ONLY)], ["STREET-12"])
    c(found(r, "STREET-12", "WARNING", "gap 199-301") == 1, "street-12 flags a numbering gap on one street")
    r = run([], [S(**LEFT_ONLY), S(FROMLEFT=201, TOLEFT=299, **LEFT_ONLY)], ["STREET-12"])
    c(len(r) == 0, "street-12 accepts a contiguous run")
    r = run([], [S(FROMLEFT=101, TOLEFT=399, Parity_L="B", **{"FROMRIGHT": 0, "TORIGHT": 0, "Parity_R": "Z"}),
                 S(FROMLEFT=150, TOLEFT=160, Parity_L="B", **{"FROMRIGHT": 0, "TORIGHT": 0, "Parity_R": "Z"}),
                 S(FROMLEFT=501, TOLEFT=599, Parity_L="B", **{"FROMRIGHT": 0, "TORIGHT": 0, "Parity_R": "Z"})],
        ["STREET-12"])
    c(found(r, "STREET-12") == 1, "street-12 reports one gap once when a both-sides segment sits in the odd and even buckets")
    a, b = S(**LEFT_ONLY), S(FROMLEFT=301, TOLEFT=399, **LEFT_ONLY)
    line(a, (0.0, 0.0), (100.0, 0.0))
    line(b, (5000.0, 0.0), (5100.0, 0.0))
    r = run([], [a, b], ["STREET-12"])
    c(len(r) == 0, "street-12 ignores a gap between two same-name stretches more than 600 ft apart")
    a, b = S(**LEFT_ONLY), S(FROMLEFT=301, TOLEFT=399, **LEFT_ONLY)
    line(a, (0.0, 0.0), (100.0, 0.0))
    line(b, (200.0, 0.0), (300.0, 0.0))
    r = run([], [a, b], ["STREET-12"])
    c(found(r, "STREET-12") == 1, "street-12 flags a gap between two stretches that touch and share a community")
    b2 = S(FROMLEFT=301, TOLEFT=399, LCITY="ELSEWHERE", RCITY="", **LEFT_ONLY)
    a2 = S(**LEFT_ONLY)
    line(a2, (0.0, 0.0), (100.0, 0.0))
    line(b2, (200.0, 0.0), (300.0, 0.0))
    r = run([], [a2, b2], ["STREET-12"])
    c(len(r) == 0, "street-12 ignores a gap when the two stretches share no community")

    # ---- STREET-13 ESN and ZIP changes
    r = run([], [S(LESN="100", **LEFT_ONLY), S(FROMLEFT=201, TOLEFT=299, LESN="200", **LEFT_ONLY)], ["STREET-13"])
    c(found(r, "STREET-13", "WARNING", "ESN changes mid-street L-side") == 1, "street-13 flags an ESN change between range-adjacent segments")
    r = run([], [S(LEFTZIP="32000", **LEFT_ONLY), S(FROMLEFT=201, TOLEFT=299, LEFTZIP="32001", **LEFT_ONLY)], ["STREET-13"])
    c(found(r, "STREET-13", "WARNING", "ZIP changes mid-street L-side") == 1, "street-13 flags a ZIP change between range-adjacent segments")
    r = run([], [S(**ZERO)], ["STREET-13"])
    c(len(r) == 0, "street-13 skips an empty side")
    r = run([], [S(FROMLEFT=None, **{"FROMRIGHT": 100, "TORIGHT": 198}), S(LESN="100", **LEFT_ONLY),
                 S(FROMLEFT=301, TOLEFT=399, LESN="300", **LEFT_ONLY)], ["STREET-13"])
    c(len(r) == 0, "street-13 ignores a numbering gap, a missing end and the other side's run")
    r = run([], [S(LESN="100", LCITY="ALPHA", RCITY="ALPHA", **LEFT_ONLY),
                 S(FROMLEFT=201, TOLEFT=299, LESN="200", LCITY="BETA", RCITY="BETA", **LEFT_ONLY)], ["STREET-13"])
    c(len(r) == 0, "street-13 suppresses an ESN change across a confirmed community boundary")
    r = run([], [S(LESN="100", LCITY="", RCITY="", **LEFT_ONLY),
                 S(FROMLEFT=201, TOLEFT=299, LESN="200", LCITY="BETA", RCITY="BETA", **LEFT_ONLY)], ["STREET-13"])
    c(found(r, "STREET-13") == 1, "street-13 keeps an ESN change when one community is unknown  <-- pinned defect")
    r = run([], [S(LESN="", **LEFT_ONLY), S(FROMLEFT=201, TOLEFT=299, LESN="200", **LEFT_ONLY)], ["STREET-13"])
    c(len(r) == 0, "street-13 does not compare a blank ESN")
    r = run([], [S(FROMLEFT=101, TOLEFT=399, LESN="100", **LEFT_ONLY), S(FROMLEFT=111, TOLEFT=121, LESN="100", **LEFT_ONLY),
                 S(FROMLEFT=401, TOLEFT=499, LESN="100", **LEFT_ONLY)], ["STREET-13"])
    c(len(r) == 0, "street-13 measures contiguity from the longest run so far")
