"""address_attr checks: one address point at a time, plus the whole-layer duplicate test."""
import re

from .model import ErrorRecord, SEVERITY, FAMILY
from .common import (normalize, get_parity, esn_eq, nguid_partition,
                     side_of_line, p_distance, addr_name_key, street_name_key, _clean,
                     is_addressable)
from . import registry


@registry.check(id="ADDR-02", family=FAMILY.ADDRESS, severity=SEVERITY.ERROR,
                priority="v1-core", target="address")
def check_addr_02(addresses, streets, ctx):
    from collections import defaultdict
    groups = defaultdict(list)
    for a in addresses:
        if not is_addressable(a):
            continue
        comp = normalize(
            str(a.get("Add_Number") or ""), a.get("PREFIX"), a.get("STREET_NA"),
            a.get("TYPE"), a.get("SUFFIX"), a.get("UNIT"), a.get("BLDG"))
        city = normalize(a.get("CITY"))
        if comp:
            groups[(comp, city)].append(a)
    out = []
    for (comp, city), rows in groups.items():
        if len(rows) <= 1:
            continue
        # A non-blank structured sub-address (UNIT/BLDG) that is identical across
        # rows makes them true duplicates regardless of the free-text ADDRESS
        # (a differing ADDRESS there is itself corruption, not a distinguisher).
        # Only when the structured sub-address is blank do we fall back to the
        # ADDRESS string to separate genuinely distinct sub-units; a blank ADDRESS
        # acts as a wildcard that joins every non-empty ADDRESS sub-cluster.
        has_subaddr = any(_clean(a.get("UNIT")) or _clean(a.get("BLDG")) for a in rows)
        if has_subaddr:
            flagged = rows
        else:
            by_addr = defaultdict(list)
            blanks = []
            for a in rows:
                addr = normalize(a.get("ADDRESS"))
                (blanks if not addr else by_addr[addr]).append(a)
            flagged_oids = set()
            # A non-empty ADDRESS sub-cluster is a duplicate when it has >= 2 of its OWN
            # rows (same comp+city+ADDRESS).
            for addr, sub in by_addr.items():
                if len(sub) >= 2:
                    flagged_oids.update(a["_OID"] for a in sub)
            # A blank ADDRESS is a wildcard, but a SINGLE blank row is ambiguous: it
            # cannot prove which distinct sub-address it duplicates. Only bridge blanks
            # to a non-empty sub-cluster when there is exactly ONE such sub-cluster (the
            # match is unambiguous); with multiple distinct sub-clusters, do not flag
            # them via a blank. Blanks still duplicate each other when >= 2.
            if len(by_addr) == 1 and blanks:
                (sub,) = by_addr.values()
                flagged_oids.update(a["_OID"] for a in sub)
                flagged_oids.update(a["_OID"] for a in blanks)
            elif len(blanks) >= 2:
                flagged_oids.update(a["_OID"] for a in blanks)
            flagged = [a for a in rows if a["_OID"] in flagged_oids]
        for a in flagged:
            out.append(ErrorRecord("ADDR-02", "Duplicate full address in city", FAMILY.ADDRESS,
                                   SEVERITY.ERROR, "address", a["_OID"], a.get("Site_NGUID", "") or "",
                                   "duplicate '%s' in %s" % (comp, city), a.get("_XY")))
    return out


@registry.check(id="ADDR-01", family=FAMILY.ADDRESS, severity=SEVERITY.ERROR,
                priority="v1", target="address")
def check_addr_01(addresses, streets, ctx):
    out = []
    for a in addresses:
        if not is_addressable(a):
            continue
        nguid = a.get("Site_NGUID", "") or ""
        xy = a.get("_XY")
        missing = []
        # Add_Number is not checked here: is_addressable already guarantees a positive
        # int-coercible house number, and ADDR-08 reports the non-addressable rows.
        if _clean(a.get("STREET_NA")) == "" and _clean(a.get("St_Name")) == "":
            missing.append("STREET_NA/St_Name")
        if _clean(a.get("CITY")) == "" and _clean(a.get("INC_MUNI")) == "":
            missing.append("CITY/INC_MUNI")
        for fld in ("STATE", "COUNTY", "Country", "ZIP_CODE", "ESN",
                    "STATUS", "Site_NGUID", "DiscrpAgID"):
            if _clean(a.get(fld)) == "":
                missing.append(fld)
        for fld in missing:
            out.append(ErrorRecord("ADDR-01", "Required address field missing", FAMILY.ADDRESS,
                                   SEVERITY.ERROR, "address", a["_OID"], nguid,
                                   "missing required field %s" % fld, xy))
    return out


@registry.check(id="ADDR-03", family=FAMILY.ADDRESS, severity=SEVERITY.WARNING,
                priority="v1", target="address")
