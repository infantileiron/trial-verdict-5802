import {state} from '../stores/session.js';import {esc} from '../utils/html.js';import {table} from '../components/common/table.js';import {field,select} from '../components/common/fields.js';import {badge} from '../components/common/status.js';import {LEDGER_KINDS,LEDGER_STATUSES,BATCH_STATES} from '../constants/enums.js';import {time,money} from '../utils/format.js';
function batchTag(st){const cls=st==='success'?'good':st==='failed'?'warning':'';return `<span class="tag ${cls}">${esc(BATCH_STATES[st]||st)}</span>`}
function entryTag(st){const cls=st==='posted'?'good':st==='isolated'?'warning':'';return `<span class="tag ${cls}">${esc(LEDGER_STATUSES[st]||st)}</span>`}
export function render(){
 const b=state.selectedBatch,rows=b?.detail||[];
 return `<div class="split"><section>
  <h2>支付退款流水 · 订单去向与净收入</h2>
  <p class="notice">支付与退款按 external_id 幂等入库，重复投递不多计；订单按<b>首次支付</b>归属实验与组别，退款可跨日回冲原订单。先到的退款/支付先<b>暂挂</b>，超额退款<b>隔离</b>并注明差额。批次失败可重跑，已记账流水不重复记账。</p>
  ${state.recon?reconPanel():''}
  <h3>对账批次（${state.batches.length}）</h3>
  ${table(['#','来源','状态','入库','已记账','暂挂','隔离','重复','更新时间'],state.batches.map(x=>[x.id,esc(x.source),batchTag(x.state),x.total,x.posted,x.held,x.isolated,x.duplicates,time(x.updated)]))}
  <p class="eyebrow">点选批次查看每条流水处理结果</p>
  <div class="records">${state.batches.map(x=>`<button data-batch="${x.id}" class="${x.id===b?.id?'active':''}">批次 #${x.id} ${BATCH_STATES[x.state]}</button>`).join('')}</div>
  ${b?`<h3>批次 #${b.id} 流水明细</h3>${table(['流水号','订单','类型','金额','状态','说明'],rows.map(d=>[esc(d.external_id),esc(d.order_id||'—'),LEDGER_KINDS[d.kind]||d.result||'',d.amount?money(d.amount):'—',d.status?entryTag(d.status):esc(d.result||''),esc(d.note||'')]))}
  ${b.state==='failed'?`<button data-rerun="${b.id}" class="primary">重跑失败批次（不重复记账）</button>`:''}`:''}
  <h3>账本流水（最近100条）</h3>
  ${table(['订单','用户','实验','组','类型','金额','状态','上海时间','说明'],state.ledger.slice(0,100).map(e=>[e.order_id,e.user_key,state.experiments.find(x=>x.id===e.experiment_id)?.code||'—',e.group||'—',LEDGER_KINDS[e.kind],money(e.amount),entryTag(e.status),time(e.occurred_at),esc(e.note||'')]))}
 </section>
 <aside><h2>接入支付/退款流水</h2>
  <form id="recon-filter">${select('实验（账本核对）','experiment_id',[['','全部实验']].concat(state.experiments.map(e=>[e.id,e.code])))}${select('流水状态','status_filter',[['','全部状态'],['held','暂挂'],['posted','已记账'],['isolated','隔离']])}<button>筛选账本</button></form>
  <form id="batch"><label>批次来源<input name="source" value="manual-支付网关导出" required></label>
   <label>流水 JSON（payment/refund）<textarea name="payload" rows="14" required placeholder='[{"external_id":"P-001","kind":"payment","order_id":"ORD-0001","user_key":"LJ-U0001","amount":100,"occurred_at":"2026-11-13T14:00:00+08:00"}]'></textarea></label>
   <button class="primary">提交对账批次</button></form>
  <p class="meta">字段：external_id、kind(payment/refund)、order_id、user_key、amount、occurred_at（带时区）。</p>
 </aside></div>`}
function reconPanel(){
 const r=state.recon,bal=r.balance,g=bal.groups;
 return `<article class="experiment"><div class="eyebrow">${esc(r.experiment.code)} · 账本版本 ${esc(r.ledger_version)}</div>
  <h3>${bal.balanced?'账本已对平，可提交净收入裁决':'账本未对平，未对平订单阻止发布'}</h3>
  ${table(['组别','总收入','已退款','净收入','订单数','付费人数'],[['A',money(g.A.gross),money(g.A.refunded),money(g.A.net),g.A.order_count,g.A.payer_count],['B',money(g.B.gross),money(g.B.refunded),money(g.B.net),g.B.order_count,g.B.payer_count]])}
  <p class="notice ${bal.balanced?'good':'warning'}">${bal.balanced?'全部流水已记账，裁决只取该完整账本版本。':esc(bal.block_reasons.join('；'))}</p>
  ${bal.isolated.length?`<h3>隔离的超额退款（不冲减净收入）</h3>${table(['#','订单','金额','说明'],bal.isolated.map(x=>[x.id,x.order_id,money(x.amount),esc(x.note)]))}`:''}
  ${bal.held.length?`<h3>暂挂流水</h3>${table(['#','订单','类型','金额','说明'],bal.held.map(x=>[x.id,x.order_id,x.kind,money(x.amount),esc(x.note)]))}`:''}
  ${r.pending_for_users.length?`<p class="meta">另有 ${r.pending_for_users.length} 条本实验用户相关的暂挂流水尚未归属，见下方账本（状态=暂挂）。</p>`:''}
 </article>`}
