"""Download official public files without API credentials (Python standard library)."""
import argparse
import concurrent.futures
import datetime as dt
import hashlib
import json
from pathlib import Path
import re
import urllib.parse
import urllib.request
import zipfile

SOURCES = {
    "shops": {"catalog_id": "15083033", "filename": "shops.zip", "encoding": "utf-8-sig"},
    "bus": {"catalog_id": "15067528", "filename": "bus.csv", "encoding": "cp949"},
    "cctv": {"catalog_id": "15143299", "filename": "cctv.csv", "encoding": "utf-8-sig"},
}


def read_url(url):
    request = urllib.request.Request(url, headers={"User-Agent": "SaljariPublicDataProbe/0.1"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def download(label, config, root, reuse):
    number = config["catalog_id"]
    source_url = f"https://www.data.go.kr/data/{number}/fileData.do"
    html = read_url(source_url).decode("utf-8")
    metadata = json.loads(read_url(f"https://www.data.go.kr/catalog/{number}/fileData.json"))
    if metadata.get("license") != "이용허락범위 제한 없음":
        raise ValueError(f"{label}: source license changed; review before downloading")
    match = re.search(r'id="publicDataDetailPk"[^>]*value="([^"]+)"', html)
    if not match:
        raise ValueError(f"{label}: official download selector not found")
    query = urllib.parse.urlencode({
        "publicDataPk": number, "publicDataDetailPk": match.group(1),
        "atchFileId": "", "fileDetailSn": "1", "publicDataTyCode": "PR0051",
    })
    resolution = json.loads(read_url("https://www.data.go.kr/tcs/dss/selectFileDataDownload.do?" + query))
    if resolution.get("status") is not True:
        raise ValueError(f"{label}: official file resolution failed")
    url = "https://www.data.go.kr/cmm/cmm/fileDownload.do?" + urllib.parse.urlencode({
        "atchFileId": resolution["atchFileId"], "fileDetailSn": resolution["fileDetailSn"],
        "insertDataPrcus": "N",
    })
    dest = root / config["filename"]
    reused = reuse and dest.exists()
    response_info = {}
    if not reused:
        request = urllib.request.Request(url, headers={"User-Agent": "SaljariPublicDataProbe/0.1"})
        partial = dest.with_suffix(dest.suffix + ".partial")
        with urllib.request.urlopen(request, timeout=60) as response, partial.open("wb") as stream:
            response_info = {"http_status": response.status, "content_type": response.headers.get("Content-Type"),
                             "content_length": response.headers.get("Content-Length"),
                             "content_disposition": response.headers.get("Content-Disposition")}
            while chunk := response.read(1024 * 1024):
                stream.write(chunk)
        if response_info["content_length"] and partial.stat().st_size != int(response_info["content_length"]):
            raise ValueError(f"{label}: incomplete transfer")
        partial.replace(dest)
    if label == "shops":
        if not zipfile.is_zipfile(dest):
            raise ValueError("Expected ZIP, got another file format")
        with zipfile.ZipFile(dest) as archive:
            if not any(item.filename.lower().endswith(".csv") for item in archive.infolist()):
                raise ValueError("ZIP has no CSV data")
    else:
        with dest.open("rb") as stream:
            header = stream.readline()
        decoded = header.decode(config["encoding"]).lstrip("\ufeff")
        if "위도" not in decoded or "경도" not in decoded:
            raise ValueError(f"{label}: not the expected coordinate CSV")
    with dest.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    result = {
        "id": label, "catalog_id": number, "title": metadata["name"],
        "version": metadata.get("alternateName"), "source_url": source_url,
        "download_url": url, "filename": dest.name, "encoding": config["encoding"],
        "license": metadata["license"], "catalog_modified": metadata.get("dateModified"),
        "checked_at": dt.datetime.now().astimezone().isoformat(),
        "reused_existing_local_file": reused, "bytes": dest.stat().st_size, "sha256": digest,
        "http": response_info,
    }
    (root / f"{label}-metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{label}: {dest.stat().st_size:,} bytes; format checked", flush=True)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", type=Path, default=Path("data/raw"))
    parser.add_argument("--reuse", action="store_true", help="Use already downloaded local files; record this explicitly.")
    args = parser.parse_args()
    args.raw_dir.mkdir(parents=True, exist_ok=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        jobs = [pool.submit(download, label, config, args.raw_dir, args.reuse) for label, config in SOURCES.items()]
        results = [job.result() for job in jobs]
    manifest = {"checked_at": dt.datetime.now().astimezone().isoformat(), "sources": results,
                "note": "Catalog modified date is not automatically a record observation date."}
    (args.raw_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
