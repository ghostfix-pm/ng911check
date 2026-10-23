"""Street-name domains: directionals and street types, plus any domain the user supplies.

The built-in tables come from the United States Postal Service, Publication 28, Postal
Addressing Standards: section 233 (the eight directionals) and Appendix C1 (primary street
suffix names and their standard abbreviations). No vendor or agency domain file ships with
this package. A user who needs a stricter or longer list supplies it as a CSV (see
load_domain_csv) and it is added to the built-ins.

Pub 28 lists several commonly used variants for some suffixes (for example AV and AVN for
AVENUE). Only the primary name and the standard abbreviation are built in, so a variant
reads as an unmapped TYPE until the user adds it.
"""
import csv

DIRECTIONS = (("NORTH", "N"), ("SOUTH", "S"), ("EAST", "E"), ("WEST", "W"),
              ("NORTHEAST", "NE"), ("NORTHWEST", "NW"), ("SOUTHEAST", "SE"),
              ("SOUTHWEST", "SW"))

# PRIMARY=ABBREVIATION, Pub 28 Appendix C1.
_C1 = """
    ALLEY=ALY ANEX=ANX ARCADE=ARC AVENUE=AVE BAYOU=BYU BEACH=BCH
    BEND=BND BLUFF=BLF BLUFFS=BLFS BOTTOM=BTM BOULEVARD=BLVD BRANCH=BR
    BRIDGE=BRG BROOK=BRK BROOKS=BRKS BURG=BG BURGS=BGS BYPASS=BYP
    CAMP=CP CANYON=CYN CAPE=CPE CAUSEWAY=CSWY CENTER=CTR CENTERS=CTRS
    CIRCLE=CIR CIRCLES=CIRS CLIFF=CLF CLIFFS=CLFS CLUB=CLB COMMON=CMN
    COMMONS=CMNS CORNER=COR CORNERS=CORS COURSE=CRSE COURT=CT COURTS=CTS
    COVE=CV COVES=CVS CREEK=CRK CRESCENT=CRES CREST=CRST CROSSING=XING
    CROSSROAD=XRD CROSSROADS=XRDS CURVE=CURV DALE=DL DAM=DM DIVIDE=DV
    DRIVE=DR DRIVES=DRS ESTATE=EST ESTATES=ESTS EXPRESSWAY=EXPY EXTENSION=EXT
    EXTENSIONS=EXTS FALL=FALL FALLS=FLS FERRY=FRY FIELD=FLD FIELDS=FLDS
    FLAT=FLT FLATS=FLTS FORD=FRD FORDS=FRDS FOREST=FRST FORGE=FRG
    FORGES=FRGS FORK=FRK FORKS=FRKS FORT=FT FREEWAY=FWY GARDEN=GDN
    GARDENS=GDNS GATEWAY=GTWY GLEN=GLN GLENS=GLNS GREEN=GRN GREENS=GRNS
    GROVE=GRV GROVES=GRVS HARBOR=HBR HARBORS=HBRS HAVEN=HVN HEIGHTS=HTS
    HIGHWAY=HWY HILL=HL HILLS=HLS HOLLOW=HOLW INLET=INLT ISLAND=IS
    ISLANDS=ISS ISLE=ISLE JUNCTION=JCT JUNCTIONS=JCTS KEY=KY KEYS=KYS
    KNOLL=KNL KNOLLS=KNLS LAKE=LK LAKES=LKS LAND=LAND LANDING=LNDG
    LANE=LN LIGHT=LGT LIGHTS=LGTS LOAF=LF LOCK=LCK LOCKS=LCKS
    LODGE=LDG LOOP=LOOP MALL=MALL MANOR=MNR MANORS=MNRS MEADOW=MDW
    MEADOWS=MDWS MEWS=MEWS MILL=ML MILLS=MLS MISSION=MSN MOTORWAY=MTWY
    MOUNT=MT MOUNTAIN=MTN MOUNTAINS=MTNS NECK=NCK ORCHARD=ORCH OVAL=OVAL
    OVERPASS=OPAS PARK=PARK PARKS=PARK PARKWAY=PKWY PARKWAYS=PKWY PASS=PASS
    PASSAGE=PSGE PATH=PATH PIKE=PIKE PINE=PNE PINES=PNES PLACE=PL
    PLAIN=PLN PLAINS=PLNS PLAZA=PLZ POINT=PT POINTS=PTS PORT=PRT
    PORTS=PRTS PRAIRIE=PR RADIAL=RADL RAMP=RAMP RANCH=RNCH RAPID=RPD
    RAPIDS=RPDS REST=RST RIDGE=RDG RIDGES=RDGS RIVER=RIV ROAD=RD
    ROADS=RDS ROUTE=RTE ROW=ROW RUE=RUE RUN=RUN SHOAL=SHL
    SHOALS=SHLS SHORE=SHR SHORES=SHRS SKYWAY=SKWY SPRING=SPG SPRINGS=SPGS
    SPUR=SPUR SPURS=SPUR SQUARE=SQ SQUARES=SQS STATION=STA STRAVENUE=STRA
    STREAM=STRM STREET=ST STREETS=STS SUMMIT=SMT TERRACE=TER THROUGHWAY=TRWY
    TRACE=TRCE TRACES=TRCE TRACK=TRAK TRACKS=TRAK TRAFFICWAY=TRFY TRAIL=TRL
    TRAILS=TRL TRAILER=TRLR TUNNEL=TUNL TURNPIKE=TPKE UNDERPASS=UPAS UNION=UN
    UNIONS=UNS VALLEY=VLY VALLEYS=VLYS VIADUCT=VIA VIEW=VW VIEWS=VWS
    VILLAGE=VLG VILLAGES=VLGS VILLE=VL VISTA=VIS WALK=WALK WALKS=WALK
    WALL=WALL WAY=WAY WAYS=WAYS WELL=WL WELLS=WLS"""