def check_addr_03(addresses, streets, ctx):
    out = []
    for a in addresses:
        if not is_addressable(a):
            continue
        num = a.get("Add_Number")   # is_addressable guarantees a positive int-coercible value
        # The ADDRESS text this check expects includes SUFFIX, BLDG and UNIT when present,
        # not just the base name.
        bldg = _clean(a.get("BLDG"))
        unit = _clean(a.get("UNIT"))
        # When the UNIT field merely duplicates BLDG (e.g. BLDG='BLDG 23',
        # UNIT='UNIT BLDG 23' or 'BLDG 23'), the authoritative ADDRESS carries
        # only the BLDG token, so drop the redundant UNIT from the expected join.
        if bldg and re.sub(r"(?i)^UNIT\s+", "", unit).strip().upper() == bldg.upper():
            unit = ""
        parts = [t for t in (str(int(num)), _clean(a.get("PREFIX")), _clean(a.get("STREET_NA")),
                             _clean(a.get("TYPE")), _clean(a.get("SUFFIX")),
                             bldg, unit) if t]
        expected = " ".join(parts)
        if normalize(a.get("ADDRESS")) != normalize(expected):
            out.append(ErrorRecord("ADDR-03", "ADDRESS concatenation mismatch", FAMILY.ADDRESS,
                                   SEVERITY.WARNING, "address", a["_OID"],
                                   a.get("Site_NGUID", "") or "",
                                   "ADDRESS '%s' != expected '%s'" % (_clean(a.get("ADDRESS")), expected),
                                   a.get("_XY")))
    return out


@registry.check(id="ADDR-04", family=FAMILY.ADDRESS, severity=SEVERITY.WARNING,
                priority="v1", target="address")
def check_addr_04(addresses, streets, ctx):
    out = []
    for a in addresses:
        if not is_addressable(a):
            continue
        num = a.get("Add_Number")
        house = _clean(a.get("HOUSE_NU"))   # _clean handles int/None safely
        if house != str(int(num)):
            out.append(ErrorRecord("ADDR-04", "HOUSE_NU does not mirror Add_Number", FAMILY.ADDRESS,
                                   SEVERITY.WARNING, "address", a["_OID"],
                                   a.get("Site_NGUID", "") or "",
                                   "HOUSE_NU '%s' != Add_Number '%s'" % (house, str(int(num))),
                                   a.get("_XY")))
    return out


@registry.check(id="ADDR-05", family=FAMILY.ADDRESS, severity=SEVERITY.WARNING,
                priority="v1", target="address")
def check_addr_05(addresses, streets, ctx):
    cw = ctx.crosswalks
    out = []
    for a in addresses:
        if not is_addressable(a):
            continue
        nguid = a.get("Site_NGUID", "") or ""
        xy = a.get("_XY")

        def emit(sev, desc):
            out.append(ErrorRecord("ADDR-05", "Address domain/bounds violation", FAMILY.ADDRESS,
                                   sev, "address", a["_OID"], nguid, desc, xy))

        status = str(a.get("STATUS", "") or "").strip().upper()
        if status and status != "ACTIVE":   # blank STATUS is ADDR-01's missing-field ERROR
            emit(SEVERITY.WARNING, "STATUS '%s' not in domain (expected ACTIVE)" % status)

        esn = _clean(a.get("ESN"))
        # int(esn) > 0 rejects a sentinel/placeholder ESN of 0 (a numeric 0.0 -> "0"),
        # which is a valid 1-digit numeric string but not a real emergency service number.
        if esn and not (esn.isdigit() and 1 <= len(esn) <= 5 and int(esn) > 0):   # blank = ADDR-01's job
            emit(SEVERITY.ERROR, "ESN '%s' not a valid 1-5 digit ESN" % esn)

        zip_code = _clean(a.get("ZIP_CODE"))
        if zip_code and not (zip_code.isdigit() and len(zip_code) == 5):   # blank = ADDR-01's job
            emit(SEVERITY.ERROR, "ZIP_CODE '%s' not exactly 5 digits" % zip_code)

        num = int(a.get("Add_Number"))   # is_addressable gate guarantees int-coercible
        if num < ctx.min_address or num > ctx.max_address:
            emit(SEVERITY.ERROR, "Add_Number %s out of bounds (%s-%s)"
                 % (num, ctx.min_address, ctx.max_address))

        prefix = _clean(a.get("PREFIX"))
        if prefix and not cw.valid_dir_abbrev(prefix):
            emit(SEVERITY.WARNING, "PREFIX '%s' not in directional domain" % prefix)

        rtype = _clean(a.get("TYPE"))
        if rtype and not cw.valid_type_abbrev(rtype):
            emit(SEVERITY.WARNING, "TYPE '%s' not a RoadType domain value" % rtype)
    return out


@registry.check(id="ADDR-06", family=FAMILY.ADDRESS, severity=SEVERITY.ERROR,
                priority="v1", target="address")
