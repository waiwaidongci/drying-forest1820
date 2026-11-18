from sqlalchemy import Column,Integer,String,Text,ForeignKey,UniqueConstraint,Index
from ..config.database import Base
class MaterialRelation(Base):
    """两个来源（母料切分后的试件流）之间的同源关系，只追加；撤销保留原行留痕。"""
    __tablename__='material_relations'
    __table_args__=(UniqueConstraint('left_source_id','right_source_id',name='uq_relation_pair'),
                    Index('ix_relation_state','state'))
    id=Column(Integer,primary_key=True)
    left_source_id=Column(Integer,ForeignKey('drying_studies.id'),nullable=False)
    right_source_id=Column(Integer,ForeignKey('drying_studies.id'),nullable=False)
    state=Column(String(20),default='active',nullable=False)
    reason=Column(Text,default='')
    created_by=Column(String(120),nullable=False)
    revoked_by=Column(String(120),default='')
    created_at=Column(String(40),nullable=False)
    revoked_at=Column(String(40),default='')
