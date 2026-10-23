"""Self-test: the recorder itself, the check catalog against the code, and the package hygiene rules."""
import ast
import hashlib
import os
import re

from . import catalog, engine, msag, registry
from . import response_area_checks as ra
from .crosswalks import load_crosswalks
from .selftest import Harness, Quiet
from .st_fix import A, AG, POOL_A, POOL_S, S, ctx_for, geom_provider, line

PKG = os.path.dirname(os.path.abspath(__file__))

# SHA-256 of words that must never appear in the package source. Hashes, so this file names none.
BANNED = frozenset([
    "467ef766006264233bc791aa57ebfbaa88a4daa3a5ebf7158a6d10ca03233911",
    "fe01ce351aec9c1edba441da0f96327f291b7141af8a7355ca425bf88e05fd40",
    "7f634d5b84cf19a7c073b537f5415ec33136cb2b3a5a7e3dc019e6ed986e7e85",
    "62915ffd2d74ebabcfe88e984f21a1aa14f601056b5367b7b5383c7d7f6d5d1e",
    "c290dd9444d4432e4f63b2c9e6029b31637efedb4c53fb34778c45a04eb1a326",
    "89d4519a655885adf65527acdad6b72b1d48ab07f7cdf4c1d291cbe28f484c73",
    "d7f59250b72e019f6779230a6dbf4bb8a20d585a40a26388fe383cf149412082",
])


def _sha(word):
    return hashlib.sha256(word.encode("ascii")).hexdigest()


def _source_files():
    return sorted(os.path.join(PKG, n) for n in os.listdir(PKG) if n.endswith(".py"))


def _ascii(path):
    with open(path, "rb") as fh:
        return all(b < 128 for b in fh.read())


def _read(path):
    with open(path, "r", encoding="ascii", newline="") as fh:
        return fh.read()


def _context(addrs, streets, authoritative, **kw):
    """A context with every capability on, over the rows it is given."""
    cw = load_crosswalks([("premod", "ALT", ""), ("postmod", "BIS", ""), ("pretypesep", "OF", "")])
    rules = dict((cid, ra.resolve_rule(cid)) for cid in ra.CHECK_IDS)
    opts = dict(crosswalks=cw, strict_fqdn=True, expected_state="FL", counties=frozenset({"EXAMPLE"}),
                sync_threshold=100.0, distance_tolerance_ft=100.0, geom_provider=geom_provider,
                area_layers=frozenset(rules), area_rules=rules, authoritative_names=authoritative)
    opts.update(kw)
    ctx = ctx_for(addrs, streets, **opts)
    ctx.msag_records = [
        {"community": "TESTVILLE", "name_key": "ELM ST", "low": 100, "high": 150, "parity": "E", "esn": "100"},
        {"community": "TESTVILLE", "name_key": "ELM ST", "low": 101, "high": 199, "parity": "O", "esn": "300"},
        {"community": "TESTVILLE", "name_key": "ELM ST", "low": 100, "high": 400, "parity": "B", "esn": "100"},
        {"community": "TESTVILLE", "name_key": "NOPE ST", "low": 1, "high": 5, "parity": "O", "esn": "100"}]
    ctx.gis_msag = msag.build_gis_msag(streets)
    ctx.msag_addr_index = msag.build_msag_addr_index(addrs)
    ctx.msag_source_age_days = 100
    ctx.max_source_age_days = 30
    return ctx


def _worlds():
    """Row sets and context options that, together, make every check show every severity it can emit.

    Some severities need a world of their own: the whole pool always holds a covering side that
    agrees with every address, and it names an agency that is a valid FQDN."""
    names = frozenset({("TESTVILLE", "ELM ST")})
    far = S()
    line(far, (0.0, 0.0), (1000.0, 0.0))
    return [
        (list(POOL_A), list(POOL_S), dict(authoritative=names)),
        (list(POOL_A), list(POOL_S), dict(authoritative=None)),
        ([A()], [S(Parity_L="E")], dict(authoritative=None)),
        ([A(Add_Number=301, HOUSE_NU="301", _XY=(500.0, 2000.0))], [far], dict(authoritative=None)),
        ([A(DiscrpAgID="badagency")], [], dict(authoritative=None, expected_agid="badagency")),
    ]


def _observed():
    both = {}
    for addrs, streets, kw in _worlds():
        authoritative = kw.pop("authoritative")
        seen = catalog.observe(addrs, streets, lambda a, s, au=authoritative, k=kw: _context(a, s, au, **k))
        for cid, (cols, sevs) in seen.items():
            old = both.get(cid, (frozenset(), frozenset()))
            both[cid] = (old[0] | cols, old[1] | sevs)
    return both


