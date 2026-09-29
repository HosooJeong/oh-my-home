"""Validate Jinju rows and build traceable map samples; does not correct source coordinates."""
import argparse
from collections import Counter
import csv
import datetime as dt
import hashlib
import io
import json
import math
from pathlib import Path
import zipfile

# Deliberately broad anomaly screen; not Jinju's administrative boundary.
SCREEN = {"lat_min": 34.9, "lat_max": 35.5, "lon_min": 127.8, "lon_max": 128.5}
ANCHORS = [
    ("chungmugong", "충무공동 주변", "MA010120220810248764"),
    ("gaho", "가호동 주변", "MA010120220814328351"),
    ("pyeonggeo", "평거동 주변", "MA0106202201A1825755"),
]


def coordinate_error(lat_text, lon_text):
    try:
        lat, lon = float(lat_text), float(lon_text)
    except (TypeError, ValueError):
        return "missing_or_non_numeric"
    if not (math.isfinite(lat) and math.isfinite(lon)):
        return "non_finite"
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return "invalid_global_range"
    if not (SCREEN["lat_min"] <= lat <= SCREEN["lat_max"] and SCREEN["lon_min"] <= lon <= SCREEN["lon_max"]):
        return "outside_broad_jinju_screen"
    return None


def distance_m(a, b):
    lat1, lat2 = math.radians(a["lat"]), math.radians(b["lat"])
    dlat, dlon = lat2 - lat1, math.radians(b["lon"] - a["lon"])
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 6371008.8 * 2 * math.asin(math.sqrt(min(1, h)))


def distinct_nearby(items, anchor, count=3, radius=2000):
    chosen, seen = [], set()
    for record in sorted(items, key=lambda r: (distance_m(anchor, r), r["id"])):
        key = (round(record["lat"], 7), round(record["lon"], 7))
        if key in seen:
            continue
        distance = distance_m(anchor, record)
        if distance > radius:
            break
        seen.add(key)
        chosen.append({**record, "anchor_distance_m": round(distance)})
        if len(chosen) == count:
            break
    return chosen


def shops_stream(raw):
    archive = zipfile.ZipFile(raw / "shops.zip")
    members = []
    for member in archive.infolist():
        name = member.filename
        if not member.flag_bits & 0x800:
            try:
                name = name.encode("cp437").decode("cp949")
            except UnicodeError:
                pass
        if "경남" in name and name.lower().endswith(".csv"):
            members.append((member, name))
    if len(members) != 1:
        archive.close()
        raise ValueError("Expected exactly one Gyeongnam CSV in the official ZIP")
    member, name = members[0]
    stream = io.TextIOWrapper(archive.open(member), encoding="utf-8-sig", newline="")
    return archive, stream, name


def process(source, stream, member_name=None):
    kind = source["id"]
    reader = csv.DictReader(stream)
    columns = reader.fieldnames or []
    required = {
        "shops": ["상가업소번호", "상호명", "시군구명", "위도", "경도", "도로명주소"],
        "bus": ["정류장번호", "정류장명", "도시명", "위도", "경도", "정보수집일"],
        "cctv": ["관리기관명", "소재지지번주소", "설치목적구분", "카메라대수", "위도", "경도"],
    }[kind]
    if any(field not in columns for field in required):
        raise ValueError(f"{kind}: missing required columns")
    total = matched = 0
    accepted, excluded, source_ids, signatures = [], [], [], Counter()
    dates, missing_addresses = Counter(), 0
    for row_number, row in enumerate(reader, 2):
        total += 1
        if kind == "shops" and row["시군구명"] != "진주시":
            continue
        if kind == "bus" and row["도시명"] != "경상남도 진주시":
            continue
        if kind == "cctv" and row["관리기관명"] != "경상남도 진주시청":
            continue
        matched += 1
        error = coordinate_error(row["위도"], row["경도"])
        if error:
            excluded.append({"source": kind, "row_number": row_number, "reason": error, "original": row})
            continue
        lat, lon = float(row["위도"]), float(row["경도"])
        if kind == "shops":
            sid, name = row["상가업소번호"], row["상호명"]
            address = row.get("도로명주소") or row.get("지번주소") or ""
            detail = row.get("상권업종소분류명", "")
            date, date_label = "2026-06-30", "분기 자료 기준일"
            # Dataset selection remains exact; reject silently reusing a new quarter.
            if "20260630" not in source["version"]:
                raise ValueError("Shop quarter changed: review source version and sample anchors")
        elif kind == "bus":
            sid, name, address = row["정류장번호"], row["정류장명"], ""
            detail = "버스정류장 · " + row["정류장번호"]
            date, date_label = row["정보수집일"], "정보수집일"
        else:
            # No public stable ID is supplied; preserve file version + physical CSV row.
            sid = f"row-{row_number}"
            name, address = row["설치목적구분"] + " CCTV", row["소재지지번주소"]
            detail = f"설치 {row.get('설치년월', '').lstrip(chr(39))} · 원본 카메라대수 {row['카메라대수']}"
            date, date_label = source["catalog_modified"], "공개본 수정일 (관측일 아님)"
        missing_addresses += not bool(address)
        source_ids.append(sid)
        signatures[tuple(row.get(k, "") for k in columns)] += 1
        dates[date] += 1
        accepted.append({
            "id": f"{kind}:{sid}", "source_id": sid, "kind": kind, "name": name,
            "address": address, "detail": detail, "lat": lat, "lon": lon,
            "date": date, "date_label": date_label, "source_row": row_number,
            "source_member": member_name, "source_url": source["source_url"],
        })
    location_counts = Counter((r["lat"], r["lon"]) for r in accepted)
    quality = {
        "id": kind, "title": source["title"], "source_version": source["version"],
        "scope_read": "경남 ZIP 구성파일" if kind == "shops" else "다운로드 파일 전체",
        "input_rows": total, "jinju_rows": matched, "coordinate_screen_pass_rows": len(accepted),
        "quarantined_rows": len(excluded), "dates": dict(dates), "columns": columns,
        "unique_coordinate_pairs": len(location_counts),
        "rows_beyond_first_at_same_coordinate": sum(n - 1 for n in location_counts.values()),
        "exact_duplicate_extra_rows": sum(n - 1 for n in signatures.values()),
        "duplicate_source_ids": {k: n for k, n in Counter(source_ids).items() if n > 1},
        "missing_address_rows": missing_addresses,
        "address_note": "주소 컬럼 없음; 결측 오류로 집계하지 않음" if kind == "bus" else "주소 컬럼 확인",
        "source_sha256": source["sha256"],
    }
    assert matched == len(accepted) + len(excluded)
    return accepted, excluded, quality


