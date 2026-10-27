"""Fechas y resultados agregados de socios. No realiza conexiones externas."""
from datetime import date, datetime
from zoneinfo import ZoneInfo
from copy import deepcopy
from pathlib import Path
import json
from math import ceil
import csv,io,re
import engine

def upgrade(s):
    s.setdefault('partners',[]);s.setdefault('partner_reports',[])
    for p in s['programs']:
        p.setdefault('group_roster_verified',False);p.setdefault('group_roster_evidence','');p.setdefault('local_close',{})
    originals={a['id']:a for a in json.loads((Path(__file__).parent/'seed.json').read_text())['allocations']} if any('original_deadline' not in a for a in s['allocations']) else {}
    for a in s['allocations']:
        orig=originals.get(a['id'],a)
        a.setdefault('original_deadline',orig.get('deadline'));a.setdefault('original_deadline_source',orig.get('deadline_source'));a.setdefault('original_deadline_cell',orig.get('deadline_cell'))
    for p in s['programs']:
        aa=[a for a in s['allocations'] if a['program']==p['id']]
        if 'deadline_tracking' not in p and aa and all(a.get('deadline_status')=='confirmada' for a in aa) and len({a['deadline'] for a in aa})==1:
            p['deadline_tracking']={'date':aa[0]['deadline'],'status':'confirmada','evidence':'Migrado de versión 1.0: '+'; '.join(a.get('deadline_note','') for a in aa),'notification_date':None}
    s['version']='2.0'
    return s

def deadline(s,pid,as_of=None):
    p=next(x for x in s['programs'] if x['id']==pid);aa=[a for a in s['allocations'] if a['program']==pid];t=p.get('deadline_tracking')
    values={a.get('deadline') for a in aa if a.get('deadline')};conflict=len(values)>1
    if t:
        end=t.get('date');status=t['status'];evidence=t.get('evidence','')
    else:
        end=min(values) if values else None;status='en_revision' if conflict or any(a.get('deadline_status')=='revisar' for a in aa) else 'provisional';evidence='Fecha procedente de la programación; pendiente de notificación.'
    now=engine.D(as_of) if as_of else datetime.now(ZoneInfo('Atlantic/Canary')).date()
    remaining=(engine.D(end)-now).days if end else None
    invalid=[c['id'] for c in s['courses'] if c['program']==pid and c.get('start') and c.get('end') and c['end']<c['start']]
    over=[c['id'] for c in s['courses'] if c['program']==pid and end and c.get('end') and c['end']>end]
    saved_over=[g['id'] for g in s['groups'] if next(c['program'] for c in s['courses'] if c['id']==g['course'])==pid and end and g['end']>end]
    return {'program':pid,'date':end,'status':status,'evidence':evidence,'notification_date':(t or {}).get('notification_date'),'days_left':remaining,'expired':remaining is not None and remaining<0,'conflicting_originals':len({a.get('original_deadline',a.get('deadline')) for a in aa})>1,'courses_after_deadline':over,'invalid_course_dates':invalid,'saved_after_deadline':saved_over,'originals':[{'entity':a['entity'],'date':a.get('original_deadline',a.get('deadline')),'source':a.get('original_deadline_source',a.get('deadline_source')),'cell':a.get('original_deadline_cell',a.get('deadline_cell'))} for a in aa],'history':p.get('deadline_history',[])}

def set_deadline(s,d,actor,now):
    pid=d.get('program')
    if not pid and d.get('allocation'):pid=next(a['program'] for a in s['allocations'] if a['id']==d['allocation'])
    p=next(x for x in s['programs'] if x['id']==pid)
    status=d.get('status','confirmada');end=d.get('deadline');evidence=str(d.get('evidence','')).strip();notification=d.get('notification_date') or None
    if status not in ['provisional','confirmada','en_revision']:raise ValueError('Estado de fecha inválido')
    if not end:raise ValueError('Indica fecha de ejecución')
    engine.D(end)
    if notification:
        engine.D(notification)
        if notification>end:raise ValueError('La notificación no puede ser posterior al fin')
    if not evidence:raise ValueError('Indica documento y página, o motivo de revisión')
    old=deadline(s,pid);p.setdefault('deadline_history',[]).append({'date':old['date'],'status':old['status'],'evidence':old['evidence'],'changed_at':now,'actor':actor})
    p['deadline_tracking']={'date':end,'status':status,'evidence':evidence,'notification_date':notification,'updated_at':now,'actor':actor}
    for a in s['allocations']:
        if a['program']==pid:a.update(deadline=end,deadline_status={'provisional':'programacion','confirmada':'confirmada','en_revision':'revisar'}[status],deadline_note=evidence,deadline_updated=now)
    for g in s['groups']:
        if next(c['program'] for c in s['courses'] if c['id']==g['course'])==pid:
            g['deadline_status']=status;g['planning_hold']=status!='confirmada' or g['end']>end
    for t in s['tasks']:
        if t.get('course') and t['id']=='captacion_'+t['course']:
            c=next(c for c in s['courses'] if c['id']==t['course'])
            if c['program']==pid:
                g=next((g for g in s['groups'] if g['course']==c['id']),None)
                t['planning_hold']=status!='confirmada' or bool(g and g['end']>end)
    return pid

