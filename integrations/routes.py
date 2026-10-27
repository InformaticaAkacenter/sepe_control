"""Admin-only staging and atomic application of API synchronization jobs."""
import json,secrets,threading,time,os
from flask import request,jsonify,abort
from . import clients,sync

def register(app,db,load_state,mutate,admin,now,audit):
    with db() as con:
        con.execute('CREATE TABLE IF NOT EXISTS sync_jobs(id TEXT PRIMARY KEY, created REAL NOT NULL, actor TEXT NOT NULL, mode TEXT NOT NULL, status TEXT NOT NULL, revision INTEGER NOT NULL, progress TEXT NOT NULL, payload TEXT, error TEXT)')

    @app.get('/api/integrations/status')
    def integration_status():return jsonify(clients.status())

    @app.get('/api/integrations')
    @admin
    def integration_settings():
        s,r=load_state()
        with db() as con:jobs=[dict(x) for x in con.execute('SELECT id,created,actor,mode,status,progress,error FROM sync_jobs ORDER BY created DESC LIMIT 20')]
        return jsonify(config=sync.config(s),connection=clients.status(),schema_warning=sync.WARNING,jobs=jobs,revision=r)

    @app.post('/api/integrations/config')
    @admin
    def integration_config():
        def change(s):s['integration_config']=sync.validate_config(request.json['config'],s);return 'Vínculos y equivalencias actualizados; no contiene credenciales'
        return mutate(change,'configuracion_apis')

    def finish(jid,status,payload=None,error=None):
        with db() as con:con.execute('UPDATE sync_jobs SET status=?,payload=?,error=?,progress=? WHERE id=?',(status,json.dumps(payload,ensure_ascii=False) if payload is not None else None,error,'Consulta terminada',jid))

    def worker(jid,state,mode):
        try:
            if mode=='demo':
                from .demo import demo_clients
                state,rest,gestion=demo_clients(state)
            else:rest,gestion=clients.live_clients()
            if mode=='catalog':payload={'mode':mode,'groups':gestion.groups(),'created_at':now()}
            else:
                def progress(done,total):
                    with db() as con:con.execute('UPDATE sync_jobs SET progress=? WHERE id=?',(f'Consultando grupo {done+1} de {total}',jid))
                payload=sync.build_preview(state,rest,gestion,mode,progress)
            finish(jid,'ready',payload)
        except (clients.IntegrationError,ValueError,KeyError,TypeError) as e:
            # Never store server replies, headers or transport exception strings.
            message=str(e) if isinstance(e,clients.IntegrationError) else 'Los datos recibidos no pasan la validación. Revisa los vínculos, identificadores y formatos.'
            finish(jid,'error',error=message[:350])
        except Exception:finish(jid,'error',error='La consulta no pudo completarse. No se aplicó ningún cambio.')

    @app.post('/api/integrations/preview')
    @admin
    def integration_preview():
        from flask import session
        mode=request.json.get('mode','live')
        if mode not in ['live','demo','catalog']:raise ValueError('Modo desconocido')
        s,rev=load_state()
        if request.json.get('revision')!=rev:abort(409,description='Actualiza la aplicación antes de consultar')
        if mode!='demo':clients.live_clients() # configuration validation only; no network
        if mode=='live' and not sync.config(s)['groups']:raise ValueError('Vincula al menos un grupo de Gestión con un curso local')
        jid=secrets.token_hex(16)
        with db() as con:
            con.execute('BEGIN IMMEDIATE')
            con.execute("UPDATE sync_jobs SET status='expired',payload=NULL,error='Consulta caducada; vuelve a preparar una vista previa' WHERE status IN ('running','ready') AND created<?",(time.time()-1800,))
            con.execute('UPDATE sync_jobs SET payload=NULL WHERE created<?',(time.time()-86400,))
            if con.execute("SELECT 1 FROM sync_jobs WHERE status='running'").fetchone():abort(409,description='Ya hay una consulta en curso. Espera a que termine.')
            con.execute('INSERT INTO sync_jobs VALUES(?,?,?,?,?,?,?,?,?)',(jid,time.time(),session['user'],mode,'running',rev,'Preparando consulta',None,None));audit(con,'consulta_apis','Modo '+mode+'; trabajo '+jid)
        threading.Thread(target=worker,args=(jid,s,mode),daemon=True).start()
        return jsonify(id=jid,status='running'),202

    @app.get('/api/integrations/jobs/<jid>')
    @admin
    def integration_job(jid):
        with db() as con:r=con.execute('SELECT * FROM sync_jobs WHERE id=?',(jid,)).fetchone()
        if not r:abort(404)
        result=dict(r);result['payload']=json.loads(result['payload']) if result['payload'] else None
        if result['status']=='ready' and time.time()-result['created']>1800:result['status']='expired'
        return jsonify(result)

    @app.post('/api/integrations/apply')
    @admin
    def integration_apply():
        jid=request.json['job_id'];expected=request.json.get('revision')
        import consortium,engine
        with db() as con:
            con.execute('BEGIN IMMEDIATE');job=con.execute('SELECT * FROM sync_jobs WHERE id=?',(jid,)).fetchone()
            if not job or job['mode']!='live' or job['status']!='ready':abort(400,description='Solo se puede aplicar una consulta real pendiente; la simulación nunca se guarda como alumnos reales')
            if time.time()-job['created']>1800:abort(409,description='La vista previa ha caducado. Consulta de nuevo.')
            row=con.execute('SELECT * FROM state WHERE id=1').fetchone()
            if expected!=row['revision'] or job['revision']!=row['revision']:abort(409,description='Los datos cambiaron después de la vista previa. Prepara una nueva consulta.')
            state=consortium.upgrade(json.loads(row['payload']));payload=json.loads(job['payload'])
            if sync.digest(sync.config(state))!=payload['config_digest']:abort(409,description='La configuración cambió. Consulta de nuevo.')
            if not payload['rows']:abort(400,description='No hay matrículas listas para aplicar')
            sync.apply_rows(state,payload['rows'],now());engine.validate_state(state)
            con.execute('UPDATE state SET payload=?,revision=revision+1 WHERE id=1',(json.dumps(state,ensure_ascii=False),))
            con.execute("UPDATE sync_jobs SET status='applied' WHERE id=?",(jid,))
            audit(con,'sincronizacion_apis',f"Trabajo {jid}; {len(payload['rows'])} matrículas; {len(payload['issues'])} excluidas para revisión")
        return jsonify(ok=True,revision=row['revision']+1)
