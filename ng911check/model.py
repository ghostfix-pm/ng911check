"""The records a check returns and the context every check reads."""
from dataclasses import dataclass, field
from typing import Optional


class SEVERITY:
    ERROR = "ERROR"
    WARNING = "WARNING"
    INFO = "INFO"


RANK = {"INFO": 0, "WARNING": 1, "ERROR": 2}   # severity ordering for the override floor


def remap_severity(severity, override, classed=False):
    """The severity a record ends up with after a [severity] override.

    The rule this package exists to keep: an override may raise a finding, but it can never
    lower an ERROR. An INFO record is a metric or summary line and is left alone, unless it
    is a classed record (it carries its own severity line, such as RA-09-BLANK), which may be
    raised or lowered, still subject to the ERROR floor."""
    if override is None:
        return severity
    if severity == "INFO" and not classed:
        return severity
    if severity == "ERROR" and RANK[override] < RANK["ERROR"]:
        return severity
    return override


class FAMILY:
    CROSS = "cross_layer"
    STREET = "street_attr"
    ADDRESS = "address_attr"
    AREA = "response_area"


@dataclass
class ErrorRecord:
    check_id: str
    check_name: str
    family: str
    severity: str
    source_layer: str          # "address" | "street" | "dataset"
    source_oid: int
    source_nguid: str
    description: str
    xy: Optional[tuple]        # (x, y) in the layer's projected units; None if unknown
    # A split-off class that carries its own [severity] line (RA-09-BLANK). None means the
    # record answers to its check_id. See engine.run_checks.
    severity_id: Optional[str] = None


@dataclass
class Context:
    """Shared, precomputed structures handed to every check."""
    addresses: list
    streets: list
    streets_by_name: dict      # name_key -> list[street dict]
    addresses_by_name: dict    # name_key -> list[address dict]
    crosswalks: object         # crosswalks.Crosswalks
    # No default agency. A default here once carried one agency's mailbox into every
    # install, so every other agency's NGUIDs failed ADDR-06 against it. The CLI refuses
    # to run until the settings file names the agency.
    expected_agid: str = ""
    strict_fqdn: bool = False
    expected_state: str = ""        # XLAYER-09: '' skips the "not the expected state" WARNING
    counties: frozenset = frozenset()  # XLAYER-09: empty skips the "county not in set" WARNING
    distance_tolerance_ft: float = 1000.0
    sync_threshold: float = 98.0
    settings: object = None         # attached Settings; None = built-in defaults
    geom_provider: object = None    # callable(layer, oid) -> geometry.Polyline or None
    area_layers: frozenset = frozenset()  # which of esn/city/zip polygons were annotated
    min_address: int = 0
    max_address: int = 99999
    max_range_gap: int = 2          # STREET-12/13: numbering gap still treated as one run
    street_names_ignored: frozenset = frozenset()
    esn_pad_width: int = 3
    # --- response-area rules (optional; filled by the runner from the [areas] settings) ---
    area_rules: dict = field(default_factory=dict)   # check id -> response_area_checks.AreaRule
    # --- MSAG reconciliation (optional; filled by engine.build_msag_context) ---
    msag_records: Optional[list] = None
    gis_msag: Optional[list] = None
    msag_addr_index: object = None
    msag_exceptions: object = None
    msag_match_rate: Optional[float] = None
    msag_result: Optional[dict] = None      # the last msag.reconcile() result, for the report
    msag_source_age_days: Optional[int] = None
    max_source_age_days: Optional[int] = None   # None: report the age, never warn on it
    min_match_rate: float = 0.98
    authoritative_names: Optional[set] = None  # None => STREET-11 runs degraded

    def name_ignored(self, name_key):
        """True if this street name should be skipped by the name-based checks.

        An ignored name matches whole words: ELM skips ELM ST and N ELM AVE, never ELMWOOD DR."""
        nk = (name_key or "").strip().upper()
        padded = " %s " % nk
        return any(" %s " % ig in padded for ig in self.street_names_ignored)

    def geom(self, layer, oid):
        if self.geom_provider is None:
            return None
        return self.geom_provider(layer, oid)
