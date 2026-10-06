"""Every check registers itself here through the @check decorator."""
from dataclasses import dataclass
from typing import Callable

_REGISTRY = {}


@dataclass
class CheckSpec:
    id: str
    family: str
    severity: str        # default/primary severity (records may differ)
    priority: str        # v1-core | v1 | v2
    target: str          # address | street | both
    func: Callable
    default_on: bool = True   # opt-in checks set this False


def check(id, family, severity, priority, target, default_on=True):
    def deco(fn):
        _REGISTRY[id] = CheckSpec(id, family, severity, priority, target, fn,
                                  default_on)
        return fn
    return deco


def all_specs():
    return list(_REGISTRY.values())


def get(check_id):
    return _REGISTRY.get(check_id)
