"""Read the input layers from CSV or GeoJSON, and put their geometry in planar feet.

This is the only module that opens an input layer. Everything it returns is plain dicts and
tuples, so the checks never see a file. A row is a dict of column name to value, plus:

    _OID      the 1-based position of the row in the file (a CSV data row, a GeoJSON feature)
    _NAMEKEY  the normalized street name, built from the name columns (common.addr_name_key)
    _XY       (x, y) in planar feet once finalize_layer has run, else None

Values are NOT stripped: ADDR-07 exists to find leading and trailing spaces. The columns that
the checks do arithmetic on are converted to int. A street range column that is not a whole
number refuses the file, because reading it as blank would make a broken range look unused.

CSV carries points only (optional X and Y columns). GeoJSON carries points for addresses and
LineString or MultiLineString for streets, plus Polygon or MultiPolygon for response areas.
Coordinates are longitude then latitude, as RFC 7946 section 3.1.1 requires.
"""
import csv
import json
import math
import os

from .common import addr_name_key, street_name_key
from .geometry import NULL_ISLAND, Polyline, point_in_polygon

ADDRESS_COLUMNS = (
    "Add_Number", "PREFIX", "STREET_NA", "TYPE", "SUFFIX", "UNIT", "BLDG", "ADDRESS",
    "HOUSE_NU", "CITY", "INC_MUNI", "STATE", "COUNTY", "Country", "ZIP_CODE", "ESN", "STATUS",
    "Site_NGUID", "DiscrpAgID", "COMPARE", "St_Name", "St_PreDir", "St_PosTyp", "St_PreTyp",
    "St_PreMod", "St_PosMod", "St_PreSep")
STREET_COLUMNS = (
    "SEGMENT_ID", "RCL_NGUID", "NAME", "PREFIX", "TYPE", "SUFFIX", "FROMLEFT", "TOLEFT",
    "FROMRIGHT", "TORIGHT", "Parity_L", "Parity_R", "ONEWAY", "LCITY", "RCITY", "LESN", "RESN",
    "LEFTZIP", "RIGHTZIP", "State_L", "State_R", "County_L", "County_R", "IncMuni_L",
    "IncMuni_R", "St_Name", "St_PreDir", "St_PosTyp", "St_PreTyp", "St_PreMod", "St_PosMod",
    "St_PreSep", "DiscrpAgID", "COMPARE")
_NUMERIC = {"addresses": ("Add_Number",),
            "streets": ("FROMLEFT", "TOLEFT", "FROMRIGHT", "TORIGHT")}
_HARD = {"addresses": False, "streets": True}   # a bad number refuses the file, or stays text
_KNOWN = {"addresses": ADDRESS_COLUMNS, "streets": STREET_COLUMNS}
_NAMEKEY = {"addresses": addr_name_key, "streets": street_name_key}

LAYERS = ("addresses", "streets")


class Layer(object):
    """The rows of one input layer and the raw geometry that goes with them."""

    def __init__(self, name, path, columns, rows, lines):
        self.name = name
        self.path = path
        self.columns = columns    # the column names the file actually has
        self.rows = rows
        self.lines = lines        # {oid: [part, ...]} of raw (x, y) pairs; streets only

    def raw_coords(self):
        for row in self.rows:
            if row["_RAW"] is not None:
                yield row["_RAW"]
        for parts in self.lines.values():
            for part in parts:
                for pair in part:
                    yield pair

    def missing_columns(self):
        """The columns the checks read that this file does not have."""
        return [c for c in _KNOWN[self.name] if c not in self.columns]


def parse_renames(items):
    """`LAYER:ACTUAL=CANONICAL` strings -> {layer: {ACTUAL: CANONICAL}}. Refuses a bad one."""
    out = {name: {} for name in LAYERS}
    for item in items or ():
        layer, sep, pair = item.partition(":")
        actual, eq, canonical = pair.partition("=")
        if not sep or not eq or layer not in out or not actual.strip() or not canonical.strip():
            raise ValueError("--rename %r: expected LAYER:ACTUAL=CANONICAL where LAYER is "
                             "addresses or streets" % item)
        out[layer][actual.strip()] = canonical.strip()
    return out


def _fail(where, msg):
    raise ValueError("%s: %s" % (where, msg))


def _number(value, field, where, hard):
    """Blank -> None; a whole number -> int; anything else is text (soft) or an error (hard)."""
    if value is None or (isinstance(value, str) and value.strip() == ""):
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        f = None
    if f is not None and math.isfinite(f) and f.is_integer() and not isinstance(value, bool):
        return int(f)
    if hard:
        _fail(where, "%s %r is not a whole number" % (field, value))
    return value


