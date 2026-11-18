from sqlalchemy import select
from fastapi import HTTPException
from redis import Redis
from ..config.settings import REDIS_URL
from ..models.run import Run
from ..models.source import Source
from ..models.record import Record
from ..utils.serialization import row,now
from .sources import source_or_404,list_records
from .relations import source_group_map,current_version_number,lock_relation_writes
from .domain_validation import validate_parameters
from .audit import log
queue=Redis.from_url(REDIS_URL)
def get_run(db,id):
    r=db.get(Run,id)
    if not r:raise HTTPException(404,'未找到分析任务')
    return r
def _collect_records(db,source_ids,group_map):
    all_records=[]
    for sid in source_ids:
        source_or_404(db,sid)
        records=list_records(db,sid)
        group_id=group_map.get(sid,sid)
        for r in records:
            r['group']=group_id
            all_records.append(r)
    return all_records
def create_run(db,user,data):
    source_ids=sorted(set(data.source_ids or [data.source_id]))
    if not source_ids:raise HTTPException(422,'请至少选择一个分析来源')
    sources=list(db.scalars(select(Source).where(Source.id.in_(source_ids))))
    if len(sources)!=len(source_ids):raise HTTPException(404,'部分来源批次不存在')
    # 与关系归并串行：提交前持锁，确保交错的关系版本要么在此研究之前
    # （已读到并钉住新版本），要么在其后（该版本失效扫描会命中本研究）。
    lock_relation_writes(db)
    version_no=current_version_number(db)
    group_map=source_group_map(db)
    records=_collect_records(db,source_ids,group_map)
    if len(records)<3:raise HTTPException(422,'至少录入3条样本后才能执行')
    try: params=validate_parameters(data.parameters)
    except ValueError as e:raise HTTPException(422,str(e))
    group_ids=sorted(set(r['group'] for r in records))
    snapshot={'sources':[row(s) for s in sources],
              'source':row(sources[0]),
              'records':records,
              'relation_version':version_no,
              'group_ids':group_ids}
    r=Run(source_id=source_ids[0],source_ids=source_ids,relation_version=version_no,
          name=data.name,parameters=params,snapshot=snapshot,
          created_at=now(),state='queued')
    db.add(r);db.flush();log(db,user,'run.queued',r.id,
        data.name+f'；关系版本 v{version_no}，来源 {source_ids}，母料组 {group_ids}')
    db.commit()
    try:queue.rpush('analysis:queue',r.id)
    except Exception:
        r.state='failed';r.error='队列暂不可用，请重新创建任务';db.commit();raise HTTPException(503,r.error)
    return row(r)
def list_runs(db):
    out=[]
    for r in db.scalars(select(Run).order_by(Run.id.desc())):
        d={k:v for k,v in row(r).items() if k not in ('snapshot','result')}
        d['source_count']=len(r.source_ids or [r.source_id])
        out.append(d)
    return out
