from sqlalchemy import Column,Integer,String,JSON,Boolean,Text
from ..config.database import Base
class RelationVersion(Base):
    """一次完整关系版本：发布时全量重算连通分量，只发布完整版本，不发布中间态。"""
    __tablename__='relation_versions'
    id=Column(Integer,primary_key=True)
    version=Column(Integer,unique=True,nullable=False)
    components=Column(JSON,nullable=False)
    source_components=Column(JSON,nullable=False)
    relations=Column(JSON,nullable=False)
    is_active=Column(Boolean,default=True,nullable=False)
    created_by=Column(String(120),nullable=False)
    created_at=Column(String(40),nullable=False)
