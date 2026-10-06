"""Small value helpers every check module shares."""
import re

_WS = re.compile(r"\s+")


def _clean(v):
    """None/''/' ' -> '' ; else stripped str. An integer-valued float (a numeric Double
    field such as ESN or ZIP read as 13.0) renders as '13', not '13.0'."""
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v).strip()


def seg_label(row):
    """How a street segment is named in a finding: its SEGMENT_ID, or "OID n" when that
    is blank. SEGMENT_ID is often a Double, so interpolating it raw would print
    "SEG 36247.0", a value that matches nothing when pasted into a definition query."""
    return _clean(row.get("SEGMENT_ID")) or "OID %s" % row.get("_OID")


def is_addressable(a):
    """True if the row is a real, validatable address: a positive house number AND a
    street name. Placeholder rows (house number 0, blank name) are reported once by
    ADDR-08, not re-flagged by every address-content check."""
    num = a.get("Add_Number")
    try:
        num = int(num)
    except (TypeError, ValueError):
        return False
    return num > 0 and bool((a.get("_NAMEKEY") or "").strip())


def normalize(*vals):
    """Upper, strip, drop blanks, strip apostrophes, collapse internal whitespace."""
    toks = []
    for v in vals:
        s = _clean(v).upper().replace("'", "")
        if s:
            toks.append(s)
    return _WS.sub(" ", " ".join(toks)).strip()


def get_parity(frm, to):
    # NULL treated as 0 so a both-empty range reads "0-0" (non-addressable) instead of
    # the "Error" sentinel that made STREET-01 false-positive on NULL segments.
    frm, to = frm or 0, to or 0
    if frm == 0 or to == 0:
        return "0-0" if (frm == 0 and to == 0) else "Error"
    if frm % 2 == 0 and to % 2 == 0:
        return "Even"
    if frm % 2 != 0 and to % 2 != 0:
        return "Odd"
    return "Both"


def esn_eq(a, b):
    """True/False if comparable; None if either side blank (caller skips)."""
    sa, sb = _clean(a), _clean(b)
    if sa == "" or sb == "":
        return None
    if sa.isdigit() and sb.isdigit():
        return int(sa) == int(sb)
    return sa.upper() == sb.upper()


def nguid_partition(val):
    """Split '<localid>@<authority>' at the FIRST @. Returns (None, None) if malformed."""
    g = _clean(val)
    i = g.find("@")
    if i < 1:
        return (None, None)
    return (g[:i], g[i + 1:])


def side_of_line(x, y, x1, y1, x2, y2):
    d = (x - x1) * (y2 - y1) - (y - y1) * (x2 - x1)
    if d > 0:
        return "Right"
    if d < 0:
        return "Left"
    return None


def p_distance(x, y, x1, y1, x2, y2):
    """Distance from point to segment, and the foot point."""
    A, B, Cc, D = x - x1, y - y1, x2 - x1, y2 - y1
    dot = A * Cc + B * D
    len_sq = Cc * Cc + D * D
    param = dot / len_sq if len_sq else -1
    if param < 0:
        xx, yy = x1, y1
    elif param > 1:
        xx, yy = x2, y2
    else:
        xx, yy = x1 + param * Cc, y1 + param * D
    return (((x - xx) ** 2 + (y - yy) ** 2) ** 0.5, (xx, yy))


def addr_name_key(row):
    """Address street-name key from the component fields. COMPARE is NOT used: it is an
    optional QC-only field, so keying on it produced stale-cache mismatches.
    Key = PREFIX+STREET_NA+TYPE+SUFFIX."""
    return normalize(row.get("PREFIX"), row.get("STREET_NA"), row.get("TYPE"), row.get("SUFFIX"))


def street_name_key(row):
    """Street name key from the component fields (COMPARE not used; see addr_name_key).
    Key = PREFIX+NAME+TYPE+SUFFIX."""
    return normalize(row.get("PREFIX"), row.get("NAME"), row.get("TYPE"), row.get("SUFFIX"))
