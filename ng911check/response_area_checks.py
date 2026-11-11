"""response_area point-in-polygon attribute-consistency checks (pure).

Analogous to XLAYER-01 (address ESN vs covering street-side ESN) but using polygon
CONTAINMENT instead of nearest-street-side: each address point's stored response-area or
zone field is compared to the key value of the polygon that geometrically contains the point.

The runner annotates each address row with the key value of the containing polygon (or None
if the point is inside no polygon of that layer) under the key annotation_key(check_id).
The comparison functions then take annotated row dicts and return ErrorRecord findings. They
need no geometry library, so the self-test drives them with hand-made annotations.

A polygon whose key is null or blank is not the same as no polygon: the runner annotates it
with "", and a point inside it is reported once, as its own finding, instead of being compared.
The runner also refuses a layer that no address point falls inside (require_hits).

Comparisons are string-normalized via common._clean, which renders a numeric 4.0 as '4' so a
stored zone '4' matches a polygon key 4.0. rollup() groups the same findings by (containing
key, stored value) so an analyst fixes a whole zone at once instead of thousands of points.

Which address field is compared with which polygon key is a rule (AreaRule). RA-08, RA-09 and
RA-10 default to the ESN, CITY and ZIP_CODE columns. RA-01, RA-02 and RA-03 carry
placeholder field names, because the name of an agency's zone column is local: set the real
column in the [areas] section of the settings file.
"""
from collections import defaultdict, namedtuple

from .model import ErrorRecord, SEVERITY, FAMILY
from .common import _clean
from . import registry

# What the [areas] settings line gives: polygon file, key property, optional stored fields,
# optional sentinel. fields and sentinel are None when the line leaves them to the default.
AreaSpec = namedtuple("AreaSpec", "path key_prop fields sentinel")

AreaRule = namedtuple("AreaRule", "check_id name fields layer_label sentinel")

# A sentinel is a stored value that legitimately means "outside every polygon of this layer".
DEFAULT_RULES = {
    "RA-01": AreaRule("RA-01", "Address response-area fields vs containing response area key",
                      ("RA_1", "RA_2"), "response area", None),
    "RA-02": AreaRule("RA-02", "Address second response-area field vs containing polygon key",
                      ("RA_3",), "second response area", None),
    "RA-03": AreaRule("RA-03", "Address zone field vs containing zone key",
                      ("ZONE",), "zone", "0"),
    "RA-08": AreaRule("RA-08", "Address ESN vs containing ESN polygon",
                      ("ESN",), "ESN area", None),
    "RA-09": AreaRule("RA-09", "Address CITY vs containing postal city polygon",
                      ("CITY",), "postal city", None),
    "RA-10": AreaRule("RA-10", "Address ZIP_CODE vs containing ZIP polygon",
                      ("ZIP_CODE",), "ZIP boundary", None),
}

CHECK_IDS = ("RA-01", "RA-02", "RA-03", "RA-08", "RA-09", "RA-10")

# RA-09's "stored CITY is blank but the point is inside a postal city" class. It is a data
# entry backlog, not a misroute, so it emits at INFO and answers to its own [severity] line.
BLANK_ID = {"RA-09": "RA-09-BLANK"}

# A polygon whose key is null or blank cannot say what a point inside it should hold. The
# point is its own finding at ERROR, named by this suffix and by NULL_KEY_LABEL in the roll-up,
# and no stored value is compared with it. Comparing would call a blank value "consistent".
NULL_KEY_SUFFIX = ": polygon key is null"
NULL_KEY_LABEL = "(null key)"


def annotation_key(check_id):
    """The row key the runner fills with the containing polygon's key for this check."""
    return "_area_" + check_id


def resolve_rule(check_id, spec=None):
    """The default rule for check_id with any [areas] override applied."""
    rule = DEFAULT_RULES[check_id]
    if spec is None:
        return rule
    return rule._replace(fields=spec.fields or rule.fields,
                         sentinel=rule.sentinel if spec.sentinel is None else spec.sentinel)


