"""Read-only clients. URLs and credentials are read only by the server."""
import base64,json,os,re,time
from urllib.request import Request,build_opener,HTTPRedirectHandler
from urllib.parse import urlsplit,quote
from urllib.error import HTTPError,URLError

class IntegrationError(ValueError):pass

GROUP_QUERY='''query SepeGroup($id: ID!) {
  grupo(id: $id) {
    id codigo nombre finicio ffin financiacion { id expediente sector }
    grupoalumnoSet {
      id estadomatricula falta fbaja motivobaja
      alumno { id nif }
      financiacion { id expediente }
    }
  }
}'''
GROUPS_QUERY='''query SepeGroups($first: Int!, $skip: Int!) {
  allGrupos(first: $first, skip: $skip, order: "id") {
    numitems items { id codigo nombre finicio ffin financiacion { id expediente sector } }
  }
}'''

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None

def endpoint(value,label):
    p=urlsplit(value)
    if p.scheme!='https' or not p.hostname or p.username or p.password or p.query or p.fragment:
        raise IntegrationError(label+': configura una URL HTTPS completa, sin credenciales ni parámetros')
    return value.rstrip('/')

class JsonTransport:
    def __init__(self,timeout=20,max_bytes=8*1024*1024):
        self.timeout=timeout;self.max_bytes=max_bytes;self.opener=build_opener(NoRedirect())
    def __call__(self,method,url,headers,payload=None):
        data=json.dumps(payload).encode() if payload is not None else None
        req=Request(url,data=data,headers={**headers,'Accept':'application/json',**({'Content-Type':'application/json'} if data is not None else {})},method=method)
        for attempt in range(2):
            try:
                with self.opener.open(req,timeout=self.timeout) as response:
                    raw=response.read(self.max_bytes+1)
                if len(raw)>self.max_bytes:raise IntegrationError('Respuesta demasiado grande; reducir el alcance de sincronización')
                return json.loads(raw)
            except HTTPError as e:
                if e.code in [429,502,503,504] and attempt==0:time.sleep(.5);continue
                raise IntegrationError('API: HTTP '+str(e.code)+'. Revisa URL, credenciales y permisos en el servidor.') from None
            except (URLError,TimeoutError,OSError):
                if attempt==0:continue
                raise IntegrationError('API no disponible o conexión agotada; no se ha aplicado ningún cambio') from None
            except (UnicodeDecodeError,json.JSONDecodeError):raise IntegrationError('La API no ha devuelto JSON válido') from None

class GestionClient:
    def __init__(self,url,token,scheme='Bearer',transport=None):
        self.url=endpoint(url,'Gestión');self.transport=transport or JsonTransport()
        if not token or any(c in token for c in '\r\n'):raise IntegrationError('Token de gestión ausente o inválido')
        if scheme not in ['Bearer','JWT','Token','raw']:raise IntegrationError('Prefijo de token no admitido')
        self.headers={'Authorization':token if scheme=='raw' else scheme+' '+token}
    def query(self,query,variables):
        if query not in [GROUP_QUERY,GROUPS_QUERY]:raise IntegrationError('Solo se permiten las consultas de lectura predefinidas')
        result=self.transport('POST',self.url,self.headers,{'query':query,'variables':variables})
        if not isinstance(result,dict) or result.get('errors') or not isinstance(result.get('data'),dict):
            raise IntegrationError('Gestión devuelve errores GraphQL o datos incompletos. Revisa esquema, token y permisos.')
        return result['data']
    def group(self,gid):
        group=self.query(GROUP_QUERY,{'id':str(gid)}).get('grupo')
        if not isinstance(group,dict) or str(group.get('id'))!=str(gid) or not isinstance(group.get('grupoalumnoSet'),list):
            raise IntegrationError('Grupo inexistente, identidad distinta o matrículas incompletas')
        if len(group['grupoalumnoSet'])>20000:raise IntegrationError('Demasiadas matrículas en un grupo')
        return group
    def groups(self,max_pages=100):
        rows=[];seen=set();expected=None;deadline=time.monotonic()+300
        for page in range(max_pages):
            if time.monotonic()>deadline:raise IntegrationError('El catálogo supera cinco minutos de consulta')
            res=self.query(GROUPS_QUERY,{'first':100,'skip':page*100}).get('allGrupos')
            if not isinstance(res,dict) or not isinstance(res.get('items'),list) or type(res.get('numitems')) is not int:
                raise IntegrationError('Paginación de grupos sin items/numitems válidos')
            if expected is None:expected=res['numitems']
            if res['numitems']!=expected:raise IntegrationError('El catálogo cambió durante la consulta; vuelve a consultar')
            for item in res['items']:
                key=str(item.get('id'))
                if not re.fullmatch(r'\d+',key) or key in seen:raise IntegrationError('Paginación repetida o grupo sin ID')
                seen.add(key);rows.append(item)
            if len(rows)==expected:return rows
            if not res['items'] or len(rows)>expected:raise IntegrationError('Paginación incompleta o incoherente')
        raise IntegrationError('Se alcanzó el límite de páginas; no se devuelve un catálogo parcial')

