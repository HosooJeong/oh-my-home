"""Convert the pinned official SHP and build shop-occupied 500m analysis cells."""
import argparse
from collections import defaultdict
from datetime import datetime
import hashlib
import io
import json
from pathlib import Path
import sys
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.boundaries import Boundary, SOURCE

ARCHIVE_SHA = "f1cf0f9de453ac7eaacb273f39cee52851183372b9ddfda428a967c3a670b2c6"


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def convert_geometry(geometry, transformer):
    def convert(value):
        if isinstance(value[0], (float, int)):
            return list(transformer.transform(*value, errcheck=True))
        return [convert(child) for child in value]
    return {"type": geometry["type"], "coordinates": convert(geometry["coordinates"])}


def prepare(archive_path, inventory_path, boundary_path, pool_path):
    import shapefile
    from pyproj import CRS, Transformer
    if sha(archive_path) != ARCHIVE_SHA:
        raise ValueError("new source version: review archive before preparing")
    features = []
    with zipfile.ZipFile(archive_path) as archive:
        for tag, code_key, name_key in [("bnd_sigungu", "SIGUNGU_CD", "SIGUNGU_NM"),
                                        ("bnd_dong", "ADM_CD", "ADM_NM")]:
            base = next(n[:-4] for n in archive.namelist() if tag in n and n.endswith(".shp"))
            crs = CRS.from_wkt(archive.read(base + ".prj").decode())
            if crs.to_epsg() != 5179 or archive.read(base + ".cpg").strip() != b"UTF-8":
                raise ValueError("source CRS or encoding changed")
            transform = Transformer.from_crs(crs, 4326, always_xy=True)
            reader = shapefile.Reader(**{ext: io.BytesIO(archive.read(base + "." + ext))
                                         for ext in ("shp", "shx", "dbf")}, encoding="utf-8")
            for record in reader.iterRecords():
                props = record.as_dict()
                if not props[code_key].startswith("38030"):
                    continue
                if props["BASE_DATE"] != "20250630":
                    raise ValueError("boundary observation date changed")
                geometry = reader.shape(record.oid).__geo_interface__
                features.append({"type": "Feature", "properties": {
                    "code": props[code_key], "name": props[name_key], "source_member": base + ".shp",
                    "source_record_index": record.oid}, "geometry": convert_geometry(geometry, transform)})
    if len(features) != 31 or next(f for f in features if f["properties"]["code"] == "38030")["properties"]["name"] != "진주시":
        raise ValueError("expected Jinju city and 30 administrative areas")
    boundary_doc = dict(type="FeatureCollection", coordinate_system="EPSG:4326",
        original_coordinate_system="EPSG:5179", data_date="2025-06-30", source_url=SOURCE,
        license="이용허락범위 제한 없음", archive_sha256=ARCHIVE_SHA, features=features)
    boundary = Boundary(boundary_doc)
    boundary_path.parent.mkdir(parents=True, exist_ok=True)
    boundary_path.write_text(json.dumps(boundary_doc, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    project = Transformer.from_crs(4326, 5179, always_xy=True)
    unproject = Transformer.from_crs(5179, 4326, always_xy=True)
    cells = defaultdict(int)
    outside = 0
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    for row in inventory["records"]:
        if row["kind"] != "shops":
            continue
        if not boundary.contains("38030", row["lat"], row["lon"]):
            outside += 1
            continue
        x, y = project.transform(row["lon"], row["lat"], errcheck=True)
        cells[int(x // 500), int(y // 500)] += 1
    points, skipped_centers = [], 0
    for (gx, gy), count in sorted(cells.items()):
        lon, lat = unproject.transform(gx * 500 + 250, gy * 500 + 250, errcheck=True)
        area = boundary.area_at(lat, lon)
        if area is None:
            skipped_centers += 1
            continue
        id = f"grid_{gx}_{gy}"
        points.append({"candidate": {"id": id, "label": f"{boundary.features[area]['properties']['name']} · 분석 지점 {gx}-{gy}",
            "latitude": lat, "longitude": lon, "origin": "generated"},
            "area_code": area, "cell": [gx, gy], "registered_shop_count": count})
    pool_path.parent.mkdir(parents=True, exist_ok=True)
    doc = dict(version="shop_grid_500m_v1", generated_at=datetime.now().astimezone().isoformat(),
        boundary_sha256=sha(boundary_path), inventory_sha256=sha(inventory_path),
        inventory_generated_at=inventory["generated_at"], grid_crs="EPSG:5179", cell_size_m=500,
        points=points, excluded_shop_rows_outside_boundary=outside,
        excluded_occupied_cells_outside_center=skipped_centers,
        note="등록 상가가 있는 500m 격자의 중심점. 주택·도로·토지 용도·거주 가능성은 미확인.")
    pool_path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in doc.items() if k != "points"}, ensure_ascii=False))
    print("points", len(points), "areas", len({p["area_code"] for p in points}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--inventory", type=Path, default=Path("data/processed/inventory.json"))
    parser.add_argument("--boundary", type=Path, default=Path("data/reference/jinju-boundary-2025.geojson"))
    parser.add_argument("--pool", type=Path, default=Path("data/processed/candidate-pool.json"))
    args = parser.parse_args()
    prepare(args.archive, args.inventory, args.boundary, args.pool)
