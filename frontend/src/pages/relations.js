import {domain} from '../constants/domain.js';
import {research} from '../stores/research.js';
import {session} from '../stores/session.js';
import {relationsApi} from '../api/research.js';
import {relationStates} from '../constants/enums.js';
import {esc,localTime} from '../utils/format.js';
import {action,toast} from '../hooks/actions.js';

const sourceName=id=>{const s=research.sources.find(x=>x.id===id);return s?s.name:('#'+id)};

export function relationsPage(){
  const rel=research.relations;
  const components=rel.components||[];
  const relations=rel.relations||[];
  const history=rel.history||[];
  return '<section class="page-heading"><p class="eyebrow">02 / MATERIAL LINEAGE</p><h1>母料关系归并，堵住近亲样本泄漏。</h1><p>同一母料切出的试件即使散在多个来源，也按连通分量归为一组（间接关联自动同组）。每次补认或撤销都发布一个完整关系版本；研究创建时钉住当时版本，留出与训练内特征选择一律按组隔离。</p></section>'
    +(rel.pending_invalidations>0?'<div class="pending banner"><span class="spinner"></span><span><b>失效处理中：</b>'+rel.pending_invalidations+' 项受影响研究正在由 worker 处理，页面稍后自动刷新。关系版本已落库，处理中断也会自动补齐、不漏。</span></div>':'')
    +'<div class="split"><section><h2>当前母料分组 <small>关系版本 v'+rel.current_version+' · '+components.length+' 个连通分量</small></h2>'
    +(components.length?components.map(c=>'<article class="group-card '+(c.merged?'merged':'solo')+'"><header><small>母料组 #'+c.group+(c.merged?' · 已归并 '+c.source_ids.length+' 个来源':' · 独立来源')+'</small></header><ul>'+c.source_ids.map(id=>'<li><strong>'+esc(sourceName(id))+'</strong><small>来源 #'+id+'</small></li>').join('')+'</ul></article>').join(''):'<p class="empty">尚未发布任何关系版本，当前每个来源各自独立成组。</p>')
    +'<h2>关系台账 <small>补认与撤销全程留痕，撤销保留原数值可追溯</small></h2>'
    +(relations.length?'<div class="relation-list">'+relations.map(r=>'<div class="relation-row '+r.state+'"><div><strong>'+esc(sourceName(r.left_source_id))+'</strong> ↔ <strong>'+esc(sourceName(r.right_source_id))+'</strong><p class="fine">'+esc(r.reason||'（无说明）')+'</p><small>'+esc(relationStates[r.state]||r.state)+' · '+esc(r.created_by)+' · '+localTime(r.created_at)+(r.state==='revoked'?' · 撤销：'+esc(r.revoked_by):'')+'</small></div>'+(r.state==='active'&&session.writable?'<button class="secondary" data-revoke="'+r.id+'">撤销关系</button>':'')+'</div>').join('')+'</div>':'<p class="empty">还没有母料关系记录。</p>')
    +'</section><aside class="entry-sheet">'
    +(session.writable?'<h2>补认母料关系</h2><form id="relation-form"><label>来源 A<select name="left_source_id">'+research.sources.map(s=>'<option value="'+s.id+'">'+esc(s.name)+'</option>').join('')+'</select></label><label>来源 B<select name="right_source_id">'+research.sources.map(s=>'<option value="'+s.id+'">'+esc(s.name)+'</option>').join('')+'</select></label><label>认定说明<textarea name="reason" rows="3" placeholder="例如：两份试件流确认切自同一母料 MB-2026-11A"></textarea></label><button type="submit">发布归并版本 →</button></form><details id="revoke-box" hidden><summary>撤销确认</summary><form id="revoke-form"><input type="hidden" name="relation_id"><label>撤销说明<textarea name="reason" rows="3" required placeholder="撤销后原关系数值仍保留，受影响研究将再次评估"></textarea></label><button type="submit">确认撤销并发布新版本</button></form></details>':'<h2>阅读权限</h2><p>可查看全部母料分组、关系台账与版本历史。关系补认或撤销由分析师或负责人执行。</p>')
    +'<h2>关系版本历史</h2><div class="version-list">'+(history.length?history.map(v=>'<div class="version-row '+(v.is_active?'active':'superseded')+'"><strong>v'+v.version+'</strong><small>'+(v.is_active?'当前生效':'已被取代')+' · '+v.component_count+' 组</small><small>'+esc(v.created_by)+'<br>'+localTime(v.created_at)+'</small></div>').join(''):'<p class="fine">暂无版本。</p>')+'</div>'
    +'<div class="method-note"><b>失效口径</b><p>关系变化只影响钉在旧版本上、且来源组成员发生变化的研究；无关研究照常有效。失效研究的数值与 CSV 保留作追溯，但停止作为有效依据，其工艺备忘同步失效。</p></div>'
    +'</aside></div>';
}
export function bindRelations(refresh){
  action('#relation-form',async form=>{
    const data=Object.fromEntries(new FormData(form));
    if(Number(data.left_source_id)===Number(data.right_source_id)){toast('请选择两个不同的来源',true);return}
    const r=await relationsApi.add({left_source_id:Number(data.left_source_id),right_source_id:Number(data.right_source_id),reason:data.reason});
    toast('已发布关系版本 v'+r.version+'，受影响研究 '+r.affected_runs.length+' 项');
    await refresh();
  });
  for(const b of document.querySelectorAll('[data-revoke]'))b.onclick=()=>{
    const box=document.getElementById('revoke-box');
    box.hidden=false;box.open=true;box.querySelector('[name=relation_id]').value=b.dataset.revoke;
    box.scrollIntoView({block:'nearest'});
  };
  action('#revoke-form',async form=>{
    const data=Object.fromEntries(new FormData(form));
    const r=await relationsApi.revoke(Number(data.relation_id),data.reason);
    toast('已撤销并发布版本 v'+r.version);
    await refresh();
  });
}
