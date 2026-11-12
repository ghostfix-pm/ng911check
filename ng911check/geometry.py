"""Plain-Python geometry: a coordinate frame, a polyline and point-in-polygon.

Pure decision code. It needs no GIS licence: the distance to a line, the nearest point with
its left or right side, and the line length are computed here. Input coordinates arrive in one
of three units. The frame turns each of them into planar feet, because every distance
threshold in the settings is in feet.

Degrees use a local equirectangular approximation about the centre of the data. Over the
few miles a county spans, that is a plausibility measure, good to about half a percent. It is not
a survey measure. A projected layer in feet or metres is exact and needs no approximation.
"""
import math

from .common import p_distance, side_of_line

UNITS = ("degrees", "feet", "meters")

# The international foot is defined as exactly 0.3048 m (NIST SP 811, appendix B.8).
FEET_PER_METER = 1.0 / 0.3048
# IUGG mean earth radius R1 in metres. One degree of latitude is R1 * pi / 180 metres.
EARTH_RADIUS_M = 6371008.8
FEET_PER_DEGREE = EARTH_RADIUS_M * math.pi / 180.0 * FEET_PER_METER


# A position of exactly 0, 0 is the usual stand-in for a missing one. In a degrees run it is a
# point in the ocean, thousands of miles from any street, so it is treated as no position.
NULL_ISLAND = (0.0, 0.0)


def fits_degrees(coords):
    """True when there is at least one pair and every pair could be longitude, latitude."""
    coords = list(coords)
    return bool(coords) and all(-180.0 <= x <= 180.0 and -90.0 <= y <= 90.0 for x, y in coords)


class Frame(object):
    """Converts raw coordinates to planar feet and back."""

    def __init__(self, units, lon0=0.0, lat0=0.0):
        if units not in UNITS:
            raise ValueError("units must be one of %s, got %r" % (", ".join(UNITS), units))
        self.units = units
        self.lon0 = lon0
        self.lat0 = lat0
        self._kx = FEET_PER_DEGREE * math.cos(math.radians(lat0))

    @classmethod
    def fit(cls, units, coords):
        """Build the frame for a set of raw (x, y) pairs. Refuse degrees that are not degrees.

        A pair at 0, 0 does not count towards the centre of a degrees frame."""
        coords = list(coords)
        if units == "degrees":
            coords = [c for c in coords if c != NULL_ISLAND]
        if units != "degrees" or not coords:
            return cls(units)
        xs = [c[0] for c in coords]
        ys = [c[1] for c in coords]
        if min(xs) < -180.0 or max(xs) > 180.0 or min(ys) < -90.0 or max(ys) > 90.0:
            raise ValueError("coordinates fall outside longitude -180..180 and latitude "
                             "-90..90, so they are not degrees; pass --units feet or "
                             "--units meters")
        return cls(units, (min(xs) + max(xs)) / 2.0, (min(ys) + max(ys)) / 2.0)

    def forward(self, x, y):
        if self.units == "feet":
            return (x, y)
        if self.units == "meters":
            return (x * FEET_PER_METER, y * FEET_PER_METER)
        return ((x - self.lon0) * self._kx, (y - self.lat0) * FEET_PER_DEGREE)

    def inverse(self, x, y):
        if self.units == "feet":
            return (x, y)
        if self.units == "meters":
            return (x / FEET_PER_METER, y / FEET_PER_METER)
        return (x / self._kx + self.lon0, y / FEET_PER_DEGREE + self.lat0)


