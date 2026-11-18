from sqlalchemy import Column,Integer,String,Text
from ..config.database import Base
class InvalidationJob(Base):
    """失效处理 outbox：与关系版本同事务落库；worker 幂等消费，中断后重试不漏。"""
    __tablename__='invalidation_jobs'
    id=Column(Integer,primary_key=True)
    run_id=Column(Integer,nullable=False)
    relation_version=Column(Integer,nullable=False)
    reason=Column(Text,nullable=False)
    state=Column(String(20),default='pending',nullable=False)
    attempts=Column(Integer,default=0,nullable=False)
    last_error=Column(Text,default='')
    created_at=Column(String(40),nullable=False)
    processed_at=Column(String(40),default='')
