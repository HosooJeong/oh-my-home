"""Validate and normalize official Jinju apartment CSV snapshots (CP949)."""
import argparse
import csv
from datetime import date, datetime
from decimal import Decimal
import hashlib
import io
import json
from pathlib import Path

from app.modules.housing import HousingIndex, SOURCE, VERSION


def money(value):
    amount = Decimal(value.strip().replace(",", "")) * 10000
    if not amount.is_finite() or amount < 0 or amount != amount.to_integral_value():
        raise ValueError("invalid KRW amount")
    return int(amount)


def prepare(paths):
    records, raw_sources, periods, retrieved = [], {}, set(), []
    excluded = {"cancelled_sale": 0, "invalid_row": 0}
    rejected = []
    for kind, path in paths.items():
        data = path.read_bytes()
        meta = json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))
        q = meta["query"]
        if (meta["source_url"] != SOURCE or q["srhSggCd"] != "48170" or q["srhThingNo"] != "A"
                or q["srhDelngSecd"] != {"sale": "1", "rent": "2"}[kind]
                or any(q.get(k) for k in ("srhEmdCd", "srhHsmpCd", "srhFromAmount", "srhToAmount", "srhNewRonSecd",
                                         "srhArea", "srhLrArea", "srhLoadCd", "srhRoadNm"))
                or meta["sha256"] != hashlib.sha256(data).hexdigest() or meta["bytes"] != len(data)):
            raise ValueError("source, query or CSV checksum differs")
        start, end = date.fromisoformat(q["srhFromDt"]), date.fromisoformat(q["srhToDt"])
        if not 0 <= (end - start).days < 366:
            raise ValueError("invalid period")
        periods.add((start.isoformat(), end.isoformat()))
        datetime.fromisoformat(meta["retrieved_at"])
        retrieved.append(meta["retrieved_at"])
        raw_sources[path.name] = {k: meta[k] for k in ("filename", "bytes", "sha256", "retrieved_at")}
        rows = list(csv.reader(io.StringIO(data.decode("cp949"))))
        header_index = next(i for i, r in enumerate(rows) if r[:2] == ["NO", "시군구"])
        required = {"NO", "시군구", "전용면적(㎡)", "계약년월", "계약일"} | (
            {"거래금액(만원)", "해제사유발생일"} if kind == "sale" else {"전월세구분", "보증금(만원)", "월세금(만원)", "계약구분"})
        header = rows[header_index]
        if len(set(header)) != len(header) or not required <= set(header):
            raise ValueError("official CSV schema changed")
        if f"계약일자 : {start.isoformat()} ~ {end.isoformat()}" not in [v for r in rows[:header_index] for v in r]:
            raise ValueError("export period differs from manifest")
        ids = set()
        for line, values in enumerate(rows[header_index + 1:], header_index + 2):
            if not values or not any(values):
                continue
            try:
                if len(values) != len(header):
                    raise ValueError("invalid column count")
                row = dict(zip(header, values))
                identity = kind + ":" + row["NO"]
                if not row["NO"].isdigit() or identity in ids:
                    raise ValueError("duplicate or invalid CSV row id")
                ids.add(identity)
                prefix = "경상남도 진주시 "
                if not row["시군구"].startswith(prefix):
                    raise ValueError("outside Jinju")
                if kind == "sale" and row["해제사유발생일"].strip() not in ("", "-"):
                    date.fromisoformat(row["해제사유발생일"].replace(".", "-"))
                    excluded["cancelled_sale"] += 1
                    continue
                ym = row["계약년월"]
                day = date(int(ym[:4]), int(ym[4:]), int(row["계약일"]))
                if not start <= day <= end:
                    raise ValueError("outside period")
                record = dict(id=identity, legal_area=row["시군구"][len(prefix):], area_m2=float(row["전용면적(㎡)"]),
                    contract_date=day.isoformat(), source_file=path.name, source_row=line,
                    sale_krw=None, deposit_krw=None, monthly_krw=None, contract="unknown")
                if kind == "sale":
                    record.update(tenure="sale", sale_krw=money(row["거래금액(만원)"]))
                else:
                    record.update(tenure={"전세": "jeonse", "월세": "monthly"}[row["전월세구분"]],
                        deposit_krw=money(row["보증금(만원)"]), monthly_krw=money(row["월세금(만원)"]),
                        contract={"신규": "new", "갱신": "renewal", "-": "unknown", "": "unknown"}[row["계약구분"]])
                records.append(record)
            except (ValueError, KeyError, ArithmeticError):
                excluded["invalid_row"] += 1
                rejected.append({"source_file": path.name, "source_row": line})
    if len(periods) != 1:
        raise ValueError("sale and rental periods differ")
    start, end = next(iter(periods))
    document = {"version": VERSION, "city_code": "48170", "source_url": SOURCE, "period_start": start,
                "period_end": end, "retrieved_at": max(retrieved), "raw_sources": raw_sources,
                "excluded": excluded, "rejected_rows": rejected, "records": records}
    HousingIndex(document)  # Fail closed when normalized tenure/amount/area validation fails.
    return document


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sale", type=Path, required=True)
    parser.add_argument("--rent", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("data/processed/housing.json"))
    parser.add_argument("--metadata-output", type=Path, default=Path("data/reference/housing-snapshot.json"))
    args = parser.parse_args()
    document = prepare({"sale": args.sale, "rent": args.rent})
    index = HousingIndex(document)
    for path, output in [(args.output, document), (args.metadata_output, index.metadata())]:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps(index.metadata(), ensure_ascii=False, indent=2))