def check_addr_06(addresses, streets, ctx):
    out = []
    for a in addresses:
        nguid = a.get("Site_NGUID", "") or ""
        # A BLANK Site_NGUID is owned elsewhere: ADDR-01 reports it as a missing required
        # field on addressable rows, ADDR-08 reports the placeholder rows. ADDR-06 only
        # validates the FORMAT/agency of a non-blank NGUID, so skip blanks entirely.
        if not _clean(nguid):
            continue
        xy = a.get("_XY")

        def emit(desc):
            out.append(ErrorRecord("ADDR-06", "Site_NGUID format/agency mismatch", FAMILY.ADDRESS,
                                   SEVERITY.ERROR, "address", a["_OID"], nguid, desc, xy))

        loc, auth = nguid_partition(nguid)
        if loc is None:
            emit("Site_NGUID '%s' is not '<localid>@<authority>'" % nguid)
            continue
        agid = _clean(a.get("DiscrpAgID"))
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", loc):
            emit("Site_NGUID localid '%s' has invalid characters" % loc)
        # Check the NGUID authority always; check DiscrpAgID only when non-blank — a
        # blank DiscrpAgID is ADDR-01's missing-field ERROR, not a second ADDR-06 one.
        # Compare case-insensitively: the authority is a domain (case-insensitive by RFC),
        # so 'domain' vs 'Domain' casing is not a real mismatch.
        exp = ctx.expected_agid
        if auth.casefold() != exp.casefold():
            emit("authority '%s' != expected '%s'" % (auth, exp))
        elif agid and agid.casefold() != exp.casefold():
            emit("DiscrpAgID '%s' != expected '%s'" % (agid, exp))
    return out


_PROHIBITED_CHARS = set("\\#^!@")


@registry.check(id="ADDR-07", family=FAMILY.ADDRESS, severity=SEVERITY.WARNING,
                priority="v2", target="both")
def check_addr_07(addresses, streets, ctx):
    out = []

    def scan(row, target, oid, nguid, xy, space_fields, prohibited_fields):
        fam = FAMILY.STREET if target == "street" else FAMILY.ADDRESS
        for fld in space_fields:
            v = row.get(fld)
            if v is None:
                continue
            v = str(v)
            if not v.strip():
                continue
            if v != v.strip():
                out.append(ErrorRecord("ADDR-07", "Leading/trailing spaces or prohibited chars",
                                       fam, SEVERITY.WARNING, target, oid, nguid,
                                       "%s '%s' has leading/trailing whitespace" % (fld, v), xy))
        for fld in prohibited_fields:
            v = row.get(fld)
            if v is None:
                continue
            v = str(v)
            bad = [c for c in v if c in _PROHIBITED_CHARS]
            if bad:
                out.append(ErrorRecord("ADDR-07", "Leading/trailing spaces or prohibited chars",
                                       fam, SEVERITY.WARNING, target, oid, nguid,
                                       "%s '%s' contains prohibited char(s) %s" % (fld, v, "".join(sorted(set(bad)))),
                                       xy))
            if v.strip().upper() == "NULL":
                out.append(ErrorRecord("ADDR-07", "Leading/trailing spaces or prohibited chars",
                                       fam, SEVERITY.WARNING, target, oid, nguid,
                                       "%s contains literal 'NULL' token" % fld, xy))

    for a in addresses:
        scan(a, "address", a["_OID"], a.get("Site_NGUID", "") or "", a.get("_XY"),
             ("CITY", "STREET_NA", "PREFIX", "TYPE"),
             ("STREET_NA", "TYPE", "UNIT"))
    for s in streets:
        scan(s, "street", s["_OID"], s.get("RCL_NGUID", "") or "", s.get("_XY"),
             ("NAME", "PREFIX", "TYPE", "RCITY", "LCITY"),
             ("NAME", "TYPE"))
    return out


@registry.check(id="ADDR-08", family=FAMILY.ADDRESS, severity=SEVERITY.WARNING,
                priority="v1", target="address")
def check_addr_08(addresses, streets, ctx):
    """Incomplete / non-addressed points: reported ONCE here so the address-content
    checks (ADDR-01..06, XLAYER-01..04/12) can skip them via is_addressable() without
    losing visibility. A record is incomplete if it has no positive house number or no
    street name."""
    out = []
    for a in addresses:
        if is_addressable(a):
            continue
        num = a.get("Add_Number")
        nm = _clean(a.get("_NAMEKEY"))
        try:
            no_num = int(num) <= 0   # mirror is_addressable: tolerate float/str Add_Number
        except (TypeError, ValueError):
            no_num = True
        if no_num and not nm:
            msg = "missing house number and street name"
        elif no_num:
            msg = "missing house number (street name '%s' present)" % nm
        else:
            msg = "missing street name (Add_Number=%s)" % num
        out.append(ErrorRecord(
            "ADDR-08", "Incomplete / non-addressed point", FAMILY.ADDRESS,
            SEVERITY.WARNING, "address", a["_OID"], a.get("Site_NGUID", "") or "",
            msg, a.get("_XY")))
    return out
