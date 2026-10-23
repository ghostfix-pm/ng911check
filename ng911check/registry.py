"""Every check registers itself here through the @check decorator."""
from dataclasses import dataclass
from typing import Callable

_REGISTRY = {}

# What a check needs from the run before it can say anything. A check that needs one of
# these and does not get it is reported as skipped, never run on nothing.
REQUIRES = ("geometry", "msag", "modifier_domains")   # plus "area:<check id>" per area rule


@dataclass
class CheckSpec:
    id: str
    family: str
    severity: str        # default/primary severity (records may differ)
    priority: str        # v1-core | v1 | v2
    target: str          # address | street | both
    func: Callable
    default_on: bool = True   # opt-in checks set this False
    # The catalog documents these three, and the self-test proves the code agrees with them.
    emits: tuple = ()         # every severity the check can emit
    summary: str = ""         # one sentence, what a finding means
    fields: tuple = ()        # every input column the check reads
    requires: tuple = ()      # see REQUIRES


def check(id, family, severity, priority, target, default_on=True,
          emits=None, summary="", fields=(), requires=()):
    def deco(fn):
        _REGISTRY[id] = CheckSpec(id, family, severity, priority, target, fn,
                                  default_on, tuple(emits or (severity,)), summary,
                                  tuple(fields), tuple(requires))
        return fn
    return deco


def load_all():
    """Import every check module, so each @check decorator has run. Returns their names."""
    from . import all_checks
    return all_checks.__all__


def all_specs():
    return list(_REGISTRY.values())


def get(check_id):
    return _REGISTRY.get(check_id)
