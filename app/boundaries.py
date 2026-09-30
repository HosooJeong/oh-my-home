"""Point inclusion in the acquired census boundary; no bounding-box substitution."""
import json
import math
from pathlib import Path

SOURCE = "https://www.data.go.kr/data/15129688/fileData.do"


def ring_contains(ring, x, y):
    inside = False
    for (ax, ay), (bx, by) in zip(ring, ring[1:]):
        cross = (x - ax) * (by - ay) - (y - ay) * (bx - ax)
        if abs(cross) < 1e-12 and min(ax, bx) <= x <= max(ax, bx) and min(ay, by) <= y <= max(ay, by):
            return True
        if (ay > y) != (by > y) and x < (bx - ax) * (y - ay) / (by - ay) + ax:
            inside = not inside
    return inside


class Boundary:
    def __init__(self, document):
        if (document["type"] != "FeatureCollection" or document["source_url"] != SOURCE
                or document["coordinate_system"] != "EPSG:4326"
                or document["data_date"] != "2025-06-30"):
            raise ValueError("unverified boundary version")
        self.document = document
        self.features = {}
        self.bounds = {}
        for feature in document["features"]:
            props, geometry = feature["properties"], feature["geometry"]
            code = props["code"]
            if code in self.features or not code.startswith("38030") or not props["name"]:
                raise ValueError("invalid boundary identity")
            if geometry["type"] not in ("Polygon", "MultiPolygon"):
                raise ValueError("polygon boundary required")
            polygons = geometry["coordinates"] if geometry["type"] == "MultiPolygon" else [geometry["coordinates"]]
            points = []
            for polygon in polygons:
                if not polygon:
                    raise ValueError("empty polygon")
                for ring in polygon:
                    if len(ring) < 4 or ring[0] != ring[-1]:
                        raise ValueError("unclosed ring")
                    for point in ring:
                        if len(point) != 2 or any(not math.isfinite(v) for v in point):
                            raise ValueError("invalid boundary coordinate")
                        if not 127.8 < point[0] < 128.5 or not 34.9 < point[1] < 35.5:
                            raise ValueError("boundary coordinate outside Jinju region")
                        points.append(point)
            self.features[code] = feature
            self.bounds[code] = (min(p[0] for p in points), min(p[1] for p in points),
                                 max(p[0] for p in points), max(p[1] for p in points))
        if "38030" not in self.features or len(self.features) < 2:
            raise ValueError("city and administrative areas required")

    @classmethod
    def load(cls, path: Path):
        return cls(json.loads(path.read_text(encoding="utf-8")))

    def contains(self, code, latitude, longitude):
        x, y = longitude, latitude
        if not math.isfinite(x) or not math.isfinite(y):
            return False
        xmin, ymin, xmax, ymax = self.bounds[code]
        if not xmin <= x <= xmax or not ymin <= y <= ymax:
            return False
        geometry = self.features[code]["geometry"]
        polygons = geometry["coordinates"] if geometry["type"] == "MultiPolygon" else [geometry["coordinates"]]
        return any(ring_contains(poly[0], x, y) and not any(ring_contains(hole, x, y) for hole in poly[1:])
                   for poly in polygons)

    def area_at(self, latitude, longitude):
        if not self.contains("38030", latitude, longitude):
            return None
        return next((code for code in sorted(self.features) if code != "38030"
                     and self.contains(code, latitude, longitude)), None)

    def metadata(self):
        return {"source_url": SOURCE, "data_date": self.document["data_date"],
                "areas": [{"code": code, "name": self.features[code]["properties"]["name"]}
                          for code in sorted(self.features) if code != "38030"]}
