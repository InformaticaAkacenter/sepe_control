"""Synthetic, offline responses. Never mixed into production records."""
import copy
from .sync import default_config

def demo_clients(state):
    state=copy.deepcopy(state);course=state['courses'][0]
    state['integration_config']=default_config()
    state['integration_config']['groups']=[{'gestion_group':'900001','course':course['id'],'evidence':'Simulación aislada'}]
    state['enrollments']=[]
    class Rest:
        def find_id(self,nif):return {'DEMO0001':'800001','DEMO0002':'800002'}[nif]
        def profile(self,rid):
            i=1 if str(rid)=='800001' else 2
            return {'id':int(rid),'nombre':'Alumno de ejemplo '+str(i),'apellidos':'SIMULACIÓN','nif':'DEMO000'+str(i),'codigo_postal':'35500' if i==1 else '28001','pais':'ES'}
    class Gestion:
        def group(self,gid):return {'id':str(gid),'codigo':'DEMO-1','nombre':'Grupo de simulación','finicio':'2026-10-01','ffin':'2026-11-30','financiacion':{'expediente':course['program']},'grupoalumnoSet':[
          {'id':'700001','estadomatricula':'finalizado','falta':'2026-10-01','fbaja':None,'motivobaja':None,'alumno':{'id':'600001','nif':'DEMO0001'}},
          {'id':'700002','estadomatricula':'baja','falta':'2026-10-01','fbaja':'2026-10-15','motivobaja':'Pendiente de clasificar','alumno':{'id':'600002','nif':'DEMO0002'}}]}
    return state,Rest(),Gestion()
