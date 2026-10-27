import os,json,sqlite3,secrets,time,hashlib,getpass,argparse,csv,io,zipfile
from pathlib import Path
from datetime import datetime,timedelta,timezone
from functools import wraps
from flask import Flask,request,jsonify,session,send_from_directory,abort
from werkzeug.security import generate_password_hash,check_password_hash
import engine,consortium
from integrations import sync as api_sync
BASE=Path(__file__).resolve().parent
DATA=Path(os.environ.get('SEPE_DATA',str(BASE/'data')));DATA.mkdir(parents=True,exist_ok=True)
SECRET=DATA/'secret.key'
if not SECRET.exists():
    try:
        fd=os.open(SECRET,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'w') as f:f.write(secrets.token_hex(32))
    except FileExistsError:pass
app=Flask(__name__,static_folder='static');app.secret_key=SECRET.read_text().strip()
if os.environ.get('SEPE_BEHIND_PROXY')=='1':
    from werkzeug.middleware.proxy_fix import ProxyFix
    app.wsgi_app=ProxyFix(app.wsgi_app,x_for=1,x_proto=1,x_host=0)
app.config.update(MAX_CONTENT_LENGTH=8*1024*1024,SESSION_COOKIE_HTTPONLY=True,SESSION_COOKIE_SAMESITE='Strict',SESSION_COOKIE_SECURE=os.environ.get('SEPE_INSECURE_LOCAL')!='1',PERMANENT_SESSION_LIFETIME=timedelta(hours=8))
DB=DATA/'sepe.sqlite3'
def db():
    con=sqlite3.connect(DB,timeout=20);con.row_factory=sqlite3.Row;con.execute('PRAGMA journal_mode=WAL');return con

def init():
    with db() as con:
        con.executescript('''CREATE TABLE IF NOT EXISTS users(username TEXT PRIMARY KEY,password TEXT NOT NULL,role TEXT NOT NULL,manager TEXT,version INTEGER DEFAULT 1,active INTEGER DEFAULT 1);
        CREATE TABLE IF NOT EXISTS state(id INTEGER PRIMARY KEY CHECK(id=1),payload TEXT NOT NULL,revision INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY,time TEXT NOT NULL,actor TEXT NOT NULL,action TEXT NOT NULL,detail TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS attempts(identity TEXT NOT NULL,time REAL NOT NULL);
        ''')
        if not con.execute('SELECT id FROM state WHERE id=1').fetchone():
            seed=json.loads((BASE/'seed.json').read_text());engine.validate_state(seed)
            con.execute('INSERT INTO state VALUES(1,?,1)',(json.dumps(seed,ensure_ascii=False),))
init()
def now():return datetime.now(timezone.utc).isoformat()
def audit(con,action,detail):con.execute('INSERT INTO audit(time,actor,action,detail) VALUES(?,?,?,?)',(now(),session.get('user','sistema'),action,detail))
def load_state():
    with db() as con:
        r=con.execute('SELECT payload,revision FROM state WHERE id=1').fetchone();return consortium.upgrade(json.loads(r['payload'])),r['revision']
def mutate(fn,action):
    expected=request.json.get('revision')
    with db() as con:
        con.execute('BEGIN IMMEDIATE');r=con.execute('SELECT payload,revision FROM state WHERE id=1').fetchone()
        if expected!=r['revision']:abort(409,description='Otro gestor ha modificado datos. Actualiza la vista y repite el cambio.')
        s=consortium.upgrade(json.loads(r['payload']));detail=fn(s);engine.validate_state(s)
        con.execute('UPDATE state SET payload=?,revision=revision+1 WHERE id=1',(json.dumps(s,ensure_ascii=False),));audit(con,action,str(detail)[:1000])
    return jsonify(ok=True,revision=r['revision']+1)
def admin(fn):
    @wraps(fn)
    def wrapper(*a,**kw):
        if session.get('role')!='admin':abort(403,description='Requiere administrador')
        return fn(*a,**kw)
    return wrapper

