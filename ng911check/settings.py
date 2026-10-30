"""Editable calibration settings (an .ini file).

The 911 GIS analyst edits the .ini; code reads it. Strict validation: an unknown
key, bad value, or unknown check id fails loud with an actionable message (a silent
typo must never weaken QC). A missing key falls back to the built-in default, so a
partial file still loads and behaves as the defaults do.

The rule the file can never break: a [severity] line may raise a finding, but it never
lowers an ERROR. effective_lines() and override_lines() print what every line did.
"""
import configparser
import math
import os

from . import registry
from .model import SEVERITY, RANK, remap_severity
from .response_area_checks import AreaSpec, CHECK_IDS as AREA_IDS

_SECTIONS = {"thresholds", "agency", "names", "checks", "severity", "areas"}
_SEVERITIES = {"ERROR", "WARNING", "INFO"}

# Ids that exist ONLY to carry a [severity]. RA-09 emits the blank-CITY class, so there is no
# separate job to switch off: accepting "[checks] RA-09-BLANK = off" would report an active
# override in effective_lines while the records kept being written, a silent no-op in a file
# whose whole contract is that a mistake fails loud.
_SEVERITY_ONLY_IDS = {"RA-09-BLANK"}

# Ids of sibling topology checks that a shared settings file may still name. This package never
# runs them, so a line for one is accepted and then reported as having no effect here.
_FOREIGN_IDS = {"RA-04", "RA-05", "RA-06", "RA-07", "RA-11", "RA-12", "RA-13", "RA-14",
                "RA-05-ENCLAVE", "RA-06-OVERSHOOT", "RA-11-PLACEHOLDER", "RA-13-PLACEHOLDER"}

# ini key -> (Context attribute, python type)
_THRESHOLDS = {
    "min_address": ("min_address", int),
    "max_address": ("max_address", int),
    "max_range_gap": ("max_range_gap", int),
    "distance_tolerance_ft": ("distance_tolerance_ft", float),
    "sync_threshold": ("sync_threshold", float),
    "oo_min_displacement_ft": ("oo_min_displacement_ft", float),
    "wb_min_margin_ft": ("wb_min_margin_ft", float),
    "wb_min_ratio": ("wb_min_ratio", float),
    "nm_min_margin_ft": ("nm_min_margin_ft", float),
    "nm_min_ratio": ("nm_min_ratio", float),
}

# The smallest value the rangefit thresholds accept. A negative margin or a ratio below 1 would
# report a point that sits on its own street, and XLAYER-19 skips its scan on the same bound.
_FLOORS = {"oo_min_displacement_ft": 0.0, "wb_min_margin_ft": 0.0, "wb_min_ratio": 1.0,
           "nm_min_margin_ft": 0.0, "nm_min_ratio": 1.0}
_AGENCY = {"expected_agid": ("expected_agid", "str"),
           "strict_fqdn": ("strict_fqdn", "bool"),
           "expected_state": ("expected_state", "state"),
           "counties": ("counties", "set")}


class Settings:
    """Parsed, validated settings ready to apply to a Context + run_checks."""
    def __init__(self):
        self.ctx_overrides = {}     # Context attr -> value
        self.names_ignored = None   # frozenset[str] or None (None = keep default)
        self.checks = {}            # check_id -> bool (on/off override)
        self.severity = {}          # check_id -> "ERROR|WARNING|INFO"
        self.areas = {}             # check_id -> response_area_checks.AreaSpec
        self.source = None


def _to_bool(v):
    s = str(v).strip().lower()
    if s in ("1", "true", "t", "yes", "y", "on"):
        return True
    if s in ("0", "false", "f", "no", "n", "off"):
        return False
    raise ValueError("expected a true/false value, got %r" % v)


