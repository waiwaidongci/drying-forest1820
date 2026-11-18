"""母料关系归并与关系版本发布。

关系是来源（母料切出的试件流）之间的边，只追加、可撤销；每次补认或撤销都在
同一事务内用并查集重算全量连通分量（间接关联自动同组），只发布完整版本，
不存在半成品版本。受影响研究的失效任务与版本同事务落库，保证“关系已落库但
失效处理中断”时可恢复、重试不漏。
"""
from fastapi import HTTPException
from sqlalchemy import select,text
from ..config.database import engine
from ..models.source import Source
from ..models.relation import MaterialRelation
from ..models.relation_version import RelationVersion
from ..models.invalidation_job import InvalidationJob
from ..models.run import Run
from ..utils.serialization import now
from .audit import log

# 关系写入串行化使用的应用级咨询锁键（PostgreSQL advisory lock 32bit 键）。
RELATION_LOCK_KEY=44001

def _lock_relations(db):
    if engine.dialect.name=='postgresql':
        db.execute(text('SELECT pg_advisory_xact_lock(:k)'),{'k':RELATION_LOCK_KEY})

def lock_relation_writes(db):
    """研究创建与关系发布共用同一把事务锁，使两者完全串行，杜绝
    “研究钉住旧版本提交、却未被该版本失效扫描命中”的交错窗口。"""
    _lock_relations(db)

def ordered_pair(left_id,right_id):
    if left_id==right_id:
        raise HTTPException(422,'同一来源无需建立母料关系')
    return (left_id,right_id) if left_id<right_id else (right_id,left_id)

def _union_find(edges,source_ids):
    parent={sid:sid for sid in source_ids}
    def find(x):
        while parent[x]!=x:
            parent[x]=parent[parent[x]];x=parent[x]
        return x
    for a,b in edges:
        ra,rb=find(a),find(b)
        if ra!=rb:parent[rb]=ra
    groups={}
    for sid in source_ids:
        root=find(sid);groups.setdefault(root,[]).append(sid)
    return groups

def _build_version(db):
    sources=list(db.scalars(select(Source).order_by(Source.id)))
    source_ids=[s.id for s in sources]
    active=list(db.scalars(select(MaterialRelation).where(MaterialRelation.state=='active')))
    edges=[(r.left_source_id,r.right_source_id) for r in active]
    raw=_union_find(edges,source_ids)
    # 以分量内最小来源编号作为稳定组号：组号含义跨版本保持可读。
    components=[];source_components={}
    for members in sorted(raw.values(),key=lambda m:min(m)):
        group_id=min(members);members=sorted(members)
        components.append({'group':group_id,'source_ids':members,
                           'merged':len(members)>1})
        for sid in members:source_components[sid]=group_id
    relations=[{'id':r.id,'left_source_id':r.left_source_id,
                'right_source_id':r.right_source_id,'state':r.state,
                'reason':r.reason,'created_by':r.created_by,
                'created_at':r.created_at,'revoked_by':r.revoked_by,
                'revoked_at':r.revoked_at} for r in db.scalars(
                    select(MaterialRelation).order_by(MaterialRelation.id))]
    return components,source_components,relations

def _current_version(db):
    return db.scalar(select(RelationVersion).where(
        RelationVersion.is_active.is_(True)).order_by(
        RelationVersion.version.desc()))

def current_version_number(db):
    v=_current_version(db)
    return v.version if v else 0

def source_group_map(db):
    """返回 {source_id: group_id}；无任何版本时每个来源自成一组。

    JSON 列在不同数据库下键可能被序列化成字符串，读取时统一归一化为整数，
    保证写入算法快照的 group 始终是整数组号。
    """
    v=_current_version(db)
    if v:return {int(k):int(g) for k,g in v.source_components.items()}
    return {sid:sid for sid in db.scalars(select(Source.id))}

def _component_members(version,group_id):
    if not version:return {group_id}
    for c in version.components:
        if c['group']==group_id:return set(c['source_ids'])
    return {group_id}

