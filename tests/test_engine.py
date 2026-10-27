import json,copy,sys
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]));import engine
@pytest.fixture
def s():return json.loads((Path(__file__).resolve().parents[1]/'seed.json').read_text())
def e(s,i,**kw):
 x=dict(id='e'+str(i),person='p'+str(i),course=s['courses'][0]['id'],state='finalizado',validated=True,certified_valid=True,employment='ocupado',sector_relation='propio',ccaa='Canarias',priority=True,source='Prueba sintética',updated_at='2026-10-26',evidence='Documento de prueba');x.update(kw);return x

def test_seed(s):
 engine.validate_state(s);assert len(s['allocations'])==13;assert len(s['programs'])==10;assert len(s['courses'])==163;assert sum(c['target'] for c in s['courses'])==2929

def test_no_data_is_not_zero(s):
 d=engine.portfolio(s);assert d['finalized'] is None;assert d['metrics'][0]['value'] is None;assert d['metrics'][2]['value'] is None;assert not d['complete']

def test_cancellations_and_unknowns(s):
 s['enrollments']=[e(s,1,employment='desempleado'),e(s,2,state='anulado',certified_valid=False),e(s,3,state='matriculado',certified_valid=False,validated=False),e(s,4,employment='desconocido',priority=None)]
 d=engine.portfolio(s);assert d['finalized']==2;assert d['certified']==2;assert d['metrics'][2]['value']==50;assert d['metrics'][2]['status']=='incompleto';assert d['unemployed_headroom'] is None;assert d['metrics'][2]['denominator_ids']==['e1','e4'];assert len(d['metrics'][2]['excluded_details'])==2

@pytest.mark.parametrize('u,n,h,repair',[(30,100,0,0),(20,100,14,0),(40,100,0,34),(0,0,None,None),(1,3,0,1)])
def test_changing_denominator(u,n,h,repair):assert engine.frozen_limit(u,n)==h and engine.repair_count(u,n)==repair

def test_geo_threshold_and_partial(s):
 s['enrollments']=[e(s,i,ccaa=engine.CCAA[i//5] if i<30 else 'Canarias') for i in range(100)]
 d=engine.portfolio(s,program=s['courses'][0]['program']);assert len(d['qualified_ccaa'])==6;assert d['geo_points']==12;assert d['geo_threshold']==5;assert not d['complete']

def test_duplicates_across_shared_entities(s):
 pair=next([(a,b) for a in s['courses'] for b in s['courses'] if a['entity']!=b['entity'] and a['program']==b['program'] and a['action']==b['action']].__iter__())
 s['enrollments']=[e(s,1,course=pair[0]['id']),e(s,2,course=pair[1]['id'],person='p1')]
 with pytest.raises(ValueError,match='duplicada'):engine.validate_state(s)

def test_penalty_boundaries():
 assert engine.penalties(78,78,50)['technical']['min']==0
 assert engine.penalties(78,73,47)['technical']['min']==1
 assert engine.penalties(78,57.99,50)['technical']['status']=='frontera_ambigua'
 assert engine.penalties(78,49,50)['technical']['min']==100
 assert engine.penalties(78,78,19.99)['priority']['min']==100
 assert engine.penalties(78,73,50,10000)['technical']['amount_min']==100

def test_dates_and_workload(s):
 p=engine.planning(s,'2026-10-26');assert p['proposals'];assert all(not x['allocation'].endswith(('F251830AA','F251835AA')) for x in p['proposals']);assert set(x['manager'] for x in p['proposals'])=={'g1','g2','g3','g4','g5'}
 for x in p['proposals']:
  a=next(a for a in s['allocations'] if a['id']==x['allocation']);assert x['start']<=x['end']<=a['deadline'];assert x['hours']>0
 assert engine.finish_day(engine.D('2026-10-30'),2,set()).isoformat()=='2026-11-02'

def test_no_duplicate_contact(s):
 task=dict(id='t1',person='p1',owner='g1',due='2026-10-30',hours=1,status='pendiente')
 s['tasks']=[task,{**task,'id':'t2','owner':'g2'}]
 with pytest.raises(ValueError,match='tarea abierta'):engine.validate_state(s)

def test_affinity_excludes_same_course_and_history(s):
 c=next(c for c in s['courses'] if 'EXCEL' in c['title'])
 r=engine.recommendations(s,c['id']);assert r;assert all(x['course']['code']!=c['code'] and x['status']=='condicionada' for x in r)
 s['enrollments']=[e(s,1,course=r[0]['course']['id'])]
 assert all(x['course']['code']!=r[0]['course']['code'] for x in engine.recommendations(s,c['id'],'p1'))