@app.before_request
def auth():
    if request.path.startswith('/api/') and request.path not in ['/api/bootstrap','/api/login']:
        with db() as con:u=con.execute('SELECT role,version,active FROM users WHERE username=?',(session.get('user',''),)).fetchone()
        if not u or not u['active'] or u['version']!=session.get('version'):session.clear();abort(401,description='Inicia sesión')
        session['role']=u['role']
        if request.method not in ['GET','HEAD','OPTIONS'] and u['role']=='lector' and request.path not in ['/api/logout','/api/password']:abort(403,description='Acceso de lectura')
    if request.method in ['POST','PUT','PATCH','DELETE']:
        token=request.headers.get('X-CSRF-Token','')
        if not token or not secrets.compare_digest(token,session.get('csrf','')):abort(403,description='Sesión caducada. Recarga la página.')
        origin=request.headers.get('Origin')
        if origin and origin.rstrip('/')!=request.host_url.rstrip('/'):
            configured=os.environ.get('SEPE_ORIGIN','').rstrip('/')
            if not configured or origin.rstrip('/')!=configured:abort(403,description='Origen no autorizado')

@app.after_request
def headers(r):
    r.headers['X-Content-Type-Options']='nosniff';r.headers['X-Frame-Options']='DENY';r.headers['Referrer-Policy']='same-origin'
    r.headers['Content-Security-Policy']="default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
    if request.path.startswith('/api/'):r.headers['Cache-Control']='no-store'
    if os.environ.get('SEPE_INSECURE_LOCAL')!='1':r.headers['Strict-Transport-Security']='max-age=31536000'
    return r
@app.errorhandler(Exception)
def error(e):
    from werkzeug.exceptions import HTTPException
    if isinstance(e,HTTPException):return jsonify(error=e.description),e.code
    if isinstance(e,(ValueError,KeyError,TypeError,IndexError)):return jsonify(error=str(e)[:500]),400
    app.logger.exception('Request failed');return jsonify(error='Error interno. Revisar el registro del servidor.'),500
@app.get('/')
def index():return send_from_directory(BASE/'static','index.html')
@app.get('/api/bootstrap')
def bootstrap():
    if 'csrf' not in session:session['csrf']=secrets.token_urlsafe(32)
    return jsonify(csrf=session['csrf'],user=session.get('user'),role=session.get('role'),manager=session.get('manager'))
@app.post('/api/login')
def login():
    d=request.get_json();username=str(d.get('username','')).strip().lower();password=str(d.get('password',''))
    identity=hashlib.sha256((request.remote_addr+'|'+username).encode()).hexdigest();ip=hashlib.sha256(('ip|'+request.remote_addr).encode()).hexdigest()
    with db() as con:
        con.execute('DELETE FROM attempts WHERE time<?',(time.time()-900,))
        if con.execute('SELECT count(*) FROM attempts WHERE identity IN (?,?)',(identity,ip)).fetchone()[0]>=20:abort(429,description='Demasiados intentos. Espera 15 minutos.')
        u=con.execute('SELECT * FROM users WHERE username=?',(username,)).fetchone()
        # Same expensive verification for unknown accounts.
        ok=check_password_hash(u['password'] if u else DUMMY_HASH,password)
        if not u or not ok or not u['active']:
            con.execute('INSERT INTO attempts VALUES(?,?)',(identity,time.time()));con.execute('INSERT INTO attempts VALUES(?,?)',(ip,time.time()));con.commit();abort(401,description='Usuario o contraseña incorrectos')
        con.execute('DELETE FROM attempts WHERE identity=?',(identity,));session.clear();session.update(user=username,role=u['role'],manager=u['manager'],version=u['version'],csrf=secrets.token_urlsafe(32));session.permanent=True;audit(con,'login','Acceso correcto')
    return jsonify(ok=True,csrf=session['csrf'],user=username,role=u['role'],manager=u['manager'])
DUMMY_HASH=generate_password_hash(secrets.token_urlsafe(24))
@app.post('/api/logout')
def logout():session.clear();return jsonify(ok=True)
@app.get('/api/state')
def state():
    s,r=load_state();return jsonify(state=s,revision=r)
@app.get('/api/dashboard')
def dashboard():
    s,r=load_state();return jsonify(deadlines={p['id']:consortium.deadline(s,p['id']) for p in s['programs']},total=engine.portfolio(s),allocations={a['id']:engine.portfolio(s,allocation=a['id']) for a in s['allocations']},programs={p['id']:engine.portfolio(s,program=p['id']) for p in s['programs']},revision=r)
@app.get('/api/recommendations')
def rec():
    s,_=load_state();return jsonify(results=engine.recommendations(s,request.args['course'],request.args.get('person')))
@app.get('/api/planning')
def plan():
    s,_=load_state();return jsonify(engine.planning(s,request.args.get('date')))
