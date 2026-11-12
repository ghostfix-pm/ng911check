"""Self-test: the response-area checks RA-01 to RA-10 and their roll-up."""
from . import response_area_checks as ra
from .st_fix import A, found, run


def _in(cid, key, **kw):
    """An address annotated as sitting inside the polygon `key` of check cid (None: inside none)."""
    row = A(**kw)
    row["_XY"] = (0.0, 0.0)
    row[ra.annotation_key(cid)] = key
    return row


def section(h):
    c = h.check
    spec = ra.AreaSpec("areas.geojson", "KEY", None, None)

    # ---- the comparison
    r = ra.check_ra_08([_in("RA-08", "20", ESN="20"), _in("RA-08", 20.0, ESN="20")])
    c(len(r) == 0, "ra-08 passes a stored ESN equal to the containing key, number or text")
    r = ra.check_ra_08([_in("RA-08", "30", ESN="20")])
    c(len(r) == 1 and r[0].severity == "ERROR" and "ESN '20' != containing ESN area '30'" in r[0].description,
      "ra-08 flags a stored ESN that differs from the containing polygon")
    r = ra.check_ra_08([_in("RA-08", "30", ESN="")])
    c(len(r) == 1 and "ESN is blank but point is inside ESN area '30'" in r[0].description and r[0].severity_id is None,
      "ra-08 flags a blank ESN inside a polygon at ERROR, with no split-off class")
    r = ra.check_ra_08([_in("RA-08", None, ESN="20"), _in("RA-08", None, ESN="")])
    c(len(r) == 1 and "point not inside any ESN area; stored ESN '20'" in r[0].description,
      "ra-08 flags a stored ESN outside every polygon and leaves a blank one alone")
    r = ra.check_ra_03([_in("RA-03", "Z1", ZONE="0"), _in("RA-03", None, ZONE="0"), _in("RA-03", "Z1", ZONE="Z1")])
    c(len(r) == 1 and "ZONE '0' means outside every zone, but point is inside zone 'Z1'" in r[0].description,
      "ra-03 reads the stored value 0 as outside every zone, and flags it inside a zone")
    r = ra.check_ra_01([_in("RA-01", "B2", RA_1="B2", RA_2="B3")])
    c(len(r) == 1 and "RA_2 'B3' != containing response area 'B2'" in r[0].description, "ra-01 reports each stored field on its own")
    r = ra.check_ra_02([_in("RA-02", "B2", RA_3="B9")])
    c(len(r) == 1 and "RA_3 'B9' != containing second response area 'B2'" in r[0].description, "ra-02 compares its own field")
    r = ra.check_ra_10([_in("RA-10", "32000", ZIP_CODE="32001")])
    c(len(r) == 1 and "ZIP_CODE '32001' != containing ZIP boundary '32000'" in r[0].description, "ra-10 compares ZIP_CODE with the ZIP polygon")

    # ---- RA-09 splits the blank class off
    r = ra.check_ra_09([_in("RA-09", "TESTVILLE", CITY=""), _in("RA-09", "TESTVILLE", CITY="OTHER"), _in("RA-09", None, CITY="OTHER")])
    sev = sorted((x.severity, x.severity_id) for x in r)
    c(sev == [("ERROR", None), ("ERROR", None), ("INFO", "RA-09-BLANK")],
      "ra-09 emits a blank CITY inside a postal city at INFO under its own id and a wrong CITY at ERROR  <-- pinned defect")
    r = ra.check_ra_09([_in("RA-09", "TESTVILLE", CITY="")], blank_severity="WARNING")
    c(r[0].severity == "WARNING" and r[0].severity_id == "RA-09-BLANK", "ra-09 takes the blank severity from its argument")

    # ---- the rule
    c(ra.resolve_rule("RA-08") is ra.DEFAULT_RULES["RA-08"], "resolve_rule returns the default rule when no [areas] line gives fields")
    rule = ra.resolve_rule("RA-03", spec._replace(fields=("MYZONE",), sentinel="NONE"))
    c(rule.fields == ("MYZONE",) and rule.sentinel == "NONE", "resolve_rule applies the fields and the sentinel of an [areas] line")
    rule = ra.resolve_rule("RA-03", spec)
    c(rule.fields == ("ZONE",) and rule.sentinel == "0", "resolve_rule keeps the default fields and sentinel when the line gives none")
    c(ra.required_fields("RA-01") == ["RA_1", "RA_2"] and ra.required_fields("RA-01", rule) == ["ZONE"],
      "required_fields lists the address columns a check compares")
    r = ra.check_ra_08([_in("RA-08", "30", MYESN="20")], rule=ra.resolve_rule("RA-08", spec._replace(fields=("MYESN",))))
    c(len(r) == 1, "a check compares the column the rule names, not the default")

    # ---- the engine runs the checks only when the polygon layer is there
    rows = [_in("RA-08", "30", ESN="20")]
    r = run(rows, [], ["RA-08"], area_layers=frozenset({"RA-08"}), area_rules={})
    c(found(r, "RA-08", "ERROR") == 1, "the engine runs ra-08 once its polygon layer is loaded")
    r = run([_in("RA-09", "TESTVILLE")], [], ["RA-09"], area_layers=frozenset({"RA-09"}), area_rules={"RA-09": ra.resolve_rule("RA-09")})
    c(len(r) == 0, "the engine runs ra-09 with the rule it was given and finds a consistent CITY")
    r = run(rows, [], ["RA-08"])
    c(len(r) == 0, "the engine skips ra-08 when no polygon layer is loaded")

    # ---- roll-up
    pts = [_in("RA-08", "B2A", ESN="B2") for _ in range(7)] + [_in("RA-08", "C1", ESN="C0"), _in("RA-08", None, ESN="20")]
    rows = ra.rollup(pts, ["RA-08"])
    c(rows[0]["count"] == 7 and rows[0]["containing"] == "B2A" and rows[0]["stored"] == "B2" and len(rows[0]["sample_oids"]) == 5,
      "rollup groups 7 points of one mismatch into one row and keeps 5 sample rows")
    c([r_["containing"] for r_ in rows[1:]] == ["(outside all)", "C1"],
      "rollup names a point inside no polygon as (outside all)")
    c(ra.rollup([], ["RA-08"]) == [] and ra.rollup(pts, ["RA-08"], sample=2)[0]["sample_oids"] == [pts[0]["_OID"], pts[1]["_OID"]],
      "rollup of nothing is empty and the sample size is a parameter")
    rows = ra.rollup([_in("RA-03", "Z1", MYZONE="Q")], ["RA-03"], rules={"RA-03": ra.resolve_rule("RA-03", spec._replace(fields=("MYZONE",)))})
    c(len(rows) == 1 and rows[0]["field"] == "MYZONE", "rollup reads the rule of each check")