REPORT_FIELDS=['certified','unemployed','priority','own_sector','other_sector','finalized','target','final_hours','target_hours','certified_hours','physical_hours']
INT_FIELDS=set(REPORT_FIELDS)-{'final_hours','target_hours','certified_hours','physical_hours'}
def validate_report(s,r):
    partner=next((p for p in s['partners'] if p['id']==r.get('partner')),None)
    if not partner or r.get('program') not in partner['programs']:raise ValueError('Socio no asignado al expediente')
    engine.D(r.get('as_of',''))
    if not r.get('as_of') or engine.D(r['as_of'])>datetime.now(ZoneInfo('Atlantic/Canary')).date():raise ValueError('Fecha de corte ausente o futura')
    if not str(r.get('source','')).strip():raise ValueError('Cada resultado necesita documento y localizador')
    if not isinstance(r.get('verified'),bool):raise ValueError('Indica si el resumen está validado')
    if not isinstance(r.get('active',True),bool):raise ValueError('Estado de informe inválido')
    for k in REPORT_FIELDS:
        v=r.get(k)
        if v is None:continue
        if isinstance(v,bool) or not isinstance(v,(int,float)) or not 0<=v<=100000000:raise ValueError('Recuento inválido: '+k)
        if k in INT_FIELDS and int(v)!=v:raise ValueError(k+' debe ser entero')
    n=r.get('certified')
    if n is None and r['verified']:raise ValueError('Para validar, indica certificados válidos; el cero es un dato explícito')
    for k in ['unemployed','priority','own_sector','other_sector']:
        if n is not None and r.get(k) is not None and r[k]>n:raise ValueError(k+' supera certificados')
    if n is not None and sum(r.get(k) or 0 for k in ['unemployed','own_sector','other_sector'])>n:raise ValueError('Desempleados y sectores exceden los certificados')
    geo=r.get('geo',{})
    if not isinstance(geo,dict) or any(k not in engine.CCAA or isinstance(v,bool) or not isinstance(v,int) or v<0 for k,v in geo.items()):raise ValueError('Desglose de CCAA inválido')
    if n is not None and sum(geo.values())>n:raise ValueError('La suma de CCAA supera certificados')
    if r.get('physical_hours') is not None and (r.get('certified_hours') is None or r['physical_hours']>r['certified_hours']):raise ValueError('Horas presenciales incompatibles con horas certificadas')
    return r

def validate(s):
    upgrade(s);ids=set();nifs={e['nif'].upper() for e in s['entities']};pids={p['id'] for p in s['programs']}
    for p in s['partners']:
        if not re.fullmatch(r'[A-Za-z0-9_.:-]{1,100}',p['id']) or p['id'] in ids:raise ValueError('ID de socio duplicado o inválido')
        ids.add(p['id']);nif=p['nif'].strip().upper()
        if not re.fullmatch(r'[A-Z0-9]{8,12}',nif) or nif in nifs:raise ValueError('NIF duplicado o inválido; no añadir de nuevo Akacenter o Juan Pablo')
        nifs.add(nif)
        if not p['name'].strip() or not p['programs'] or not set(p['programs'])<=pids:raise ValueError('Socio sin nombre o expediente válido')
    ids=set();active=set()
    for r in s['partner_reports']:
        if not r.get('id') or r['id'] in ids:raise ValueError('ID de informe duplicado');
        ids.add(r['id']);validate_report(s,r)
        if r.get('active',True):
            key=(r['partner'],r['program'])
            if key in active:raise ValueError('Solo puede haber un corte activo por socio y expediente')
            active.add(key)
    return s

