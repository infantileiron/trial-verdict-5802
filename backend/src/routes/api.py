import os,json
from datetime import timezone
import redis
from fastapi import APIRouter,Depends,HTTPException,Response
from sqlalchemy.exc import IntegrityError
from src.config.database import db
from src.models.entities import User,Experiment,Event,Decision,Audit,LedgerEntry,ReconBatch
from src.schemas.business import Login,ExperimentInput,EventInput,BatchInput,RunInput,RationaleInput,PublishInput
from src.middlewares.auth import current,editor,admin
from src.utils.security import verify,token
from src.services.business import audit,dump,utc
from src.services import ledger
from src.controllers.business import experiment,decision,validate_event,snapshot,publish,require_balanced
router=APIRouter()
@router.post('/auth/login')
def login(data:Login,s=Depends(db)):
 u=s.query(User).filter_by(email=data.email).first()
 if not u or not verify(data.password,u.password):raise HTTPException(401,'账号或密码错误')
 return {'token':token(u),'user':dump(u)}
@router.get('/me')
def me(u=Depends(current)):return dump(u)
@router.get('/experiments')
def experiments(u=Depends(current),s=Depends(db)):
 out=[]
 for e in s.query(Experiment).order_by(Experiment.id.desc()):
  bal=ledger.balance(s,e)
  out.append({**dump(e),'exposures':s.query(Event).filter_by(experiment_id=e.id,kind='exposure').count(),
              'ledger_balanced':bal['balanced'],'held_count':bal['held_count'],'isolated_count':bal['isolated_count'],
              'net_a':bal['groups']['A']['net'],'net_b':bal['groups']['B']['net']})
 return out
@router.post('/experiments')
def create_experiment(data:ExperimentInput,u=Depends(editor),s=Depends(db)):
 d=data.model_dump();d['starts_at']=utc(data.starts_at);d['ends_at']=utc(data.ends_at);r=Experiment(**d);s.add(r)
 try:s.commit()
 except IntegrityError:s.rollback();raise HTTPException(409,'实验编号已存在')
 audit(s,u,'建立实验 '+r.code);return dump(r)
@router.put('/experiments/{i}')
def edit_experiment(i:int,data:ExperimentInput,u=Depends(editor),s=Depends(db)):
 r=experiment(s,i)
 if s.query(Event).filter_by(experiment_id=i).first():raise HTTPException(409,'已有事件，禁止事后修改实验定义；请建立新实验')
 d=data.model_dump();d['starts_at']=utc(data.starts_at);d['ends_at']=utc(data.ends_at)
 for k,v in d.items():setattr(r,k,v)
 try:s.commit()
 except IntegrityError:s.rollback();raise HTTPException(409,'实验编号已存在')
 audit(s,u,'修订实验 '+str(i));return dump(r)
@router.get('/events')
def events(experiment_id:int|None=None,u=Depends(current),s=Depends(db)):
 q=s.query(Event)
 if experiment_id:q=q.filter_by(experiment_id=experiment_id)
 return [dump(e) for e in q.order_by(Event.id.desc())]
@router.post('/events')
def create_event(data:EventInput,u=Depends(editor),s=Depends(db)):
 stamp=validate_event(s,data);d=data.model_dump();d['occurred_at']=stamp;r=Event(**d);s.add(r)
 try:s.commit()
 except IntegrityError:s.rollback();raise HTTPException(409,'该用户事件已存在')
 # 采集期间对账仍可用：新曝光到达后，自动尝试消化该用户的暂挂支付，不重记已入账流水
 held_ids=[h.id for h in s.query(LedgerEntry).filter_by(user_key=data.user_key,status='held').all()]
 for held in s.query(LedgerEntry).filter(LedgerEntry.id.in_(held_ids)).all():
  ledger.process_entry(s,held)
 ledger.refresh_batches_for(s,held_ids)
 s.commit()
 audit(s,u,'采集事件 '+str(r.id));return dump(r)
# ---------- 支付/退款流水与对账批次 ----------
@router.post('/recon/batches')
def create_batch(data:BatchInput,u=Depends(editor),s=Depends(db)):
 b=ledger.ingest(s,data.entries,data.source,u);s.commit()
 return dump(b)
