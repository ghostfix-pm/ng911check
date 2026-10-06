"""Editable calibration settings (validation_settings.ini).

The 911 GIS analyst edits the .ini; code reads it. Strict validation: an unknown
key, bad value, or unknown check id fails loud with an actionable message (a silent
typo must never weaken QC). A missing key falls back to the built-in default, so a
partial or absent file still loads and behaves as today.
"""
import os
import configparser

from . import registry

DEFAULT_FILE = "validation_settings.ini"
_SECTIONS = {"thresholds", "agency", "names", "checks", "severity"}
_SEVERITIES = {"ERROR", "WARNING", "INFO"}
# Checks that run outside the engine registry (ResponseAreaChecks.pyt) but are still
# valid [severity]/[checks] ids so the analyst can calibrate them from the same .ini.
_EXTRA_CHECK_IDS = {"RA-01", "RA-02", "RA-03",           # point-in-polygon attribute checks
                    "RA-08", "RA-09", "RA-10",           # ESN / postal-city / ZIP containment
                    "RA-04", "RA-05", "RA-06", "RA-07",  # boundary polygon topology checks
                    # RA-05's designed-enclave findings (a hole drawn into a SINGLE polygon)
                    # carry their own severity so they can be raised or demoted apart from the
                    # real coverage gaps — on PD_Zones they are 25 of the 28 RA-05 findings.
                    "RA-05-ENCLAVE",
                    # RA-09's blank-CITY findings, same reason and a far more lopsided split:
                    # ~99.5% of its county-wide findings are "CITY is blank but the point is
                    # inside postal city X" (a data-entry backlog) — measured 2026-07-30, 50,432
                    # of 50,695 — and only ~260 are genuine disagreements that misroute.
                    # Demoting RA-09 itself would bury those.
                    "RA-09-BLANK",
                    # RA-06's endpoint-overshoot findings, same two-tier reason: 166 of the 309
                    # ResponseArea crossings have under 25 ft in the smaller area and 156 (94%)
                    # of those end at a road intersection (measured 2026-08-03,
                    # tools/_evidence/ra06_minor_side.py). They are real geometry, but acting on one
                    # means splitting a street feet from its end, so they carry their own
                    # severity and the ~74 substantive crossings keep ERROR.
                    "RA-06-OVERSHOOT",
                    "RA-11", "RA-12", "RA-13", "RA-14",  # sided street attribution checks
                    # RA-11's and RA-13's placeholder findings: a stored code that NO polygon
                    # in the layer carries, i.e. never assigned rather than wrong. Measured
                    # 2026-08-04 over 47,239 segments (94,478 sides): ESN '99' on 11,615 sides
                    # against 150 genuine ESN disagreements, ZIP '99999' on 270 against 746.
                    # Demoting the parents to clear them would bury the real mismatches.
                    "RA-11-PLACEHOLDER", "RA-13-PLACEHOLDER"}
# Ids that exist ONLY to carry a [severity]. RA-05 emits the enclave records, RA-06 the
# endpoint-overshoot ones and RA-09 the blank-CITY ones, so there is no separate job to switch
# off: accepting
# "[checks] RA-05-ENCLAVE = off" would report an active override in effective_lines while the
# records kept being written — a silent no-op in a file whose whole contract is that a mistake
# fails loud.
_SEVERITY_ONLY_IDS = {"RA-05-ENCLAVE", "RA-09-BLANK", "RA-06-OVERSHOOT",
                      "RA-11-PLACEHOLDER", "RA-13-PLACEHOLDER"}

# ini key -> (Context attribute, python type)
_THRESHOLDS = {
    "min_address": ("min_address", int),
    "max_address": ("max_address", int),
    "max_range_gap": ("max_range_gap", int),
    "distance_tolerance_ft": ("distance_tolerance_ft", float),
    "sync_threshold": ("sync_threshold", float),
    "geom_xy_tol_deg": ("geom_xy_tol", float),
    "geom_near_min_ft": ("geom_near_min", float),
    "geom_near_max_ft": ("geom_near_max", float),
    "geom_snap_tol_ft": ("geom_snap_tol", float),
    "geom_isolated_tol_ft": ("geom_isolated_tol", float),
    "ra_overlap_tol_sqft": ("ra_overlap_tol_sqft", float),
    "ra_gap_tol_sqft": ("ra_gap_tol_sqft", float),
    "ra_gap_min_width_ft": ("ra_gap_min_width_ft", float),
    "ra_coincident_tol_ft": ("ra_coincident_tol_ft", float),
    "ra_street_edge_tol_ft": ("ra_street_edge_tol_ft", float),
    "ra_street_along_tol_ft": ("ra_street_along_tol_ft", float),
    "ra_street_along_share": ("ra_street_along_share", float),
    "ra_offset_run_min_ft": ("ra_offset_run_min_ft", float),
    "ra_street_min_span_ft": ("ra_street_min_span_ft", float),
    "ra_side_offset_ft": ("ra_side_offset_ft", float),
}
_AGENCY = {"expected_agid": ("expected_agid", "str"),
           "strict_fqdn": ("strict_fqdn", "bool"),
           "county_boundary": ("county_boundary_path", "str")}


