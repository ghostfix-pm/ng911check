"""The check catalog, generated from the registry so the documentation cannot drift.

A check's id, family, target, severities, default state, requirements, summary and the
columns it reads are declared once, in its @registry.check decorator. This module renders
that declaration as a Markdown table, compares the table in a README against the registry,
and observes what the code really does so the self-test can prove the declaration true:

  - observe() runs every check on instrumented rows and records which columns it read and
    which severities it emitted.
  - The self-test fails if a check reads a column it did not declare, emits a severity it
    did not declare, or declares a column or severity the fixture never shows.
"""
import re

from . import registry

START = "<!-- catalog:start -->"
END = "<!-- catalog:end -->"


def _sort_key(spec):
    m = re.match(r"^([A-Za-z]+)-(\d+)(.*)$", spec.id)
    return (m.group(1), int(m.group(2)), m.group(3))


def ordered_specs():
    registry.load_all()
    return sorted(registry.all_specs(), key=_sort_key)


def _needs(spec):
    return ", ".join(r.replace("area:", "area ") .replace("_", " ") for r in spec.requires)


def render_markdown():
    """The catalog as a Markdown table, one row per check."""
    lines = ["| Check | Target | Emits | On by default | Needs | What a finding means |",
             "|---|---|---|---|---|---|"]
    for spec in ordered_specs():
        lines.append("| %s | %s | %s | %s | %s | %s |" % (
            spec.id, spec.target, ", ".join(spec.emits), "yes" if spec.default_on else "no",
            _needs(spec) or "-", spec.summary))
    return "\n".join(lines)


def block(text):
    """The part of `text` between the catalog markers, or None when the markers are absent."""
    i, j = text.find(START), text.find(END)
    if i < 0 or j < i:
        return None
    return text[i + len(START):j].strip("\n")


def check_document(text):
    """(ok, message): does the catalog block in `text` equal the generated catalog?"""
    got = block(text)
    if got is None:
        return False, "the document has no %s ... %s block" % (START, END)
    want = render_markdown()
    if got.strip() == want.strip():
        return True, "the catalog block matches the registry (%d checks)" % len(ordered_specs())
    have = set(got.strip().splitlines())
    need = set(want.strip().splitlines())
    stale = sorted(have - need)
    missing = sorted(need - have)
    return False, ("the catalog block is out of date: %d line(s) are not in the registry, "
                   "%d registry line(s) are missing. First stale line: %s"
                   % (len(stale), len(missing), stale[0] if stale else "(none)"))


class Tracked(dict):
    """A row that remembers which columns were read from it."""

    def __init__(self, data, log):
        dict.__init__(self, data)
        self._log = log

    def get(self, key, default=None):
        self._log.add(key)
        return dict.get(self, key, default)

    def __getitem__(self, key):
        self._log.add(key)
        return dict.__getitem__(self, key)


def observe(addresses, streets, make_context):
    """Run every registered check once on instrumented copies of the rows.

    `make_context(addresses, streets)` must return a Context with every capability on (street
    geometry, an MSAG, area rules, modifier domains), built over the rows it is given.
    Returns {check_id: (columns_read, severities_emitted)}. Columns that start with an
    underscore are internal and are left out."""
    log = set()
    tracked_a = [Tracked(r, log) for r in addresses]
    tracked_s = [Tracked(r, log) for r in streets]
    ctx = make_context(tracked_a, tracked_s)
    seen = {}
    for spec in ordered_specs():
        log.clear()
        records = spec.func(tracked_a, tracked_s, ctx) or []
        seen[spec.id] = (frozenset(c for c in log if not c.startswith("_")),
                         frozenset(r.severity for r in records))
    return seen
