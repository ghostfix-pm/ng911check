from collections import defaultdict
from .model import Context
from .crosswalks import load_crosswalks
from .common import normalize
from . import registry

_RANK = {"INFO": 0, "WARNING": 1, "ERROR": 2}   # severity ordering for the override floor-clamp


def build_context(addresses, streets, crosswalks=None, settings=None, **overrides):
    sbn = defaultdict(list)
    for s in streets:
        sbn[s["_NAMEKEY"]].append(s)
        # Also index under the segment's own raw-component name (PREFIX+NAME+
        # TYPE+SUFFIX). When COMPARE is stale/wrong its _NAMEKEY points at an
        # unrelated name, so address lookups by the (correct) component name miss
        # the segment. Adding the raw key only widens the match set with the
        # segment's true name; it never removes a real range gap.
        raw_key = normalize(s.get("PREFIX"), s.get("NAME"),
                            s.get("TYPE"), s.get("SUFFIX"))
        if raw_key and raw_key != s["_NAMEKEY"] and s not in sbn[raw_key]:
            sbn[raw_key].append(s)
    abn = defaultdict(list)
    for a in addresses:
        abn[a["_NAMEKEY"]].append(a)
    ctx = Context(
        addresses=addresses,
        streets=streets,
        streets_by_name=dict(sbn),
        addresses_by_name=dict(abn),
        crosswalks=crosswalks or load_crosswalks(),
    )
    # Apply editable calibration (validation_settings.ini): explicit `settings`
    # (a Settings, a path, or None to auto-discover the bundled .ini). Code overrides
    # below still win over the file.
    from . import settings as _settings
    st = settings
    if st is None:
        p = _settings.default_path()
        st = _settings.load(p) if p else None
    elif isinstance(st, str):
        st = _settings.load(st)
    if st is not None:
        _settings.apply_to_context(ctx, st)
    for k, v in overrides.items():
        if not hasattr(ctx, k):
            raise ValueError("Unknown Context field: %r" % k)   # catch typo'd overrides
        setattr(ctx, k, v)
    return ctx


def attach_boundary(ctx, target_sr=None, warn=None):
    """If a county boundary is configured ([agency] county_boundary), load it into
    ctx.county_boundary projected to target_sr (the street SR) so GEOM-05/08 can suppress
    boundary dangles. No-op when unset; never raises (loader returns None on failure).

    When a path IS configured but the load yields nothing (bad/renamed path, empty FC),
    the boundary suppression the analyst asked for is silently off — so call warn(msg) if
    provided, letting the caller surface it (arcpy message / stdout)."""
    if getattr(ctx, "county_boundary_path", None) and ctx.county_boundary is None:
        from . import loader
        ctx.county_boundary = loader.load_boundary(ctx.county_boundary_path, target_sr)
        if ctx.county_boundary is None and warn is not None:
            warn("county_boundary is configured (%s) but could not be loaded (missing/renamed "
                 "path or empty feature class); GEOM-05/08 boundary dangles will NOT be "
                 "suppressed this run." % ctx.county_boundary_path)
    return ctx


def build_msag_context(ctx, config):
    """Load the MSAG sources described by `config` onto `ctx` (optional).

    When `config` is None the MSAG fields stay None and the MSAG checks no-op.
    Otherwise parses the xlsx, rolls GIS streets into MSAG-style records, and
    loads exceptions so XLAYER-16 can reconcile without re-querying the sources.
    """
    if config is None:
        return ctx
    from . import msag
    ctx.msag_records = msag.load_msag_xlsx(config)
    ctx.gis_msag = msag.build_gis_msag(ctx.streets, config.esn_pad_width)
    ctx.msag_addr_index = msag.build_msag_addr_index(ctx.addresses)
    # STREET-11's authoritative name list = the frozen DOMAINSTREETNAMES table UNIONED with the
    # names in the MSAG spreadsheet itself. The table is a MapSAG-era artifact that is not
    # rebuilt from anything and has drifted from the MSAG (see
    # msag.authoritative_names_from_msag), so on its own it warns on valid roads. The union also
    # means STREET-11 has a real list even with no exceptions gdb configured, instead of falling
    # back to the degraded fuzzy self-check.
    names = set()
    if config.exceptions_gdb:
        ctx.msag_exceptions = msag.load_exceptions(
            config.exceptions_gdb, config.esn_pad_width)
        domain = msag.load_authoritative_names(config.exceptions_gdb)
        if domain:
            names |= domain
    names |= msag.authoritative_names_from_msag(ctx.msag_records)
    ctx.authoritative_names = names or None
    ctx.min_match_rate = config.min_match_rate
    return ctx