@app.post('/api/planning/apply')
def apply_plan():
    def change(s):
        proposal=engine.planning(s);n=0
        for p in proposal['proposals']:
            tid='captacion_'+p['course']
            gid='propuesta_'+p['course']
            if not any(g['id']==gid for g in s['groups']):s['groups'].append({'id':gid,'course':p['course'],'owner':p['manager'],'start':p['start'],'end':p['end'],'cohorts':p['cohorts'],'deadline_status':p['deadline_status'],'planning_hold':p['deadline_status']!='confirmada','note':'Propuesta orientativa; confirmar aulas, docentes y alumnos','source':p['source'],'source_locator':p['locator'],'updated_at':now()})
            if p['deadline_status']!='confirmada':continue
            if any(t['id']==tid for t in s['tasks']):continue
            s['tasks'].append({'id':tid,'title':'Captación '+next(c['code'] for c in s['courses'] if c['id']==p['course']),'course':p['course'],'owner':p['manager'],'person':'','due':p['start'],'hours':p['hours'],'status':'pendiente','note':f"Objetivo orientativo {p['contacts']} contactos, {p['enrollments']} matrículas. Confirmar calendario y plazas.",'source':'Planificador interno','updated_at':now()});n+=1
        return str(n)+' tareas con plazo confirmado creadas; borradores con fecha provisional guardados sin generar captación'
    return mutate(change,'planificacion')
@app.post('/api/group')
def group():
    def change(s):
        d=request.json['group'];g=next(x for x in s['groups'] if x['id']==d['id']);c=next(x for x in s['courses'] if x['id']==g['course']);a=next(x for x in s['allocations'] if x['id']==c['allocation'])
        engine.D(d['start']);engine.D(d['end'])
        if d['start']>d['end']:raise ValueError('Inicio posterior al fin')
        if a.get('deadline_status')=='revisar' or not a.get('deadline'):raise ValueError('Confirmar fecha límite del plan')
        if d['end']>a['deadline']:raise ValueError('Fin posterior al plazo del plan')
        if not d.get('note'):raise ValueError('Documenta el ajuste de calendario')
        if d['owner'] not in {m['id'] for m in s['managers']}:raise ValueError('Gestor no reconocido')
        g.update({k:d[k] for k in ['start','end','owner','note']});g['updated_at']=now();g['deadline_status']=consortium.deadline(s,c['program'])['status'];g['planning_hold']=g['deadline_status']!='confirmada'
        for t in s['tasks']:
            if t['id']=='captacion_'+g['course']:t.update(owner=g['owner'],due=g['start'],planning_hold=g['planning_hold'],updated_at=now())
        return g['id']
    return mutate(change,'calendario')

@app.post('/api/task')
def task():
    d=request.json['task']
    def change(s):
        item={k:d.get(k) for k in ['id','title','course','owner','person','due','hours','status','note']};item['updated_at']=now();item['source']='Manual: '+session['user']
        if not item['id']:item['id']=secrets.token_hex(8)
        if item.get('course') and item['course'] not in {c['id'] for c in s['courses']}:raise ValueError('Curso no reconocido')
        item['hours']=float(item['hours']);item['title']=str(item['title'])[:250];item['note']=str(item.get('note') or '')[:3000]
        existing=next((t for t in s['tasks'] if t['id']==item['id']),None)
        if existing:existing.update(item)
        else:s['tasks'].append(item)
        return item['id']
    return mutate(change,'tarea')
@app.post('/api/enrollment')
def enrollment():
    d=request.json['enrollment']
    def change(s):
        allowed={'id','person','course','state','employment','sector_relation','ccaa','priority','company','progress','validated','certified_valid','evidence'}
        if set(d)-allowed:raise ValueError('Campos de matrícula no editables')
        e=dict(d);e.setdefault('id',secrets.token_hex(8));
        if e.get('validated') and not e.get('evidence'):raise ValueError('Indica la evidencia del resultado validado')
        e['updated_at']=now();e['source']='Manual: '+session['user']
        old=next((x for x in s['enrollments'] if x['id']==e['id']),None)
        affected={next(c['program'] for c in s['courses'] if c['id']==cid) for cid in [e['course']]+([old['course']] if old else [])}
        for p in s['programs']:
            if p['id'] in affected:p['local_close']={}
        api_sync.record_manual_changes(old,e)
        if old:old.update(e)
        else:s['enrollments'].append(e)
        return e['id']
    return mutate(change,'matricula')
@app.post('/api/settings')
@admin
def settings():
    def change(s):s['settings'].update(request.json['settings']);return 'Parámetros de planificación'
    return mutate(change,'parametros')