def build(raw_dir, out_dir):
    manifest = json.loads((raw_dir / "manifest.json").read_text(encoding="utf-8"))
    all_records, all_excluded, quality = [], [], []
    for source in manifest["sources"]:
        with (raw_dir / source["filename"]).open("rb") as stream:
            actual_hash = hashlib.file_digest(stream, "sha256").hexdigest()
        if actual_hash != source["sha256"]:
            raise ValueError(f"{source['id']}: source hash does not match manifest")
        if source["id"] == "shops":
            archive, stream, member = shops_stream(raw_dir)
            try:
                records, excluded, stats = process(source, stream, member)
            finally:
                stream.close()
                archive.close()
        else:
            with (raw_dir / source["filename"]).open(encoding=source["encoding"], newline="") as stream:
                records, excluded, stats = process(source, stream)
        all_records.extend(records)
        all_excluded.extend(excluded)
        quality.append(stats)
    now = dt.datetime.now().astimezone().isoformat()
    regions = []
    for region_id, name, source_id in ANCHORS:
        matches = [r for r in all_records if r["id"] == "shops:" + source_id]
        if len(matches) != 1:
            raise ValueError(f"Anchor missing or ambiguous: {source_id}")
        anchor = matches[0]
        samples = []
        for kind in ("shops", "bus", "cctv"):
            samples.extend(distinct_nearby([r for r in all_records if r["kind"] == kind], anchor))
        regions.append({"id": region_id, "name": name,
                        "anchor": {k: anchor[k] for k in ("id", "name", "lat", "lon")},
                        "samples": samples})
    notes = [
        "표본은 좌표와 출처를 확인하는 용도이며 주거 추천 순위가 아니다.",
        "같은 원천의 반복 CCTV 행은 보존하고 지도 표본에서만 같은 좌표 중복을 피했다.",
        "넓은 좌표 범위 선별은 행정경계 또는 전체 위치 정확성 검증이 아니다.",
        "상가 현재 영업, 버스 현재 운행, CCTV 작동 여부는 미확인이다.",
    ]
    preview = {"generated_at": now, "regions": regions, "quality": quality,
               "sources": manifest["sources"], "notes": notes, "coordinate_screen": SCREEN}
    out_dir.mkdir(parents=True, exist_ok=True)
    outputs = {"inventory.json": {"generated_at": now, "records": all_records},
               "quarantine.json": {"generated_at": now, "records": all_excluded},
               "quality.json": {"generated_at": now, "coordinate_screen": SCREEN, "sources": quality, "notes": notes},
               "preview.json": preview}
    for name, value in outputs.items():
        (out_dir / name).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    return preview


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", type=Path, default=Path("data/raw"))
    parser.add_argument("--out-dir", type=Path, default=Path("data/processed"))
    args = parser.parse_args()
    result = build(args.raw_dir, args.out_dir)
    print(json.dumps({"quality": [{k: r[k] for k in ["id", "input_rows", "jinju_rows", "coordinate_screen_pass_rows",
                      "quarantined_rows", "unique_coordinate_pairs", "exact_duplicate_extra_rows", "duplicate_source_ids"]}
                    for r in result["quality"]],
                     "samples_by_region": {r["name"]: len(r["samples"]) for r in result["regions"]}},
                     ensure_ascii=False, indent=2))