def save_report(s,r,actor,now):
    r=deepcopy(r);r.setdefault('active',True);validate_report(s,r)
    current=next((x for x in s['partner_reports'] if x['partner']==r['partner'] and x['program']==r['program'] and x.get('active',True)),None)
    if current and r.get('active',True) and r['as_of']<current['as_of']:raise ValueError('No se puede sustituir el corte activo por otro anterior')
    old=next((x for x in s['partner_reports'] if x['id']==r['id']),None)
    if old and (old['partner'],old['program'])!=(r['partner'],r['program']):raise ValueError('Un informe no puede cambiar de socio o expediente')
    if r['active']:
        for x in s['partner_reports']:
            if x['partner']==r['partner'] and x['program']==r['program'] and x['id']!=r['id']:x['active']=False
    r['updated_at']=now;r['actor']=actor
    if old:
        history=old.get('history',[])+[{k:v for k,v in old.items() if k!='history'}];old.clear();old.update(r);old['history']=history
    else:s['partner_reports'].append(r)
    return r['id']

def csv_reports(text):
    reader=csv.DictReader(io.StringIO(text.lstrip('\ufeff')),delimiter=';' if text.splitlines()[0].count(';')>text.splitlines()[0].count(',') else ',')
    rows=[]
    for x in reader:
        r={k:x.get(k,'').strip() for k in ['id','partner','program','as_of','source']};r['verified']=x.get('verified','').strip().lower() in ['true','si','sí','1'];r['active']=True;r['geo']={}
        for k in REPORT_FIELDS:
            v=x.get(k,'').strip();r[k]=None if v=='' else float(v.replace(',','.'))
            if r[k] is not None and k in INT_FIELDS:
                if not r[k].is_integer():raise ValueError(k+' debe ser entero')
                r[k]=int(r[k])
        for i,c in enumerate(engine.CCAA,1):
            v=x.get('ccaa_'+str(i).zfill(2),'').strip()
            if v:r['geo'][c]=int(v)
        rows.append(r)
    if not rows or len(rows)>2000:raise ValueError('El CSV debe contener entre 1 y 2000 informes')
    if len({r['id'] for r in rows})!=len(rows):raise ValueError('ID de informe repetido en el lote')
    if len({(r['partner'],r['program']) for r in rows})!=len(rows):raise ValueError('Un único corte por socio y expediente en cada lote')
    return rows