def section(h):
    c = h.check

    # ---- the recorder records a failure
    inner = Harness()
    q = Quiet()
    with q:
        inner.check(False, "a failing check")
        inner.raises(lambda: None, "no error")
        inner.raises(lambda: 1 // 0, "wrong error")
        inner.raises(lambda: int("x"), "the right error")
        inner.raises(lambda: 1 // 0, "a chosen error", ZeroDivisionError)
        status = inner.footer()
    c(status == 1 and len(inner.failed) == 3 and inner.passed == 2, "check() and raises() really do record a failure  <-- pinned defect")
    c("5 assertions, 3 failed" in q.out.getvalue() and "FAILED: no error (no error raised)" in q.out.getvalue() and "(wrong exception" in q.out.getvalue(),
      "the footer reports failures by count and by name, and exits 1  <-- pinned defect")
    q = Quiet()
    with q:
        status = Harness().footer()
    c(status == 0 and "0 assertions, 0 failed" in q.out.getvalue(), "an empty run reports zero failures and exits 0")

    # ---- the catalog text
    specs = catalog.ordered_specs()
    md = catalog.render_markdown().splitlines()
    ids = [s.id for s in specs]
    c(len(md) == len(specs) + 2 and md[0].startswith("| Check |") and len(set(ids)) == len(ids), "the catalog has one row per check, once each")
    c(ids.index("XLAYER-04") < ids.index("XLAYER-04b") < ids.index("XLAYER-05") and ids.index("ADDR-08") < ids.index("RA-01") < ids.index("STREET-01") < ids.index("XLAYER-01")
      and ids.index("STREET-10") < ids.index("STREET-11"), "the catalog sorts by family, then by check number, then by suffix")
    c(len(ids) == len(registry.all_specs()) and "XLAYER-16" in ids and "RA-10" in ids, "the catalog lists every registered check")
    doc = "text\n" + catalog.START + "\n" + catalog.render_markdown() + "\n" + catalog.END + "\nmore"
    c(catalog.block(doc) == catalog.render_markdown() and catalog.block("no markers") is None and catalog.block(catalog.END + catalog.START) is None, "block finds the text between the markers")
    ok, msg = catalog.check_document(doc)
    c(ok and "matches the registry (%d checks)" % len(specs) in msg, "check_document accepts a README whose block equals the registry")
    ok, msg = catalog.check_document(doc.replace("ADDR-01 | address", "ADDR-01 | street"))
    c(not ok and "out of date: 1 line(s) are not in the registry, 1 registry line(s) are missing" in msg and "First stale line: | ADDR-01 | street" in msg,
      "check_document names the first stale line  <-- pinned defect")
    short = doc.replace(md[3] + "\n", "")
    ok, msg = catalog.check_document(short)
    c(not ok and "0 line(s) are not in the registry, 1 registry line(s) are missing" in msg and "(none)" in msg, "check_document reports a missing row when nothing is stale")
    ok, msg = catalog.check_document("nothing")
    c(not ok and "no <!-- catalog:start -->" in msg, "check_document refuses a README with no catalog block")
    t = catalog.Tracked({"A": 1}, set())
    c(t.get("A") == 1 and t["A"] == 1 and t.get("B", 7) == 7 and t._log == {"A", "B"}, "a tracked row remembers every column read, by get or by index")

    # ---- the declaration against the code
    seen = _observed()
    for spec in specs:
        cols, sevs = seen[spec.id]
        c(set(spec.fields) == set(cols), "%s declares exactly the columns it reads" % spec.id)
        c(set(spec.emits) == set(sevs), "%s declares exactly the severities it emits" % spec.id)
    words = [len(s.summary.split()) for s in specs]
    c(min(words) >= 4 and max(words) <= 25, "every check has a summary of 4 to 25 words")
    c(all(s.summary.endswith(".") for s in specs) and len(set(s.summary for s in specs)) == len(specs), "every summary is one sentence and no two checks share one")
    c(all(s.severity in s.emits for s in specs), "every check lists its primary severity among the severities it emits")
    c(all(r in registry.REQUIRES or r.startswith("area:") for s in specs for r in s.requires), "every requirement a check names is one the engine knows")
    for spec in (s for s in specs if s.requires):
        res = engine.run_report([], [], ctx_for([], []), ids=[spec.id])
        c(res.records == [] and len(res.notices) >= 1 and "was skipped: it needs" in res.notices[0], "%s is skipped with a notice when its input is missing" % spec.id)

    # ---- package hygiene
    files = _source_files()
    c(len(files) >= 20 and all(_ascii(f) for f in files), "every source file is plain ASCII")
    c(all(isinstance(ast.parse(_read(f), feature_version=(3, 9)), ast.Module) for f in files), "every source file parses as Python 3.9 source")
    c(not any(isinstance(n, ast.JoinedStr) for f in files for n in ast.walk(ast.parse(_read(f)))), "no source file uses an f-string")
    listing = [n for n in os.listdir(PKG) if n != "__pycache__"]
    c(all(n.endswith(".py") for n in listing), "the package folder holds Python files only, so no vendor domain file ships  <-- pinned defect")
    tokens = set(t for f in files for t in re.findall(r"[a-z0-9]+", _read(f).lower()))
    c(not (set(_sha(t) for t in tokens) & BANNED), "no banned word appears in the package source")
    c(re.search(r"\.(csv|xlsx|xls|gdb|sde|json|ini)\b", " ".join(listing)) is None, "no data file extension appears in the package folder")
    c(AG.endswith(".example.org") and A()["COUNTY"] == "EXAMPLE", "the fixtures use the reserved example domain and an invented county")
