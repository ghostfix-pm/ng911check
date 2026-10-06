"""response_area point-in-polygon attribute-consistency checks (PURE, no arcpy).

Analogous to XLAYER-01 (address ESN vs covering street-side ESN) but using polygon
CONTAINMENT instead of nearest-street-side: each address point's stored response-area /
zone field is compared to the key value of the response-area POLYGON that geometrically
contains the point.

Each address row dict is pre-annotated by the ResponseAreaChecks.pyt tool with the key
value of the containing polygon (or None if the point is inside no polygon of that layer)
under a fixed key:

    row["_ra_key"]   -> ResponseArea.RA_KEY   (RA-01: vs RA_MCFR and RA_OFR)
    row["_ra_mcso"]  -> RA_MCSO.RA_Code       (RA-02: vs RA_MCSO)
    row["_pd_id"]   -> PD_Zones.ID           (RA-03: vs PD_ZONE)
    row["_esn"]      -> NEW_ESN.ESN            (RA-08: vs ESN)
    row["_city"]     -> ZIPCODE_BOUNDARIES.PO_NAME (RA-09: vs CITY)

Comparisons are string-normalized via common._clean, which renders an arcpy Double 4.0
as '4' so PD_ZONE '4' matches PD_Zones.ID 4.0. These functions take annotated row dicts
and return legacy_checks.model.ErrorRecord findings (severity is configurable — the tool
passes the [severity] override from validation_settings.ini), so they are unit-testable
without arcpy. rollup() groups the same findings by (containing key, stored value) so the
analyst fixes a whole zone at once instead of thousands of individual points.
"""
from collections import defaultdict

from .model import ErrorRecord, SEVERITY
from .common import _clean

FAMILY_RA = "response_area"

# Fixed annotation keys (see module docstring). The .pyt tool sets these; the comparison
# functions read them.
KEY_RA_KEY = "_ra_key"
KEY_RA_MCSO = "_ra_mcso"
KEY_PD_ID = "_pd_id"
KEY_ESN = "_esn"
KEY_CITY = "_city"
KEY_ZIP = "_zip"

# check_id -> (check_name, [(stored_field, annotation_key)], layer_label, outside_sentinel)
_CHECKS = {
    "RA-01": ("Address RA_MCFR/RA_OFR vs containing ResponseArea RA_KEY",
              [("RA_MCFR", KEY_RA_KEY), ("RA_OFR", KEY_RA_KEY)], "ResponseArea", None),
    "RA-02": ("Address RA_MCSO vs containing RA_MCSO polygon RA_Code",
              [("RA_MCSO", KEY_RA_MCSO)], "RA_MCSO", None),
    "RA-03": ("Address PD_ZONE vs containing PD_Zones ID",
              [("PD_ZONE", KEY_PD_ID)], "PD zone", "0"),
    "RA-08": ("Address ESN vs containing NEW_ESN polygon ESN",
              [("ESN", KEY_ESN)], "ESN area", None),
    "RA-09": ("Address CITY vs containing ZIP boundary postal city PO_NAME",
              [("CITY", KEY_CITY)], "postal city", None),
    "RA-10": ("Address ZIP_CODE vs containing ZIPCODE_BOUNDARIES polygon ZIP",
              [("ZIP_CODE", KEY_ZIP)], "ZIP boundary", None),
}

CHECK_IDS = ("RA-01", "RA-02", "RA-03", "RA-08", "RA-09", "RA-10")


def required_fields(check_id):
    """The address-side stored field(s) this check compares against the containing polygon.

    The .pyt asserts these exist on the address FC before running the check, so a dropped or
    renamed field fails loudly (warn-and-skip) instead of collapsing a.get()->None into a
    false 'blank but inside' finding for every contained point."""
    return [field for field, _annot in _CHECKS[check_id][1]]


def _describe(field, stored, poly_val, inside, layer_label, sentinel):
    """One comparison: return (description, is_blank_inside), or (None, False) when the stored
    value is consistent with (or cannot be contradicted by) the containing polygon.

    stored/poly_val are already normalized (upper, _clean). inside is True when the point
    is inside a polygon of this layer (poly_val may still be "" for a null-keyed polygon,
    distinct from inside=False for 'inside no polygon'). sentinel is a stored value that
    legitimately means 'outside every polygon of this layer' (PD_ZONE '0'); None disables it.

    is_blank_inside marks the "field is empty but the point IS inside a polygon" class. It is
    returned here rather than re-derived by callers so the classification and the wording can
    never disagree: RA-09 tiers that class to its own severity (see check_ra_09).
    """
    if inside:
        if sentinel is not None and stored == sentinel:
            return ("%s '%s' means outside every %s, but point is inside %s '%s'"
                    % (field, stored, layer_label, layer_label, poly_val), False)
        if stored == "":
            return ("%s is blank but point is inside %s '%s'"
                    % (field, layer_label, poly_val), True)
        if stored != poly_val:
            return ("%s '%s' != containing %s '%s'"
                    % (field, stored, layer_label, poly_val), False)
        return None, False
    # Point is inside NO polygon of this layer. A blank stored value (or the sentinel)
    # cannot be contradicted; any other stored value is a finding.
    if stored == "" or (sentinel is not None and stored == sentinel):
        return None, False
    return "point not inside any %s; stored %s '%s'" % (layer_label, field, stored), False


