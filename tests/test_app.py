import os,tempfile,json,sys
from pathlib import Path
os.environ['SEPE_DATA']=tempfile.mkdtemp(prefix='sepe-tests-');os.environ['SEPE_INSECURE_LOCAL']='1'
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import app as a
from werkzeug.security import generate_password_hash
import pytest
@pytest.fixture
def c():
 with a.db() as db:
  db.execute('DELETE FROM users');db.execute('DELETE FROM attempts');db.execute('DELETE FROM audit');db.execute('UPDATE state SET payload=?,revision=1',(json.dumps(json.loads((a.BASE/'seed.json').read_text())),))
  for u,role in [('admin','admin'),('gestor','gestor'),('lector','lector')]:db.execute('INSERT INTO users(username,password,role,manager) VALUES(?,?,?,?)',(u,generate_password_hash('Test-only-password-123!'),role,'g1'))
 return a.app.test_client()
def login(c,u='admin'):
 csrf=c.get('/api/bootstrap').json['csrf'];r=c.post('/api/login',json={'username':u,'password':'Test-only-password-123!'},headers={'X-CSRF-Token':csrf});assert r.status_code==200;return r.json['csrf']
def post(c,path,csrf,data):return c.post('/api/'+path,json=data,headers={'X-CSRF-Token':csrf})
def test_auth_sources_csrf(c):
 assert c.get('/api/state').status_code==401;assert c.get('/api/source/excel_aka').status_code==401
 csrf=login(c);assert c.get('/api/source/excel_aka').status_code==200
 assert c.post('/api/settings',json={'revision':1,'settings':{}}).status_code==403
 assert c.get('/api/state').headers['Cache-Control']=='no-store'
 assert c.post('/api/settings',json={'revision':1,'settings':{}},headers={'X-CSRF-Token':csrf,'Origin':'https://evil.invalid'}).status_code==403

def test_role_boundary(c):
 csrf=login(c,'lector');assert post(c,'planning/apply',csrf,{'revision':1}).status_code==403
 assert post(c,'logout',csrf,{}).status_code==200
 csrf=login(c,'gestor');assert post(c,'settings',csrf,{'revision':1,'settings':{}}).status_code==403

def test_atomic_import_revision_audit(c):
 csrf=login(c);cid=c.get('/api/state').json['state']['courses'][0]['id'];row=dict(id='m1',person='p1',course=cid,state='matriculado',employment='desconocido',sector_relation='desconocido',validated=False,certified_valid=False)
 data={'schema_version':'sepe-import-v1','source':'Prueba','enrollments':[row,{**row,'id':'m2','course':'missing'}]}
 assert post(c,'import',csrf,{'revision':1,'data':data}).status_code==400
 assert not c.get('/api/state').json['state']['enrollments']
 data['enrollments']=[row];assert post(c,'import',csrf,{'revision':1,'data':data}).status_code==200
 assert post(c,'import',csrf,{'revision':1,'data':data}).status_code==409
 assert post(c,'import',csrf,{'revision':2,'data':data}).status_code==200
 assert len(c.get('/api/state').json['state']['enrollments'])==1
 assert any(r['action']=='importacion' for r in c.get('/api/audit').json['rows'])

def test_planning_idempotence_and_calendar(c):
 csrf=login(c);assert post(c,'planning/apply',csrf,{'revision':1}).status_code==200
 st=c.get('/api/state').json;assert st['state']['groups'];assert not st['state']['tasks'];assert all(g['planning_hold'] for g in st['state']['groups'])
 loads=c.get('/api/planning').json['loads'];assert post(c,'planning/apply',csrf,{'revision':2}).status_code==200
 assert c.get('/api/planning').json['loads']==loads
 assert len(c.get('/api/state').json['state']['tasks'])==len(st['state']['tasks'])
 g=st['state']['groups'][0];assert post(c,'group',csrf,{'revision':3,'group':{**g,'end':'2099-01-01','note':'Test'}}).status_code==400

def test_password_revokes_other_sessions(c):
 csrf=login(c);other=a.app.test_client();login(other)
 assert post(c,'password',csrf,{'old':'Test-only-password-123!','new':'New-test-password-456!'}).status_code==200
 assert other.get('/api/state').status_code==401;assert c.get('/api/state').status_code==200

def test_manual_validation_needs_evidence(c):
 csrf=login(c);cid=c.get('/api/state').json['state']['courses'][0]['id']
 row=dict(person='p1',course=cid,state='finalizado',validated=True,certified_valid=True,employment='ocupado',sector_relation='propio')
 assert post(c,'enrollment',csrf,{'revision':1,'enrollment':row}).status_code==400
 row['evidence']='Informe firmado de resultados';assert post(c,'enrollment',csrf,{'revision':1,'enrollment':row}).status_code==200