def _parse_area(cid, value, base):
    """`file|key[|fields[|sentinel]]`. A relative file is resolved against the settings folder."""
    parts = [p.strip() for p in value.split("|")]
    if len(parts) < 2 or len(parts) > 4 or not parts[0] or not parts[1]:
        raise ValueError("[areas] %s: expected file|key[|fields[|sentinel]], got %r"
                         % (cid, value))
    path = parts[0]
    if not os.path.isabs(path):
        path = os.path.normpath(os.path.join(base, path))
    fields = None
    if len(parts) > 2 and parts[2]:
        fields = tuple(f.strip() for f in parts[2].split(",") if f.strip())
    sentinel = parts[3].upper() if len(parts) > 3 and parts[3] else None
    return AreaSpec(path, parts[1], fields or None, sentinel)


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
        raise ValueError("Settings file not found or unreadable: %s" % path)
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
    registry.load_all()   # the registry must be full before the check ids are validated
    valid_ids = {s.id for s in registry.all_specs()} | _SEVERITY_ONLY_IDS | _FOREIGN_IDS

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
        if typ is float and not math.isfinite(val):
            raise ValueError("[thresholds] %s: must be a finite number, got %r" % (k, v))
        if k in _FLOORS and val < _FLOORS[k]:
            raise ValueError("[thresholds] %s: must be %s or more, got %r"
                             % (k, _FLOORS[k], v))
        st.ctx_overrides[attr] = val

    for k, v in _items("agency"):
        k = k.lower()
        if k not in _AGENCY:
            raise ValueError("Unknown [agency] key %r (valid: %s)"
                             % (k, ", ".join(sorted(_AGENCY))))
        attr, typ = _AGENCY[k]
        if typ == "bool":
            st.ctx_overrides[attr] = _to_bool(v)
        elif typ == "state":
            st.ctx_overrides[attr] = v.strip().upper()
        elif typ == "set":
            st.ctx_overrides[attr] = frozenset(
                x.strip().upper() for x in v.split(",") if x.strip())
        else:
            st.ctx_overrides[attr] = v.strip()

    for k, v in _items("names"):
        if k.lower() != "ignored":
            raise ValueError("Unknown [names] key %r (only 'ignored' is valid)" % k)
        vals = frozenset(x.strip().upper() for x in v.split(",") if x.strip())
        st.names_ignored = vals or None   # empty list -> keep built-in default, don't disable all

    for cid, v in _items("checks"):
        if cid not in valid_ids:
            raise ValueError("[checks] unknown check id %r" % cid)
        if cid in _SEVERITY_ONLY_IDS:
            # Name the check that actually emits the records: telling an analyst who wrote
            # "RA-09-BLANK = off" to switch off the wrong id would send them to the wrong line.
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

    base = os.path.dirname(os.path.abspath(path))
    for cid, v in _items("areas"):
        if cid not in AREA_IDS:
            raise ValueError("[areas] %r is not an area check (valid: %s)"
                             % (cid, ", ".join(AREA_IDS)))
        st.areas[cid] = _parse_area(cid, v, base)

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


def _emitted(check_id):
    """(severities the id can emit, whether its records answer to their own line) or None."""
    if check_id in _SEVERITY_ONLY_IDS:
        return ((SEVERITY.INFO,), True)
    spec = registry.get(check_id)
    if spec is None:
        return None
    return (spec.emits, False)


def override_note(check_id, sv):
    """Say, before any run, whether a [severity] line can change anything.

    The note comes from remap_severity over the severities the check declares it emits, so it
    cannot disagree with what the engine does."""
    known = _emitted(check_id)
    if known is None:
        return "  (no effect: %s is not run by this package)" % check_id
    emits, classed = known
    changed = [e for e in emits if remap_severity(e, sv, classed) != e]
    if not changed:
        if emits == (SEVERITY.INFO,) and not classed:
            return "  (no effect: emits only INFO findings; cannot be escalated)"
        if emits == (SEVERITY.ERROR,) and sv != SEVERITY.ERROR:
            return "  (no effect: emits only ERROR findings; the engine never lowers an ERROR)"
        return "  (no effect: every finding it emits stays where it is)"
    if SEVERITY.ERROR in emits and sv != SEVERITY.ERROR and RANK[sv] < RANK[SEVERITY.ERROR]:
        return "  (ERROR findings stay ERROR; the others become %s)" % sv
    return ""


def _check_note(cid, on):
    if cid in _FOREIGN_IDS:
        return "  (no effect: %s is not run by this package)" % cid
    spec = registry.get(cid)
    if not on and spec is not None and SEVERITY.ERROR in spec.emits:
        return "  (can emit ERROR: its findings are NOT in this report)"
    return ""


def effective_lines(st):
    """Human-readable summary of what the settings change, before any run."""
    out = ["Settings source: %s" % (st.source or "(built-in defaults)")]
    if st.ctx_overrides:
        out.append("Thresholds/agency overrides:")
        for k, v in sorted(st.ctx_overrides.items()):
            if isinstance(v, frozenset):
                v = ", ".join(sorted(v))
            out.append("  %-24s = %s" % (k, v))
    if st.names_ignored is not None:
        out.append("Ignored street names: %s" % ", ".join(sorted(st.names_ignored)))
    if st.checks:
        out.append("Check on/off overrides:")
        for cid, on in sorted(st.checks.items()):
            note = _check_note(cid, on)
            out.append("  %-12s %s%s" % (cid, "on" if on else "off", note))
    if st.areas:
        out.append("Response-area rules:")
        for cid, spec in sorted(st.areas.items()):
            out.append("  %-12s %s key=%s" % (cid, os.path.basename(spec.path), spec.key_prop))
    if st.severity:
        out.append("Severity overrides:")
        for cid, sv in sorted(st.severity.items()):
            out.append("  %-12s %s%s" % (cid, sv, override_note(cid, sv)))
    if len(out) == 1:
        out.append("(no overrides - every check uses its built-in default)")
    return out


def override_lines(tally):
    """What each [severity] line actually did on this run. `tally` comes from the engine."""
    out = []
    for t in tally:
        out.append("  %-14s %s: %d raised or lowered, %d held at ERROR, %d INFO untouched, "
                   "%d already %s" % (t["id"], t["override"], t["changed"], t["held"],
                                      t["info"], t["same"], t["override"]))
    return out
