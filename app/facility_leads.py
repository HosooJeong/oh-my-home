"""Public registry leads for fact research, never silently promoted to measured evidence."""
from datetime import date
from .geo import distance_m
from .research_policy import today

MEDICAL_TYPES={'내과/소아과 의원','피부/비뇨기과 의원','외과 의원','성형외과 의원','일반병원',
               '요양병원','기타 의원','치과의원','치과병원','이비인후과 의원','안과 의원',
               '산부인과 의원','종합병원','신경/정신과 의원','한의원'}


def medical_types(question):
    targeted=set()
    for words,types in [ (('내과','소아','가정의학'),{'내과/소아과 의원','기타 의원','일반병원','종합병원'}),
                        (('정형외과','외과','재활'),{'외과 의원','기타 의원','일반병원','종합병원'}),
                        (('이비인후',),{'이비인후과 의원','기타 의원','일반병원','종합병원'}),
                        (('안과',),{'안과 의원','일반병원','종합병원'}),
                        (('치과',),{'치과의원','치과병원'}),
                        (('피부','비뇨'),{'피부/비뇨기과 의원','일반병원','종합병원'}),
                        (('정신','신경'),{'신경/정신과 의원','기타 의원','일반병원','종합병원'}),
                        (('산부인',),{'산부인과 의원','일반병원','종합병원'}),
                        (('한의',),{'한의원'}) ]:
        if any(word in question for word in words):targeted.update(types)
    return targeted or MEDICAL_TYPES


def nearby_leads(rows,candidates,radius,name=None):
    leads=[]
    for row in rows:
        if name is not None and row['name']!=name:continue
        if row.get('lat') is None or row.get('lon') is None:continue
        dates=[row.get('date')]
        if row['kind']=='academy':dates.append(row.get('coordinate_date'))
        try:
            if any(not 0<=(today()-date.fromisoformat(d)).days<=365 for d in dates):continue
        except (ValueError,TypeError):continue
        distances={c.id:round(distance_m(c.latitude,c.longitude,row['lat'],row['lon']),3) for c in candidates}
        ids=[id for id,value in distances.items() if value<=radius]
        if ids:leads.append({**row,'candidate_ids':ids,'candidate_distances':distances,'research_lead':True})
    return leads
