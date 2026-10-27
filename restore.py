"""Restauración offline; detener app antes de ejecutar."""
import argparse,sqlite3,json,os,shutil,tempfile,datetime
from pathlib import Path
import engine
p=argparse.ArgumentParser();p.add_argument('backup');a=p.parse_args();src=Path(a.backup).resolve();data=Path(os.environ.get('SEPE_DATA','data')).resolve();data.mkdir(exist_ok=True,parents=True);dest=data/'sepe.sqlite3'
owner=dest.stat() if dest.exists() else data.stat()
if src==dest:raise ValueError('La copia debe ser un archivo distinto a la base activa')
with sqlite3.connect(f'file:{src}?mode=ro',uri=True) as con:
 if con.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('La copia no supera integrity_check')
 if not {'state','users','audit','attempts'}.issubset({r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}):raise ValueError('Faltan tablas requeridas')
 engine.validate_state(json.loads(con.execute('SELECT payload FROM state WHERE id=1').fetchone()[0]))
 tmp=data/'restore.tmp.sqlite3'
 with sqlite3.connect(tmp) as out:con.backup(out);out.execute('UPDATE users SET version=version+1');out.commit()
if dest.exists():
 prev=data/('before_restore_'+datetime.datetime.now().strftime('%Y%m%d_%H%M%S')+'.sqlite3')
 with sqlite3.connect(dest) as old,sqlite3.connect(prev) as out:old.backup(out)
 os.chmod(prev,0o600)
for suffix in ['-wal','-shm']:
 path=Path(str(dest)+suffix)
 if path.exists():path.unlink()
os.replace(tmp,dest);os.chmod(dest,0o600)
if os.geteuid()==0:os.chown(dest,owner.st_uid,owner.st_gid)
print('Copia restaurada y sesiones anteriores invalidadas. Arranca la aplicación.')