class InternalClient:
    def __init__(self,url,username,password,transport=None):
        self.url=endpoint(url,'API interna');self.transport=transport or JsonTransport()
        if not username or not password or ':' in username or any(c in username+password for c in '\r\n'):
            raise IntegrationError('Usuario o contraseña de la API interna ausentes o inválidos')
        self.headers={'Authorization':'Basic '+base64.b64encode((username+':'+password).encode()).decode()}
    def get(self,path):return self.transport('GET',self.url+path,self.headers)
    def profile(self,rest_id):
        if not re.fullmatch(r'\d+',str(rest_id)):raise IntegrationError('ID interno inválido')
        row=self.get('/gestion/alumnos/'+str(rest_id))
        if not isinstance(row,dict) or str(row.get('id'))!=str(rest_id):raise IntegrationError('Ficha interna sin identidad coincidente')
        return row
    def find_id(self,nif):
        if not re.fullmatch(r'[A-Z0-9]{5,20}',nif):raise IntegrationError('Documento de identidad ausente o no reconocido para enlazar APIs')
        value=self.get('/gestion/alumnos/'+quote(nif,safe='')+'/id')
        # OpenAPI leaves this response untyped. Accept only one explicit positive ID.
        if isinstance(value,dict):value=value.get('id')
        if isinstance(value,list):
            if len(value)!=1:raise IntegrationError('La búsqueda de identidad es ambigua o no encuentra alumno')
            value=value[0]
        if isinstance(value,bool) or not re.fullmatch(r'[1-9]\d*',str(value)):raise IntegrationError('Formato de ID interno no reconocido; configura un enlace explícito')
        return str(value)

def status():
    return {'enabled':os.environ.get('SEPE_API_ENABLED')=='1',
      'rest_url':bool(os.environ.get('SEPE_INTERNAL_BASE_URL')),
      'rest_credentials':bool(os.environ.get('SEPE_INTERNAL_USERNAME') and os.environ.get('SEPE_INTERNAL_PASSWORD')),
      'graphql_url':bool(os.environ.get('SEPE_GESTION_GRAPHQL_URL')),
      'graphql_token':bool(os.environ.get('SEPE_GESTION_TOKEN')),
      'graphql_auth_scheme':os.environ.get('SEPE_GESTION_AUTH_SCHEME','Bearer')}

def live_clients():
    if os.environ.get('SEPE_API_ENABLED')!='1':raise IntegrationError('Conexiones reales desactivadas. Actívalas en el servidor después de configurar y revisar.')
    return (InternalClient(os.environ.get('SEPE_INTERNAL_BASE_URL',''),os.environ.get('SEPE_INTERNAL_USERNAME',''),os.environ.get('SEPE_INTERNAL_PASSWORD','')),
      GestionClient(os.environ.get('SEPE_GESTION_GRAPHQL_URL',''),os.environ.get('SEPE_GESTION_TOKEN',''),os.environ.get('SEPE_GESTION_AUTH_SCHEME','Bearer')))