class Settings:
    """Parsed, validated settings ready to apply to a Context + run_checks."""
    def __init__(self):
        self.ctx_overrides = {}     # Context attr -> value
        self.names_ignored = None   # frozenset[str] or None (None = keep default)
        self.checks = {}            # check_id -> bool (on/off override)
        self.severity = {}          # check_id -> "ERROR|WARNING|INFO"
        self.source = None


def default_path():
    """Locate validation_settings.ini: the toolbox's config/ folder first, then the toolbox
    root (legacy). Both are anchored to the package location. The current working directory is
    NOT searched: under ArcGIS Pro the cwd is arbitrary (the Pro project home), so a partial
    copy missing config/ could otherwise silently pick up a foreign/stale ini from there."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for p in (os.path.join(root, "config", DEFAULT_FILE),
              os.path.join(root, DEFAULT_FILE)):
        if os.path.exists(p):
            return p
    return None


def _to_bool(v):
    s = str(v).strip().lower()
    if s in ("1", "true", "t", "yes", "y", "on"):
        return True
    if s in ("0", "false", "f", "no", "n", "off"):
        return False
    raise ValueError("expected a true/false value, got %r" % v)


def load(path):
    """Parse + validate an .ini; raise ValueError with a clear message on any problem."""
    cp = configparser.ConfigParser(interpolation=None)   # allow literal '%' in values
    cp.optionxform = str   # preserve case so check ids like XLAYER-05 survive
    try:
        read_ok = cp.read(path, encoding="utf-8-sig")   # tolerate a UTF-8 BOM
    except configparser.Error as e:
        raise ValueError("Settings file is malformed (%s): %s" % (path, e))
    except UnicodeDecodeError as e:
        raise ValueError("Settings file is not UTF-8 text (%s): %s. Re-save it as UTF-8."
                         % (path, e))
    if not read_ok:
        raise ValueError("Settings file not found or empty: %s" % path)
    if cp.defaults():
        raise ValueError("A [DEFAULT] section is not allowed in %s (its keys leak into "
                         "every section); move those keys into the section they belong to."
                         % path)
    # Section names are matched case-insensitively (like the keys within them), so
    # [Checks] and [checks] are equivalent. Reject case-variant DUPLICATES, which would
    # otherwise collapse and silently drop one section's keys.
    sec_map = {}
    for s in cp.sections():
        low = s.lower()
        if low in sec_map:
            raise ValueError("Duplicate section %r and %r (case-insensitive) in %s"
                             % (sec_map[low], s, path))
        sec_map[low] = s
    unknown = set(sec_map) - _SECTIONS
    if unknown:
        raise ValueError("Unknown settings section(s): %s (valid: %s)"
                         % (", ".join(sorted(unknown)), ", ".join(sorted(_SECTIONS))))

    def _items(section):
        actual = sec_map.get(section)
        return cp.items(actual) if actual else []

    st = Settings()
    st.source = path
    from . import all_checks  # noqa: F401  ensure the registry is populated before id checks
    # RA-01..RA-07 run in ResponseAreaChecks.pyt (outside the engine registry) but are still
    # configurable here: the .pyt reads st.severity for them. Unlike engine checks there is no
    # floor-clamp, so a [severity] demote applies straight; they are single-severity apart from
    # RA-05/RA-06/RA-09, whose split-off classes carry the _SEVERITY_ONLY_IDS lines above.
    valid_ids = {s.id for s in registry.all_specs()} | _EXTRA_CHECK_IDS

    for k, v in _items("thresholds"):
        k = k.lower()   # threshold/agency/names keys are case-insensitive (check ids are not)
        if k not in _THRESHOLDS:
            raise ValueError("Unknown [thresholds] key %r (valid: %s)"
                             % (k, ", ".join(sorted(_THRESHOLDS))))
        attr, typ = _THRESHOLDS[k]
        try:
            val = typ(v)
        except (TypeError, ValueError):
            raise ValueError("[thresholds] %s: expected %s, got %r" % (k, typ.__name__, v))
        import math
        if typ is float and not math.isfinite(val):
            raise ValueError("[thresholds] %s: must be a finite number, got %r" % (k, v))
        st.ctx_overrides[attr] = val

    for k, v in _items("agency"):
        k = k.lower()
        if k == "bbox":
            parts = [p.strip() for p in v.split(",")]
            if len(parts) != 4:
                raise ValueError("[agency] bbox needs 4 comma-separated numbers, got %r" % v)
            try:
                st.ctx_overrides["bbox"] = tuple(float(p) for p in parts)
            except ValueError:
                raise ValueError("[agency] bbox values must be numbers, got %r" % v)
            continue
        if k not in _AGENCY:
            raise ValueError("Unknown [agency] key %r" % k)
        attr, typ = _AGENCY[k]
        st.ctx_overrides[attr] = _to_bool(v) if typ == "bool" else v

    for k, v in _items("names"):
        if k.lower() != "ignored":
            raise ValueError("Unknown [names] key %r (only 'ignored' is valid)" % k)
        vals = frozenset(x.strip().upper() for x in v.split(",") if x.strip())
        st.names_ignored = vals or None   # empty list -> keep built-in default, don't disable all

    for cid, v in _items("checks"):
        if cid not in valid_ids:
            raise ValueError("[checks] unknown check id %r" % cid)
        if cid in _SEVERITY_ONLY_IDS:
            # Name the check that actually emits the records — telling an analyst who wrote
            # "RA-09-BLANK = off" to switch off RA-05 would send them to the wrong tool.
            owner = cid.rsplit("-", 1)[0]
            raise ValueError(
                "[checks] %s is a severity-only id and cannot be switched on or off: %s emits "
                "those records. Turn %s off to silence both, or set [severity] %s to demote "
                "them (INFO) instead." % (cid, owner, owner, cid))
        st.checks[cid] = _to_bool(v)

    for cid, v in _items("severity"):
        if cid not in valid_ids:
            raise ValueError("[severity] unknown check id %r" % cid)
        sv = str(v).strip().upper()
        if sv not in _SEVERITIES:
            raise ValueError("[severity] %s: expected ERROR/WARNING/INFO, got %r" % (cid, v))
        st.severity[cid] = sv

    return st


def apply_to_context(ctx, st):
    """Apply threshold/agency/names overrides to a Context and attach the Settings."""
    for attr, val in st.ctx_overrides.items():
        if not hasattr(ctx, attr):
            raise ValueError("Settings target unknown Context field: %r" % attr)
        setattr(ctx, attr, val)
    if st.names_ignored is not None:
        ctx.street_names_ignored = st.names_ignored
    ctx.settings = st
    return ctx


def _emits_only_error(check_id):
    """True if the check's source emits ERROR records and no WARNING/INFO ones — a demote
    override on it is neutralized by the engine's ERROR floor-clamp. Best-effort source scan."""
    import inspect
    spec = registry.get(check_id)
    if spec is None:
        return False
    try:
        src = inspect.getsource(spec.func)
    except Exception:
        return False
    return "SEVERITY.ERROR" in src and "SEVERITY.WARNING" not in src and "SEVERITY.INFO" not in src


