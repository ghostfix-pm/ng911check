"""Synthetic fixtures for the self-test. Nothing here names a real place or agency.

A() and S() build a clean address and a clean street segment, then apply the overrides. Every
row is also kept in POOL_A and POOL_S, so the catalog test can run every check once over all of
the rows the other tests made. reset() empties the pools at the start of a run.
"""
from . import engine
from .common import addr_name_key, street_name_key
from .geometry import Polyline

AG = "agency.example.org"

POOL_A = []
POOL_S = []
GEOMS = {}
_NEXT = {"a": 0, "s": 0}


def reset():
    del POOL_A[:]
    del POOL_S[:]
    GEOMS.clear()
    _NEXT["a"] = 0
    _NEXT["s"] = 0


def A(**kw):
    """A clean address point on ELM ST, with the overrides applied."""
    _NEXT["a"] += 1
    row = {
        "_OID": _NEXT["a"], "_XY": None,
        "Add_Number": 101, "PREFIX": "", "STREET_NA": "ELM", "TYPE": "ST", "SUFFIX": "",
        "UNIT": "", "BLDG": "", "ADDRESS": "101 ELM ST", "HOUSE_NU": "101",
        "CITY": "TESTVILLE", "INC_MUNI": "TESTVILLE", "STATE": "FL", "COUNTY": "EXAMPLE",
        "Country": "US", "ZIP_CODE": "32000", "ESN": "100", "STATUS": "ACTIVE",
        "Site_NGUID": "ADR%d@%s" % (_NEXT["a"], AG), "DiscrpAgID": AG, "COMPARE": "ELM ST",
        "St_Name": "ELM", "St_PreDir": "", "St_PosTyp": "STREET", "St_PreTyp": "",
        "St_PreMod": "", "St_PosMod": "", "St_PreSep": "",
    }
    row.update(kw)
    if "_NAMEKEY" not in kw:
        row["_NAMEKEY"] = addr_name_key(row)
    POOL_A.append(row)
    return row


def S(**kw):
    """A clean street segment: ELM ST, odd numbers on the left, even on the right."""
    _NEXT["s"] += 1
    row = {
        "_OID": _NEXT["s"], "_XY": None,
        "SEGMENT_ID": _NEXT["s"], "RCL_NGUID": "RCL%d@%s" % (_NEXT["s"], AG),
        "NAME": "ELM", "PREFIX": "", "TYPE": "ST", "SUFFIX": "",
        "FROMLEFT": 101, "TOLEFT": 199, "FROMRIGHT": 100, "TORIGHT": 198,
        "Parity_L": "O", "Parity_R": "E", "ONEWAY": "B",
        "LCITY": "TESTVILLE", "RCITY": "TESTVILLE", "LESN": "100", "RESN": "100",
        "LEFTZIP": "32000", "RIGHTZIP": "32000", "State_L": "FL", "State_R": "FL",
        "County_L": "EXAMPLE", "County_R": "EXAMPLE", "IncMuni_L": "TESTVILLE",
        "IncMuni_R": "TESTVILLE", "St_Name": "ELM", "St_PreDir": "", "St_PosTyp": "STREET",
        "St_PreTyp": "", "St_PreMod": "", "St_PosMod": "", "St_PreSep": "",
        "DiscrpAgID": AG, "COMPARE": "ELM ST",
    }
    row.update(kw)
    if "_NAMEKEY" not in kw:
        row["_NAMEKEY"] = street_name_key(row)
    POOL_S.append(row)
    return row


def line(row, *points):
    """Attach a polyline (in feet) to a street row and give the row its midpoint."""
    geom = Polyline([list(points)])
    GEOMS[row["_OID"]] = geom
    row["_XY"] = geom.midpoint()
    return geom


def geom_provider(layer, oid):
    return GEOMS.get(oid) if layer == "street" else None


def ctx_for(addresses, streets, **kw):
    """A Context over the rows, built the way the runner builds one."""
    return engine.build_context(addresses, streets, **kw)


def run(addresses, streets, ids=None, **kw):
    """Records from the checks named in ids (or all default-on checks) over the rows."""
    ctx = ctx_for(addresses, streets, **kw)
    return engine.run_checks(addresses, streets, ctx, ids=ids, include_optional=ids is None)


def found(records, check_id, severity=None, text="", layer=None, oid=None):
    """How many records match. `text` is a substring of the description."""
    return sum(1 for r in records
               if r.check_id == check_id
               and (severity is None or r.severity == severity)
               and text in r.description
               and (layer is None or r.source_layer == layer)
               and (oid is None or r.source_oid == oid))
