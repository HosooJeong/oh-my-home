"""Acquire complete public school-location and Jinju NEIS academy snapshots."""
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen, Request

SCHOOL_SOURCE = 'https://www.data.go.kr/data/15021148/standard.do'
ACADEMY_SOURCE = 'https://open.neis.go.kr/portal/data/service/selectServicePage.do?infId=OPEN19220231012134453534385&infSeq=1'


def read(url):
    with urlopen(url, timeout=30) as response:
        return response.read()


def fetch(root):
    root.mkdir(parents=True, exist_ok=True)
    header = json.loads(read('https://www.data.go.kr/download/columList.json?pk=15021148&ext=JSON'))
    total, school = int(header['totalCount']), []
    for page in range(1, (total + 9999) // 10000 + 1):
        params = {'publicDataPk': '15021148', 'colNmList': header['tableVO']['colNmList'],
                  'svcTableNm': header['tableVO']['svcTableNm'], 'totalCount': total, 'perPage': 10000, 'page': page}
        rows = json.loads(read('https://www.data.go.kr/download/standard.json?' + urlencode(params, doseq=True)))
        if not isinstance(rows, list):
            raise ValueError('school download failed')
        school.extend(rows)
    if len(school) != total:
        raise ValueError('incomplete school snapshot')
    # Anonymous hub calls return only five sample rows. Use the public portal download.
    params = {'infId': 'OPEN19220231012134453534385', 'infSeq': '1', 'rows': '100', 'page': '1',
              'ATPT_OFCDC_SC_CODE': 'S10', 'ADMST_ZONE_NM': '진주시', 'downloadType': 'J',
              'ACA_INSTI_SC_NM': '', 'ACA_NM': '', 'REALM_SC_NM': '', 'LE_ORD_NM': '', 'LE_CRSE_NM': ''}
    request = Request('https://open.neis.go.kr/portal/data/sheet/downloadSheetData.do',
                      data=urlencode(params).encode(), headers={'Referer': ACADEMY_SOURCE})
    with urlopen(request, timeout=30) as response:
        downloaded = json.loads(response.read())
    if not isinstance(downloaded, list) or downloaded[0].get('ACA_NM') != '학원명':
        raise ValueError('academy download schema changed')
    academies = downloaded[1:]
    count_doc = json.loads(read('https://open.neis.go.kr/hub/acaInsTiInfo?' + urlencode(
        {'Type': 'json', 'ATPT_OFCDC_SC_CODE': 'S10', 'ADMST_ZONE_NM': '진주시'})))
    expected = count_doc['acaInsTiInfo'][0]['head'][0]['list_total_count']
    if len(academies) != expected or any(r['ADMST_ZONE_NM'] != '진주시' for r in academies):
        raise ValueError('academy count differs')
    manifest = {'retrieved_at': datetime.now().astimezone().isoformat(), 'sources': []}
    for label, rows, source in [('schools', school, SCHOOL_SOURCE), ('academies', academies, ACADEMY_SOURCE)]:
        raw = json.dumps(rows, ensure_ascii=False).encode('utf-8')
        path = root / (label + '.json'); path.write_bytes(raw)
        manifest['sources'].append({'id': label, 'source_url': source, 'filename': path.name,
                                    'rows': len(rows), 'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()})
        print(label, len(rows), len(raw), flush=True)
    (root / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--raw-dir', type=Path, default=Path('data/raw/education'))
    fetch(parser.parse_args().raw_dir)
