"""Acquire complete public park/library downloads with row counts and hashes."""
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen

SOURCES = {'parks': '15012890', 'libraries': '15013109'}


def read(url):
    with urlopen(url, timeout=30) as response:
        return response.read()


def fetch(root):
    root.mkdir(parents=True, exist_ok=True)
    manifest = {'retrieved_at': datetime.now().astimezone().isoformat(), 'sources': []}
    for kind, pk in SOURCES.items():
        header = json.loads(read('https://www.data.go.kr/download/columList.json?' + urlencode({'pk': pk, 'ext': 'JSON'})))
        total, rows = int(header['totalCount']), []
        for page in range(1, (total + 9999) // 10000 + 1):
            params = {'publicDataPk': pk, 'colNmList': header['tableVO']['colNmList'],
                      'svcTableNm': header['tableVO']['svcTableNm'], 'totalCount': total,
                      'perPage': 10000, 'page': page}
            batch = json.loads(read('https://www.data.go.kr/download/standard.json?' + urlencode(params, doseq=True)))
            if not isinstance(batch, list):
                raise ValueError('invalid public download')
            rows.extend(batch)
        if len(rows) != total:
            raise ValueError('incomplete public snapshot')
        raw = json.dumps(rows, ensure_ascii=False).encode('utf-8')
        name = kind + '.json'; (root / name).write_bytes(raw)
        manifest['sources'].append({'id': kind, 'source_url': f'https://www.data.go.kr/data/{pk}/standard.do',
            'filename': name, 'rows': total, 'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()})
        print(kind, total, 'fields', list(rows[0]) if rows else [], flush=True)
    (root / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--raw-dir', type=Path, default=Path('data/raw/leisure/20260930'))
    fetch(parser.parse_args().raw_dir)
