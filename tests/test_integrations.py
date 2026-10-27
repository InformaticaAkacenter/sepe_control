import copy,json,re,time
from pathlib import Path
import pytest
import engine
from integrations import clients,sync
from integrations.demo import demo_clients
from test_app import c,login,post
import app as a

@pytest.fixture
def setup():
    state=json.loads((a.BASE/'seed.json').read_text());course=state['courses'][0]
    cfg=sync.default_config();cfg['groups']=[{'gestion_group':'10','course':course['id'],'evidence':'Comprobación expediente y sede'}];state['integration_config']=cfg
    group={'id':'10','financiacion':{'expediente':course['program']},'finicio':'2026-10-01','ffin':'2026-10-26','grupoalumnoSet':[{'id':'30','alumno':{'id':'20','nif':'TEST0001'},'estadomatricula':'finalizado','falta':'2026-10-01','fbaja':None,'motivobaja':None}]}
    profile={'id':40,'nif':'TEST0001','nombre':'Prueba','apellidos':'Ficticia','codigo_postal':'35500','pais':'ES'}
    class Rest:
        def find_id(self,n):assert n=='TEST0001';return '40'
        def profile(self,r):assert r=='40';return copy.deepcopy(profile)
    class Gestion:
        def group(self,g):assert g=='10';return copy.deepcopy(group)
    return state,group,profile,Rest(),Gestion()

def test_rest_basic_and_graphql_variables():
    calls=[]
    def transport(method,url,headers,payload=None):
        calls.append((method,url,headers,payload))
        return {'id':3} if method=='GET' else {'data':{'grupo':{'id':'4','grupoalumnoSet':[]}}}
    rest=clients.InternalClient('https://internal.example/gestion/api','user','secret',transport);assert rest.profile('3')['id']==3
    assert calls[0][1]=='https://internal.example/gestion/api/gestion/alumnos/3'
    assert calls[0][2]['Authorization']=='Basic dXNlcjpzZWNyZXQ='
    g=clients.GestionClient('https://gestion.example/graphql','secret','JWT',transport);g.group('4')
    assert calls[1][2]['Authorization']=='JWT secret';assert calls[1][3]['variables']=={'id':'4'}
    with pytest.raises(clients.IntegrationError):g.query('mutation DeleteEverything {}',{})

@pytest.mark.parametrize('url',['http://example.test','https://user:pass@example.test','https://example.test/?secret=x','https://example.test/#fragment','/relative'])
def test_endpoint_guards(url):
    with pytest.raises(clients.IntegrationError):clients.InternalClient(url,'u','p')

def test_graphql_error_no_partial_data_or_secret():
    g=clients.GestionClient('https://example.test/graphql','secret',transport=lambda *x:{'data':{'grupo':{}},'errors':[{'message':'private secret'}]})
    with pytest.raises(clients.IntegrationError) as err:g.group('1')
    assert 'private secret' not in str(err.value)

def test_paginated_catalog_and_repeated_page():
    def transport(m,u,h,p):
        skip=p['variables']['skip'];n=100 if skip==0 else 1
        return {'data':{'allGrupos':{'numitems':101,'items':[{'id':str(skip+i+1)} for i in range(n)]}}}
    g=clients.GestionClient('https://example.test/graphql','secret',transport=transport);assert len(g.groups())==101
    g.transport=lambda *args:{'data':{'allGrupos':{'numitems':2,'items':[{'id':'1'}]}}}
    with pytest.raises(clients.IntegrationError):g.groups()

def test_unknown_lookup_shape_is_rejected():
    r=clients.InternalClient('https://example.test','u','p',transport=lambda *x:[1,2])
    with pytest.raises(clients.IntegrationError):r.find_id('TEST001')

def test_queries_match_uploaded_sdl():
    """Validate all selected fields and nested return types against the supplied SDL."""
    schema=(a.BASE/'integrations/schemas/gestion.graphql').read_text();schema=re.sub(r'""".*?"""','',schema,flags=re.S)
    types={name:dict(re.findall(r'^\s*(\w+)(?:\([^\n]*\))?\s*:\s*[\[!]*([\w]+)',body,re.M)) for name,body in re.findall(r'type (\w+)[^{]*\{(.*?)\n\}',schema,re.S)}
    for query in [clients.GROUP_QUERY,clients.GROUPS_QUERY]:
        tokens=re.findall(r'[A-Za-z_]\w*|[{}()]',query[query.index('{'):]);pos=0
        def selection(typ):
            nonlocal pos
            assert tokens[pos]=='{';pos+=1
            while tokens[pos]!='}':
                name=tokens[pos];pos+=1;assert name in types[typ],(typ,name)
                if tokens[pos]=='(':
                    depth=1;pos+=1
                    while depth:
                        depth+=int(tokens[pos]=='(')-int(tokens[pos]==')');pos+=1
                target=types[typ][name]
                if tokens[pos]=='{':selection(target)
                else:assert target not in types,(typ,name,'missing nested selection')
            pos+=1
        selection('Query');assert pos==len(tokens)
    spec=json.loads((a.BASE/'integrations/schemas/interna.openapi.json').read_text())
    assert '/gestion/alumnos/{alumno_id}' in spec['paths']
    assert 'sector' not in spec['components']['schemas']['Alumno']['properties']

