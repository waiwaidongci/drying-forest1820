"""失效处理 outbox 的消费端。

每个失效任务独立事务、逐条提交：处理中断后重试不重复、不漏。
- 研究结果（含其数值与 CSV 产物）原样保留作追溯，仅置有效性标志与原因；
- 已完成的旧计算即使迟归，也不会恢复有效性（worker 写结果前先查 is_valid）；
- 关联的工艺试验备忘同步失效，泄漏研究停止作为有效依据。
"""
import logging
from sqlalchemy import select
from ..config.database import Session
from ..models.invalidation_job import InvalidationJob
from ..models.run import Run
from ..models.note import Note
from ..utils.serialization import now
from .audit import log

def process_job(db,job):
    job.attempts+=1
    try:
        r=db.get(Run,job.run_id)
        if r:
            # 幂等：只写一次原因；后续版本若再次命中会追加新版本号。
            r.is_valid=False
            r.invalid_reason=job.reason
            r.invalidated_version=job.relation_version
            for n in db.scalars(select(Note).where(Note.run_id==r.id,Note.is_valid.is_(True))):
                n.is_valid=False
                n.invalid_reason='关联研究已因母料关系变化失效：'+job.reason
        job.state='done';job.processed_at=now();job.last_error=''
        log(db,'worker','run.invalidated',job.run_id,
            f'关系版本 v{job.relation_version} 失效处理完成')
        db.commit()
        return True
    except Exception as e:
        db.rollback()
        job.last_error=str(e)[:2000]
        try:
            db.add(job);db.commit()
        except Exception:
            logging.exception('invalidation job failure could not be recorded')
        return False

def process_pending(limit=100):
    """取出待处理任务逐条独立事务提交；返回 (成功数, 剩余待处理数)。"""
    processed=0
    with Session() as db:
        jobs=list(db.scalars(select(InvalidationJob).where(
            InvalidationJob.state=='pending').order_by(
            InvalidationJob.id).limit(limit)))
    for job in jobs:
        with Session() as db:
            fresh=db.get(InvalidationJob,job.id)
            if not fresh or fresh.state!='pending':continue
            if process_job(db,fresh):processed+=1
    with Session() as db:
        remaining=db.scalar(select(InvalidationJob.id).where(
            InvalidationJob.state=='pending').limit(1)) is not None
    return processed,remaining
