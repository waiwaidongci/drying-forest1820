import os,logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from sqlalchemy import text
from .config.database import Base,engine
from .config.settings import CONFIG
from .models import user,source,record,run,note,audit,relation,relation_version,invalidation_job
from .middlewares.errors import error_boundary
from .middlewares.rate_limit import rate_limit
from .routes import auth,sources,runs,notes,audit as audit_routes,relations
from .services.runs import queue
@asynccontextmanager
async def lifespan(app):
    Base.metadata.create_all(engine)
    # 关系落库后即使后端重启，未处理的失效任务仍由 worker 扫描补齐；这里也兜底一次。
    try:
        from .services.invalidation import process_pending
        process_pending()
    except Exception:logging.exception('startup invalidation sweep failed')
    if os.getenv('SEED_DEMO','true')=='true':
        try:
            from scripts.seed_demo import seed
            seed()
        except Exception:logging.exception('seed failed; service remains available')
    yield
app=FastAPI(title=CONFIG['title'],lifespan=lifespan)
app.middleware('http')(error_boundary)
app.middleware('http')(rate_limit)
for router in (auth.router,sources.router,runs.router,notes.router,audit_routes.router,relations.router):app.include_router(router)
@app.get('/health')
def health():
    with engine.connect() as c:c.execute(text('SELECT 1'))
    queue.ping();return {'status':'ok'}
@app.get('/catalog')
def catalog():return CONFIG
