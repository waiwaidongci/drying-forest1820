import {validityStates} from '../../constants/enums.js';
import {esc} from '../../utils/format.js';
// 研究/备忘的有效性呈现：处理中、已生效、已失效（失效原因在调用处展示）。
export function validityBadge(item,pending=false){
  if(item.is_valid===false)return '<span class="status invalid" title="'+esc(item.invalid_reason||'')+'">'+validityStates.invalid+'</span>';
  if(pending)return '<span class="status pending">'+validityStates.pending+'</span>';
  return '<span class="status valid">'+validityStates.valid+'</span>';
}
export function invalidReason(item){
  return item.is_valid===false&&item.invalid_reason?'<p class="invalid-reason"><b>失效原因：</b>'+esc(item.invalid_reason)+'</p>':'';
}
