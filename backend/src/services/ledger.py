"""支付/退款流水与对账。

口径：
- 支付与退款统一 append-only 流水，external_id 自然键，重复投递幂等丢弃，不多计。
- 订单归属按「首次支付」解析：首次支付发生时，取该用户当时已曝光的实验与组别；
  曝光尚未来到时支付暂挂(held)，后续批次再解析；同订单后续支付不改变归属。
- 退款可跨日到达，回冲原订单：匹配原订单支付，累计退款不超过已支付金额则 posted 冲减；
  超额部分隔离(isolated)，不参与净收入，并在 note 记录差额；找不到原订单的先到退款暂挂。
- 批次失败可重跑：已记账流水不重复记账，暂挂与隔离会被重新尝试。
"""
from datetime import datetime,timezone
from src.models.entities import Event,LedgerEntry,ReconBatch,Audit
def _now():return datetime.now(timezone.utc).isoformat()
def _stamp(t):return t.astimezone(timezone.utc).isoformat()
def resolve_payment(s,e):
 """解析支付归属：同订单已有支付则沿用首次支付归属，否则按用户当前曝光解析；解析不了暂挂。"""
 first=s.query(LedgerEntry).filter(LedgerEntry.order_id==e.order_id,LedgerEntry.kind=='payment',LedgerEntry.status.in_(['posted','held'])).order_by(LedgerEntry.occurred_at,LedgerEntry.id).first()
 if first and first.experiment_id:
  e.experiment_id=first.experiment_id;e.group=first.group;e.status='posted';e.note='沿用订单首次支付归属'
  return
 exposure=(s.query(Event).filter(Event.user_key==e.user_key,Event.kind=='exposure')
           .order_by(Event.occurred_at).all())
 if not exposure:
  e.status='held';e.note='支付先于曝光到达，暂挂待归属'
  return
 # 同一用户禁止跨组（采集侧已保证），取最早曝光的实验/组别
 anchor=exposure[0]
 if any(x.group!=anchor.group for x in exposure):
  e.status='held';e.note='用户存在跨组曝光，归属冲突，暂挂待排查'
  return
 e.experiment_id=anchor.experiment_id;e.group=anchor.group;e.status='posted';e.note='按首次支付时曝光归属'
def apply_refund(s,e):
 """退款回冲原订单；先到退款暂挂，超额退款隔离并说明差额。"""
 payments=s.query(LedgerEntry).filter(LedgerEntry.order_id==e.order_id,LedgerEntry.kind=='payment',LedgerEntry.status=='posted').order_by(LedgerEntry.occurred_at,LedgerEntry.id).all()
 if not payments:
  e.status='held';e.note='退款先于原订单支付到达，暂挂待匹配'
  return
 prior=sum(x.amount for x in s.query(LedgerEntry).filter(LedgerEntry.order_id==e.order_id,LedgerEntry.kind=='refund',LedgerEntry.status=='posted').all())
 paid=sum(x.amount for x in payments)
 base=payments[0]
 e.experiment_id=base.experiment_id;e.group=base.group;e.payment_entry_id=base.id
 if prior+e.amount>paid+1e-9:
  e.status='isolated';e.refunded_amount=0.0
  e.note=f'超额退款隔离：订单已付{paid:.2f}，已退{prior:.2f}，本笔{e.amount:.2f}，差额{prior+e.amount-paid:.2f} 不冲减净收入'
  return
 e.status='posted';e.refunded_amount=e.amount;e.note=f'回冲原订单支付 #{base.id}'
def process_entry(s,e):
 if e.kind=='payment':resolve_payment(s,e)
 else:apply_refund(s,e)
def resolve_pending_for_order(s,order_id):
 """原订单支付到达后，自动消化该订单此前暂挂的先到退款（不重记已入账流水）。"""
 changed=[]
 for held in s.query(LedgerEntry).filter(LedgerEntry.order_id==order_id,LedgerEntry.status=='held',LedgerEntry.kind=='refund').all():
  apply_refund(s,held);changed.append(held)
 return changed
def ingest(s,items,source,user):
 batch=ReconBatch(source=source,state='pending',total=len(items),detail=[],dup_detail=[],created=_now(),updated=_now())
 s.add(batch);s.flush()
 dup_detail=[];touched_batch_ids=set()
 for raw in items:
  if s.query(LedgerEntry).filter_by(external_id=raw.external_id).first():
   batch.duplicates=(batch.duplicates or 0)+1
   dup_detail.append({'external_id':raw.external_id,'result':'duplicate','note':'重复投递已忽略，不多计'})
   continue
  e=LedgerEntry(batch_id=batch.id,external_id=raw.external_id,kind=raw.kind,order_id=raw.order_id,
                user_key=raw.user_key,amount=raw.amount,occurred_at=_stamp(raw.occurred_at),received_at=_now())
  s.add(e);s.flush()
  try:
   process_entry(s,e)
   # 支付成功记账后，尝试匹配该订单先到的暂挂退款
   if e.kind=='payment' and e.status=='posted':
    for moved in resolve_pending_for_order(s,e.order_id):touched_batch_ids.add(moved.batch_id)
  except Exception as ex:
   e.status='held';e.note='处理异常暂挂：'+str(ex)[:200]
  s.flush()
 batch.dup_detail=dup_detail
 refresh_batch(s,batch)
 for bid in touched_batch_ids:
  other=s.get(ReconBatch,bid)
  if other and bid!=batch.id:refresh_batch(s,other)
 s.add(Audit(actor=user.email,action=f'对账批次 {batch.id} 入库 {batch.total} 条：{batch.state}',created=_now()))
 return batch