def effective_lines(st):
    """Human-readable summary of what the settings actually change (for the GP tool)."""
    out = ["Settings source: %s" % (st.source or "(built-in defaults)")]
    if st.ctx_overrides:
        out.append("Thresholds/agency overrides:")
        for k, v in sorted(st.ctx_overrides.items()):
            out.append("  %-24s = %s" % (k, v))
    if st.names_ignored is not None:
        out.append("Ignored street names: %s" % ", ".join(sorted(st.names_ignored)))
    if st.checks:
        out.append("Check on/off overrides:")
        for cid, on in sorted(st.checks.items()):
            out.append("  %-12s %s" % (cid, "on" if on else "off"))
    if st.severity:
        out.append("Severity overrides:")
        for cid, sv in sorted(st.severity.items()):
            spec = registry.get(cid)
            # Flag overrides the engine cannot actually apply, so they aren't trusted silently:
            #  - an INFO-default check emits only INFO findings, which are never escalated;
            #  - a solely-ERROR check demoted below ERROR is a no-op (the floor-clamp keeps ERROR).
            if spec is not None and spec.severity == "INFO" and sv != "INFO":
                note = "  (no effect: emits only INFO findings; cannot be escalated)"
            elif sv != "ERROR" and _emits_only_error(cid):
                note = "  (no effect: emits only ERROR findings; the engine never lowers an ERROR)"
            else:
                note = ""
            out.append("  %-12s %s%s" % (cid, sv, note))
    if len(out) == 1:
        out.append("(no overrides — every check uses its built-in default)")
    return out