class Polyline(object):
    """One or more vertex runs in planar feet."""

    def __init__(self, parts):
        self.parts = [list(p) for p in parts if len(p) >= 2]
        if not self.parts:
            raise ValueError("a line needs at least one part with two vertices")
        self.length = sum(_part_length(p) for p in self.parts)

    def query(self, x, y):
        """Return (along, distance, on_right) for the nearest point on the line.

        `along` is the distance from the start of the first part to the nearest point.
        `on_right` is True when the point lies to the right of the direction of travel and
        False when it lies to the left. A point exactly ON the line has no side, so
        `on_right` is None: reporting it as left (or right) decided a wrong-side verdict by
        the house number's parity instead of by geometry."""
        best = None
        offset = 0.0
        for part in self.parts:
            run = 0.0
            for (x1, y1), (x2, y2) in zip(part, part[1:]):
                seg = math.hypot(x2 - x1, y2 - y1)
                dist, foot = p_distance(x, y, x1, y1, x2, y2)
                if best is None or dist < best[1]:
                    along = offset + run + math.hypot(foot[0] - x1, foot[1] - y1)
                    side = side_of_line(x, y, x1, y1, x2, y2)
                    best = (along, dist, None if side is None else side == "Right")
                run += seg
            offset += run
        return best

    def distance_to(self, x, y):
        return self.query(x, y)[1]

    def ends(self):
        """The first vertex of the first part and the last vertex of the last part."""
        return (self.parts[0][0], self.parts[-1][-1])

    def midpoint(self):
        """The point half way along the first part, used to place a finding on the map."""
        part = self.parts[0]
        half = _part_length(part) / 2.0
        segs = list(zip(part, part[1:]))
        run = 0.0
        for i, ((x1, y1), (x2, y2)) in enumerate(segs):  # pragma: no branch
            seg = math.hypot(x2 - x1, y2 - y1)
            # The last segment always answers, so float rounding cannot fall off the end.
            if run + seg >= half or i == len(segs) - 1:
                t = (half - run) / seg if seg else 0.0
                return (x1 + t * (x2 - x1), y1 + t * (y2 - y1))
            run += seg


STREET_EXTENT_MARGIN_FT = 5280.0


def require_street_overlap(points, lines, path):
    """The number of points inside the bounding box of every street vertex, widened by a mile.

    Raises ValueError when points exist and none is inside, and when points exist and none has
    a position. A street layer in another coordinate system puts every point far from every
    line, and an address file with no positions gives the checks nothing to measure. Either way
    XLAYER-17, XLAYER-18 and XLAYER-19 would judge nothing and zero findings would read as
    clean. Returns 0 without raising when there is no point at all."""
    verts = [v for line in lines for part in line.parts for v in part]
    xs = [v[0] for v in verts]
    ys = [v[1] for v in verts]
    m = STREET_EXTENT_MARGIN_FT
    lox, hix, loy, hiy = min(xs) - m, max(xs) + m, min(ys) - m, max(ys) + m
    placed = [p for p in points if p is not None]
    hits = sum(1 for x, y in placed if lox <= x <= hix and loy <= y <= hiy)
    if points and not placed:
        raise ValueError("none of the %d address(es) has a position, so the street checks "
                         "judged nothing and a result with no finding would read as clean. "
                         "Check the coordinate columns (--x-field and --y-field) or the "
                         "geometry of the address file, or drop %s." % (len(points), path))
    if placed and not hits:
        raise ValueError("none of the %d address point(s) with a position lies within the "
                         "extent of the street geometry in %s, so the street checks judged "
                         "nothing and a result with no finding would read as clean. Check that "
                         "--units and the coordinate system of the street file match the "
                         "address file." % (len(placed), path))
    return hits


def _part_length(part):
    return sum(math.hypot(x2 - x1, y2 - y1) for (x1, y1), (x2, y2) in zip(part, part[1:]))


def point_in_ring(x, y, ring):
    """Even-odd ray test against one closed ring. A point on the boundary is not defined."""
    inside = False
    for (x1, y1), (x2, y2) in zip(ring, ring[1:]):
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


def point_in_polygon(x, y, rings):
    """True when the point is inside the first ring and outside every later ring (holes)."""
    if not point_in_ring(x, y, rings[0]):
        return False
    return not any(point_in_ring(x, y, hole) for hole in rings[1:])