def test_offline_demo_is_explicit_and_incomplete():
    state=json.loads((a.BASE/'seed.json').read_text());state,r,g=demo_clients(state);p=sync.build_preview(state,r,g,'demo')
    assert p['counts']=={'received':2,'ready':1,'blocked':1,'missing':0,'incomplete':1,'observed_final':1,'validated_final':0}
    assert not p['rows'][0]['validated'];assert p['rows'][0]['ccaa']=='Canarias'

def test_rest_owns_demographics_graphql_owns_outcome(setup):
    s,g,p,r,c=setup;p['estadomatricula']='anulado';g['grupoalumnoSet'][0]['estado']='ocupado';g['grupoalumnoSet'][0]['empresa']={'sector':'METAL'}
    out=sync.build_preview(s,r,c);e=out['rows'][0]
    assert e['state']=='finalizado' and e['employment']=='desconocido' and e['sector_relation']=='desconocido'
    assert e['company']=='' and e['progress'] is None and e['priority'] is None
    assert not e['validated'] and not e['certified_valid'];assert 'Inferida' in e['integration']['provenance']['ccaa']['rule']

def test_mismatch_identity_blocks_join(setup):
    s,g,p,r,c=setup;p['nif']='OTHER0001';out=sync.build_preview(s,r,c)
    assert out['counts']['blocked']==1 and not out['rows']

@pytest.mark.parametrize('changed_person',[{'id':'21','nif':'TEST0001'},{'id':'20','nif':'TEST0002'}])
def test_conflicting_person_identity_is_not_silently_joined(setup,changed_person):
    s,g,p,r,c=setup
    second=copy.deepcopy(g['grupoalumnoSet'][0]);second['id']='31';second['alumno']=changed_person
    g['grupoalumnoSet'].append(second)
    out=sync.build_preview(s,r,c)
    assert out['counts']['ready']==1 and out['counts']['blocked']==1
    assert out['issues'][0]['enrollment']=='31'

def test_malformed_configuration_returns_validation_error(setup):
    s,*_=setup
    for key,value in [('groups',[None]),('field_evidence',None)]:
        cfg=sync.config(s);cfg[key]=value
        with pytest.raises(clients.IntegrationError):sync.validate_config(cfg,s)

def test_group_or_member_wrong_plan_block(setup):
    s,g,p,r,c=setup;g['financiacion']['expediente']='WRONG'
    with pytest.raises(clients.IntegrationError):sync.build_preview(s,r,c)
    g['financiacion']['expediente']=s['courses'][0]['program'];g['grupoalumnoSet'][0]['financiacion']={'expediente':'WRONG'}
    assert sync.build_preview(s,r,c)['counts']['blocked']==1

def test_unmapped_baja_and_explicit_rule(setup):
    s,g,p,r,c=setup;g['grupoalumnoSet'][0]['estadomatricula']='BAJA'
    assert sync.build_preview(s,r,c)['counts']['blocked']==1
    s['integration_config']['state_map']['baja']='abandono';s['integration_config']['state_evidence']='Baja confirmada como abandono en este sistema'
    e=sync.build_preview(s,r,c)['rows'][0];assert e['state']=='abandono' and not e['certified_valid']

def test_sector_mapping_is_per_plan_and_not_default_other(setup):
    s,g,p,r,c=setup;cfg=s['integration_config'];cfg['profile_fields'].update({'sector':'empresa.sector','company':'empresa.cif','employment':'situacion','as_of':'fecha_referencia','priority':'prioritario'})
    cfg['field_evidence']='Campos contrastados en ejemplo documentado';p.update(empresa={'sector':'EDU','cif':'EMP1'},situacion='ocupado',fecha_referencia='2026-10-01',prioritario=False)
    assert sync.build_preview(s,r,c)['rows'][0]['sector_relation']=='desconocido'
    cfg['sector_rules'][s['courses'][0]['program']]={'own':['EDU'],'other':['METAL'],'evidence':'Convenio contrastado'}
    e=sync.build_preview(s,r,c)['rows'][0];assert e['sector_relation']=='propio' and e['company']=='EMP1' and e['priority'] is False
    p['empresa']['sector']='UNKNOWN';assert sync.build_preview(s,r,c)['rows'][0]['sector_relation']=='desconocido'