def require_hits(check_id, addresses, path):
    """The number of address points that fall inside any polygon of this check's layer.

    Raises ValueError when it is zero. With no hit every point reads as "outside", and a
    blank stored value cannot be contradicted there, so a layer in the wrong coordinate system
    would give zero findings and read as clean."""
    annot = annotation_key(check_id)
    hits = sum(1 for a in addresses if a.get(annot) is not None)
    if hits:
        return hits
    placed = sum(1 for a in addresses if a.get("_XY") is not None)
    raise ValueError("%s: none of the %d address point(s) with a position falls inside a "
                     "polygon of %s, so the check judged nothing and a result with no finding "
                     "would read as clean. Check that --units and the coordinate system of the polygon "
                     "file match the address file, and that the polygon file is the right "
                     "layer." % (check_id, placed, path))


def required_fields(check_id, rule=None):
    """The address-side stored field(s) this check compares against the containing polygon.

    The runner asserts these exist on the address layer before running the check, so a dropped
    or renamed field fails loudly instead of collapsing a.get() to None into a false 'blank but
    inside' finding for every contained point."""
    return list((rule or DEFAULT_RULES[check_id]).fields)


def _describe(field, stored, poly_val, inside, layer_label, sentinel):
    """One comparison: return (description, is_blank_inside), or (None, False) when the stored
    value is consistent with (or cannot be contradicted by) the containing polygon.

    stored/poly_val are already normalized (upper, _clean). inside is True when the point
    is inside a polygon of this layer (_iter_findings never passes a null-keyed polygon here:
    it reports that class itself). sentinel is a stored value that
    legitimately means 'outside every polygon of this layer'; None disables it.

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


def _iter_findings(addresses, check_id, rule=None):
    """Yield (row, field, stored, containing_key_or_None, description, is_blank_inside,
    is_null_key) for each finding of this check. Shared by the ErrorRecord builders and
    rollup() so both use one comparison.

    A point inside a polygon whose key is null or blank yields ONE finding for the row, with
    is_null_key True and the fields joined in `field`: no stored value is compared."""
    rule = rule or DEFAULT_RULES[check_id]
    annot = annotation_key(check_id)
    for a in addresses:
        poly_key = a.get(annot)
        inside = poly_key is not None
        poly_val = _clean(poly_key).upper()
        if inside and poly_val == "":
            yield (a, ", ".join(rule.fields), "", NULL_KEY_LABEL,
                   "point is inside a polygon of the %s layer whose key is null or blank, so %s cannot be "
                   "checked" % (rule.layer_label, ", ".join(rule.fields)), False, True)
            continue
        for field in rule.fields:
            stored = _clean(a.get(field)).upper()
            desc, blank = _describe(field, stored, poly_val, inside, rule.layer_label,
                                    rule.sentinel)
            if desc is not None:
                yield a, field, stored, (poly_val if inside else None), desc, blank, False


def _check(addresses, check_id, severity=SEVERITY.ERROR, blank_severity=None, rule=None):
    """Build ErrorRecords for one check.

    blank_severity, when given, is used for the "stored field is blank but the point is inside
    a polygon" class instead of severity, and those records carry the check's BLANK_ID so the
    engine applies the matching [severity] line to them. None (the default for every check but
    RA-09) means the whole check emits at one severity."""
    rule = rule or DEFAULT_RULES[check_id]
    out = []
    for a, _field, _stored, _poly, desc, blank, null_key in _iter_findings(addresses, check_id,
                                                                           rule):
        tiered = blank and blank_severity is not None
        out.append(ErrorRecord(check_id, rule.name + (NULL_KEY_SUFFIX if null_key else ""),
                               FAMILY.AREA,
                               blank_severity if tiered else severity, "address",
                               a["_OID"], a.get("Site_NGUID", "") or "", desc, a.get("_XY"),
                               BLANK_ID[check_id] if tiered else None))
    return out


def check_ra_01(addresses, severity=SEVERITY.ERROR, rule=None):
    """RA-01: each stored response-area field vs the containing response area key (every
    field reported separately)."""
    return _check(addresses, "RA-01", severity, rule=rule)


def check_ra_02(addresses, severity=SEVERITY.ERROR, rule=None):
    """RA-02: the second response-area field vs the containing polygon key."""
    return _check(addresses, "RA-02", severity, rule=rule)


def check_ra_03(addresses, severity=SEVERITY.ERROR, rule=None):
    """RA-03: the stored zone vs the containing zone key ('0' = outside every zone)."""
    return _check(addresses, "RA-03", severity, rule=rule)


def check_ra_08(addresses, severity=SEVERITY.ERROR, rule=None):
    """RA-08: address ESN vs the containing ESN polygon.

    The polygon ESN may be a number and the address ESN a string; _clean renders both to
    bare digits ('20'), so the comparison is on the value, not the storage type."""
    return _check(addresses, "RA-08", severity, rule=rule)


def check_ra_09(addresses, severity=SEVERITY.ERROR, blank_severity=SEVERITY.INFO, rule=None):
    """RA-09: address CITY vs the containing postal city polygon.

    Two-tier: "CITY is blank but the point is inside postal city X" is usually a data-entry
    backlog, far larger than the real disagreements, and emits at blank_severity, INFO by
    default. A stored CITY that DISAGREES with the containing postal city, or that sits outside
    every postal city, stays at severity: a wrong CITY feeds MSAG and ALI matching, so demoting
    the whole check to bury the blanks would bury those too."""
    return _check(addresses, "RA-09", severity, blank_severity=blank_severity, rule=rule)


def check_ra_10(addresses, severity=SEVERITY.ERROR, rule=None):
    """RA-10: address ZIP_CODE vs the containing ZIP polygon.

    The point-in-polygon companion to XLAYER-06, which can only compare an address ZIP to the
    ZIP recorded on the covering street SIDE: this validates it against the ZIP boundary
    itself, so a wrong ZIP is caught even where the centerline attribution agrees with it."""
    return _check(addresses, "RA-10", severity, rule=rule)


def rollup(addresses, check_ids=CHECK_IDS, sample=5, rules=None):
    """Collapse point-level findings into the distinct boundary/stamp mismatches driving
    them: group by (check_id, field, containing key, stored value) -> {count, sample_oids}.

    This is the actionable 'fix a whole zone at once' view: one row saying 1,240 points inside
    response area 'B2A' are stamped 'B2'. Sorted by count desc (ties by key), so the systematic
    drift sits at the top and one-off boundary or moved points fall out at the bottom. Returns
    a list of dicts."""
    rules = rules or {}
    groups = defaultdict(lambda: {"count": 0, "oids": []})
    for cid in check_ids:
        for a, field, stored, poly_val, _desc, _blank, _null in _iter_findings(
                addresses, cid, rules.get(cid)):
            key = (cid, field, poly_val if poly_val is not None else "(outside all)", stored)
            g = groups[key]
            g["count"] += 1
            if len(g["oids"]) < sample:
                g["oids"].append(a["_OID"])
    out = [{"check_id": k[0], "field": k[1], "containing": k[2], "stored": k[3],
            "count": v["count"], "sample_oids": v["oids"]} for k, v in groups.items()]
    out.sort(key=lambda r: (-r["count"], r["check_id"], r["field"], r["containing"],
                            r["stored"]))
    return out


_SUMMARY = {
    "RA-01": "Flag an address whose response-area field disagrees with the area it sits in.",
    "RA-02": "Flag an address whose second response-area field disagrees with its area.",
    "RA-03": "Flag an address whose zone field disagrees with the zone it sits in.",
    "RA-08": "Flag an address whose ESN disagrees with the ESN polygon it sits in.",
    "RA-09": "Flag an address whose CITY disagrees with the postal city it sits in.",
    "RA-10": "Flag an address whose ZIP_CODE disagrees with the ZIP polygon it sits in.",
}


def _register(check_id):
    def run(addresses, streets, ctx):
        rule = ctx.area_rules.get(check_id)
        if check_id == "RA-09":
            return check_ra_09(addresses, rule=rule)
        return _check(addresses, check_id, rule=rule)
    run.__name__ = "run_" + check_id.lower().replace("-", "_")
    registry.check(
        id=check_id, family=FAMILY.AREA, severity=SEVERITY.ERROR, priority="v1",
        target="address", default_on=False, emits=(SEVERITY.ERROR, SEVERITY.INFO) if check_id == "RA-09"
        else (SEVERITY.ERROR,),
        summary=_SUMMARY[check_id], fields=DEFAULT_RULES[check_id].fields + ("Site_NGUID",),
        requires=("area:" + check_id,))(run)


for _cid in CHECK_IDS:
    _register(_cid)
