"""The records a check returns and the context every check reads."""
from dataclasses import dataclass
from typing import Optional


class SEVERITY:
    ERROR = "ERROR"
    WARNING = "WARNING"
    INFO = "INFO"


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
    # No default agency. A default here once carried one county's mailbox into every
    # install, so every other agency's NGUIDs failed ADDR-06 against it. The CLI refuses
    # to run until the settings file names the agency.
    expected_agid: str = ""
    strict_fqdn: bool = False
    expected_state: str = ""        # XLAYER-09: '' skips the "not the expected state" WARNING
    counties: frozenset = frozenset()  # XLAYER-09: empty skips the "county not in set" WARNING
    distance_tolerance_ft: float = 1000.0
    sync_threshold: float = 98.0
    settings: object = None         # attached Settings; None = built-in defaults
    geom_provider: object = None    # callable(layer, oid) -> loader.Polyline or None
    area_layers: frozenset = frozenset()  # which of esn/city/zip polygons were annotated
    min_address: int = 0
    max_address: int = 99999
    max_range_gap: int = 2          # STREET-12/13: numbering gap still treated as one run
    street_names_ignored: frozenset = frozenset()
    esn_pad_width: int = 3
    # --- MSAG reconciliation (optional; filled by engine.build_msag_context) ---
    msag_records: Optional[list] = None
    gis_msag: Optional[list] = None
    msag_addr_index: object = None
    msag_match_rate: Optional[float] = None
    min_match_rate: float = 0.98
    authoritative_names: Optional[set] = None  # None => STREET-11 runs degraded

    def name_ignored(self, name_key):
        """True if this street name should be skipped by the name-based checks."""
        nk = (name_key or "").strip().upper()
        return any(ig in nk for ig in self.street_names_ignored)

    def geom(self, layer, oid):
        if self.geom_provider is None:
            return None
        return self.geom_provider(layer, oid)
