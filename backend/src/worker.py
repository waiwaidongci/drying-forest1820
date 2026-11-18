import json,time,logging
from redis import Redis
from sqlalchemy import select
from .config.database import Session
from .config.settings import REDIS_URL,ARTIFACT_DIR
from .models.run import Run
from .models import source,record,user,note,audit,relation,relation_version,invalidation_job
from .services.algorithm import calculate
from .services.audit import log
from .services.invalidation import process_pending
from .services.export import csv_response
queue=Redis.from_url(REDIS_URL)
ARTIFACT_DIR.mkdir(parents=True,exist_ok=True)
SWEEP_INTERVAL=15
def execute(id):
    with Session() as db:
        r=db.get(Run,id)
        if not r or r.state!='queued':return
        # 关系版本可能在排队期间已将其失效：数值仍算并保留，但不恢复有效性。
        already_invalid=not r.is_valid
        r.state='running';db.commit()
        try:
            result=calculate(r.snapshot['records'],r.parameters)
            json.dumps(result,allow_nan=False)
            r.result=result;r.state='completed'
            response=csv_response(result,'run.csv')
            (ARTIFACT_DIR/f'run-{r.id}.csv').write_bytes(response.body)
            log(db,'worker','run.completed',r.id,
                '已失效研究的迟归计算，有效性不恢复' if already_invalid else '')
        except Exception as e:
            logging.exception('analysis failed');r.state='failed';r.error=str(e)[:2000]
            log(db,'worker','run.failed',r.id,r.error)
        # 迟归保护：落库前重读失效标志，计算期间到达的失效同样不被覆盖。
        db.flush();fresh=db.get(Run,id)
        if not fresh.is_valid:
            r.is_valid=False
            r.invalid_reason=fresh.invalid_reason
            r.invalidated_version=fresh.invalidated_version
        db.commit()
def main():
    last_sweep=0.0
    while True:
        (ARTIFACT_DIR/'heartbeat').write_text(str(time.time()))
        value=queue.blpop('analysis:queue',timeout=2)
        if value:execute(int(value[1]))
        # 定期兜底扫描 outbox：覆盖落库后本 worker 未收到通知或处理中断的任务。
        if time.time()-last_sweep>SWEEP_INTERVAL:
            last_sweep=time.time()
            try:process_pending()
            except Exception:logging.exception('invalidation sweep failed')
if __name__=='__main__':main()