def refresh_batch(s,batch):
 """以流水行的真实状态重算批次计数与明细，避免自动消化/重跑导致计数漂移。"""
 rows=s.query(LedgerEntry).filter_by(batch_id=batch.id).order_by(LedgerEntry.id).all()
 batch.posted=sum(1 for e in rows if e.status=='posted')
 batch.held=sum(1 for e in rows if e.status=='held')
 batch.isolated=sum(1 for e in rows if e.status=='isolated')
 batch.duplicates=batch.duplicates or 0
 batch.total=len(rows)+batch.duplicates
 detail=[{'external_id':e.external_id,'order_id':e.order_id,'kind':e.kind,'amount':e.amount,'status':e.status,'note':e.note} for e in rows]
 detail.extend(batch.dup_detail or [])
 batch.detail=detail
 batch.state='success' if batch.held==0 and batch.isolated==0 else 'failed'
 batch.updated=_now()
 return batch
def rerun(s,batch,user):
 """重跑失败批次：只重新处理 held/isolated 条目，posted 不动，保证不重复记账。"""
 if batch.state=='success':return batch
 retry=s.query(LedgerEntry).filter(LedgerEntry.batch_id==batch.id,LedgerEntry.status.in_(['held','isolated'])).all()
 for e in retry:
  e.note=(e.note+'；' if e.note else '')+f'{_now()} 批次重跑'
  process_entry(s,e)
 refresh_batch(s,batch)
 s.add(Audit(actor=user.email,action=f'对账批次 {batch.id} 重跑：{batch.state}',created=_now()))
 return batch
def refresh_batches_for(s,entry_ids):
 """事件采集等路径自动消化暂挂后，同步受影响批次的计数。"""
 if not entry_ids:return
 bid_rows=s.query(LedgerEntry.batch_id).filter(LedgerEntry.id.in_(entry_ids)).distinct().all()
 for (bid,) in bid_rows:
  b=s.get(ReconBatch,bid)
  if b:refresh_batch(s,b)
def ledger_snapshot(s,exp):
 rows=s.query(LedgerEntry).filter(LedgerEntry.experiment_id==exp.id).order_by(LedgerEntry.id).all()
 return [{'id':e.id,'external_id':e.external_id,'kind':e.kind,'order_id':e.order_id,'user_key':e.user_key,
          'group':e.group,'amount':e.amount,'occurred_at':e.occurred_at,'status':e.status,'note':e.note,
          'payment_entry_id':e.payment_entry_id,'refunded_amount':e.refunded_amount} for e in rows]
def pending_outside(s,exp):
 """属于本实验用户、但尚未归属的暂挂流水（先到支付/退款），用于页面核对订单去向。"""
 keys=[r[0] for r in s.query(Event.user_key).filter_by(experiment_id=exp.id).distinct().all()]
 if not keys:return []
 return [e for e in s.query(LedgerEntry).filter(LedgerEntry.status=='held',LedgerEntry.user_key.in_(keys)).order_by(LedgerEntry.id).all()]
def balance(s,exp,entries=None):
 """账本对平：净收入只统计 posted；held/isolated 未对平，未对平订单阻止发布。

 归属本实验的 held 条目 experiment_id 可能尚未解析（NULL），
 因此把本实验用户名下仍暂挂的流水一并计入未对平，避免漏检先到支付/退款。
 """
 if entries is None:entries=s.query(LedgerEntry).filter_by(experiment_id=exp.id).all()
 held=[e for e in entries if e.status=='held'];isolated=[e for e in entries if e.status=='isolated']
 held.extend(pending_outside(s,exp))
 posted=[e for e in entries if e.status=='posted']
 totals={'A':{'gross':0.0,'refunded':0.0,'net':0.0,'orders':set(),'payers':set()},
         'B':{'gross':0.0,'refunded':0.0,'net':0.0,'orders':set(),'payers':set()}}
 for e in posted:
  t=totals[e.group]
  if e.kind=='payment':t['gross']+=e.amount;t['orders'].add(e.order_id);t['payers'].add(e.user_key)
  else:t['refunded']+=e.amount
 for g in totals:
  t=totals[g];t['net']=round(t['gross']-t['refunded'],2)
  t['order_count']=len(t['orders']);t['payer_count']=len(t['payers']);t.pop('orders');t.pop('payers')
 reasons=[]
 if held:reasons.append(f'{len(held)} 条流水暂挂未对平（先到支付/退款待匹配）')
 if isolated:reasons.append(f'{len(isolated)} 条超额退款被隔离，需人工核对差额')
 return {'balanced':not reasons,'block_reasons':reasons,'held_count':len(held),'isolated_count':len(isolated),
         'posted_count':len(posted),'groups':totals,
         'held':[{'id':e.id,'order_id':e.order_id,'kind':e.kind,'amount':e.amount,'note':e.note} for e in held],
         'isolated':[{'id':e.id,'order_id':e.order_id,'kind':e.kind,'amount':e.amount,'note':e.note} for e in isolated]}
def ledger_version(s):
 """账本版本：以全部流水主键与状态的哈希表示，裁决只取完整账本版本。"""
 import hashlib
 rows=s.query(LedgerEntry.id,LedgerEntry.status,LedgerEntry.experiment_id).order_by(LedgerEntry.id).all()
 raw='|'.join(f'{i}:{st}:{exp}' for i,st,exp in rows)
 return hashlib.sha256(raw.encode()).hexdigest()[:16]