@app.post('/api/manager')
@admin
def manager():
    def change(s):
        m=next(x for x in s['managers'] if x['id']==request.json['manager']['id']);m.update({k:v for k,v in request.json['manager'].items() if k in ['name','weekly_hours','focus','active']});return m['id']
    return mutate(change,'gestor')
@app.post('/api/deadline')
@admin
def deadline():
    return mutate(lambda s:consortium.set_deadline(s,request.json,session['user'],now()),'fecha_limite_expediente')

@app.post('/api/partner')
@admin
def partner():
    def change(s):
        d=request.json['partner'];item={k:d[k] for k in ['id','name','nif','programs']};item['nif']=item['nif'].strip().upper();item['name']=item['name'].strip()
        if not item['id']:item['id']='socio_'+secrets.token_hex(6)
        old=next((p for p in s['partners'] if p['id']==item['id']),None)
        affected=set(item['programs']) | set(old['programs'] if old else [])
        if old:old.update(item)
        else:s['partners'].append(item)
        for p in s['programs']:
            if p['id'] in affected:p['group_roster_verified']=False
        return item['id']
    return mutate(change,'socio_agrupacion')

@app.post('/api/partner-report')
@admin
def partner_report():
    def change(s):
        r=request.json['report'];r.setdefault('id','informe_'+secrets.token_hex(8))
        return consortium.save_report(s,r,session['user'],now())
    return mutate(change,'resultado_socio')

@app.post('/api/partner-import')
@admin
def partner_import():
    def change(s):
        rows=consortium.csv_reports(request.json['csv'])
        for r in rows:consortium.save_report(s,r,session['user'],now())
        return str(len(rows))+' cortes de socios importados; no se suman cortes históricos'
    return mutate(change,'importacion_socios')

@app.post('/api/group-coverage')
@admin
def group_coverage():
    def change(s):
        d=request.json;p=next(p for p in s['programs'] if p['id']==d['program'])
        if not isinstance(d.get('roster_verified',False),bool):raise ValueError('Confirmación de composición debe ser booleana')
        if d.get('roster_verified'):
            if not d.get('roster_evidence') or not any(p['id'] in x['programs'] for x in s['partners']):raise ValueError('Registrar todos los socios y la evidencia de composición antes de confirmar')
        if d.get('as_of'):
            if engine.D(d['as_of'])>engine.today() or not d.get('local_evidence'):raise ValueError('Fecha de corte futura o sin evidencia de cierre local')
        p['group_roster_verified']=bool(d.get('roster_verified'));p['group_roster_evidence']=d.get('roster_evidence','')
        p['local_close']={'as_of':d['as_of'],'evidence':d['local_evidence'],'updated_at':now(),'actor':session['user']} if d.get('as_of') else {}
        return p['id']
    return mutate(change,'cobertura_agrupacion')

@app.get('/api/partner-template.csv')
def partner_template():
    cols=['id','partner','program','as_of','source','verified']+consortium.REPORT_FIELDS+['ccaa_'+str(i).zfill(2) for i in range(1,20)]
    buf=io.StringIO();writer=csv.writer(buf,delimiter=';');writer.writerow(cols)
    return app.response_class('\ufeff'+buf.getvalue(),mimetype='text/csv',headers={'Content-Disposition':'attachment; filename=plantilla_resultados_socios.csv'})

@app.post('/api/import')
@admin
def import_data():
    payload=request.json['data']
    def change(s):
        if payload.get('schema_version')!='sepe-import-v1':raise ValueError('Usa schema_version sepe-import-v1')
        if not payload.get('source'):raise ValueError('Origen de datos obligatorio')
        rows=payload.get('enrollments',[])
        if not isinstance(rows,list) or not rows or len(rows)>20000:raise ValueError('La importación admite entre 1 y 20000 matrículas')
        if len({e.get('id') for e in rows})!=len(rows):raise ValueError('ID de matrícula duplicado dentro del lote')
        idx={e['id']:e for e in s['enrollments']}
        for e in rows:
            if not e.get('id'):raise ValueError('Cada matrícula necesita un id estable')
            e={**e,'source':str(payload['source'])[:500],'updated_at':now()}
            affected={c['program'] for c in s['courses'] if c['id'] in [e['course'],idx.get(e['id'],{}).get('course')]}
            for p in s['programs']:
                if p['id'] in affected:p['local_close']={}
            if e['id'] in idx:idx[e['id']].update(e)
            else:s['enrollments'].append(e);idx[e['id']]=e
        return f"{len(rows)} matrículas; origen {payload['source']}"
    return mutate(change,'importacion')
