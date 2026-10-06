import json
import os

# Reference crosswalk data is bundled inside the package (portable — no machine paths).
_REF = os.path.join(os.path.dirname(os.path.abspath(__file__)), "reference")
ADM_DOMAINS = os.path.join(_REF, "adm_domains.json")
MAPSAG_DOMAINS = os.path.join(_REF, "mapsag_domains.json")

# Hardcoded directional fallback (used only if MapSAG domain is unavailable).
_DIR = {
    "N": "NORTH", "S": "SOUTH", "E": "EAST", "W": "WEST",
    "NE": "NORTHEAST", "NW": "NORTHWEST", "SE": "SOUTHEAST", "SW": "SOUTHWEST",
}

STATES = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI", "ID",
    "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS",
    "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH", "OK",
    "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV",
    "WI", "WY", "DC", "PR", "VI", "GU", "AS", "MP",
}

FL_COUNTIES = {"EXAMPLE", "ALACHUA", "LAKE", "SUMTER", "CITRUS", "LEVY", "PUTNAM", "VOLUSIA"}

COUNTRIES = {"US", "USA", "UNITED STATES", "UNITED STATES OF AMERICA"}


def county_canonical(name):
    """Normalize a county value for comparison: upper, strip, drop a trailing ' COUNTY'.
    'Example County' -> 'EXAMPLE'."""
    v = (name or "").strip().upper()
    if v.endswith(" COUNTY"):
        v = v[: -len(" COUNTY")].strip()
    return v


class Crosswalks:
    def __init__(self, dir_map, type_map, dir_pairs, type_pairs,
                 premod, postmod, pretypesep):
        self._dir = dir_map                # abbrev(upper) -> representative full(upper)
        self._type = type_map              # abbrev(upper) -> representative full(upper)
        self._dir_pairs = dir_pairs        # set of (abbrev_upper, full_upper)
        self._type_pairs = type_pairs      # set of (abbrev_upper, full_upper)
        self._type_values = {f for (_a, f) in type_pairs}  # spelled-out forms (e.g. VIEW)
        self._dir_values = {f for (_a, f) in dir_pairs}    # spelled-out forms (e.g. NORTHWEST)
        self._premod = premod              # set of valid upper values (full + abbrev)
        self._postmod = postmod
        self._pretypesep = pretypesep
        self.states = STATES
        self.fl_counties = FL_COUNTIES
        self.countries = COUNTRIES

    # --- representative full-name lookups (back-compat) ---
    def dir_full(self, abbrev):
        return self._dir.get((abbrev or "").strip().upper())

    def type_full(self, abbrev):
        return self._type.get((abbrev or "").strip().upper())

    # --- abbreviation membership ---
    def valid_dir_abbrev(self, abbrev):
        # Accept a known abbreviation OR an already-spelled-out direction (Example may
        # store 'NORTHWEST' in PREFIX); mirrors valid_type_abbrev.
        v = (abbrev or "").strip().upper()
        return v in self._dir or v in self._dir_values

    def valid_type_abbrev(self, abbrev):
        # Valid if it is a known abbreviation OR an already-spelled-out type name
        # (Example stores e.g. 'VIEW' rather than 'VW'); the crosswalk maps VW<->VIEW.
        v = (abbrev or "").strip().upper()
        return v in self._type or v in self._type_values

    # --- pair validity (handles AVE->AVENUE/AVENIDA, etc.) ---
    def dir_ok(self, abbrev, full):
        a = (abbrev or "").strip().upper()
        f = (full or "").strip().upper()
        if (a, f) in self._dir_pairs or (f, a) in self._dir_pairs:  # either spelling order
            return True
        # Identical tokens trivially agree (avoid a self-contradictory "NE != NE").
        return bool(a) and a == f

    def type_ok(self, abbrev, full):
        a = (abbrev or "").strip().upper()
        f = (full or "").strip().upper()
        if (a, f) in self._type_pairs:
            return True
        # Either spelling order agrees: the stored pairs are (abbrev, full), so also
        # accept the reverse (full TYPE, abbrev St_PosTyp), e.g. ('AVENUE','AVE').
        if (f, a) in self._type_pairs:
            return True
        # Identical values trivially agree (avoids a self-contradictory "X != X"
        # message when both TYPE and St_PosTyp store the same token, abbrev or full,
        # e.g. Example's spelled-out 'VIEW' mirrored in St_PosTyp).
        return bool(a) and a == f

    # --- NENA modifier / separator domains ---
    def valid_premod(self, v):
        return (v or "").strip().upper() in self._premod

    def valid_postmod(self, v):
        return (v or "").strip().upper() in self._postmod

    def valid_pretypesep(self, v):
        return (v or "").strip().upper() in self._pretypesep

    @staticmethod
    def county_canonical(name):
        return county_canonical(name)


def _load_json(path):
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def _pairs_to_maps(pairs):
    """pairs = [[full, abbrev], ...] -> (abbrev->full map [last wins], set of (abbrev,full))."""
    amap, pset = {}, set()
    for full, abbrev in pairs:
        fu, au = full.strip().upper(), abbrev.strip().upper()
        # Keep the SHORTEST full form as the representative (the canonical singular,
        # e.g. PARK over PARKS, AVENUE over AVENIDA), independent of list order.
        if au not in amap or len(fu) < len(amap[au]):
            amap[au] = fu
        pset.add((au, fu))
    return amap, pset


def _value_set(pairs):
    """All full + abbrev values (upper) for membership tests on modifier/sep domains."""
    s = set()
    for full, abbrev in pairs:
        s.add(full.strip().upper())
        s.add(abbrev.strip().upper())
    return s


def load_crosswalks(adm_domains_path=ADM_DOMAINS, mapsag_path=MAPSAG_DOMAINS):
    """Authoritative source is MapSAG's own domains (mapsag_domains.json); ADM RoadType
    is a fallback for any type abbreviations MapSAG does not cover."""
    mapsag = _load_json(mapsag_path)

    def pairs(key):
        return mapsag.get(key, {}).get("pairs", [])

    dir_map, dir_pairs = _pairs_to_maps(pairs("direction"))
    if not dir_map:
        dir_map = dict(_DIR)
        dir_pairs = {(a, f) for a, f in _DIR.items()}

    # type = union of MapSAG pretype + posttype, with ADM RoadType as fallback.
    type_pairs_list = pairs("pretype") + pairs("posttype")
    type_map, type_pairs = _pairs_to_maps(type_pairs_list)
    adm = _load_json(adm_domains_path)
    rt = adm.get("RoadType", {}).get("values", {})  # {"Rd": "Road", ...}
    for abbrev, full in rt.items():
        au, fu = abbrev.strip().upper(), full.strip().upper()
        type_pairs.add((au, fu))
        type_map.setdefault(au, fu)   # MapSAG wins; ADM only fills gaps

    return Crosswalks(
        dir_map, type_map, dir_pairs, type_pairs,
        _value_set(pairs("premod")), _value_set(pairs("postmod")), _value_set(pairs("pretypesep")),
    )