def _iter_findings(addresses, check_id):
    """Yield (row, field, stored, containing_key_or_None, description, is_blank_inside) for
    each finding of this check. Shared by the ErrorRecord builders and rollup() so both use one
    comparison."""
    _name, fields, layer_label, sentinel = _CHECKS[check_id]
    for a in addresses:
        for field, annot in fields:
            poly_key = a.get(annot)
            inside = poly_key is not None
            stored = _clean(a.get(field)).upper()
            poly_val = _clean(poly_key).upper()
            desc, blank = _describe(field, stored, poly_val, inside, layer_label, sentinel)
            if desc is not None:
                yield a, field, stored, (poly_val if inside else None), desc, blank


def _check(addresses, check_id, severity=SEVERITY.ERROR, blank_severity=None):
    """Build ErrorRecords for one check.

    blank_severity, when given, is used for the "stored field is blank but the point is inside
    a polygon" class instead of severity; None (the default for every check but RA-09) means
    the whole check emits at one severity."""
    name = _CHECKS[check_id][0]
    out = []
    for a, _field, _stored, _poly, desc, blank in _iter_findings(addresses, check_id):
        sev = blank_severity if (blank and blank_severity is not None) else severity
        out.append(ErrorRecord(check_id, name, FAMILY_RA, sev, "address",
                               a["_OID"], a.get("Site_NGUID", "") or "", desc, a.get("_XY")))
    return out


def check_ra_01(addresses, severity=SEVERITY.ERROR):
    """RA-01: address RA_MCFR and RA_OFR each vs containing ResponseArea.RA_KEY (both
    reported separately)."""
    return _check(addresses, "RA-01", severity)


def check_ra_02(addresses, severity=SEVERITY.ERROR):
    """RA-02: address RA_MCSO vs containing RA_MCSO polygon RA_Code."""
    return _check(addresses, "RA-02", severity)


def check_ra_03(addresses, severity=SEVERITY.ERROR):
    """RA-03: address PD_ZONE vs containing PD_Zones.ID ('0' = outside Riverton)."""
    return _check(addresses, "RA-03", severity)


def check_ra_08(addresses, severity=SEVERITY.ERROR):
    """RA-08: address ESN vs containing NEW_ESN polygon ESN.

    The polygon ESN is a SmallInteger and the address ESN a 5-char string; _clean renders
    both to bare digits ('20'), so the comparison is on the value, not the storage type."""
    return _check(addresses, "RA-08", severity)


def check_ra_09(addresses, severity=SEVERITY.ERROR, blank_severity=SEVERITY.INFO):
    """RA-09: address CITY vs the containing ZIP boundary's PO_NAME (postal city name).

    Read Postal_Cities.CITY until 2026-08-06, when the 911 team retired that layer for
    ZIPCODE_BOUNDARIES, which carries the postal city as PO_NAME alongside the code.

    Two-tier, like RA-05's enclaves: "CITY is blank but the point is inside postal city X" is a
    data-entry backlog (measured 2026-07-30, 50,432 of the 50,695 county-wide findings — ~14% of
    all address points carry no CITY at all) and emits at blank_severity, INFO by default. A
    stored CITY that DISAGREES with the containing postal city, or that sits outside every
    postal city, stays at severity: only ~260 findings county-wide, and a wrong CITY feeds
    MSAG/ALI matching, so demoting the whole check to bury the blanks would bury those too."""
    return _check(addresses, "RA-09", severity, blank_severity=blank_severity)


def check_ra_10(addresses, severity=SEVERITY.ERROR):
    """RA-10: address ZIP_CODE vs the containing ZIPCODE_BOUNDARIES polygon's ZIP.

    The point-in-polygon companion to XLAYER-06, which can only compare an address ZIP to the
    ZIP recorded on the covering street SIDE: this validates it against the authoritative ZIP
    boundary itself, so a wrong ZIP is caught even where the centerline attribution agrees with
    it. ZIP is a 5-digit code on both sides and _clean renders either storage type to bare
    digits, so the comparison is on the value."""
    return _check(addresses, "RA-10", severity)


def rollup(addresses, check_ids=CHECK_IDS, sample=5):
    """Collapse point-level findings into the distinct boundary/stamp mismatches driving
    them: group by (check_id, field, containing key, stored value) -> {count, sample_oids}.

    This is the actionable 'fix a whole zone at once' view — e.g. one row saying 1,240
    points inside ResponseArea 'MP7B2A' are stamped 'MP7B2'. Sorted by count desc, so the
    systematic drift (big groups) sits at the top and one-off boundary/moved points fall out
    at the bottom. Returns a list of dicts."""
    groups = defaultdict(lambda: {"count": 0, "oids": []})
    for cid in check_ids:
        for a, field, stored, poly_val, _desc, _blank in _iter_findings(addresses, cid):
            key = (cid, field, poly_val if poly_val is not None else "(outside all)", stored)
            g = groups[key]
            g["count"] += 1
            if len(g["oids"]) < sample:
                g["oids"].append(a["_OID"])
    out = [{"check_id": k[0], "field": k[1], "containing": k[2], "stored": k[3],
            "count": v["count"], "sample_oids": v["oids"]} for k, v in groups.items()]
    out.sort(key=lambda r: -r["count"])
    return out
