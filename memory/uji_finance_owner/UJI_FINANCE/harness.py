import os, sys, asyncio
os.environ.setdefault('MONGO_URL','mongodb://x'); os.environ.setdefault('DB_NAME','t'); os.environ.setdefault('JWT_SECRET','x'*32)
REPO = os.environ.get('DAHOST_REPO', os.path.expanduser('~/DAHOST'))
sys.path.insert(0, os.path.join(REPO, 'backend')); sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mmpatch; mmpatch.install()
import importlib.abc, importlib.machinery, types
class _Stub(types.ModuleType):
    def __getattr__(self, name):
        if name.startswith('__'): raise AttributeError(name)
        return type(name, (), {'__init__': lambda self,*a,**k: None, '__call__': lambda self,*a,**k: None})
class _Finder(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    PFX = ('emergentintegrations',)
    def find_spec(self, name, path, target=None):
        if name.split('.')[0] in self.PFX:
            return importlib.machinery.ModuleSpec(name, self, is_package=True)
    def create_module(self, spec): 
        m=_Stub(spec.name); m.__path__=[]; return m
    def exec_module(self, m): pass
sys.meta_path.insert(0, _Finder())

from mongomock_motor import AsyncMongoMockClient
import database
CLI = AsyncMongoMockClient(); DB = CLI['t']
database.get_db = lambda: DB
for attr in ('db','client'):
    if hasattr(database, attr):
        try: setattr(database, attr, DB if attr=='db' else CLI)
        except Exception: pass
import server
from fastapi.testclient import TestClient
from auth import create_token
app = server.app
client = TestClient(app, raise_server_exceptions=False)
def tok(role, uid=None, name=None):
    u = {'id': uid or f'u-{role}', 'email': f'{role}@da.test', 'name': name or role, 'role': role}
    return {'Authorization': 'Bearer ' + create_token(u)}
def run(coro): return asyncio.get_event_loop().run_until_complete(coro)