def _rename_row(row, renames, where):
    for actual, canonical in renames.items():
        if actual in row:
            if canonical in row:
                _fail(where, "cannot rename %s to %s: the file already has a %s column"
                      % (actual, canonical, canonical))
            row[canonical] = row.pop(actual)


def _finish_row(row, name, oid, where):
    for field in _NUMERIC[name]:
        if field in row:
            row[field] = _number(row[field], field, where, _HARD[name])
    row["_OID"] = oid
    row["_NAMEKEY"] = _NAMEKEY[name](row)


def _plain_values(row, name, where):
    """A GeoJSON number in a text column becomes the text a CSV would hold. A list, an
    object or a boolean refuses the file, because no check can read it."""
    for key, value in list(row.items()):
        if value is None or isinstance(value, str):
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            _fail(where, "property %s must be a string, a number or null, got %r"
                  % (key, value))
        if key not in _NUMERIC[name]:
            row[key] = "%d" % value if float(value).is_integer() else repr(value)


def _finite(v):
    """A JSON number that is finite as a float. A huge integer, 10**400, is not."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return False
    try:
        return math.isfinite(v)
    except OverflowError:
        return False


def _pair(pos, where):
    ok = isinstance(pos, list) and len(pos) >= 2 and all(_finite(v) for v in pos[:2])
    if not ok:
        _fail(where, "a position must be [x, y] with two finite numbers, got %r" % (pos,))
    return (float(pos[0]), float(pos[1]))


def _read_csv(path, name, renames, x_field, y_field):
    rows = []
    with open(path, "r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.reader(fh)
        header = [h.strip() for h in next(reader, [])]
        if not any(header):
            _fail(path, "the file has no header row")
        dupes = sorted({h for h in header if header.count(h) > 1})
        if dupes:
            _fail(path, "duplicate column name(s): %s" % ", ".join(dupes))
        header = [renames.get(h, h) for h in header]
        if len(set(header)) != len(header):
            _fail(path, "a --rename makes two columns share one name")
        has_xy = x_field in header and y_field in header
        for values in reader:
            if not any(v.strip() for v in values):
                continue
            where = "%s line %d" % (path, reader.line_num)
            row = dict(zip(header, values))
            for h in header[len(values):]:
                row[h] = ""
            raw = None
            if has_xy:
                xs, ys = row[x_field].strip(), row[y_field].strip()
                if xs or ys:
                    try:
                        raw = _pair([float(xs), float(ys)], where)
                    except ValueError:
                        _fail(where, "%s %r and %s %r must both be numbers"
                              % (x_field, xs, y_field, ys))
            row["_RAW"] = raw
            _finish_row(row, name, len(rows) + 1, where)
            rows.append(row)
    return Layer(name, path, set(header), rows, {})


def _load_json(path):
    with open(path, "r", encoding="utf-8-sig") as fh:
        try:
            doc = json.load(fh)
        except ValueError as exc:
            _fail(path, "not valid JSON (%s)" % exc)
    if not isinstance(doc, dict) or doc.get("type") != "FeatureCollection" \
            or not isinstance(doc.get("features"), list):
        _fail(path, "expected a GeoJSON FeatureCollection with a features list")
    return doc["features"]


def _geometry(feature, where):
    geom = feature.get("geometry") if isinstance(feature, dict) else None
    if geom is None:
        return None, None
    if not isinstance(geom, dict) or not isinstance(geom.get("coordinates"), list):
        _fail(where, "geometry must be null or an object with coordinates")
    return geom.get("type"), geom["coordinates"]


def _read_geojson(path, name, renames):
    rows, lines, columns = [], {}, set()
    for index, feature in enumerate(_load_json(path), start=1):
        where = "%s feature %d" % (path, index)
        props = feature.get("properties") if isinstance(feature, dict) else None
        row = dict(props) if isinstance(props, dict) else {}
        _rename_row(row, renames, where)
        _plain_values(row, name, where)
        columns.update(row)
        kind, coords = _geometry(feature, where)
        raw = None
        if kind is None:
            pass
        elif name == "addresses" and kind == "Point":
            raw = _pair(coords, where)
        elif name == "streets" and kind == "LineString":
            lines[index] = [[_pair(p, where) for p in coords]]
        elif name == "streets" and kind == "MultiLineString":
            lines[index] = [[_pair(p, where) for p in part] for part in coords]
        else:
            _fail(where, "a %s layer cannot hold a %s geometry (addresses take Point, "
                  "streets take LineString or MultiLineString)" % (name, kind))
        if index in lines and (not lines[index] or any(len(part) < 2 for part in lines[index])):
            _fail(where, "a line part needs at least two positions")
        row["_RAW"] = raw
        _finish_row(row, name, index, where)
        rows.append(row)
    return Layer(name, path, columns, rows, lines)


def read_layer(path, name, renames=None, x_field="X", y_field="Y"):
    """Read one layer. The file type comes from the extension: .csv, .geojson or .json.

    `renames` is {ACTUAL: CANONICAL} for this layer (see parse_renames)."""
    renames = renames or {}
    ext = os.path.splitext(path)[1].lower()
    if ext == ".csv":
        layer = _read_csv(path, name, renames, x_field, y_field)
    elif ext in (".geojson", ".json"):
        layer = _read_geojson(path, name, renames)
    else:
        raise ValueError("%s: unsupported file type %r (use .csv, .geojson or .json)"
                         % (path, ext))
    if not layer.rows:
        _fail(path, "the %s file has no rows, so nothing was checked. An empty file passes "
              "as clean; re-export the layer or point --%s at the right file." % (name, name))
    return layer


def read_areas(path, key_prop):
    """Read a polygon layer: a list of (key, rings) with raw coordinates.

    Each ring list is [outer, hole, ...]. A MultiPolygon becomes one entry per polygon, all
    with the same key."""
    areas = []
    for index, feature in enumerate(_load_json(path), start=1):
        where = "%s feature %d" % (path, index)
        props = feature.get("properties") if isinstance(feature, dict) else None
        if not isinstance(props, dict) or key_prop not in props:
            _fail(where, "no %r property to use as the area key" % key_prop)
        kind, coords = _geometry(feature, where)
        if kind == "Polygon":
            polygons = [coords]
        elif kind == "MultiPolygon":
            polygons = coords
        else:
            _fail(where, "an area layer takes Polygon or MultiPolygon, got %s" % kind)
        for poly in polygons:
            rings = [[_pair(p, where) for p in ring] for ring in poly]
            if not rings or any(len(r) < 4 or r[0] != r[-1] for r in rings):
                _fail(where, "a polygon ring needs at least four positions and must close "
                      "(first position equal to last)")
            areas.append((props[key_prop], rings))
    return areas


# ----------------------------------------------------------------- planar feet

def finalize_layer(layer, frame):
    """Give every row its _XY in planar feet and return {oid: Polyline} for the layer."""
    geoms = {}
    degrees = frame.units == "degrees"
    for oid, parts in layer.lines.items():
        if degrees and any(p == NULL_ISLAND for part in parts for p in part):
            _fail("%s feature %d" % (layer.path, oid), "a street vertex is at 0, 0, which is not "
                  "a position in a degrees file. Remove or fix the vertex.")
        geoms[oid] = Polyline([[frame.forward(x, y) for x, y in part] for part in parts])
    for row in layer.rows:
        raw = row.pop("_RAW")
        if degrees and raw == NULL_ISLAND:
            raw = None
        if row["_OID"] in geoms:
            row["_XY"] = geoms[row["_OID"]].midpoint()
        elif raw is not None:
            row["_XY"] = frame.forward(*raw)
        else:
            row["_XY"] = None
    return geoms


def annotate_areas(addresses, areas, key, frame):
    """Set row[key] to the key of the first area that contains the address, else None.

    A polygon whose key is null or blank sets "" (inside, key unknown), never None, so a
    point inside it is not mistaken for a point outside every polygon. A point that lies in
    a null-keyed polygon and a keyed one at once also gets "", whatever the file order, so
    the null key is never hidden behind an agreeing neighbour.

    A point on a polygon edge is not defined, and a point in two keyed overlapping polygons
    takes the first in file order. Both are topology defects this package does not judge."""
    planar = [(k, [[frame.forward(x, y) for x, y in ring] for ring in rings])
              for k, rings in areas]
    for row in addresses:
        row[key] = None
        if row["_XY"] is None:
            continue
        hits = [k for k, rings in planar if point_in_polygon(row["_XY"][0], row["_XY"][1], rings)]
        if hits:
            blank = any(k is None or not str(k).strip() for k in hits)
            row[key] = "" if blank else hits[0]