@router.get('/recon/batches')
def list_batches(state:str|None=None,u=Depends(current),s=Depends(db)):
 q=s.query(ReconBatch)
 if state:
  if state not in ('pending','success','failed'):raise HTTPException(422,'批次状态仅支持 pending/success/failed')
  q=q.filter_by(state=state)
 return [dump(b) for b in q.order_by(ReconBatch.id.desc()).all()]
@router.get('/recon/batches/{i}')
def batch_detail(i:int,u=Depends(current),s=Depends(db)):
 b=s.get(ReconBatch,i)
 if not b:raise HTTPException(404,'对账批次不存在')
 return dump(b)
@router.post('/recon/batches/{i}/rerun')
def rerun_batch(i:int,u=Depends(editor),s=Depends(db)):
 b=s.get(ReconBatch,i)
 if not b:raise HTTPException(404,'对账批次不存在')
 if b.state=='success':raise HTTPException(409,'批次已成功，无需重跑')
 b=ledger.rerun(s,b,u);s.commit();return dump(b)
@router.get('/ledger')
def ledger_entries(experiment_id:int|None=None,status:str|None=None,u=Depends(current),s=Depends(db)):
 q=s.query(LedgerEntry)
 if experiment_id:q=q.filter_by(experiment_id=experiment_id)
 if status:
  if status not in ('held','posted','isolated'):raise HTTPException(422,'流水状态仅支持 held/posted/isolated')
  q=q.filter_by(status=status)
 return [dump(e) for e in q.order_by(LedgerEntry.id.desc()).limit(500).all()]
@router.get('/experiments/{i}/reconciliation')
def experiment_recon(i:int,u=Depends(current),s=Depends(db)):
 exp=experiment(s,i);bal=ledger.balance(s,exp)
 return {'experiment':dump(exp),'balance':bal,'ledger_version':ledger.ledger_version(s),
         'pending_for_users':[dump(e) for e in ledger.pending_outside(s,exp)]}
@router.get('/decisions')
def decisions(u=Depends(current),s=Depends(db)):return [dump(r) for r in s.query(Decision).order_by(Decision.id.desc())]
@router.post('/decisions')
def run(data:RunInput,u=Depends(editor),s=Depends(db)):
 exp=experiment(s,data.experiment_id)
 if s.query(Decision).filter(Decision.state.in_(['queued','running'])).count()>=10:raise HTTPException(429,'队列已满，请等待任务完成')
 snap=snapshot(s,exp)
 # 裁决只取完整账本版本：未对平订单阻止提交，采集/对账可继续进行
 require_balanced(snap)
 r=Decision(experiment_id=exp.id,snapshot=snap);s.add(r);s.commit()
 try:redis.Redis.from_url(os.environ['REDIS_URL']).rpush('trial:decisions',r.id)
 except redis.RedisError:r.state='failed';r.error='队列暂不可用，恢复后重新提交';s.commit();raise HTTPException(503,r.error)
 audit(s,u,'提交实验裁决 '+str(r.id)+' 账本版本 '+snap['ledger']['version']);return dump(r)
@router.get('/decisions/{i}')
def detail(i:int,u=Depends(current),s=Depends(db)):return dump(decision(s,i))
@router.put('/decisions/{i}/rationale')
def rationale(i:int,data:RationaleInput,u=Depends(editor),s=Depends(db)):
 r=decision(s,i)
 if r.published_at:raise HTTPException(409,'已发布裁决不可覆盖，请重新创建裁决')
 if r.state!='done':raise HTTPException(409,'计算完成后再填写裁决理由')
 r.rationale=data.rationale;s.commit();audit(s,u,'保存裁决理由 '+str(i));return dump(r)
@router.post('/decisions/{i}/publish')
def release(i:int,data:PublishInput,u=Depends(admin),s=Depends(db)):
 r=publish(s,decision(s,i),data.action,u);audit(s,u,'发布裁决 '+str(i)+' '+data.action);return r
@router.get('/decisions/{i}/export')
def export(i:int,u=Depends(current),s=Depends(db)):
 r=decision(s,i)
 if r.state!='done':raise HTTPException(409,'尚无成功结果')
 return Response(json.dumps(dump(r),ensure_ascii=False,indent=2),media_type='application/json',headers={'Content-Disposition':f'attachment; filename="trial-verdict-{i}.json"'})
@router.get('/audits')
def audits(u=Depends(admin),s=Depends(db)):return [dump(r) for r in s.query(Audit).order_by(Audit.id.desc()).limit(100)]
