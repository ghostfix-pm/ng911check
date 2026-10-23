"""Self-test: defensive paths that the normal gates keep out of reach.

Several checks guard a number with try/except or a bound test even though is_addressable has
already screened the row. The guards stay, because they are what keeps a later change to the
gate from turning a bad cell into a crash. Each test here removes the gate for one call, so the
guard runs, and proves it neither crashes nor reports.
"""
from . import address_checks, cross_layer_checks as xl, msag, street_checks
from .model import ErrorRecord
from .st_fix import A, S, ctx_for, found


class Patched(object):
    """Replace one module attribute for the length of a with block."""

    def __init__(self, module, name, value):
        self.module, self.name, self.value = module, name, value

    def __enter__(self):
        self.old = getattr(self.module, self.name)
        setattr(self.module, self.name, self.value)

    def __exit__(self, *exc):
        setattr(self.module, self.name, self.old)
        return False


def always(_row):
    return True


def section(h):
    c = h.check
    bad = [A(Add_Number="x"), A(Add_Number=0), A(Add_Number=-4), A(Add_Number=None)]
    ctx = ctx_for(bad, [S()])

    c(ctx.geom("street", 1) is None, "a context with no geometry provider answers None for any segment")
    c(xl._range_only_segments(A(Add_Number="x"), ctx) == [] and xl._covering_segments(A(Add_Number="x"), ctx) == [],
      "the segment lookups return nothing for a house number that is not a number")

    with Patched(xl, "is_addressable", always):
        c(xl.check_xlayer_02(bad, [S()], ctx) == [], "xlayer-02 survives a house number the gate let through")
        c(len(xl.check_xlayer_14([], [S()], ctx_for(bad, [S()]))) == 1, "xlayer-14 survives a house number the gate let through and still reports the empty range")
    with Patched(msag, "is_addressable", always):
        c(msag.build_msag_addr_index(bad) == {}, "the MSAG address index survives a house number the gate let through")
    with Patched(address_checks, "is_addressable", always):
        c(address_checks.check_addr_02([A(Add_Number=None, STREET_NA="", TYPE="", PREFIX="", SUFFIX="")], [], ctx) == [],
          "addr-02 skips a row whose full address is empty")

    def street_hit(addresses, streets, context):
        return [ErrorRecord("XLAYER-04", "n", "f", "ERROR", "street", 99, "", "d", None)]

    with Patched(xl, "check_xlayer_04", street_hit):
        out = xl.check_xlayer_11([A()], [S()], ctx_for([A()], [S()]))
        c(found(out, "XLAYER-11", "INFO", "100.0% (1/1 active reconcile)") == 1, "xlayer-11 counts only address findings against the sync rate")

    cands = street_checks._street_name_candidates(S(_NAMEKEY=""), None)
    c(cands == {"ELM ST", "ELM"}, "the name candidates of a segment with no _NAMEKEY come from its parts alone")
