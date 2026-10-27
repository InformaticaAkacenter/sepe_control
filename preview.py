"""Solo revisión local mediante el entorno de preview; no usar en producción."""
import os,argparse
p=argparse.ArgumentParser();p.add_argument('--port',type=int,default=int(os.environ.get('PORT','3000')));p.add_argument('--host',default='0.0.0.0');args,_=p.parse_known_args()
os.environ.setdefault('SEPE_INSECURE_LOCAL','1')
from app import app
app.run(host=args.host,port=args.port,debug=False)
