"""Normalize official records; connect academy buildings by exact public road address."""
import argparse
from collections import defaultdict
from datetime import date
import hashlib
import json
from pathlib import Path
import re

from app.geo import distance_m, in_supported_window
from app.modules.education import EducationIndex, LEVELS, SUBJECTS, SCHOOL_SOURCE, ACADEMY_SOURCE


def address_key(value):
    return re.sub(r'\s+', '', re.split(r'[,（(]', value)[0].strip())


def stages(text):
    found = [key for key, word in [('elementary', '초등'), ('middle', '중등'), ('high', '고등')] if word in text]
    if '중학생' in text: found.append('middle')
    if '초·중·고' in text or '초중고' in text: found.extend(LEVELS)
    return sorted(set(found))


def prepare(raw_dir, inventory):
    manifest = json.loads((raw_dir / 'manifest.json').read_text(encoding='utf-8'))
    source_rows = {}
    for source in manifest['sources']:
        data = (raw_dir / source['filename']).read_bytes()
        expected = SCHOOL_SOURCE if source['id'] == 'schools' else ACADEMY_SOURCE
        if source['source_url'] != expected or hashlib.sha256(data).hexdigest() != source['sha256']:
            raise ValueError('source checksum differs')
        rows = json.loads(data)
        if len(rows) != source['rows']: raise ValueError('incomplete snapshot')
        source_rows[source['id']] = rows
    buildings = defaultdict(list)
    for row in inventory['records']:
        if row['kind'] == 'shops': buildings[address_key(row['address'])].append(row)
    records, excluded = [], defaultdict(int)
    for number, row in enumerate(source_rows['schools'], 1):
        if not (row.get('RDNMADR', '').startswith('경상남도 진주시 ') or row.get('LNMADR', '').startswith('경상남도 진주시 ')):
            continue
        if row['OPER_STTUS'] != '운영' or row['SCHOOL_SE'] not in LEVELS.values():
            excluded['school_status_or_level'] += 1; continue
        lat, lon = float(row['LATITUDE']), float(row['LONGITUDE'])
        if not in_supported_window(lat, lon): raise ValueError('invalid official school coordinates')
        records.append({'id': 'school:' + row['SCHOOL_ID'], 'kind': 'school', 'name': row['SCHOOL_NM'],
            'address': row.get('RDNMADR') or row['LNMADR'], 'level': next(k for k,v in LEVELS.items() if v == row['SCHOOL_SE']),
            'lat': lat, 'lon': lon, 'coordinate_method': 'official_school_location', 'coordinate_source_ids': [],
            'date': row['REFERENCE_DATE'], 'source_url': SCHOOL_SOURCE, 'source_row': number,
            'linked_at': row['CHANGE_DATE']})
    grouped = {}
    for number, row in enumerate(source_rows['academies'], 1):
        if row['ADMST_ZONE_NM'] != '진주시' or row['ATPT_OFCDC_SC_CODE'] != 'S10':
            raise ValueError('outside official scope')
        if row['REG_STTUS_NM'] != '개원': excluded['academy_not_registered_open'] += 1; continue
        if '성인' in row.get('LE_CRSE_NM', '') and '유아' not in row.get('LE_CRSE_NM', ''):
            excluded['academy_adult_only'] += 1; continue
        identity = 'academy:S10:' + row['ACA_ASNUM']
        if identity in grouped: raise ValueError('duplicate academy registration requires review')
        courses = ' / '.join(row.get(k, '') or '' for k in ('LE_CRSE_LIST_NM', 'LE_CRSE_NM', 'PSNBY_THCC_CNTNT'))
        subjects = [key for key, word in SUBJECTS.items() if word in courses or
                    (key == 'music' and any(w in courses for w in ('피아노', '바이올린', '기타', '드럼', '성악')))]
        subject_levels = {}
        for subject in subjects:
            fragments = [f for f in re.split(r'[,/]', courses) if SUBJECTS[subject] in f or
                         (subject == 'music' and any(w in f for w in ('피아노', '바이올린', '기타', '드럼', '성악')))]
            # A general official youth language-course classification covers all school levels.
            broad = stages(row.get('LE_CRSE_NM', '')) if '유아/초·중·고' in row.get('LE_CRSE_NM', '') else []
            subject_levels[subject] = sorted(set(stages(' '.join(fragments)) + broad))
        matches = buildings.get(address_key(row['FA_RDNMA']), [])
        lat = lon = None
        if matches:
            lat = sum(r['lat'] for r in matches) / len(matches); lon = sum(r['lon'] for r in matches) / len(matches)
            if any(distance_m(lat, lon, r['lat'], r['lon']) > 50 for r in matches):
                lat = lon = None; excluded['academy_address_coordinate_conflict'] += 1
        if lat is None: excluded['academy_unlocated'] += 1
        linked_date = date.fromisoformat(str(row['LOAD_DTM'])[:4] + '-' + str(row['LOAD_DTM'])[4:6] + '-' + str(row['LOAD_DTM'])[6:8]).isoformat()
        grouped[identity] = {'id': identity, 'kind': 'academy', 'name': row['ACA_NM'],
            'address': row['FA_RDNMA'], 'address_detail': row.get('FA_RDNDA', ''), 'lat': lat, 'lon': lon,
            'coordinate_method': 'exact_road_address_building_join' if lat is not None else 'unavailable',
            'coordinate_source_ids': [r['id'] for r in matches] if lat is not None else [],
            'coordinate_date': min(r['date'] for r in matches) if lat is not None else None, 'date': linked_date,
            'linked_at': row.get('LOAD_DTM'), 'source_url': ACADEMY_SOURCE, 'source_row': number,
            'subjects': subjects, 'subject_levels': subject_levels, 'levels': stages(courses),
            'courses': (row.get('LE_CRSE_LIST_NM') or '') + ' / ' + (row.get('LE_CRSE_NM') or ''),
            'capacity': int(row['TOFOR_SMTOT']) if row.get('TOFOR_SMTOT') is not None else None,
            'simultaneous_capacity': int(row['DTM_RCPTN_ABLTY_NMPR_SMTOT']) if row.get('DTM_RCPTN_ABLTY_NMPR_SMTOT') is not None else None}
    records.extend(grouped.values())
    doc = {'version': 'm4-1', 'retrieved_at': manifest['retrieved_at'], 'sources': manifest['sources'],
           'coordinate_inventory_sha256': hashlib.sha256(json.dumps(inventory, sort_keys=True).encode()).hexdigest(),
           'excluded': dict(excluded), 'records': records}
    EducationIndex(doc)
    return doc


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--raw-dir', type=Path, required=True)
    parser.add_argument('--inventory', type=Path, default=Path('data/processed/inventory.json'))
    parser.add_argument('--output', type=Path, default=Path('data/processed/education.json'))
    args = parser.parse_args()
    document = prepare(args.raw_dir, json.loads(args.inventory.read_text(encoding='utf-8')))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(document, ensure_ascii=False), encoding='utf-8')
    snapshot = Path('data/reference/education-snapshot.json')
    snapshot.write_text(json.dumps({k:v for k,v in document.items() if k != 'records'} | EducationIndex(document).metadata(),
                                    ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(EducationIndex(document).metadata(), ensure_ascii=False))
