"""Build the shared context, pick the checks to run and apply the severity overrides."""
from collections import defaultdict, namedtuple

from .model import Context, RANK, SEVERITY, remap_severity
from .crosswalks import load_crosswalks
from .common import normalize
from . import rangefit, registry

# What run_report returns. `tally` says what each [severity] line did on this run.
Result = namedtuple("Result", "records notices tally")

_NEEDS = {
    "addresses": "an address file (--addresses)",
    "streets": "a street file (--streets)",
    "geometry": "street geometry (a GeoJSON streets file)",
    "msag": "an MSAG file (--msag)",
    "modifier_domains": "modifier domains (--domains with premod, postmod or pretypesep rows)",
}


def build_context(addresses, streets, crosswalks=None, settings=None, **overrides):
    sbn = defaultdict(list)
    for s in streets:
        sbn[s["_NAMEKEY"]].append(s)
        # Also index under the segment's own raw-component name (PREFIX+NAME+
        # TYPE+SUFFIX). When a caller's _NAMEKEY was built some other way, it can point at an
        # unrelated name, so address lookups by the (correct) component name miss the segment.
        # Adding the raw key only widens the match set with the segment's true name; it never
        # removes a real range gap.
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
    # Apply editable calibration: explicit `settings` (a Settings, a path, or None for the
    # built-in defaults). Code overrides below still win over the file.
    from . import settings as _settings
    st = settings
    if isinstance(st, str):
        st = _settings.load(st)
    if st is not None:
        _settings.apply_to_context(ctx, st)
    for k, v in overrides.items():
        if not hasattr(ctx, k):
            raise ValueError("Unknown Context field: %r" % k)   # catch typo'd overrides
        setattr(ctx, k, v)
    return ctx


def build_msag_context(ctx, config, now=None):
    """Load the MSAG sources described by `config` onto `ctx` (optional).

    When `config` is None the MSAG fields stay None and the MSAG checks are skipped, with a
    notice. Otherwise parses the MSAG CSV, rolls GIS streets into MSAG-style records, and loads
    exceptions so XLAYER-16 can reconcile without re-reading the sources.
    """
    if config is None:
        return ctx
    from . import msag
    ctx.msag_records = msag.load_msag_csv(config)
    ctx.gis_msag = msag.build_gis_msag(ctx.streets, config.esn_pad_width)
    ctx.msag_addr_index = msag.build_msag_addr_index(ctx.addresses)
    # STREET-11's authoritative name list = the optional street-name table UNIONED with the
    # names in the MSAG file itself. A name table drifts from the MSAG it mirrors (see
    # msag.authoritative_names_from_msag), so on its own it warns on valid roads. The union also
    # means STREET-11 has a real list even with no name table configured, instead of falling
    # back to the degraded fuzzy self-check.
    names = set()
    if config.exceptions_path:
        ctx.msag_exceptions = msag.load_exceptions(config.exceptions_path, config.esn_pad_width)
    if config.names_path:
        names |= msag.load_authoritative_names(config.names_path)
    names |= msag.authoritative_names_from_msag(ctx.msag_records)
    ctx.authoritative_names = names or None
    ctx.min_match_rate = config.min_match_rate
    ctx.max_source_age_days = config.max_source_age_days
    ctx.msag_source_age_days = msag.source_age_days(config.source_path, now)
    return ctx


DEGRADED_NOTICE = {
    "STREET-11": (
        "STREET-11 ran in DEGRADED mode: no MSAG was loaded, so there was no authoritative "
        "road-name list to check against. Its findings here are a fallback heuristic: it "
        "flags a name only because that name shares no significant word with any OTHER name "
        "in the street layer, which false-positives on legitimately unique roads, and they "
        "are emitted at INFO to say so. A road being in the MSAG cannot help in this mode, "
        "because this run never opened the MSAG. For the real check, run with --msag."),
}


def capabilities(ctx):
    """The set of things this run has, matched against CheckSpec.requires."""
    have = set()
    if ctx.addresses:
        have.add("addresses")
    if ctx.streets:
        have.add("streets")
    if ctx.geom_provider is not None:
        have.add("geometry")
    if ctx.msag_records is not None:
        have.add("msag")
    if ctx.crosswalks.has_modifier_domains():
        have.add("modifier_domains")
    have.update("area:" + cid for cid in ctx.area_layers)
    return have


def _need_text(req):
    if req.startswith("area:"):
        return "a polygon layer for %s (an [areas] line)" % req[5:]
    return _NEEDS[req]


def apply_overrides(records, severity):
    """Apply [severity] overrides in place and return one tally row per override line.

    A record answers to its severity_id when it has one, else to its check_id. The tally
    covers every line, including a line that matched nothing or changed nothing."""
    rows = {cid: {"id": cid, "override": ov, "changed": 0, "held": 0, "info": 0, "same": 0}
            for cid, ov in severity.items()}
    for r in records:
        cid = r.severity_id or r.check_id
        ov = severity.get(cid)
        if ov is None:
            continue
        new = remap_severity(r.severity, ov, r.severity_id is not None)
        row = rows[cid]
        if new != r.severity:
            row["changed"] += 1
        elif r.severity == SEVERITY.INFO and r.severity_id is None:
            row["info"] += 1
        elif r.severity == SEVERITY.ERROR and RANK[ov] < RANK[SEVERITY.ERROR]:
            row["held"] += 1
        else:
            row["same"] += 1
        r.severity = new
    return [rows[cid] for cid in sorted(rows)]


def run_report(addresses, streets, ctx, priority=None, family=None, target=None,
               include_optional=False, ids=None, warn=None):
    registry.load_all()
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
        wanted = []
        for i in ids:
            s = registry.get(i)
            if s is None:
                continue
            if st and s.id in st.checks and not st.checks[s.id]:
                continue
            wanted.append(s)
    else:
        wanted = []
        for s in registry.all_specs():
            if not _enabled(s):
                continue
            if priority and s.priority != priority:
                continue
            if family and s.family != family:
                continue
            if target and s.target not in (target, "both"):
                continue
            wanted.append(s)
    notices = []
    have = capabilities(ctx)
    specs = []
    for s in wanted:
        missing = [r for r in s.requires if r not in have]
        if missing:
            notices.append("%s was skipped: it needs %s." % (s.id, "; ".join(
                _need_text(r) for r in missing)))
        else:
            specs.append(s)
    if "STREET-11" in {s.id for s in specs} and getattr(ctx, "authoritative_names", None) is None:
        notices.append(DEGRADED_NOTICE["STREET-11"])
    notices.extend(rangefit.coverage_notices(addresses, streets, ctx, {s.id for s in specs}))
    records = []
    for spec in specs:
        records.extend(spec.func(addresses, streets, ctx) or [])
    # [severity] overrides remap a check's findings with two protections: (1) INFO records are
    # left alone, because those are metric or summary lines (the XLAYER-11 sync metric, the
    # XLAYER-16 match rate) that must stay informational; (2) a per-record ERROR is never
    # lowered, so demoting an ERROR-capable check (a stray `[severity] ADDR-05 = INFO`) quiets
    # only its WARNING findings and can never silently hide a real routing ERROR. Overrides
    # may still escalate a WARNING to ERROR. See model.remap_severity.
    tally = apply_overrides(records, st.severity) if st and st.severity else []
    if warn is not None:
        for n in notices:
            warn(n)
    return Result(records, notices, tally)


def run_checks(addresses, streets, ctx, **kwargs):
    """The records alone; run_report also returns the notices and the override tally."""
    return run_report(addresses, streets, ctx, **kwargs).records