def summary(s,pid):
    p=next(p for p in s['programs'] if p['id']==pid);local=engine._local_portfolio(s,program=pid);partners=[x for x in s.get('partners',[]) if pid in x['programs']]
    reports=[r for r in s.get('partner_reports',[]) if r['program']==pid and r.get('active',True)];chosen=[r for r in reports if r['verified']]
    missing=[x['id'] for x in partners if not any(r['partner']==x['id'] for r in chosen)]
    close=p.get('local_close',{});cutoff=close.get('as_of');same_dates=bool(cutoff and all(r['as_of']==cutoff for r in chosen));local_closed=bool(cutoff and close.get('evidence'))
    # A cutoff declaration is invalidated by every local enrollment write.
    complete=bool(partners and p.get('group_roster_verified') and p.get('group_roster_evidence') and local_closed and not missing and same_dates)
    geos=dict(local['geo'])
    for r in chosen:
        for k,v in r.get('geo',{}).items():geos[k]=geos.get(k,0)+v
    n=local['certified']+sum(r['certified'] for r in chosen);u=local['unemployed']+sum(r.get('unemployed') or 0 for r in chosen);pri=local['metrics'][3]['numerator']+sum(r.get('priority') or 0 for r in chosen)
    unk_emp=bool(local['metrics'][2].get('unknown_ids') or any(r.get('unemployed') is None for r in chosen));unk_pri=bool(local['metrics'][3].get('unknown_ids') or any(r.get('priority') is None for r in chosen));unk_geo=sum(geos.values())!=n
    qual=[k for k,v in geos.items() if n and 20*v>=n];points=20 if len(qual)>=10 else 12 if len(qual)>=6 else 5 if len(qual)>=2 else 0
    target=local['target']+sum(r.get('target') or 0 for r in chosen);finals=(local['finalized'] or 0)+sum(r.get('finalized') or 0 for r in chosen)
    known_final=(local['finalized'] is not None or local_closed) and all(r.get('finalized') is not None for r in chosen)
    hp=local['metrics'][5]['numerator']+sum(r.get('physical_hours') or 0 for r in chosen);ht=local['metrics'][5]['denominator']+sum(r.get('certified_hours') or 0 for r in chosen)
    status='cobertura_declarada' if complete else 'parcial';metrics=deepcopy(local['metrics'])
    values=[(finals if known_final else None,target),(sum(r.get('final_hours') or 0 for r in chosen)+(local['metrics'][1]['numerator'] or 0),sum(r.get('target_hours') or 0 for r in chosen)+local['metrics'][1]['denominator']),(u,n),(pri,n),(len(qual) if n else None,n),(hp,ht)]
    unknown=[not known_final or any(r.get('target') is None for r in chosen),not(local['data_count'] or local_closed) or any(r.get('final_hours') is None or r.get('target_hours') is None for r in chosen),unk_emp,unk_pri,unk_geo,any(r.get('physical_hours') is None or r.get('certified_hours') is None for r in chosen)]
    for i,(m,(num,den)) in enumerate(zip(metrics,values)):
        m.update(numerator=num,denominator=den,value=num if i==4 else engine.pct(num,den),status='incompleto' if unknown[i] else status)
        if unknown[i]:m['value']=None
        m['formula']='Consolidado: sumar los recuentos locales y los cortes activos validados de cada socio; después aplicar: '+m['formula']
        m['partner_sources']=[{'id':r['id'],'partner':next(x['name'] for x in partners if x['id']==r['partner']),'source':r['source'],'as_of':r['as_of'],'numerator':r.get(['finalized','final_hours','unemployed','priority','certified','physical_hours'][i]),'denominator':r.get(['target','target_hours','certified','certified','certified','certified_hours'][i])} for r in chosen]
        m['denominator_ids']+=['informe:'+r['id'] for r in chosen];m['data_sources']+=list({r['source'] for r in chosen});m['updated_at']=max([m['updated_at'] or '']+[r.get('updated_at','') for r in chosen]) or None
    result=deepcopy(local);result.update(target=target,finalized=finals if known_final else None,certified=n,unemployed=u,metrics=metrics,geo=geos,geo_threshold=ceil(n/20),geo_points=points,qualified_ccaa=qual,complete=complete,unemployed_headroom=engine.frozen_limit(u,n) if not unk_emp and complete else None,occupied_needed=engine.repair_count(u,n) if not unk_emp and complete else None,own_sector=local['own_sector']+sum(r.get('own_sector') or 0 for r in chosen),other_sector=local['other_sector']+sum(r.get('other_sector') or 0 for r in chosen))
    result['employed']=n-u if not unk_emp else None
    result['sector_unknown']=max(0,n-u-result['own_sector']-result['other_sector']) if not unk_emp else None
    result['a3_points']=None if metrics[5]['value'] is None else 0 if metrics[5]['value']<5 else 3 if metrics[5]['value']<=15 else 6 if metrics[5]['value']<=30 else 9 if metrics[5]['value']<=50 else 12 if metrics[5]['value']<=70 else 15
    result['scope']='agrupacion';result['coverage_note']='Cobertura de todas las entidades declarada, con corte común. Los resúmenes agregados no permiten comprobar duplicados individuales.' if complete else 'Cobertura parcial o cortes no comparables: no acredita cumplimiento global.'
    result['coverage']={'registered_partners':len(partners),'validated_reports':len(chosen),'missing_partners':missing,'pending_reports':[r['id'] for r in reports if not r['verified']],'roster_verified':p.get('group_roster_verified',False),'local_close':close,'same_dates':same_dates,'cutoff':cutoff,'reports':reports,'individual_deduplication':False}
    result['alerts']=[]
    if n and u/n>.3:result['alerts'].append({'level':'alta','message':'La muestra consolidada supera el 30 % de desempleo'})
    if unk_pri:result['alerts'].append({'level':'media','message':'Faltan clasificaciones de colectivos prioritarios en los cortes disponibles'})
    elif n and pri/n<.5:result['alerts'].append({'level':'media','message':'Colectivos prioritarios por debajo del 50 % en los datos disponibles'})
    if n and points<p['vt']['a2']:result['alerts'].append({'level':'media','message':'El alcance territorial observado pierde puntos A.2'})
    return result