def _publish_and_enqueue(db,user,action_label,target,detail):
    """重算并发布完整版本，同时为受影响研究落失效任务，全部在同一事务内。"""
    components,source_components,relations=_build_version(db)
    prev=_current_version(db)
    prev_map=dict(prev.source_components) if prev else {}
    version_no=(prev.version+1) if prev else 1
    snapshot=RelationVersion(
        version=version_no,components=components,
        source_components=source_components,relations=relations,
        is_active=True,created_by=user.email,created_at=now())
    db.add(snapshot);db.flush()
    if prev:
        prev.is_active=False
    # 受影响研究：钉在旧版本上、且其任一来源所在组的成员集合发生变化的研究。
    # 无关来源（组成员从未变化）的研究不会被波及，照常有效。
    affected=[]
    for r in db.scalars(select(Run).where(Run.relation_version<version_no)):
        member_sources=set(r.source_ids or [r.source_id])
        changed=False
        for sid in member_sources:
            old_group=prev_map.get(sid,sid)
            old_members=_component_members(prev,old_group)
            new_members=_component_members(snapshot,source_components[sid])
            if old_members!=new_members:changed=True;break
        if changed:
            reason=(f'母料关系版本 v{version_no} 调整了来源组成员，研究钉住的 v{r.relation_version} '
                    '拆分口径可能使近亲样本同时进入训练与留出，结果停止作为有效依据')
            db.add(InvalidationJob(run_id=r.id,relation_version=version_no,
                                   reason=reason,created_at=now()))
            affected.append(r.id)
    log(db,user,action_label,target,detail+f'；失效研究 {len(affected)} 项')
    return version_no,affected

def add_relation(db,user,data):
    a,b=ordered_pair(int(data.left_source_id),int(data.right_source_id))
    for sid in (a,b):
        if not db.get(Source,sid):raise HTTPException(404,f'未找到来源批次 #{sid}')
    _lock_relations(db)
    existing=db.scalar(select(MaterialRelation).where(
        MaterialRelation.left_source_id==a,MaterialRelation.right_source_id==b))
    if existing and existing.state=='active':
        raise HTTPException(409,'该母料关系已在生效中')
    if existing:  # 撤销后重新补认：沿用原行并恢复，保留撤销痕迹于审计
        existing.state='active';existing.reason=data.reason or existing.reason
        existing.created_by=user.email;existing.created_at=now()
        existing.revoked_by='';existing.revoked_at=''
        target=existing.id
    else:
        rel=MaterialRelation(left_source_id=a,right_source_id=b,state='active',
                             reason=data.reason or '',created_by=user.email,
                             created_at=now())
        db.add(rel);db.flush();target=rel.id
    version_no,affected=_publish_and_enqueue(
        db,user,'relation.added',target,
        f'补认来源 #{a} 与 #{b} 同母料')
    db.commit()
    return {'version':version_no,'affected_runs':affected}

def revoke_relation(db,user,relation_id,reason=''):
    _lock_relations(db)
    rel=db.get(MaterialRelation,relation_id)
    if not rel:raise HTTPException(404,'未找到母料关系')
    if rel.state!='active':raise HTTPException(409,'该关系已撤销，原数值仍保留可追溯')
    rel.state='revoked';rel.revoked_by=user.email;rel.revoked_at=now()
    if reason:rel.reason=(rel.reason+' | 撤销说明：'+reason)[:2000]
    version_no,affected=_publish_and_enqueue(
        db,user,'relation.revoked',rel.id,
        f'撤销来源 #{rel.left_source_id} 与 #{rel.right_source_id} 的母料关系')
    db.commit()
    return {'version':version_no,'affected_runs':affected}

def list_relations(db):
    versions=list(db.scalars(select(RelationVersion).order_by(RelationVersion.version.desc())))
    current=versions[0] if versions else None
    pending_jobs=list(db.scalars(select(InvalidationJob).where(
        InvalidationJob.state=='pending').order_by(InvalidationJob.id)))
    return {
        'current_version':current.version if current else 0,
        'components':current.components if current else [],
        'relations':current.relations if current else [],
        'pending_invalidations':len(pending_jobs),
        'pending_run_ids':sorted({j.run_id for j in pending_jobs}),
        'history':[{'version':v.version,'is_active':v.is_active,
                    'created_by':v.created_by,'created_at':v.created_at,
                    'component_count':len(v.components)} for v in versions],
    }
