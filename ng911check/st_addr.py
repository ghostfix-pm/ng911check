"""Self-test: the address_attr checks (ADDR-01 to ADDR-08)."""
from .st_fix import A, AG, S, found, run


def section(h):
    c = h.check

    # ---- ADDR-01 required fields
    r = run([A(STATE="")], [], ["ADDR-01"])
    c(found(r, "ADDR-01", "ERROR", "STATE") == 1, "addr-01 flags a blank STATE as an ERROR")
    r = run([A(STREET_NA="", St_Name="", _NAMEKEY="ELM ST")], [], ["ADDR-01"])
    c(found(r, "ADDR-01", text="STREET_NA/St_Name") == 1,
      "addr-01 flags a point with neither STREET_NA nor St_Name")
    r = run([A(STREET_NA="", St_Name="ELM")], [], ["ADDR-01"])
    c(len(r) == 0, "addr-01 accepts St_Name when STREET_NA is blank")
    r = run([A(CITY="", INC_MUNI="")], [], ["ADDR-01"])
    c(found(r, "ADDR-01", text="CITY/INC_MUNI") == 1, "addr-01 flags a point with neither CITY nor INC_MUNI")
    r = run([A(CITY="", INC_MUNI="TESTVILLE")], [], ["ADDR-01"])
    c(len(r) == 0, "addr-01 accepts INC_MUNI when CITY is blank")
    r = run([A(Add_Number=0, STATE="")], [], ["ADDR-01"])
    c(len(r) == 0, "addr-01 leaves a placeholder point to addr-08")
    r = run([A()], [], ["ADDR-01"])
    c(len(r) == 0, "addr-01 passes a complete point")

    # ---- ADDR-02 duplicates
    r = run([A(), A()], [], ["ADDR-02"])
    c(found(r, "ADDR-02", "ERROR") == 2, "addr-02 flags two points with one full address and one ADDRESS text")
    r = run([A(), A(ADDRESS="101 ELM ST REAR")], [], ["ADDR-02"])
    c(len(r) == 0, "addr-02 keeps two ADDRESS texts apart when no unit or building is set")
    r = run([A(), A(ADDRESS="")], [], ["ADDR-02"])
    c(found(r, "ADDR-02") == 2, "addr-02 joins one blank ADDRESS to the single other sub-cluster")
    r = run([A(ADDRESS=""), A(ADDRESS="")], [], ["ADDR-02"])
    c(found(r, "ADDR-02") == 2, "addr-02 flags two blank ADDRESS texts")
    r = run([A(), A(ADDRESS="101 ELM ST REAR"), A(ADDRESS="")], [], ["ADDR-02"])
    c(len(r) == 0, "addr-02 does not flag a lone blank ADDRESS beside two different sub-clusters")
    r = run([A(UNIT="2", ADDRESS="x"), A(UNIT="2", ADDRESS="y")], [], ["ADDR-02"])
    c(found(r, "ADDR-02") == 2, "addr-02 flags two points with one UNIT even when ADDRESS differs")
    r = run([A(), A(CITY="OTHERVILLE")], [], ["ADDR-02"])
    c(len(r) == 0, "addr-02 treats one number in two cities as two addresses")
    r = run([A(Add_Number=0), A(Add_Number=0)], [], ["ADDR-02"])
    c(len(r) == 0, "addr-02 skips placeholder points")

    # ---- ADDR-03 ADDRESS text
    r = run([A(ADDRESS="999 OAK AVE")], [], ["ADDR-03"])
    c(found(r, "ADDR-03", "WARNING", "999 OAK AVE") == 1, "addr-03 flags an ADDRESS that is not the joined parts")
    r = run([A(BLDG="BLDG 23", UNIT="UNIT BLDG 23", ADDRESS="101 ELM ST BLDG 23")], [], ["ADDR-03"])
    c(len(r) == 0, "addr-03 drops a UNIT that only repeats the BLDG")
    r = run([A(BLDG="BLDG 23", UNIT="4", ADDRESS="101 ELM ST BLDG 23 4")], [], ["ADDR-03"])
    c(len(r) == 0, "addr-03 keeps a UNIT that differs from the BLDG")
    r = run([A(SUFFIX="N", ADDRESS="101 ELM ST N")], [], ["ADDR-03"])
    c(len(r) == 0, "addr-03 includes the SUFFIX in the expected text")
    r = run([A(Add_Number=0, ADDRESS="zzz")], [], ["ADDR-03"])
    c(len(r) == 0, "addr-03 skips placeholder points")

    # ---- ADDR-04 HOUSE_NU
    r = run([A(HOUSE_NU="102")], [], ["ADDR-04"])
    c(found(r, "ADDR-04", "WARNING", "'102' != Add_Number '101'") == 1, "addr-04 flags a HOUSE_NU that differs from Add_Number")
    r = run([A(HOUSE_NU=101.0)], [], ["ADDR-04"])
    c(len(r) == 0, "addr-04 reads a numeric 101.0 as 101")
    r = run([A(Add_Number=0, HOUSE_NU="5")], [], ["ADDR-04"])
    c(len(r) == 0, "addr-04 skips placeholder points")

    # ---- ADDR-05 domains and bounds
    r = run([A(STATUS="RETIRED")], [], ["ADDR-05"])
    c(found(r, "ADDR-05", "WARNING", "STATUS") == 1, "addr-05 warns on a STATUS that is not ACTIVE")
    r = run([A(STATUS="")], [], ["ADDR-05"])
    c(len(r) == 0, "addr-05 leaves a blank STATUS to addr-01")
    for esn in ("ABC", "0", "123456"):
        r = run([A(ESN=esn)], [], ["ADDR-05"])
        c(found(r, "ADDR-05", "ERROR", "ESN") == 1, "addr-05 flags ESN %r as an ERROR" % esn)
    r = run([A(ESN="")], [], ["ADDR-05"])
    c(len(r) == 0, "addr-05 leaves a blank ESN to addr-01")
    r = run([A(ZIP_CODE="1234")], [], ["ADDR-05"])
    c(found(r, "ADDR-05", "ERROR", "ZIP_CODE") == 1, "addr-05 flags a ZIP_CODE that is not 5 digits")
    r = run([A(Add_Number=100000, HOUSE_NU="100000")], [], ["ADDR-05"])
    c(found(r, "ADDR-05", "ERROR", "out of bounds (0-99999)") == 1, "addr-05 flags an Add_Number over max_address")
    r = run([A(Add_Number=50)], [], ["ADDR-05"], min_address=100)
    c(found(r, "ADDR-05", "ERROR", "out of bounds (100-99999)") == 1, "addr-05 reads min_address from the context")
    r = run([A(PREFIX="XX")], [], ["ADDR-05"])
    c(found(r, "ADDR-05", "WARNING", "PREFIX") == 1, "addr-05 warns on a PREFIX outside the directional domain")
    r = run([A(PREFIX="N", TYPE="STREET")], [], ["ADDR-05"])
    c(len(r) == 0, "addr-05 accepts an abbreviated directional and a spelled-out type")
    r = run([A(TYPE="ZZZ")], [], ["ADDR-05"])
    c(found(r, "ADDR-05", "WARNING", "TYPE") == 1, "addr-05 warns on a TYPE outside the road-type domain")
    r = run([A(Add_Number=0, ESN="ABC")], [], ["ADDR-05"])
    c(len(r) == 0, "addr-05 skips placeholder points")

    # ---- ADDR-06 NGUID
    r = run([A(Site_NGUID="")], [], ["ADDR-06"])
    c(len(r) == 0, "addr-06 leaves a blank Site_NGUID to addr-01")
    r = run([A(Site_NGUID="NOAT")], [], ["ADDR-06"])
    c(found(r, "ADDR-06", "ERROR", "not '<localid>@<authority>'") == 1, "addr-06 flags a Site_NGUID with no @")
    r = run([A(Site_NGUID="@" + AG)], [], ["ADDR-06"])
    c(found(r, "ADDR-06", "ERROR", "not '<localid>@") == 1, "addr-06 flags a Site_NGUID with an empty localid")
    r = run([A(Site_NGUID="A B@" + AG)], [], ["ADDR-06"])
    c(found(r, "ADDR-06", "ERROR", "invalid characters") == 1, "addr-06 flags a localid with a space")
    r = run([A(Site_NGUID="X1@other.example.net")], [], ["ADDR-06"])
    c(found(r, "ADDR-06", "ERROR", "authority 'other.example.net' != expected") == 1, "addr-06 flags another agency's authority")
    r = run([A(Site_NGUID="X1@" + AG, DiscrpAgID="other.example.net")], [], ["ADDR-06"])
    c(found(r, "ADDR-06", "ERROR", "DiscrpAgID 'other.example.net' != expected") == 1, "addr-06 flags a DiscrpAgID that differs from the authority")
    r = run([A(Site_NGUID="X1@" + AG.upper(), DiscrpAgID="")], [], ["ADDR-06"])
    c(len(r) == 0, "addr-06 compares the authority without regard to case and skips a blank DiscrpAgID")
    r = run([A(Site_NGUID="X1@" + AG)], [], ["ADDR-06"], expected_agid="")
    c(found(r, "ADDR-06") == 1, "addr-06 never matches an empty expected agency  <-- pinned defect")

    # ---- ADDR-07 whitespace and prohibited characters
    r = run([A(CITY=" TESTVILLE")], [S(NAME="ELM ")], ["ADDR-07"])
    c(found(r, "ADDR-07", "WARNING", "CITY", layer="address") == 1 and found(r, "ADDR-07", text="NAME", layer="street") == 1,
      "addr-07 flags surrounding whitespace on an address field and on a street field")
    r = run([A(STREET_NA="EL#M")], [], ["ADDR-07"])
    c(found(r, "ADDR-07", text="prohibited char(s) #") == 1, "addr-07 flags a prohibited character")
    r = run([A(UNIT="NULL")], [], ["ADDR-07"])
    c(found(r, "ADDR-07", text="literal 'NULL'") == 1, "addr-07 flags the literal text NULL")
    r = run([A(CITY="   ", UNIT=None, PREFIX=None)], [], ["ADDR-07"])
    c(len(r) == 0, "addr-07 ignores a blank-only value and a missing value")

    # ---- ADDR-08 placeholders
    r = run([A(Add_Number=0, STREET_NA="", _NAMEKEY=""), A(Add_Number=0), A(STREET_NA="", _NAMEKEY=""),
             A(Add_Number="x", STREET_NA="", _NAMEKEY=""), A(Add_Number=None)], [], ["ADDR-08"])
    c(found(r, "ADDR-08", "WARNING", "missing house number and street name") == 2, "addr-08 reports a point with no usable number and no name")
    c(found(r, "ADDR-08", text="missing house number (street name") == 2, "addr-08 reports a point with a name but no usable number")
    c(found(r, "ADDR-08", text="missing street name (Add_Number=101)") == 1, "addr-08 reports a point with a number but no name")
    r = run([A()], [], ["ADDR-08"])
    c(len(r) == 0, "addr-08 passes an addressable point")