DEGRADED_NOTICE = {
    "STREET-11": (
        "STREET-11 ran in DEGRADED mode: no MSAG was loaded, so there was no authoritative "
        "road-name list to check against. Its findings here are a fallback heuristic: it "
        "flags a name only because that name shares no significant word with any OTHER name "
        "in the street layer, which false-positives on legitimately unique roads, and they "
        "are emitted at INFO to say so. A road being in the MSAG cannot help in this mode, "
        "because this run never opened the MSAG. For the real check, run "
        "MSAGTools.pyt -> 'Validate MSAG <-> GIS', which loads the MSAG plus "
        "DOMAINSTREETNAMES and reports genuine unknown names at WARNING."),
}


def _warn_degraded(specs, ctx, warn):
    """Announce a check that silently fell back to a weaker mode.

    STREET-11 has two modes and picks one from whether ctx.authoritative_names was loaded.
    Nothing said which mode ran, so an analyst saw INFO findings on roads that ARE in the MSAG
    and reasonably concluded the check was wrong (911 team, 2026-08-25). The severity was the
    only clue and it is not a self-explanatory one.
    """
    if warn is None:
        return
    ran = {s.id for s in specs}
    if "STREET-11" in ran and getattr(ctx, "authoritative_names", None) is None:
        warn(DEGRADED_NOTICE["STREET-11"])


def run_checks(addresses, streets, ctx, priority=None, family=None, target=None,
               include_optional=False, ids=None, warn=None):
    st = getattr(ctx, "settings", None)

    def _enabled(spec):
        # An explicit [checks] on/off in the .ini always wins (analyst's deliberate
        # choice); otherwise include_optional forces opt-in checks on; otherwise the
        # built-in default_on.
        if st and spec.id in st.checks:
            return st.checks[spec.id]
        if include_optional:
            return True
        return spec.default_on

    if ids is not None:
        # Direct per-check run: honor an explicit [checks] OFF (the analyst disabled it),
        # but still run a default-off opt-in check when its own tool asks for it by id.
        specs = []
        for i in ids:
            s = registry.get(i)
            if s is None:
                continue
            if st and s.id in st.checks and not st.checks[s.id]:
                continue
            specs.append(s)
    else:
        specs = []
        for s in registry.all_specs():
            if not _enabled(s):
                continue
            if priority and s.priority != priority:
                continue
            if family and s.family != family:
                continue
            if target and s.target not in (target, "both"):
                continue
            specs.append(s)
    _warn_degraded(specs, ctx, warn)
    records = []
    for spec in specs:
        records.extend(spec.func(addresses, streets, ctx) or [])
    # [severity] overrides remap a check's real findings (ERROR/WARNING) to the configured
    # level, with two protections: (1) INFO records are left alone — those are metric/KPI/
    # summary lines (XLAYER-11 sync metric, XLAYER-16 match-rate) that must stay informational;
    # (2) a per-record ERROR is never lowered below ERROR, so demoting an ERROR-capable check
    # (e.g. a stray `[severity] ADDR-05 = INFO`) quiets only its WARNING findings and can never
    # silently hide a real routing ERROR. Overrides may still escalate a WARNING to ERROR.
    if st and st.severity:
        for r in records:
            ov = st.severity.get(r.check_id)
            if ov and r.severity != "INFO" and not (r.severity == "ERROR" and _RANK[ov] < _RANK["ERROR"]):
                r.severity = ov
    return records
