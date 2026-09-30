"""Normalize traceable Jinju public leisure rows without inferring missing locations."""
import argparse
from collections import Counter
from datetime import date
import hashlib
import json
import math
from pathlib import Path
from app.geo import in_supported_window
from app.modules.leisure import LeisureIndex, PARK_SOURCE, LIBRARY_SOURCE


def prepare(root):
    manifest = json.loads((root/'manifest.json').read_text(encoding='utf-8'))
    records, excluded = [], Counter()
    for source in manifest['sources']:
        kind = {'parks':'park','libraries':'library'}[source['id']]
        expected = PARK_SOURCE if kind=='park' else LIBRARY_SOURCE
        raw = (root/source['filename']).read_bytes(); rows = json.loads(raw)
        if source['source_url']!=expected or hashlib.sha256(raw).hexdigest()!=source['sha256'] or len(rows)!=source['rows']:
            raise ValueError('leisure source checksum/count differs')
        for number,row in enumerate(rows,1):
            if not (any(str(row.get(k) or '').startswith('경상남도 진주시 ') for k in ('RDNMADR','LNMADR')) or row.get('SIGNGU_NM')=='진주시'): continue
            name = row['PARK_NM' if kind=='park' else 'LBRRY_NM']
            address = row.get('RDNMADR') or row.get('LNMADR') or ''
            identity = 'park:'+row['MANAGE_NO'] if kind=='park' else 'library:'+hashlib.sha256((name+'|'+address).encode()).hexdigest()[:24]
            date.fromisoformat(row['REFERENCE_DATE'])
            try:
                lat,lon = float(row['LATITUDE']),float(row['LONGITUDE'])
                if not math.isfinite(lat) or not math.isfinite(lon) or not in_supported_window(lat,lon): raise ValueError('invalid')
            except (ValueError,TypeError):
                lat=lon=None; excluded[kind+'_unlocated']+=1
            records.append({'id':identity,'kind':kind,'name':name,'address':address,'lat':lat,'lon':lon,
                'type':row['PARK_SE' if kind=='park' else 'LBRRY_SE'], 'date':row['REFERENCE_DATE'],
                'source_url':source['source_url'],'source_row':number,
                'facilities':{key:row.get(key) or '' for key in ('MVM_FCLTY','AMSMT_FCLTY','CNVNNC_FCLTY','CLTR_FCLTY','ETC_FCLTY')} if kind=='park' else {},
                'area_m2':row.get('PARK_AR') if kind=='park' else None,
                'books':row.get('BOOK_CO') if kind=='library' else None,
                'seats':row.get('SEAT_CO') if kind=='library' else None})
    doc = {'version':'m6-1','retrieved_at':manifest['retrieved_at'],'records':records,'excluded':dict(excluded),'sources':manifest['sources']}
    LeisureIndex(doc)
    return doc


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--raw-dir',type=Path,default=Path('data/raw/leisure/20260930'))
    parser.add_argument('--output',type=Path,default=Path('data/processed/leisure.json'))
    args=parser.parse_args(); doc=prepare(args.raw_dir)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(doc,ensure_ascii=False,indent=2),encoding='utf-8')
    meta={k:v for k,v in doc.items() if k!='records'}
    meta.update(counts=dict(Counter(r['kind'] for r in doc['records'])), data_dates=sorted({r['date'] for r in doc['records']}))
    Path('data/reference/leisure-snapshot.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(LeisureIndex(doc).metadata(),ensure_ascii=False))
