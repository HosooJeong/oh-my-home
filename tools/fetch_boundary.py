"""Acquire the reviewed public SGIS 2025-Q2 archive without an API key."""
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import sys
import urllib.parse
import urllib.request
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.fetch_public_data import read_url
from tools.prepare_candidates import ARCHIVE_SHA


def fetch(root, reuse=False):
    root.mkdir(parents=True, exist_ok=True)
    source = "https://www.data.go.kr/data/15129688/fileData.do"
    html = read_url(source).decode("utf-8")
    meta = json.loads(read_url("https://www.data.go.kr/catalog/15129688/fileData.json"))
    if meta["license"] != "이용허락범위 제한 없음" or not meta["alternateName"].endswith("_20250630"):
        raise ValueError("boundary version or license changed; review before acquisition")
    detail = re.search(r'id="publicDataDetailPk"[^>]*value="([^"]+)"', html)
    if not detail:
        raise ValueError("official download selector unavailable")
    query = urllib.parse.urlencode(dict(publicDataPk="15129688", publicDataDetailPk=detail[1],
        atchFileId="", fileDetailSn="1", publicDataTyCode="PR0051"))
    resolution = json.loads(read_url("https://www.data.go.kr/tcs/dss/selectFileDataDownload.do?" + query))
    if resolution.get("status") is not True:
        raise ValueError("download resolution failed")
    url = "https://www.data.go.kr/cmm/cmm/fileDownload.do?" + urllib.parse.urlencode(dict(
        atchFileId=resolution["atchFileId"], fileDetailSn=resolution["fileDetailSn"], insertDataPrcus="N"))
    dest = root / "sgis-2025.zip"
    reused = reuse and dest.exists()
    if not reused:
        partial = dest.with_suffix(".partial")
        with urllib.request.urlopen(url, timeout=60) as response, partial.open("wb") as stream:
            length = response.headers.get("Content-Length")
            while chunk := response.read(1024 * 1024):
                stream.write(chunk)
        if length and partial.stat().st_size != int(length):
            raise ValueError("incomplete transfer")
        if not zipfile.is_zipfile(partial):
            raise ValueError("expected ZIP")
        partial.replace(dest)
    with dest.open("rb") as stream:
        sha = hashlib.file_digest(stream, "sha256").hexdigest()
    if sha != ARCHIVE_SHA:
        raise ValueError("archive changed; review before conversion")
    manifest = dict(source_url=source, download_url=url, title=meta["alternateName"],
        license=meta["license"], checked_at=datetime.now().astimezone().isoformat(),
        bytes=dest.stat().st_size, sha256=sha, reused_existing_local_file=reused)
    (root / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", type=Path, default=Path("data/raw/boundary"))
    parser.add_argument("--reuse", action="store_true")
    args = parser.parse_args()
    fetch(args.raw_dir, args.reuse)
