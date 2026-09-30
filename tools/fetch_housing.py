"""Download the official public CSV export; no API key or portal login required."""
import argparse
from datetime import date, datetime
import hashlib
import http.cookiejar
import json
from pathlib import Path
import urllib.parse
import urllib.request

BASE = "https://rt.molit.go.kr"
SOURCE = BASE + "/pt/xls/xls.do?mobileAt="


def fetch(raw_dir, start, end):
    if not 0 <= (date.fromisoformat(end) - date.fromisoformat(start)).days < 366:
        raise ValueError("select at most one year")
    raw_dir.mkdir(parents=True, exist_ok=True)
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    with opener.open(SOURCE, timeout=40) as response:
        page = response.read().decode("utf-8")
    if "/pt/xls/ptXlsCSVDown.do" not in page:
        raise ValueError("official export changed; inspect the public page")
    def post(route, fields):
        request = urllib.request.Request(BASE + route, data=urllib.parse.urlencode(fields).encode(),
                                        headers={"Referer": SOURCE})
        return opener.open(request, timeout=40)
    with post("/data/sgg.do", {"signguCode": "48"}) as response:
        regions = json.loads(response.read())
    if not any(r["signguCode"] == "48170" and r["signguNm"] == "진주시" for r in regions):
        raise ValueError("Jinju legal city code not verified")
    params = dict(srhThingNo="A", srhAddrGbn="1", srhLfstsSecd="1", sidoNm="경상남도", sggNm="진주시",
        emdNm="전체", loadNm="전체", areaNm="전체", hsmpNm="전체", mobileAt="", srhFromDt=start, srhToDt=end,
        srhNewRonSecd="", srhSidoCd="48000", srhSggCd="48170", srhEmdCd="", srhRoadNm="", srhLoadCd="",
        srhHsmpCd="", srhArea="", srhLrArea="", srhFromAmount="", srhToAmount="")
    for kind, code in [("sale", "1"), ("rent", "2")]:
        params["srhDelngSecd"] = code
        path = raw_dir / f"jinju-apartment-{kind}-{start[:7].replace('-', '')}-{end[:7].replace('-', '')}.csv"
        if path.exists() or path.with_suffix(".json").exists():
            raise ValueError("preserve previous snapshots; choose a new raw directory")
        with post("/pt/xls/ptXlsCSVDown.do", params) as response:
            data = response.read(20_000_001)
        if len(data) > 20_000_000:
            raise ValueError("oversized export")
        decoded = data.decode("cp949")
        if '"시군구"' not in decoded or "진주시" not in decoded:
            raise ValueError("not the expected public CSV; use the official download page")
        path.write_bytes(data)
        manifest = {"source_url": SOURCE, "download_url": BASE + "/pt/xls/ptXlsCSVDown.do",
            "retrieved_at": datetime.now().astimezone().isoformat(), "query": dict(params), "filename": path.name,
            "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
        path.with_suffix(".json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"{kind}: {len(data):,} bytes -> {path}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", type=Path, required=True)
    parser.add_argument("--start", default="2025-09-01")
    parser.add_argument("--end", default="2026-08-31")
    args = parser.parse_args()
    fetch(args.raw_dir, args.start, args.end)
