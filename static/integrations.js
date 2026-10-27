'use strict';
let INT=null,JOB=null,jobTimer=null;
const jobLabel=x=>({demo:'simulación',live:'datos reales',catalog:'catálogo',running:'en curso',ready:'lista para revisar',error:'error',applied:'aplicada',expired:'caducada'}[x]||x);
async function integrationsView(){
 if(AUTH.role!=='admin'){$('#content').innerHTML='<div class="panel">La configuración y sincronización requieren una cuenta administradora.</div>';return;}
 try{INT=await api('integrations');if(view!=='integrations')return;drawIntegrations();}catch(e){toast(e.message);}
}
function drawIntegrations(){
 const c=INT.connection;
 $('#content').innerHTML=`<div class="banner"><strong>REST para datos personales. GraphQL para el estado en el curso.</strong><br>${esc(INT.schema_warning)}</div>
 <div class="cards"><div class="card"><h3>API interna REST</h3>${badge(c.rest_url&&c.rest_credentials?'Configuración disponible':'Falta URL o credencial',c.rest_url&&c.rest_credentials?'good':'warn')}<p>Autenticación Basic. Las credenciales se configuran en el servidor.</p></div><div class="card"><h3>Gestión GraphQL</h3>${badge(c.graphql_url&&c.graphql_token?'Configuración disponible':'Falta URL o token',c.graphql_url&&c.graphql_token?'good':'warn')}<p>Prefijo de autenticación: ${esc(c.graphql_auth_scheme)}. Configuración disponible no significa conexión comprobada.</p></div><div class="card"><h3>Conexiones reales</h3>${badge(c.enabled?'Habilitadas':'Desactivadas',c.enabled?'good':'warn')}<p>Las consultas se inician desde los botones. No hay sincronización periódica.</p></div></div>
 <div class="panel"><div class="toolbar"><h2>1. Vincular grupos y cursos</h2>${button('Añadir vínculo','api-link')}${button('Consultar grupos de Gestión','api-start','catalog')}</div><p>Esta configuración abarca todos los planes, con independencia de los filtros superiores. Relaciona el ID del grupo en Gestión con el curso, empresa y expediente de esta herramienta.</p>${table(['Grupo Gestión','Curso local','Evidencia',''],INT.config.groups.map((g,i)=>[esc(g.gestion_group),esc(cname(g.course)),esc(g.evidence),button('Editar','api-link',String(i))+button('Quitar vínculo','api-unlink',String(i))]))}</div>
 <div class="panel"><h2>2. Revisar campos y estados</h2><p>Empresa, sector y situación laboral necesitan campos confirmados en la API interna. «Baja» no se interpreta automáticamente como abandono o anulación.</p><div class="toolbar">${button('Campos personales REST','api-fields')}${button('Equivalencias de estados','api-states')}${button('Sectores por expediente','api-sectors')}${button('Enlaces de identidades y matrículas','api-identities')}</div></div>
 <div class="panel"><h2>3. Consultar y revisar</h2><p>La vista previa muestra los registros listos y las incidencias. Aplicar guarda únicamente los registros listos. Los excluidos permanecen pendientes y las ausencias nunca se convierten en bajas.</p><div class="toolbar">${button('Simulación sin conexión','api-start','demo')}${button('Consultar APIs reales','api-start','live','primary')}</div><p class="mini">Los resultados importados requieren revisión documental para considerarse certificados válidos. El esquema recibido no incluye un porcentaje directo de avance.</p><div id="sync-job"></div></div>
 <div class="panel"><h2>Consultas recientes</h2>${table(['Fecha','Modo','Estado','Usuario',''],INT.jobs.map(j=>[esc(new Date(j.created*1000).toLocaleString('es-ES')),esc(jobLabel(j.mode)),esc(jobLabel(j.status)),esc(j.actor),button('Abrir','api-job',j.id)]))}</div>`;
 if(JOB)drawJob();
}
async function saveIntegration(config){await api('integrations/config',{revision:REV,config});$('#detail').close();JOB=null;await refresh();toast('Configuración guardada');}
function integrationDialog(action,id){
 const cfg=INT.config;
 if(action==='api-link'){
  const i=id===''?-1:+id,g=cfg.groups[i]||{};
  dialog(`<h2>Vincular grupo de Gestión</h2><form id="api-link-form" class="form-grid"><input type="hidden" name="index" value="${i}">${field('gestion_group','ID numérico del grupo en Gestión',g.gestion_group,'text','required pattern="[0-9]+"')}<label>Curso de Akacenter o Juan Pablo<select name="course">${S.courses.map(c=>`<option value="${esc(c.id)}" ${g.course===c.id?'selected':''}>${esc(ename(c.entity)+' · '+c.program+' · '+c.code+' · '+c.location)}</option>`).join('')}</select></label>${field('evidence','Documento o comprobación del vínculo',g.evidence,'text','required')}<button class="primary">Guardar vínculo</button></form>`);
 }
 if(action==='api-fields')dialog(`<h2>Campos personales de la API interna</h2><p>Rutas dentro de la respuesta GET /gestion/alumnos/{id}. Deja vacío lo que el servicio no devuelva. Ejemplo de sintaxis: empresa.cif. El ejemplo no implica que ese campo exista en el esquema recibido.</p><form id="api-fields-form" class="form-grid">${[['ccaa','Comunidad autónoma'],['company','Identificador de empresa / CIF'],['company_name','Nombre de empresa'],['sector','Sector / convenio / CNAE'],['employment','Situación laboral al inicio'],['priority','Prioritario (booleano)'],['as_of','Fecha de referencia de los datos']].map(([k,l])=>field(k,l,cfg.profile_fields[k])).join('')}<label class="full">Correspondencias de situación laboral (JSON)<textarea name="employment_map" rows="6">${esc(JSON.stringify(cfg.employment_map,null,2))}</textarea></label><label class="full">Evidencia del significado y fecha de estos campos<textarea name="evidence">${esc(cfg.field_evidence)}</textarea></label><p class="mini full">Si no hay CCAA explícita se puede derivar del código postal de domicilio cuando el país es España. Esa derivación queda identificada.</p><button class="primary">Guardar campos</button></form>`);
 if(action==='api-states')dialog(`<h2>Estados de matrícula</h2><p>Claves como las devuelve Gestión, en minúsculas y sin tildes. Destinos: matriculado, iniciado, finalizado, abandono, anulado o sustituido. Este mapa no valida asistencia ni certificación.</p><form id="api-states-form"><label>Equivalencias (JSON)<textarea name="mapping" rows="12">${esc(JSON.stringify(cfg.state_map,null,2))}</textarea></label>${field('evidence','Documento que explica los estados',cfg.state_evidence,'text','required')}<button class="primary">Guardar equivalencias</button></form>`);
 if(action==='api-sectors')dialog(`<h2>Sectores por expediente</h2><p>Configura los valores exactos del sector de la empresa en listas own (propio) y other (otro), con evidence. No se considera «otro» todo lo que no coincida. Ejemplo: {"F251838AA":{"own":["EDUCACIÓN"],"other":[],"evidence":"Documento revisado"}}.</p><form id="api-sectors-form"><textarea aria-label="Reglas de sector" name="rules" rows="14">${esc(JSON.stringify(cfg.sector_rules,null,2))}</textarea><button class="primary">Guardar reglas</button></form>`);
 if(action==='api-identities')dialog(`<h2>Enlaces explícitos</h2><p>Por defecto se busca el ID interno por NIF y se comprueba que ambas fichas coincidan. Si la API de búsqueda devuelve un formato diferente o falta el NIF, documenta el enlace. Una discrepancia de NIF siempre bloquea la unión.</p><form id="api-identities-form"><label>ID alumno Gestión a ID REST (JSON)<textarea name="identities" rows="7">${esc(JSON.stringify(cfg.identity_links,null,2))}</textarea></label><p class="mini">Formato: {"ID_GESTION":{"rest_id":"ID_REST","evidence":"Comprobación"}}</p><label>ID matrícula Gestión a ID matrícula local ya existente (JSON)<textarea name="enrollments" rows="7">${esc(JSON.stringify(cfg.enrollment_links,null,2))}</textarea></label><p class="mini">Formato: {"ID_MATRICULA_GESTION":{"local_id":"ID_LOCAL","evidence":"Conciliación"}}. Evita duplicar matrículas cargadas manualmente.</p><button class="primary">Guardar enlaces</button></form>`);
}
async function integrationAction(act,id){
 if(!act.startsWith('api-'))return;
 if(['api-link','api-fields','api-states','api-sectors','api-identities'].includes(act))return integrationDialog(act,id);
 if(act==='api-unlink'){const cfg=structuredClone(INT.config);cfg.groups.splice(+id,1);return saveIntegration(cfg);}
 if(act==='api-start'){const r=await api('integrations/preview',{revision:REV,mode:id});return pollJob(r.id);}
 if(act==='api-job')return pollJob(id);
 if(act==='api-apply'){await api('integrations/apply',{revision:REV,job_id:JOB.id});JOB=null;await refresh();toast('Registros listos aplicados. Revisa las incidencias pendientes.');}
 if(act==='api-provenance'){
  const e=S.enrollments.find(x=>x.id===id),src=e.integration;
  dialog(`<h2>Origen de ${esc(e.name||e.person)}</h2><p>Gestión: alumno ${esc(src.gestion_person_id)}, matrícula ${esc(src.gestion_id)}, grupo ${esc(src.group_id)}. Interna REST: alumno ${esc(src.rest_person_id)}.</p><p>Última consulta: ${esc(src.synced_at)}. Estado original: ${esc(src.raw_state)}.</p>${table(['Dato','Fuente','Campo y regla'],Object.entries(src.provenance).map(([k,v])=>[esc(k),esc(v.api),esc(v.field||'')+'<br>'+esc(v.rule||'')]))}<h3>Datos pendientes</h3><ul>${src.issues.map(x=>'<li>'+esc(x)+'</li>').join('')}</ul><h3>Correcciones manuales</h3><pre>${esc(JSON.stringify(e.manual_overrides||{},null,2))}</pre><h3>Versiones anteriores</h3><pre>${esc(JSON.stringify(e.integration_history||[],null,2))}</pre>`);
 }
}
async function integrationSubmit(f,d){
 if(!f.getAttribute('id').startsWith('api-'))return false;
 const cfg=structuredClone(INT.config),id=f.getAttribute('id');
 if(id==='api-link-form'){const g={gestion_group:d.gestion_group,course:d.course,evidence:d.evidence};if(+d.index<0)cfg.groups.push(g);else cfg.groups[+d.index]=g;}
 if(id==='api-fields-form'){for(const k of Object.keys(cfg.profile_fields))cfg.profile_fields[k]=d[k].trim();cfg.employment_map=JSON.parse(d.employment_map);cfg.field_evidence=d.evidence;}
 if(id==='api-states-form'){cfg.state_map=JSON.parse(d.mapping);cfg.state_evidence=d.evidence;}
 if(id==='api-sectors-form')cfg.sector_rules=JSON.parse(d.rules);
 if(id==='api-identities-form'){cfg.identity_links=JSON.parse(d.identities);cfg.enrollment_links=JSON.parse(d.enrollments);}
 await saveIntegration(cfg);return true;
}
async function pollJob(id){
 if(jobTimer)clearTimeout(jobTimer);
 try{JOB=await api('integrations/jobs/'+encodeURIComponent(id));if(view!=='integrations')return;drawJob();if(JOB.status==='running')jobTimer=setTimeout(()=>pollJob(id),1500);}catch(e){toast(e.message);}
}
function drawJob(){
 const target=$('#sync-job');if(!target||!JOB)return;const p=JOB.payload;
 let html=`<h3>Consulta ${esc(jobLabel(JOB.mode))}: ${esc(jobLabel(JOB.status))}</h3><p>${esc(JOB.progress||'')}</p>`;
 if(JOB.error)html+=`<div class="banner">${esc(JOB.error)}</div>`;
 if(p?.mode==='catalog')html+=table(['ID grupo Gestión','Código','Nombre','Expediente','Inicio','Fin'],p.groups.map(g=>[esc(g.id),esc(g.codigo),esc(g.nombre),esc(g.financiacion?.expediente),date(g.finicio),date(g.ffin)]));
 else if(p){html+=`<p><strong>${p.counts.ready} registros listos</strong> de ${p.counts.received}. ${p.counts.blocked} excluidos. ${p.counts.incomplete} con información pendiente. ${p.counts.observed_final} finales comunicados; ${p.counts.validated_final} finales validados.</p>`;
  if(p.mode==='demo')html+='<div class="banner">SIMULACIÓN: datos ficticios. No se pueden incorporar a los alumnos reales.</div>';
  if(JOB.status==='ready'&&p.mode==='live'&&p.counts.ready)html+=button(`Aplicar ${p.counts.ready} registros listos`,'api-apply','','primary');
  html+=table(['Matrícula','Alumno','Estado','CCAA','Empresa / sector','Datos pendientes'],p.rows.slice(0,100).map(e=>[esc(e.integration.gestion_id),esc(e.name),badge(e.state),esc(e.ccaa||'Pendiente'),esc(e.company_name||e.company||'Pendiente')+'<br>'+esc(e.sector_code||'Pendiente'),esc(e.integration.issues.join('; '))]));
  if(p.rows.length>100)html+='<p>Vista limitada a las primeras 100 filas. El recuento y la aplicación incluyen todos los registros listos.</p>';
  html+='<h3>Excluidos y ausencias</h3>'+table(['Grupo','Matrícula','Motivo'],[...p.issues,...p.missing].map(i=>[esc(i.group),esc(i.enrollment||i.id),esc(i.message)]));
 }
 target.innerHTML=html;
}