def test_idempotence_manual_review_and_source_changes(setup):
    s,g,p,r,c=setup;out=sync.build_preview(s,r,c);sync.apply_rows(s,out['rows'],sync.stamp());old=s['enrollments'][0]
    old.update(validated=True,certified_valid=True,evidence='Cierre firmado')
    change={'employment':'ocupado','evidence':'Acreditación de situación laboral al inicio'};sync.record_manual_changes(old,change);old.update(change)
    out=sync.build_preview(s,r,c);assert out['rows'][0]['validated'] and out['rows'][0]['employment']=='ocupado'
    sync.apply_rows(s,out['rows'],sync.stamp());assert len(s['enrollments'])==1
    g['grupoalumnoSet'][0]['estadomatricula']='abandono';out=sync.build_preview(s,r,c)
    assert not out['rows'][0]['validated'] and not out['rows'][0]['certified_valid'] and 'manual_overrides' not in out['rows'][0]
    sync.apply_rows(s,out['rows'],sync.stamp());assert s['enrollments'][0]['integration_history'] and 'manual_overrides' not in s['enrollments'][0]

def test_missing_is_preserved_and_partial_errors_not_deleted(setup):
    s,g,p,r,c=setup;sync.apply_rows(s,sync.build_preview(s,r,c)['rows'],sync.stamp());g['grupoalumnoSet']=[]
    out=sync.build_preview(s,r,c);sync.apply_rows(s,out['rows'],sync.stamp());assert len(out['missing'])==1 and s['enrollments'][0]['state']=='finalizado'

def test_foreign_postcode_and_unknown_values():
    assert sync.community({'codigo_postal':'35500','pais':'US'},None)[0] is None
    assert sync.community({'codigo_postal':'35500'},None)[0] is None
    assert sync.community({'codigo_postal':'35500','pais':'ES'},'unknown')[0] is None

def test_manual_records_require_reconciliation(setup):
    s,g,p,r,c=setup;e=sync.build_preview(s,r,c)['rows'][0];e.pop('integration');e['id']='manual_1';s['enrollments']=[e]
    assert sync.build_preview(s,r,c)['counts']['blocked']==1
    s['integration_config']['enrollment_links']={'30':{'local_id':'manual_1','evidence':'Registro conciliado'}}
    out=sync.build_preview(s,r,c);sync.apply_rows(s,out['rows'],sync.stamp());assert len(s['enrollments'])==1 and s['enrollments'][0]['id']=='manual_1'

def wait_job(c,jid):
    for _ in range(100):
        r=c.get('/api/integrations/jobs/'+jid).json
        if r['status']!='running':return r
        time.sleep(.01)
    raise AssertionError('Worker did not finish')

def test_routes_permissions_demo_and_no_secret(c,monkeypatch):
    monkeypatch.setenv('SEPE_GESTION_TOKEN','secret-must-never-leak');monkeypatch.setenv('SEPE_API_ENABLED','0')
    token=login(c,'gestor');assert c.get('/api/integrations').status_code==403
    assert post(c,'integrations/preview',token,{'revision':1,'mode':'demo'}).status_code==403
    token=login(c);assert 'secret-must-never-leak' not in c.get('/api/integrations').text
    assert post(c,'integrations/preview',token,{'revision':1,'mode':'live'}).status_code==400
    response=post(c,'integrations/preview',token,{'revision':1,'mode':'demo'});assert response.status_code==202
    job=wait_job(c,response.json['id']);assert job['status']=='ready'
    assert post(c,'integrations/apply',token,{'revision':1,'job_id':job['id']}).status_code==400
    assert not c.get('/api/state').json['state']['enrollments']

def test_routes_live_fixture_apply_once_and_reject_stale(c,setup,monkeypatch):
    s,g,p,r,gs=setup;monkeypatch.setattr(clients,'live_clients',lambda:(r,gs))
    with a.db() as con:con.execute('UPDATE state SET payload=?',(json.dumps(s),))
    token=login(c);job=post(c,'integrations/preview',token,{'revision':1,'mode':'live'});j=wait_job(c,job.json['id']);assert j['status']=='ready',j
    assert post(c,'integrations/apply',token,{'revision':1,'job_id':j['id']}).status_code==200
    assert len(c.get('/api/state').json['state']['enrollments'])==1
    assert post(c,'integrations/apply',token,{'revision':2,'job_id':j['id']}).status_code==400
    j2=wait_job(c,post(c,'integrations/preview',token,{'revision':2,'mode':'live'}).json['id'])
    assert post(c,'settings',token,{'revision':2,'settings':{}}).status_code==200
    assert post(c,'integrations/apply',token,{'revision':3,'job_id':j2['id']}).status_code==409

def test_config_validation_and_manual_injection(c,setup):
    s,*_=setup;cfg=sync.config(s);cfg['groups'].append(copy.deepcopy(cfg['groups'][0]))
    with pytest.raises(clients.IntegrationError):sync.validate_config(cfg,s)
    token=login(c);e={'course':s['courses'][0]['id'],'person':'p','state':'matriculado','employment':'desconocido','sector_relation':'desconocido','integration':{'evil':True}}
    assert post(c,'enrollment',token,{'revision':1,'enrollment':e}).status_code==400
