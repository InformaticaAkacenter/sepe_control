import sys,json,copy
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import engine,consortium
from test_app import c,login,post
@pytest.fixture
def s():return consortium.upgrade(json.loads((Path(__file__).resolve().parents[1]/'seed.json').read_text()))
def setup_partner(s):
 pid=s['programs'][0]['id'];s['partners']=[{'id':'soc1','name':'Socio de prueba','nif':'B11111111','programs':[pid]}];return pid

def report(pid,**kw):
 r=dict(id='r1',partner='soc1',program=pid,as_of='2026-10-26',source='Prueba p. 1',verified=True,active=True,certified=100,unemployed=20,priority=60,own_sector=70,other_sector=10,finalized=90,target=100,final_hours=4500,target_hours=5000,certified_hours=5000,physical_hours=1000,geo={'Canarias':80,'Andalucía':20});r.update(kw);return r

def test_dates_preserve_source_propagate_and_block(s):
 pid='F251834AA';before=[a['deadline'] for a in s['allocations'] if a['program']==pid]
 consortium.set_deadline(s,{'program':pid,'deadline':'2027-06-30','status':'confirmada','evidence':'Notificación p.2'},'admin','now')
 aa=[a for a in s['allocations'] if a['program']==pid];assert len(aa)==2;assert all(a['deadline']=='2027-06-30' for a in aa);assert [a['original_deadline'] for a in aa]==before
 consortium.set_deadline(s,{'program':pid,'deadline':'2027-06-30','status':'en_revision','evidence':'Revisar prórroga'},'admin','now')
 d=consortium.deadline(s,pid,'2026-10-26');assert len(d['history'])==2;assert d['originals'][0]['source'];assert all(x['allocation'] not in [a['id'] for a in aa] for x in engine.planning(s,'2026-10-26')['proposals'])

def test_single_active_cut_and_no_historical_sum(s):
 pid=setup_partner(s);consortium.save_report(s,report(pid), 'admin','1');consortium.save_report(s,report(pid,id='r2',certified=120,geo={'Canarias':120}), 'admin','2')
 g=engine.portfolio(s,program=pid);assert g['certified']==120;assert not s['partner_reports'][0]['active'];assert not g['complete'];assert g['unemployed_headroom'] is None
 with pytest.raises(ValueError,match='anterior'):consortium.save_report(s,report(pid,id='r3',as_of='2026-09-26'),'admin','3')

def test_weighted_percentages_and_local_separation(s):
 pid=setup_partner(s);cid=next(c['id'] for c in s['courses'] if c['program']==pid)
 s['enrollments']=[dict(id='m'+str(i),person='p'+str(i),course=cid,state='finalizado',validated=True,certified_valid=True,employment='desempleado' if i<5 else 'ocupado',sector_relation='propio',priority=True,ccaa='Canarias') for i in range(10)]
 consortium.save_report(s,report(pid),'admin','1');g=engine.portfolio(s,program=pid)
 assert g['certified']==110;assert g['unemployed']==25;assert g['metrics'][2]['value']==pytest.approx(25/110*100,abs=.001);assert g['geo']['Canarias']==90
 assert engine.portfolio(s)['certified']==10;assert len(g['metrics'][2]['partner_sources'])==1

def test_incomplete_fields_are_unknown_not_zero(s):
 pid=setup_partner(s);consortium.save_report(s,report(pid,unemployed=None,priority=None,geo={},physical_hours=None),'admin','1')
 g=engine.portfolio(s,program=pid);assert g['metrics'][2]['status']=='incompleto';assert g['metrics'][3]['status']=='incompleto';assert g['metrics'][4]['status']=='incompleto';assert g['metrics'][5]['value'] is None

def test_coverage_requires_roster_local_and_matching_dates(s):
 pid=setup_partner(s);p=next(p for p in s['programs'] if p['id']==pid);consortium.save_report(s,report(pid),'admin','1')
 p.update(group_roster_verified=True,group_roster_evidence='Composición p.6',local_close={'as_of':'2026-10-25','evidence':'Cierre local'})
 assert not engine.portfolio(s,program=pid)['complete']
 p['local_close']['as_of']='2026-10-26';assert engine.portfolio(s,program=pid)['complete']
 s['partners'].append({'id':'soc2','name':'Otro socio','nif':'B22222222','programs':[pid]});assert not engine.portfolio(s,program=pid)['complete']

@pytest.mark.parametrize('change',[{'geo':{'Canarias':101}},{'unemployed':101},{'priority':-1},{'physical_hours':5001},{'certified':1.5}])
def test_bad_counts_rejected(s,change):
 pid=setup_partner(s)
 with pytest.raises(ValueError):consortium.save_report(s,report(pid,**change),'admin','1')

def test_duplicate_local_partner_rejected(s):
 pid=setup_partner(s);s['partners'][0]['nif']=s['entities'][0]['nif']
 with pytest.raises(ValueError,match='NIF'):engine.validate_state(s)

def test_csv_atomic_and_permissions(c):
 csrf=login(c);state=c.get('/api/state').json['state'];pid=state['programs'][0]['id'];partner={'id':'soc1','name':'Socio prueba','nif':'B11111111','programs':[pid]}
 assert post(c,'partner',csrf,{'revision':1,'partner':partner}).status_code==200
 csv='id;partner;program;as_of;source;verified;certified;unemployed;ccaa_05\nr1;soc1;'+pid+';2026-10-26;Acta;true;100;20;100\n'
 bad=csv+'r2;otro;'+pid+';2026-10-26;Acta;true;1;0;1\n'
 assert post(c,'partner-import',csrf,{'revision':2,'csv':bad}).status_code==400;assert not c.get('/api/state').json['state']['partner_reports']
 assert post(c,'partner-import',csrf,{'revision':2,'csv':csv}).status_code==200
 assert c.get('/api/dashboard').json['programs'][pid]['certified']==100
 csrf=login(c,'gestor');assert post(c,'partner-report',csrf,{'revision':3,'report':report(pid)}).status_code==403

def test_local_change_invalidates_declared_cutoff(c):
 csrf=login(c);st=c.get('/api/state').json['state'];pid=st['programs'][0]['id'];cid=next(x['id'] for x in st['courses'] if x['program']==pid)
 assert post(c,'group-coverage',csrf,{'revision':1,'program':pid,'as_of':'2026-10-26','local_evidence':'Cierre','roster_verified':False}).status_code==200
 row=dict(id='e1',person='p1',course=cid,state='matriculado',employment='desconocido',sector_relation='desconocido',validated=False,certified_valid=False)
 assert post(c,'enrollment',csrf,{'revision':2,'enrollment':row}).status_code==200
 assert not c.get('/api/dashboard').json['programs'][pid]['coverage']['local_close']

def test_confirmed_deadline_enables_tasks(c):
 csrf=login(c);pid=c.get('/api/state').json['state']['programs'][0]['id']
 assert post(c,'deadline',csrf,{'revision':1,'program':pid,'deadline':'2027-07-16','status':'confirmada','evidence':'Notificación p.2'}).status_code==200
 assert post(c,'planning/apply',csrf,{'revision':2}).status_code==200
 st=c.get('/api/state').json['state'];assert st['tasks'];assert all(next(x['program'] for x in st['courses'] if x['id']==t['course'])==pid for t in st['tasks'])
 assert post(c,'deadline',csrf,{'revision':3,'program':pid,'deadline':'2026-10-27','status':'en_revision','evidence':'Revisión'}).status_code==200
 assert all(t['planning_hold'] for t in c.get('/api/state').json['state']['tasks'])