STREET_TYPES = tuple(tuple(item.split("=")) for item in _C1.split())

STATES = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI", "ID",
    "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS",
    "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH", "OK",
    "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV",
    "WI", "WY", "DC", "PR", "VI", "GU", "AS", "MP",
}

COUNTRIES = {"US", "USA", "UNITED STATES", "UNITED STATES OF AMERICA"}

DOMAIN_KINDS = ("direction", "type", "premod", "postmod", "pretypesep")


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
        self.countries = COUNTRIES

    # --- representative full-name lookups ---
    def dir_full(self, abbrev):
        return self._dir.get((abbrev or "").strip().upper())

    def type_full(self, abbrev):
        return self._type.get((abbrev or "").strip().upper())

    # --- abbreviation membership ---
    def valid_dir_abbrev(self, abbrev):
        # Accept a known abbreviation OR an already-spelled-out direction ('NORTHWEST'
        # stored in PREFIX); mirrors valid_type_abbrev.
        v = (abbrev or "").strip().upper()
        return v in self._dir or v in self._dir_values

    def valid_type_abbrev(self, abbrev):
        # Valid if it is a known abbreviation OR an already-spelled-out type name
        # ('VIEW' stored rather than 'VW'); the crosswalk maps VW<->VIEW.
        v = (abbrev or "").strip().upper()
        return v in self._type or v in self._type_values

    # --- pair validity (handles AVE->AVENUE and any user-supplied alias) ---
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
        # message when both TYPE and St_PosTyp store the same token, abbrev or full).
        return bool(a) and a == f

    # --- NENA modifier / separator domains (user supplied; empty by default) ---
    def has_modifier_domains(self):
        return bool(self._premod or self._postmod or self._pretypesep)

    def valid_premod(self, v):
        return (v or "").strip().upper() in self._premod

    def valid_postmod(self, v):
        return (v or "").strip().upper() in self._postmod

    def valid_pretypesep(self, v):
        return (v or "").strip().upper() in self._pretypesep

    @staticmethod
    def county_canonical(name):
        return county_canonical(name)


def _pairs_to_maps(pairs):
    """pairs = [(full, abbrev), ...] -> (abbrev->full map, set of (abbrev, full)).

    The shortest full form is the representative (PARK over PARKS), independent of list order."""
    amap, pset = {}, set()
    for full, abbrev in pairs:
        fu, au = full.strip().upper(), abbrev.strip().upper()
        if au not in amap or len(fu) < len(amap[au]):
            amap[au] = fu
        pset.add((au, fu))
    return amap, pset


def _value_set(pairs):
    """All full + abbrev values (upper) for membership tests on modifier/sep domains."""
    s = set()
    for full, abbrev in pairs:
        for v in (full.strip().upper(), abbrev.strip().upper()):
            if v:
                s.add(v)
    return s


def load_domain_csv(path):
    """Read a user domain file: header `domain,full,abbrev`, one value per row.

    `domain` is one of direction, type, premod, postmod, pretypesep. `abbrev` may be blank
    for the three modifier kinds. Returns a list of (domain, full, abbrev). Raises ValueError
    with the line number on a bad row, because a silently dropped row would shrink a domain."""
    rows = []
    with open(path, "r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.reader(fh)
        header = [(h or "").strip().lower() for h in next(reader, [])]
        if header[:3] != ["domain", "full", "abbrev"]:
            raise ValueError("%s: the header must be domain,full,abbrev" % path)
        for rec in reader:
            if not any(c.strip() for c in rec):
                continue
            rec = (list(rec) + ["", "", ""])[:3]
            kind, full, abbrev = rec[0].strip().lower(), rec[1].strip(), rec[2].strip()
            if kind not in DOMAIN_KINDS:
                raise ValueError("%s line %d: domain %r is not one of %s"
                                 % (path, reader.line_num, kind, ", ".join(DOMAIN_KINDS)))
            if not full:
                raise ValueError("%s line %d: full is blank" % (path, reader.line_num))
            if kind in ("direction", "type") and not abbrev:
                raise ValueError("%s line %d: a %s row needs an abbrev"
                                 % (path, reader.line_num, kind))
            rows.append((kind, full, abbrev))
    return rows


def load_crosswalks(extra=None):
    """The built-in Pub 28 tables plus `extra`, a list of (domain, full, abbrev)."""
    extra = extra or []

    def of(kind):
        return [(f, a) for (k, f, a) in extra if k == kind]

    dir_map, dir_pairs = _pairs_to_maps(list(DIRECTIONS) + of("direction"))
    type_map, type_pairs = _pairs_to_maps(list(STREET_TYPES) + of("type"))
    return Crosswalks(
        dir_map, type_map, dir_pairs, type_pairs,
        _value_set(of("premod")), _value_set(of("postmod")), _value_set(of("pretypesep")),
    )
