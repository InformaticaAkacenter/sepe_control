"""Deterministic, auditable calculations. No network access and no assumed API schema."""
from datetime import date,timedelta
from decimal import Decimal, ROUND_HALF_UP
from math import ceil,floor
from collections import Counter,defaultdict
import re,unicodedata

def today():
    from datetime import datetime
    from zoneinfo import ZoneInfo
    return datetime.now(ZoneInfo('Atlantic/Canary')).date()
def D(s):return date.fromisoformat(s[:10]) if s else None
def pct(n,d):return round(n/d*100,4) if d and n is not None else None
def norm(s):return ''.join(c for c in unicodedata.normalize('NFD',str(s).lower()) if unicodedata.category(c)!='Mn')
def frozen_limit(n,total,limit=.3):
    """Additional target members when every new member increases the denominator."""
    if total<=0:return None
    return max(0,int((Decimal(str(limit))*total-n)//(1-Decimal(str(limit)))))
def repair_count(n,total,limit=.3):
    return max(0,ceil(Decimal(n)/Decimal(str(limit))-total)) if total else None

def explain(label,num,den,formula,source,locator,records=None,excluded=None,unit='%',status='provisional'):
    return dict(label=label,value=pct(num,den) if unit=='%' else num,numerator=num,denominator=den,formula=formula,source=source,locator=locator,record_ids=records or [],excluded=excluded or [],unit=unit,status=status)

def selected(state,allocation=None,program=None):
    return [c for c in state['courses'] if (not allocation or c['allocation']==allocation) and (not program or c['program']==program)]

def _local_portfolio(state,allocation=None,program=None):
    courses=selected(state,allocation,program);cmap={c['id']:c for c in courses}
    rows=[e for e in state['enrollments'] if e['course'] in cmap]
    cancelled=[e for e in rows if e['state'] in ['anulado','sustituido']]
    usable=[e for e in rows if e['state'] not in ['anulado','sustituido']]
    finals=[e for e in usable if e['state']=='finalizado' and e.get('validated') is True]
    certified=[e for e in usable if e.get('certified_valid') is True and e.get('validated') is True and e['state'] in ['finalizado','abandono']]
    complete=bool(program and not allocation and next((p.get('complete') for p in state['programs'] if p['id']==program),False))
    status='verificado' if complete else 'provisional'
    n=len(certified);unem=[e for e in certified if e.get('employment')=='desempleado'];emp=[e for e in certified if e.get('employment') in ['ocupado','autonomo','erte']]
    unknown_employment=[e['id'] for e in certified if not e.get('employment') or e['employment']=='desconocido']
    priority=[e for e in certified if e.get('priority') is True];unknown_priority=[e['id'] for e in certified if e.get('priority') is None]
    geo=Counter(e['ccaa'] for e in certified if e.get('ccaa'));geounknown=[e['id'] for e in certified if not e.get('ccaa')]
    qualified=[k for k,v in geo.items() if v*20>=n and n];geopoints=20 if len(qualified)>=10 else 12 if len(qualified)>=6 else 5 if len(qualified)>=2 else 0
    # Operational execution uses confirmed finishers only, not uncertified financing.
    target=sum(c['target'] for c in courses);hours_target=sum(c['target']*c['hours'] for c in courses);hours_final=sum(cmap[e['course']]['hours'] for e in finals)
    ids=lambda rs:[e['id'] for e in rs]
    metrics=[explain('Ejecución por participantes',len(finals) if rows else None,target,'100 × finalizados validados / participantes comprometidos','programacion','Columna PARTICIPANTES COMPROMETIDOS',ids(finals),ids(cancelled)),explain('Ejecución en horas participante',hours_final if rows else None,hours_target,'100 × Σ(finalizados validados × horas) / Σ(objetivo × horas)','anexo_vii','p. 2, grado de ejecución',ids(finals),ids(cancelled)),explain('Desempleados certificados',len(unem),n,'100 × desempleados al inicio certificados válidos / certificados válidos','convocatoria','art. 5.1.f y 5.2, p. 8',ids(unem),ids(cancelled),status=status),explain('Colectivos prioritarios',len(priority),n,'100 × certificados válidos de algún colectivo prioritario / certificados válidos','convocatoria','arts. 7 y 21.13',ids(priority),ids(cancelled),status=status),explain('Alcance territorial',len(qualified),n,'Contar CCAA de domicilio con participantes certificados válidos ≥ 5 % del total','anexo_vi','A.2, pp. 2-3',ids(certified),ids(cancelled),unit='CCAA',status=status)]
    physical=[e for e in certified if cmap[e['course']]['mode']=='P']
    hp=sum(cmap[e['course']]['hours'] for e in physical);ht=sum(cmap[e['course']]['hours'] for e in certified)
    share=pct(hp,ht);a3=None if share is None else 0 if share<5 else 3 if share<=15 else 6 if share<=30 else 9 if share<=50 else 12 if share<=70 else 15
    metrics.append(explain('Peso presencial / aula virtual',hp,ht,'100 × Σ(certificados válidos presenciales × horas) / Σ(certificados válidos × horas)','anexo_vi','A.3, pp. 3–4',ids(physical),ids(cancelled),status=status))
    for m in metrics:
        m['denominator_ids']=ids(certified) if m in metrics[2:] else list(cmap)
        m['excluded_details']=[{'id':e['id'],'reason':'Anulado o sustituido' if e in cancelled else 'No finalizado/validado' if m in metrics[:2] else 'Sin certificación válida y validación'} for e in rows if e['id'] not in (ids(finals) if m in metrics[:2] else ids(certified))]
        if m['numerator'] is None:m['value']=None
        m['data_sources']=sorted({e.get('source','Manual') for e in rows});m['updated_at']=max((e.get('updated_at','') for e in rows),default=None)
    if unknown_employment:metrics[2]['status']='incompleto';metrics[2]['unknown_ids']=unknown_employment
    if unknown_priority:metrics[3]['status']='incompleto';metrics[3]['unknown_ids']=unknown_priority
    if geounknown:metrics[4]['status']='incompleto';metrics[4]['unknown_ids']=geounknown
    for m in metrics[:2]:
        m['source_cells']=[{'course':c['id'],'source':c['source'],'locator':c['source_locator']} for c in courses]
    active=sum(e['state'] in ['matriculado','iniciado'] for e in usable)
    observations=[x for x in state['snapshots'] if x['course'] in cmap]
    count=sum(x['fields'].get('started',{}).get('value',0) for x in observations)
    other=[e for e in emp if e.get('sector_relation')=='otro'];same=[e for e in emp if e.get('sector_relation')=='propio']
    local_gap=max(0,target-len(finals));settings=state['settings']
    return dict(target=target,finalized=len(finals) if rows else None,active=active,certified=n,annulled=len(cancelled),started_observation=count if observations else None,unemployed=len(unem),employed=len(emp),other_sector=len(other),own_sector=len(same),sector_unknown=len(emp)-len(other)-len(same),unemployed_headroom=frozen_limit(len(unem),n) if not unknown_employment else None,occupied_needed=repair_count(len(unem),n) if not unknown_employment else None,geo=dict(geo),geo_threshold=ceil(n*.05),geo_points=geopoints,a3_points=a3,qualified_ccaa=qualified,complete=complete,metrics=metrics,scope='expediente' if program and not allocation else 'entidad' if allocation else 'cartera',remaining=local_gap if rows else None,remaining_planning=local_gap,needed_enrollments=max(0,ceil(local_gap/settings['completion'])-active),data_count=len(rows),alerts=([{'level':'alta','message':'La muestra supera el 30 % de desempleados certificados'}] if n and len(unem)/n>.3 else [])+([{'level':'media','message':'La muestra no alcanza el 50 % de colectivos prioritarios; faltan '+str(max(0,ceil(n*.5)-len(priority)))+' participaciones prioritarias con total fijo'}] if n and len(priority)/n<.5 else [])+([{'level':'media','message':'La distribución territorial observada pierde puntos A.2 frente a la resolución'}] if program and n and geopoints<next(p['vt']['a2'] for p in state['programs'] if p['id']==program) else []),coverage_note='Se incluyen todas las entidades según declaración documentada del administrador.' if complete else 'Cobertura parcial. No acredita el cumplimiento del expediente completo. Datos de socios y GraphQL pendientes.')

# Human-reviewed curriculum families. These describe affinity, never admission rights.
FAMILIES={
 'idiomas':['ingles','idioma','frances','aleman','chino','espanol'],
 'contabilidad':['contab','fiscal','financier','sage','nomina','salario'],
 'datos':['excel','big data','inteligencia artificial','chatgpt','business intelligence','bussines intelligence','trasnformacion','power bi','ofimat','base de datos'],
 'seguridad':['ciberseg','seguridad informat','teletrabajo','proteccion de datos'],
 'docencia':['docen','formador','ensenanza','educa','aprendiz','competencia','tutor','alumn','escolar'],
 'comercio':['comerc','marketing','redes sociales','client','venta','gamific','fideliz','negocio'],
 'hosteleria':['cocin','menu','alerg','aliment','restaur','catering','pasteler','gastron','hostel'],
 'turismo':['turis','amadeus','evento','protocolo','animacion'],
 'tecnica':['electri','domot','industrial','hibrid','vehicul','mantenim'],
 'logistica':['almacen','logist','carretilla'],
 'personas':['recursos humanos','igualdad','emocional','equip','lider','seleccion','asertiv','resiliencia','mediacion','conflicto']}
def tags(c):
    text=norm(c['title']);return {k for k,words in FAMILIES.items() if any(w in text for w in words)}
def stage(c):
    t=norm(c['title']);return 3 if any(w in t for w in ['avanzad','power bi','business intelligence']) else 2 if any(w in t for w in ['intermedio','financiera','nomina','analisis']) else 1 if any(w in t for w in ['inicial','basico','basica','fundamento','introduc']) else 2

def recommendations(state,course_id,person=None):
    origin=next(c for c in state['courses'] if c['id']==course_id);ta=tags(origin);out=[]
    history=[e for e in state['enrollments'] if person and e['person']==person and e['state'] not in ['anulado','sustituido']]
    cmap={c['id']:c for c in state['courses']};used={cmap[e['course']]['code'] for e in history}
    for c in state['courses']:
        if c.get('date_issue') or (c.get('end') and D(c['end'])<today()):continue
        if c['code']==origin['code'] or c['code'] in used:continue
        overlap=ta&tags(c)
        if not overlap:continue
        if ta=={'idiomas'} and stage(c)<stage(origin):continue
        alloc=next(a for a in state['allocations'] if a['id']==c['allocation'])
        reasons=['Competencias comunes: '+', '.join(sorted(overlap))];conditions=['Comprobar requisitos de acceso y situación laboral al inicio.']
        points=40*len(overlap)+ (12 if stage(c)>=stage(origin) else -15)
        if c['program']!=origin['program']:reasons.append('Continuidad entre planes');points+=4
        if c['entity']!=origin['entity']:reasons.append('Oferta de la otra entidad')
        if origin.get('end') and c.get('start'):
            if D(c['start'])<=D(origin['end']):continue
            points+=10;reasons.append('Fechas posteriores al curso de origen')
        else:conditions.append('Pendiente de calendario compatible')
        if alloc.get('deadline_status')=='revisar':conditions.append('Fecha límite del plan pendiente de corrección')
        elif c.get('end') and alloc.get('deadline') and D(c['end'])>D(alloc['deadline']):continue
        if person:
            conflict=False
            for e in history:
                oc=cmap[e['course']]
                if all([c.get('start'),c.get('end'),oc.get('start'),oc.get('end')]) and max(c['start'],oc['start'])<=min(c['end'],oc['end']):conflict=True
            if conflict:continue
        p=next(p for p in state['programs'] if p['id']==c['program'])
        if p['kind']=='sectorial':conditions.append('Validar sector y cupo del plan de destino; afinidad no equivale a admisión')
        if p['kind']=='autonomos':conditions.append('Verificar acceso al programa de autónomos')
        if c['comparison_status']=='revisar':conditions.append('Contrastar discrepancia de programación con resolución')
        out.append({'course':c,'score':points,'reasons':reasons,'conditions':conditions,'status':'condicionada','formula':'40 × familias compartidas + 12 por progresión (−15 si retrocede) + 4 por cambio de plan + 10 por fechas compatibles. Regla orientativa propia.'})
    return sorted(out,key=lambda x:(-x['score'],x['course']['hours'],x['course']['id']))[:12]

def workday(d,holidays):
    while d.weekday()>4 or d.isoformat() in holidays:d+=timedelta(days=1)
    return d

def finish_day(start,days,holidays):
    d=workday(start,holidays)
    for _ in range(max(0,days-1)):d=workday(d+timedelta(days=1),holidays)
    return d

def planning(state,as_of=None):
    now=D(as_of) if as_of else today();cfg=state['settings'];holidays=set(cfg['holidays']);managers=[m for m in state['managers'] if m['active'] and m['weekly_hours']>0]
    if not managers:raise ValueError('Se necesita al menos un gestor activo con capacidad positiva')
    load=Counter();assigned=[];blocked=[];capacity=defaultdict(float)
    for t in state['tasks']:
        if t['status']!='hecha' and not t.get('planning_hold'):load[t['owner']]+=t['hours']
    def deadline(c):
        import consortium
        a=dict(next(a for a in state['allocations'] if a['id']==c['allocation']));v=consortium.deadline(state,c['program'],as_of)
        a.update(deadline=v['date'],deadline_status='revisar' if v['status']=='en_revision' else v['status']);return a
    ordered=sorted(state['courses'],key=lambda c:(deadline(c).get('deadline') or '9999',-c['target']))
    for c in ordered:
        alloc=deadline(c)
        if c.get('comparison_status')=='revisar':
            blocked.append({'course':c['id'],'reason':'Resolver discrepancia con la resolución o fechas antes de captar','source':c['source'],'locator':c['source_locator']});continue
        if not alloc.get('deadline') or alloc.get('deadline_status')=='revisar':
            blocked.append({'course':c['id'],'reason':'Confirmar fecha límite','source':alloc.get('deadline_source'),'locator':alloc.get('deadline_cell')});continue
        if c.get('start') and D(c['start'])<now:
            blocked.append({'course':c['id'],'reason':'Curso ya iniciado o pasado; revisar cierre y necesidad de nuevos grupos'});continue
        ends=D(alloc['deadline'])-timedelta(days=int(cfg['buffer_days']));start=workday(D(c['start']) if c.get('start') else now+timedelta(days=int(cfg['lead_days'])),holidays)
        duration=max(1,ceil(c['hours']/cfg['hours_per_day']));end=D(c['end']) if c.get('end') else finish_day(start,duration,holidays)
        if end>ends or start<now or end<start:
            blocked.append({'course':c['id'],'reason':'No cabe en plazo con el margen configurado'});continue
        existing=[e for e in state['enrollments'] if e['course']==c['id'] and e['state'] not in ['anulado','sustituido']]
        finals=sum(e['state']=='finalizado' and e.get('validated') is True for e in existing)
        active=sum(e['state'] in ['matriculado','iniciado'] for e in existing)
        enroll=max(0,ceil(max(0,c['target']-finals)/cfg['completion'])-active)
        leads=ceil(enroll/cfg['conversion']);hours=round((leads*cfg['contact_minutes']+enroll*cfg['followup_minutes'])/60,1)
        if not enroll:continue
        existing_task=next((t for t in state['tasks'] if t['id']=='captacion_'+c['id']),None)
        manager=next((m for m in managers if existing_task and m['id']==existing_task['owner']),None) or min(managers,key=lambda m:(load[m['id']]/m['weekly_hours'],m['id']))
        saved_group=next((g for g in state['groups'] if g['course']==c['id']),None)
        if saved_group:
            start=D(saved_group['start']);end=D(saved_group['end'])
        elif not c.get('start'):
            ready=now+timedelta(days=ceil((load[manager['id']]+hours)/manager['weekly_hours']*7))
            start=workday(max(start,ready),holidays);end=finish_day(start,duration,holidays)
        if start<now or end<start or end>ends:
            blocked.append({'course':c['id'],'reason':'La carga de captación no cabe antes del cierre con el margen configurado'});continue
        weeks=max(1,(start-now).days/7);available=weeks*manager['weekly_hours'];load[manager['id']]+=0 if existing_task else hours
        capacity[manager['id']]=available
        assigned.append({'course':c['id'],'allocation':c['allocation'],'manager':manager['id'],'start':start.isoformat(),'end':end.isoformat(),'enrollments':enroll,'contacts':leads,'hours':hours,'cohorts':ceil(enroll/cfg['cohort_size']),'deadline_status':alloc['deadline_status'],'deadline':alloc['deadline'],'capacity_warning':load[manager['id']]>available,'source':c['source'],'locator':c['source_locator'],'formula':'Matrículas=ceil((objetivo−finalizados)/tasa_finalización)−activos; contactos=ceil(matrículas/conversión); horas=(contactos×min_contacto+matrículas×min_seguimiento)/60. Reparto por carga acumulada/capacidad semanal. Sin fecha fija: inicio después de preparación y disponibilidad estimada del gestor; fin tras ceil(horas/horas_día) días laborables.'})
    return {'as_of':now.isoformat(),'proposals':assigned,'blocked':blocked,'loads':[{'manager':m['id'],'hours':round(load[m['id']],1),'weeks':round(load[m['id']]/m['weekly_hours'],1),'weekly_capacity':m['weekly_hours']} for m in managers],'method':'Heurística por fecha límite y menor carga relativa. No garantiza un óptimo global. Las horas docentes, aulas y disponibilidad de alumnos requieren confirmación.','assumptions':cfg}

def penalty_band(deviation,bands,maxdev):
    d=Decimal(str(deviation)).quantize(Decimal('.01'),rounding=ROUND_HALF_UP)
    if d>Decimal(str(maxdev)):return {'min':100,'max':100,'status':'incumplimiento_total'}
    if d<Decimal(str(bands[0][0])):return {'min':0,'max':0,'status':'sin_minoracion_en_escala'}
    hits=[]
    for a,b,c,e in bands:
        a,b,c,e=map(lambda x:Decimal(str(x)),(a,b,c,e))
        if a<=d<=b:hits.append(float(c+(d-a)/(b-a)*(e-c)))
    if not hits:return {'min':None,'max':None,'status':'revisar_limite'}
    return {'min':round(min(hits),4),'max':round(max(hits),4),'status':'frontera_ambigua' if len(hits)>1 else 'estimacion'}

def penalties(approved,current,priority_rate,justified=None):
    vt=penalty_band(max(0,approved-current),[(5,10,1,7),(10.01,15,7.01,14),(15.01,20.01,14.01,20),(20.01,25,20.01,25)],25)
    if current<50:vt={'min':100,'max':100,'status':'incumplimiento_total'}
    cp=penalty_band(max(0,50-priority_rate),[(3,10,1,5),(10.01,20,5.01,10),(20.01,30,10.01,15)],30)
    for x in [vt,cp]:
        x['amount_min']=round(justified*x['min']/100,2) if justified is not None and x['min'] is not None else None
        x['amount_max']=round(justified*x['max']/100,2) if justified is not None and x['max'] is not None else None
    return {'technical':vt,'priority':cp,'technical_deviation':approved-current,'priority_deviation':50-priority_rate,'source':'anexo_vii','locator':'pp. 4-5','formula':'Interpolación lineal entre extremos de cada tramo, con desviación redondeada a dos decimales (hipótesis de cálculo). Importe=base justificada×minoración/100. No se suman automáticamente causas distintas.','note':'El anexo solapa 20,01 en dos tramos de valoración técnica. Se muestran ambos resultados. Las cifras son una simulación, no una liquidación.'}

def validate_state(s):
    if not isinstance(s,dict):raise ValueError('Objeto JSON requerido')
    for key in ['entities','programs','allocations','courses','enrollments','tasks','managers','groups','sources','issues','snapshots']:
        if not isinstance(s.get(key),list):raise ValueError('Falta lista '+key)
    for collection in ['entities','programs','allocations','courses','enrollments','tasks','managers','groups']:
        ids=[x.get('id') for x in s[collection]]
        if any(not isinstance(i,str) or not re.fullmatch(r'[a-zA-Z0-9_.:-]{1,120}',i) for i in ids) or len(set(ids))!=len(ids):raise ValueError('Identificadores inválidos o duplicados en '+collection)
    cmap={c['id']:c for c in s['courses']};aids={a['id'] for a in s['allocations']};pids={p['id'] for p in s['programs']};mids={m['id'] for m in s['managers']}
    cfg=s['settings']
    for k in ['conversion','completion','continuation']:
        if not isinstance(cfg.get(k),(float,int)) or not 0<cfg[k]<=1:raise ValueError(k+' debe ser mayor que cero y como máximo 1')
    for k in ['contact_minutes','followup_minutes','hours_per_day','lead_days','buffer_days','cohort_size']:
        if not isinstance(cfg.get(k),(float,int)) or not 0<cfg[k]<=10000:raise ValueError('Valor inválido '+k)
    if cfg['hours_per_day']>8:raise ValueError('Máximo operativo de 8 horas al día')
    for d in cfg['holidays']:D(d)
    for m in s['managers']:
        if not 0<=float(m['weekly_hours'])<=60:raise ValueError('Capacidad semanal entre 0 y 60')
    for a in s['allocations']:
        if a['program'] not in pids:raise ValueError('Expediente desconocido')
        if a.get('deadline'):D(a['deadline'])
    for c in s['courses']:
        if c['allocation'] not in aids or c['program'] not in pids:raise ValueError('Asignación de curso desconocida')
        if not isinstance(c['target'],int) or not 0<=c['target']<=100000 or not 0<float(c['hours'])<=2000:raise ValueError('Horas u objetivo inválidos')
        if c.get('start'):D(c['start'])
        if c.get('end'):D(c['end'])
        if not c.get('date_issue') and c.get('start') and c.get('end') and c['start']>c['end']:raise ValueError('Inicio posterior al fin del curso')
    seen=set()
    for e in s['enrollments']:
        if e.get('course') not in cmap:raise ValueError('Curso no reconocido '+str(e.get('course')))
        if e.get('ccaa') and e['ccaa'] not in CCAA:raise ValueError('CCAA no reconocida; usar nombre oficial de la plantilla')
        if not e.get('person') or len(e['person'])>100:raise ValueError('Identificador de alumno obligatorio')
        if e.get('state') not in ['matriculado','iniciado','finalizado','abandono','anulado','sustituido']:raise ValueError('Estado de matrícula inválido')
        if e.get('employment') not in ['ocupado','desempleado','autonomo','erte','desconocido']:raise ValueError('Situación laboral inválida')
        if e.get('sector_relation') not in ['propio','otro','desconocido','no_aplica']:raise ValueError('Sector inválido')
        for k in ['validated','certified_valid','started_valid','priority']:
            if e.get(k) is not None and not isinstance(e[k],bool):raise ValueError(k+' debe ser booleano o nulo')
        if e.get('progress') is not None and (not isinstance(e['progress'],(int,float)) or not 0<=e['progress']<=100):raise ValueError('Progreso fuera de 0–100')
        if e.get('certified_valid') and (not e.get('validated') or e['state'] not in ['finalizado','abandono']):raise ValueError('Certificación incompatible con estado o validación')
        if e['state'] not in ['anulado','sustituido']:
            key=(e['person'].strip().upper(),cmap[e['course']]['program'],cmap[e['course']]['action'])
            if key in seen:raise ValueError('Matrícula duplicada para la misma persona y acción en el expediente')
            seen.add(key)
    task_people=set()
    for t in s['tasks']:
        if t['owner'] not in mids or t['status'] not in ['pendiente','en_curso','hecha'] or not 0<float(t['hours'])<=500:raise ValueError('Tarea inválida')
        D(t['due'])
        if t.get('person') and t['status']!='hecha':
            if t['person'].upper() in task_people:raise ValueError('Ese alumno ya tiene una tarea abierta; coordinar con su responsable')
            task_people.add(t['person'].upper())
    for p in s['programs']:
        if p.get('complete') and not p.get('coverage_source'):raise ValueError('La cobertura completa requiere evidencia de todas las entidades')
    import consortium
    return consortium.validate(s)

CCAA=['Andalucía','Aragón','Principado de Asturias','Illes Balears','Canarias','Cantabria','Castilla y León','Castilla-La Mancha','Cataluña','Comunitat Valenciana','Extremadura','Galicia','Comunidad de Madrid','Región de Murcia','Comunidad Foral de Navarra','País Vasco','La Rioja','Ceuta','Melilla']

def portfolio(state,allocation=None,program=None):
    if program and not allocation:
        import consortium
        return consortium.summary(state,program)
    return _local_portfolio(state,allocation,program)