@app.post('/api/penalties')
def pen():
    d=request.json;vals=[float(d[k]) for k in ['approved','current','priority']]
    if not all(0<=x<=100 for x in vals):raise ValueError('Puntuaciones y porcentajes entre 0 y 100')
    amount=float(d['amount']) if d.get('amount') not in [None,''] else None
    if amount is not None and amount<0:raise ValueError('Base negativa')
    return jsonify(engine.penalties(*vals,amount))
@app.get('/api/source/<sid>')
def source(sid):
    s,_=load_state();src=next((x for x in s['sources'] if x['id']==sid),None)
    if not src:abort(404)
    return send_from_directory(BASE/'sources',src['file'],as_attachment=False)
@app.get('/api/audit')
@admin
def audit_log():
    with db() as con:return jsonify(rows=[dict(r) for r in con.execute('SELECT * FROM audit ORDER BY id DESC LIMIT 200')])
@app.get('/api/export')
@admin
def export():
    s,r=load_state();res=jsonify(schema_version='sepe-backup-v1',revision=r,exported_at=now(),state=s);res.headers['Content-Disposition']='attachment; filename=sepe_copia_datos.json';return res
@app.get('/api/courses.csv')
def courses_csv():
    s,_=load_state();buf=io.StringIO();w=csv.writer(buf);w.writerow(['id','entidad','expediente','accion','codigo','curso','objetivo','horas','inicio','fin','fuente','localizador'])
    def safe(x):
        x=str(x or '');return "'"+x if x.startswith(('=','+','-','@')) else x
    for c in s['courses']:w.writerow([safe(c.get(k)) for k in ['id','entity','program','action','code','title','target','hours','start','end','source','source_locator']])
    return app.response_class('\ufeff'+buf.getvalue(),mimetype='text/csv',headers={'Content-Disposition':'attachment; filename=cursos_sepe.csv'})
@app.post('/api/password')
def password():
    d=request.json;new=str(d.get('new',''))
    if len(new)<12:raise ValueError('Contraseña de al menos 12 caracteres')
    with db() as con:
        u=con.execute('SELECT * FROM users WHERE username=?',(session['user'],)).fetchone()
        if not check_password_hash(u['password'],d.get('old','')):abort(400,description='Contraseña actual incorrecta')
        con.execute('UPDATE users SET password=?,version=version+1 WHERE username=?',(generate_password_hash(new),session['user']));session['version']+=1;audit(con,'password','Contraseña actualizada')
    return jsonify(ok=True)

from integrations.routes import register as register_integration_routes
register_integration_routes(app,db,load_state,mutate,admin,now,audit)

def cli():
    parser=argparse.ArgumentParser();sub=parser.add_subparsers(dest='cmd');p=sub.add_parser('user');p.add_argument('username');p.add_argument('--role',choices=['admin','gestor','lector'],default='gestor');p.add_argument('--manager',default='g1');p=sub.add_parser('disable');p.add_argument('username');sub.add_parser('backup');args=parser.parse_args()
    if args.cmd=='user':
        username=args.username.lower().strip()
        if not __import__('re').fullmatch(r'[a-z0-9_.@-]{3,100}',username):raise ValueError('Nombre de usuario inválido')
        password=getpass.getpass('Contraseña (mínimo 12 caracteres): ')
        if len(password)<12 or password!=getpass.getpass('Repetir contraseña: '):raise ValueError('Contraseña demasiado corta o no coincide')
        with db() as con:
            if con.execute('SELECT 1 FROM users WHERE username=?',(username,)).fetchone():
                con.execute('UPDATE users SET password=?,role=?,manager=?,version=version+1,active=1 WHERE username=?',(generate_password_hash(password),args.role,args.manager,username))
            else:con.execute('INSERT INTO users(username,password,role,manager) VALUES(?,?,?,?)',(username,generate_password_hash(password),args.role,args.manager))
        print('Usuario guardado. No hay contraseñas predeterminadas.')
    elif args.cmd=='disable':
        with db() as con:con.execute('UPDATE users SET active=0,version=version+1 WHERE username=?',(args.username,))
        print('Usuario desactivado')
    elif args.cmd=='backup':
        path=DATA/('backup_'+datetime.now().strftime('%Y%m%d_%H%M%S')+'.sqlite3')
        with db() as con,sqlite3.connect(path) as dest:con.backup(dest)
        os.chmod(path,0o600);print(path)
    else:app.run(host='0.0.0.0' if os.environ.get('PORT') else '127.0.0.1',port=int(os.environ.get('PORT','8000')),debug=False)
if __name__=='__main__':cli()
