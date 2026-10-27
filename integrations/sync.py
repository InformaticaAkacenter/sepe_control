"""Join REST personal data and GraphQL enrollment outcomes, with explicit provenance."""
import copy,hashlib,json,re,time,unicodedata
from datetime import datetime,date,timezone
from .clients import IntegrationError

STATES=['matriculado','iniciado','finalizado','abandono','anulado','sustituido']
FACTS=['person','course','state','employment','sector_relation','ccaa','priority','company','company_name','sector_code','name','started_at','left_at','leave_reason']
FIELDS=['ccaa','company','company_name','sector','employment','priority','as_of']
WARNING='El OpenAPI aportado describe una pasarela de Gestión. No declara empresa, sector, CCAA ni situación laboral al inicio en Alumno. Los campos no disponibles quedan pendientes.'

def norm(x):return ''.join(c for c in unicodedata.normalize('NFD',str(x or '').strip().lower()) if unicodedata.category(c)!='Mn')
def stamp():return datetime.now(timezone.utc).isoformat()
def digest(x):return hashlib.sha256(json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
def nif(x):return re.sub(r'[^A-Z0-9]','',str(x or '').upper())
def default_config():
    return {'groups':[],'profile_fields':dict.fromkeys(FIELDS,''),'field_evidence':'',
      'employment_map':{x:x for x in ['ocupado','desempleado','autonomo','erte']},
      'state_map':{x:x for x in STATES},'state_evidence':'Estados literales. Baja y códigos propios requieren interpretación documentada.',
      'sector_rules':{},'identity_links':{},'enrollment_links':{}}
def config(state):return copy.deepcopy(state.get('integration_config') or default_config())
def validate_config(value,state):
    if not isinstance(value,dict) or set(value)-set(default_config()):raise IntegrationError('Configuración de integración no reconocida')
    cfg={**default_config(),**copy.deepcopy(value)}
    if not isinstance(cfg['groups'],list) or len(cfg['groups'])>300:raise IntegrationError('Máximo 300 vínculos de grupo')
    course_ids={c['id'] for c in state['courses']};seen=set()
    for g in cfg['groups']:
        if not isinstance(g,dict) or set(g)-{'gestion_group','course','evidence'} or not re.fullmatch(r'[1-9]\d*',str(g.get('gestion_group',''))) or g.get('course') not in course_ids or not str(g.get('evidence','')).strip():raise IntegrationError('Cada grupo necesita ID de Gestión, curso local y evidencia del vínculo')
        g['gestion_group']=str(g['gestion_group'])
        if g['gestion_group'] in seen:raise IntegrationError('Un grupo de Gestión no puede asignarse dos veces')
        seen.add(g['gestion_group'])
    if not isinstance(cfg['profile_fields'],dict) or set(cfg['profile_fields'])-set(FIELDS):raise IntegrationError('Campos personales no reconocidos')
    cfg['profile_fields']={**dict.fromkeys(FIELDS,''),**cfg['profile_fields']}
    for path in cfg['profile_fields'].values():
        if not isinstance(path,str) or (path and not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*(\.[A-Za-z][A-Za-z0-9_]*){0,5}',path)):raise IntegrationError('Usa rutas de campos separadas por puntos, sin expresiones')
    if not isinstance(cfg['field_evidence'],str) or (any(cfg['profile_fields'].values()) and not cfg['field_evidence'].strip()):raise IntegrationError('Documenta el origen y significado de los campos REST configurados')
    for key,allowed in [('state_map',STATES),('employment_map',['ocupado','desempleado','autonomo','erte'])]:
        if not isinstance(cfg[key],dict) or any(not k or norm(k)!=k or v not in allowed for k,v in cfg[key].items()):raise IntegrationError('Mapa inválido: '+key+'. Claves en minúsculas y sin tildes.')
    if not str(cfg['state_evidence']).strip():raise IntegrationError('Documenta el significado de los estados')
    pids={p['id'] for p in state['programs']}
    if not isinstance(cfg['sector_rules'],dict):raise IntegrationError('Reglas sectoriales inválidas')
    for pid,rule in cfg['sector_rules'].items():
        if pid not in pids or not isinstance(rule,dict) or set(rule)-{'own','other','evidence'} or not rule.get('evidence'):raise IntegrationError('Regla sectorial sin expediente o evidencia')
        for key in ['own','other']:
            if not isinstance(rule.get(key,[]),list) or any(not isinstance(v,str) or not v.strip() for v in rule.get(key,[])):raise IntegrationError('Los sectores deben ser listas de códigos o nombres exactos')
        if {norm(x) for x in rule.get('own',[])}&{norm(x) for x in rule.get('other',[])}:raise IntegrationError('Sector clasificado a la vez como propio y otro')
    for key,target in [('identity_links','rest_id'),('enrollment_links','local_id')]:
        if not isinstance(cfg[key],dict):raise IntegrationError('Enlaces inválidos')
        vals=[]
        for gid,link in cfg[key].items():
            if not re.fullmatch(r'\d+',str(gid)) or not isinstance(link,dict) or not link.get(target) or not link.get('evidence'):raise IntegrationError('Cada enlace explícito necesita identificadores y evidencia')
            if key=='identity_links' and not re.fullmatch(r'\d+',str(link[target])):raise IntegrationError('ID REST inválido')
            if key=='enrollment_links' and link[target] not in {e['id'] for e in state['enrollments']}:raise IntegrationError('Matrícula local desconocida')
            vals.append(str(link[target]))
        if len(vals)!=len(set(vals)):raise IntegrationError('Enlaces de identidad no unívocos')
    return cfg

def get_path(obj,path):
    if not path:return None
    for part in path.split('.'):
        if not isinstance(obj,dict):return None
        obj=obj.get(part)
    return obj

# INE province codes and community names; only infer when the country is explicitly Spain.
PROVINCES={
 '01':'País Vasco','02':'Castilla-La Mancha','03':'Comunitat Valenciana','04':'Andalucía','05':'Castilla y León','06':'Extremadura','07':'Illes Balears','08':'Cataluña','09':'Castilla y León','10':'Extremadura','11':'Andalucía','12':'Comunitat Valenciana','13':'Castilla-La Mancha','14':'Andalucía','15':'Galicia','16':'Castilla-La Mancha','17':'Cataluña','18':'Andalucía','19':'Castilla-La Mancha','20':'País Vasco','21':'Andalucía','22':'Aragón','23':'Andalucía','24':'Castilla y León','25':'Cataluña','26':'La Rioja','27':'Galicia','28':'Comunidad de Madrid','29':'Andalucía','30':'Región de Murcia','31':'Comunidad Foral de Navarra','32':'Galicia','33':'Principado de Asturias','34':'Castilla y León','35':'Canarias','36':'Galicia','37':'Castilla y León','38':'Canarias','39':'Cantabria','40':'Castilla y León','41':'Andalucía','42':'Castilla y León','43':'Cataluña','44':'Aragón','45':'Castilla-La Mancha','46':'Comunitat Valenciana','47':'Castilla y León','48':'País Vasco','49':'Castilla y León','50':'Aragón','51':'Ceuta','52':'Melilla'}
def community(profile,explicit):
    from engine import CCAA
    canonical={norm(x):x for x in CCAA}
    canonical.update({'madrid':'Comunidad de Madrid','valencia':'Comunitat Valenciana','baleares':'Illes Balears','asturias':'Principado de Asturias','murcia':'Región de Murcia','navarra':'Comunidad Foral de Navarra'})
    if explicit not in [None,'']:
        return canonical.get(norm(explicit)), 'Campo REST explícito' if norm(explicit) in canonical else 'CCAA no reconocida'
    country=profile.get('pais') or get_path(profile,'domicilio.pais')
    cp=profile.get('codigo_postal') or get_path(profile,'domicilio.cp')
    if norm(country) in ['es','esp','espana','spain'] and re.fullmatch(r'\d{5}',str(cp or '')) and str(cp)[:2] in PROVINCES:
        return PROVINCES[str(cp)[:2]],'Inferida del CP de domicilio REST '+str(cp)+'; país España; tabla provincia/CCAA'
    return None,'Sin CCAA explícita ni CP español utilizable'

def normalize(profile,group,member,course,cfg,at):
    raw_state=member.get('estadomatricula');state=cfg['state_map'].get(norm(raw_state))
    if not state:raise IntegrationError('Estado de Gestión sin equivalencia: '+str(raw_state or '(vacío)')[:70])
    pid=course['program'];fields={k:get_path(profile,v) for k,v in cfg['profile_fields'].items()}
    if any(isinstance(v,(dict,list)) for v in fields.values()):raise IntegrationError('Un campo personal devuelve una lista u objeto; configura la ruta hasta su valor concreto')
    ccaa,geo_note=community(profile,fields['ccaa']);issues=[]
    employment=cfg['employment_map'].get(norm(fields['employment']),'desconocido')
    if employment=='desconocido':issues.append('Situación laboral al inicio pendiente')
    elif not fields['as_of']:issues.append('La situación laboral REST no tiene fecha de referencia; confirmar que corresponde al inicio')
    if employment!='desempleado' and not fields['company']:issues.append('Identificador de empresa pendiente')
    sector=fields['sector'];rule=cfg['sector_rules'].get(pid,{})
    relation='no_aplica' if employment=='desempleado' else 'desconocido'
    if employment not in ['desempleado','desconocido']:
        if norm(sector) and norm(sector) in {norm(x) for x in rule.get('own',[])}:relation='propio'
        elif norm(sector) and norm(sector) in {norm(x) for x in rule.get('other',[])}:relation='otro'
    if relation=='desconocido':issues.append('Sector o correspondencia con el plan pendiente')
    if not ccaa:issues.append(geo_note)
    priority=fields['priority'] if isinstance(fields['priority'],bool) else None
    if priority is None:issues.append('Colectivo prioritario pendiente')
    # Never derive employment from matrícula.state and never use a course's sector as the employer's sector.
    aid=str(member['alumno']['id']);remote_id=str(member['id']);local_id=cfg['enrollment_links'].get(remote_id,{}).get('local_id','gestion_'+remote_id)
    e={'id':local_id,'person':'gestion:'+aid,'course':course['id'],'state':state,'employment':employment,
      'sector_relation':relation,'ccaa':ccaa,'priority':priority,'company':str(fields['company'] or ''),
      'company_name':str(fields['company_name'] or ''),'sector_code':str(sector or ''),
      'name':' '.join(str(x) for x in [profile.get('nombre'),profile.get('apellidos') or ' '.join(filter(None,[profile.get('apellido1'),profile.get('apellido2')]))] if x),
      'started_at':member.get('falta'),'left_at':member.get('fbaja'),'leave_reason':member.get('motivobaja'),
      'progress':None,'validated':False,'certified_valid':False,'evidence':'','updated_at':at,
      'source':'API interna REST + Gestión GraphQL',
      'integration':{'gestion_id':remote_id,'gestion_person_id':aid,'rest_person_id':str(profile['id']),'group_id':str(group['id']),
        'synced_at':at,'raw_state':raw_state,'profile_as_of':fields['as_of'],'issues':issues,
        'provenance':{'name':{'api':'Interna REST','field':'nombre / apellidos / apellido1 / apellido2'},
          'state':{'api':'Gestión GraphQL','field':'grupo.grupoalumnoSet.estadomatricula','raw':raw_state,'rule':cfg['state_evidence']},
          'dates':{'api':'Gestión GraphQL','field':'falta / fbaja / motivobaja'},
          'ccaa':{'api':'Interna REST','field':cfg['profile_fields']['ccaa'] or 'codigo_postal / domicilio.cp / pais','rule':geo_note},
          **{key:{'api':'Interna REST','field':cfg['profile_fields'][key] or 'No declarado en el esquema recibido','raw':fields[key],'rule':cfg['field_evidence']} for key in ['company','company_name','sector','employment','priority','as_of']},
          'sector_relation':{'api':'Interna REST + regla del expediente','rule':rule.get('evidence','Sin regla documentada'),'sector':sector,'program':pid},
          'progress':{'api':'Gestión GraphQL','field':'No existe un porcentaje de avance directo en GrupoAlumnoType'}}}}
    # Fingerprint contains data and mapping semantics, never fetch timestamp.
    e['integration']['fingerprint']=digest({'facts':{k:e[k] for k in FACTS},'group_id':str(group['id']),'rest_id':str(profile['id']),'provenance':e['integration']['provenance']})
    return e

def build_preview(state,rest,gestion,mode='live',progress=None):
    cfg=validate_config(config(state),state);courses={c['id']:c for c in state['courses']};existing={e['id']:e for e in state['enrollments']}
    at=stamp();rows=[];issues=[];missing=[];profile_cache={};seen_remote=set();identity_docs={};doc_ids={};rest_ids={};group_result=[];deadline=time.monotonic()+300
    for pos,link in enumerate(cfg['groups']):
        if time.monotonic()>deadline:raise IntegrationError('La consulta superó cinco minutos. Divide los grupos en lotes menores.')
        if progress:progress(pos,len(cfg['groups']))
        group=gestion.group(link['gestion_group']);course=courses[link['course']];fin=(group.get('financiacion') or {}).get('expediente')
        if fin and str(fin).strip()!=course['program']:raise IntegrationError('El expediente del grupo '+str(group['id'])+' no coincide con el curso local')
        group_ids=set();n0=len(rows)
        for member in group['grupoalumnoSet']:
            if time.monotonic()>deadline:raise IntegrationError('La consulta superó cinco minutos. Reduce el número de grupos.')
            remote_id=str(member.get('id',''))
            if not re.fullmatch(r'\d+',remote_id) or remote_id in seen_remote:raise IntegrationError('Matrícula remota sin ID válido o repetida')
            seen_remote.add(remote_id);group_ids.add(remote_id)
            if len(seen_remote)>20000:raise IntegrationError('Máximo 20000 matrículas por consulta')
            try:
                person=member.get('alumno') or {};aid=str(person.get('id',''));doc=nif(person.get('nif'))
                if not re.fullmatch(r'\d+',aid):raise IntegrationError('Alumno de Gestión sin ID válido')
                if aid in identity_docs and identity_docs[aid]!=doc:raise IntegrationError('Un mismo alumno de Gestión presenta documentos de identidad distintos')
                if doc and doc in doc_ids and doc_ids[doc]!=aid:raise IntegrationError('El mismo documento aparece con varios IDs de alumno en Gestión; conciliar antes de unir')
                identity_docs[aid]=doc
                if doc:doc_ids[doc]=aid
                mf=(member.get('financiacion') or {}).get('expediente')
                if mf and str(mf).strip()!=course['program']:raise IntegrationError('La financiación de la matrícula pertenece a otro expediente')
                key=(aid,doc)
                if key not in profile_cache:
                    identity=cfg['identity_links'].get(aid)
                    rid=str(identity['rest_id']) if identity else rest.find_id(doc)
                    profile=rest.profile(rid);rdoc=nif(profile.get('nif'))
                    if rid in rest_ids and rest_ids[rid]!=aid:raise IntegrationError('Una ficha interna se está vinculando a varios alumnos de Gestión')
                    if doc and rdoc and doc!=rdoc:raise IntegrationError('Los documentos de identidad no coinciden entre APIs')
                    if not identity and (not doc or not rdoc):raise IntegrationError('Identidad no comprobable; requiere enlace explícito con evidencia')
                    rest_ids[rid]=aid
                    profile_cache[key]=profile
                profile=profile_cache[key]
                e=normalize(profile,group,member,course,cfg,at);old=existing.get(e['id'])
                manual=[x for x in state['enrollments'] if x['course']==course['id'] and not x.get('integration') and x['id'] not in {v['local_id'] for v in cfg['enrollment_links'].values()}]
                if manual:raise IntegrationError('Hay matrículas manuales en este curso. Vincúlalas por ID antes de importar para evitar duplicados.')
                if old and old['course']!=e['course']:raise IntegrationError('La matrícula existente pertenece a otro curso; conciliar el vínculo antes de importar')
                if old and old.get('integration',{}).get('fingerprint')==e['integration']['fingerprint']:
                    for k in ['validated','certified_valid','evidence','progress']:e[k]=old.get(k)
                    e['manual_overrides']=copy.deepcopy(old.get('manual_overrides',{}))
                    for k,v in e['manual_overrides'].items():e[k]=v['value']
                elif old and (old.get('validated') or old.get('certified_valid') or old.get('manual_overrides')):
                    e['integration']['issues'].append('Los datos de origen cambiaron; se requiere nueva revisión de validaciones y correcciones manuales')
                e['integration']['operation']='actualizar' if old else 'crear';rows.append(e)
            except IntegrationError as err:issues.append({'group':str(group['id']),'enrollment':remote_id,'message':str(err)})
        for old in state['enrollments']:
            src=old.get('integration',{})
            if src.get('group_id')==str(group['id']) and src.get('gestion_id') not in group_ids:
                missing.append({'id':old['id'],'group':str(group['id']),'message':'No aparece en la respuesta. Se conserva sin convertirlo en baja o anulación.'})
        group_result.append({'id':str(group['id']),'course':course['id'],'received':len(group['grupoalumnoSet']),'ready':len(rows)-n0,'start':group.get('finicio'),'end':group.get('ffin'),'financing_present':bool(fin)})
    candidate=copy.deepcopy(state);apply_rows(candidate,rows,at)
    import engine
    engine.validate_state(candidate)
    return {'mode':mode,'created_at':at,'config_digest':digest(cfg),'rows':rows,'issues':issues,'missing':missing,'groups':group_result,
      'counts':{'received':len(seen_remote),'ready':len(rows),'blocked':len(issues),'missing':len(missing),'incomplete':sum(bool(e['integration']['issues']) for e in rows),'observed_final':sum(e['state']=='finalizado' for e in rows),'validated_final':sum(e['state']=='finalizado' and e['validated'] for e in rows)},'schema_warning':WARNING}

def apply_rows(state,rows,at):
    index={e['id']:e for e in state['enrollments']};cmap={c['id']:c for c in state['courses']};affected=set()
    for row in rows:
        e=copy.deepcopy(row);old=index.get(e['id']);affected.add(cmap[e['course']]['program'])
        if old:
            history=old.get('integration_history',[])
            if old.get('integration',{}).get('fingerprint')!=e['integration']['fingerprint']:
                history=history+[{'at':at,'facts':{k:old.get(k) for k in FACTS},'validated':old.get('validated'),'certified_valid':old.get('certified_valid'),'evidence':old.get('evidence'),'source':old.get('integration'),'manual_overrides':old.get('manual_overrides',{})}]
            e['integration_history']=history
            # Preserve non-API fields, but clear stale overrides after a changed source.
            old.update(e)
            if 'manual_overrides' not in e:old.pop('manual_overrides',None)
        else:state['enrollments'].append(e);index[e['id']]=e
    for p in state['programs']:
        if p['id'] in affected:p['local_close']={}
    state['last_api_sync']={'at':at,'rows':len(rows)};state['version']='2.0'

def record_manual_changes(old,new):
    if not old or not old.get('integration'):return
    if any(new.get(k,old[k])!=old[k] for k in ['course','person']):raise IntegrationError('La identidad y el curso sincronizados se corrigen en los vínculos de integración')
    changed={k:new[k] for k in FACTS+['progress'] if k in new and new[k]!=old.get(k)}
    if changed and not str(new.get('evidence','')).strip():raise IntegrationError('Documenta la corrección manual de datos importados')
    overrides=copy.deepcopy(old.get('manual_overrides',{}))
    for k,v in changed.items():overrides[k]={'value':v,'evidence':new['evidence'],'at':stamp()}
    if changed:new['manual_overrides']=overrides
