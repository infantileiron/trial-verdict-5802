from datetime import datetime,timezone,timedelta
from src.config.database import Base,engine,Session
from src.models.entities import User,Experiment,Event,LedgerEntry,ReconBatch
from src.services import ledger
from src.utils.security import hash_password
def seed():
 Base.metadata.create_all(engine)
 with Session() as s:
  for role in ('admin','analyst','viewer'):
   email=role+'@demo.local'
   if not s.query(User).filter_by(email=email).first():s.add(User(email=email,role=role,password=hash_password('Demo123!')))
  s.commit()
  today=datetime.now(timezone.utc).replace(hour=0,minute=0,second=0,microsecond=0)
  for code,name,ends in [('LJ-1115-A','首次引导文案 / 成熟对照',today-timedelta(days=1)),('LJ-1115-B','快捷模板入口 / 观察中',today+timedelta(days=3)),('LJ-1116-R','付费引导定价 / 净收入裁决',today-timedelta(days=1))]:
   exp=s.query(Experiment).filter_by(code=code).first()
   if not exp:
    exp=Experiment(code=code,name=name,starts_at=(today-timedelta(days=7)).isoformat(),ends_at=ends.isoformat(),a_ratio=.5,hypothesis='更清晰的首次引导能提升首次激活率，预先固定观察期与分流比例');s.add(exp);s.flush()
   if code.endswith('-A'):
    stamp=(datetime.fromisoformat(exp.starts_at)+timedelta(hours=12)).isoformat()
    for i in range(1200):
     group='A' if i<600 else 'B';key=f'LJ-U{i+1:04}';activated=(i<120 if group=='A' else i-600<180)
     for kind in ['exposure']+(['activation'] if activated else []):
      if not s.query(Event).filter_by(experiment_id=exp.id,user_key=key,kind=kind).first():s.add(Event(experiment_id=exp.id,user_key=key,group=group,kind=kind,occurred_at=stamp))
  s.commit()
  _seed_ledger(s,today)
  s.commit();print({'users':s.query(User).count(),'experiments':s.query(Experiment).count(),'events':s.query(Event).count(),'ledger_entries':s.query(LedgerEntry).count(),'batches':s.query(ReconBatch).count()})
def _entry(external_id,kind,order,user,amount,day_offset,hour=14):
 from src.schemas.business import LedgerItem
 return LedgerItem(external_id=external_id,kind=kind,order_id=order,user_key=user,amount=float(amount),
                   occurred_at=datetime.now(timezone.utc).replace(hour=hour,minute=5,second=0,microsecond=0)+timedelta(days=day_offset))
def _seed_ledger(s,today):
 """剧本：批次1正常支付+跨日退款；批次2先到退款/先到支付暂挂与超额退款隔离；批次3消化全部暂挂。"""
 if s.query(LedgerEntry).first():return
 class _U:email='seed@demo.local'
 # 批次1：成熟实验前40名用户（各20/组）支付，A组3笔次日退款、B组1笔隔日退款（跨日回冲）
 items=[]
 for i in range(40):
  user=f'LJ-U{i+1:04}';group='A' if i<20 else 'B'
  price=100 if group=='A' else 120
  items.append(_entry(f'P-{i+1:03}','payment',f'ORD-{i+1:04}',user,price,-3))
 for i in (0,1,2):
  items.append(_entry(f'R-{i+1:03}','refund',f'ORD-{i+1:04}',f'LJ-U{i+1:04}',100,-2))
 items.append(_entry('R-020','refund','ORD-0021','LJ-U0021',120,-1))
 b1=ledger.ingest(s,items,'seed-batch-1-正常支付与跨日退款',_U());s.commit()
 # 批次2：异常——先到退款（原订单不存在→held）、先到支付（无曝光用户→held）、超额退款（isolated）、重复投递
 items2=[
  _entry('R-EARLY','refund','ORD-9001','LJ-U0010',50,-2),                       # 原订单后到，先到退款暂挂
  _entry('P-LATE','payment','ORD-9002','LJ-GHOST-1',200,-2),                    # 无曝光用户，先到支付暂挂
  _entry('P-9001','payment','ORD-9001','LJ-U0010',80,-1),                       # 原订单到达，重跑后匹配先到退款
  _entry('P-0005','payment','ORD-0005','LJ-U0005',100,-1),                      # 重复 external_id 测试另用同ID
 ]
 # 超额退款：ORD-0006 已付100，退100再退30 → 第二笔隔离
 items2 += [_entry('R-006A','refund','ORD-0006','LJ-U0006',100,-1),
            _entry('R-006B','refund','ORD-0006','LJ-U0006',30,-1)]
 items2[3]=_entry('P-001','payment','ORD-0001','LJ-U0001',100,-3)               # 与批次1同 external_id → 重复丢弃
 b2=ledger.ingest(s,items2,'seed-batch-2-暂挂隔离与重复投递',_U());s.commit()
 # 批次3：给幽灵用户补曝光（采集仍可用），事件入库会自动消化暂挂；超额退款保持隔离
 ghost_exp=s.query(Experiment).filter_by(code='LJ-1115-A').first()
 if not s.query(Event).filter_by(user_key='LJ-GHOST-1').first():
  s.add(Event(experiment_id=ghost_exp.id,user_key='LJ-GHOST-1',group='B',kind='exposure',
              occurred_at=(today-timedelta(days=1,hours=2)).isoformat()));s.commit()
 for held in s.query(LedgerEntry).filter_by(status='held').all():
  ledger.process_entry(s,held)
 ledger.refresh_batch(s,b2)
 s.commit()
 _seed_revenue_experiment(s,today)
def _seed_revenue_experiment(s,today):
 """LJ-1116-R：账本完全对平的净收入裁决实验，可走完提交→裁决→发布全流程。"""
 exp=s.query(Experiment).filter_by(code='LJ-1116-R').first()
 if not exp or s.query(LedgerEntry).filter(LedgerEntry.experiment_id==exp.id).first():return
 class _U:email='seed@demo.local'
 n=60
 for i in range(n*2):
  user=f'RV-U{i+1:04}';group='A' if i<n else 'B'
  if not s.query(Event).filter_by(experiment_id=exp.id,user_key=user).first():
   s.add(Event(experiment_id=exp.id,user_key=user,group=group,kind='exposure',occurred_at=(today-timedelta(days=5)).isoformat()))
   # A激活18人(30%)，B激活30人(50%)：激活差异显著且 B 净收入更高
   act=(i<18) or (n<=i<n+30)
   if act:s.add(Event(experiment_id=exp.id,user_key=user,group=group,kind='activation',occurred_at=(today-timedelta(days=5,hours=1)).isoformat()))
 s.commit()
 items=[]
 for i in range(n*2):
  user=f'RV-U{i+1:04}';group='A' if i<n else 'B'
  # 约60%参与者付费；A客单价100，B客单价130，B 人均净收入更高
  if i%5<3:
   items.append(_entry(f'RV-P{i+1:04}','payment',f'RV-ORD-{i+1:04}',user,100 if group=='A' else 130,-4))
 # A组两笔跨日退款、B组一笔，均不超额
 for i in (0,5):
  items.append(_entry(f'RV-R{i+1:04}','refund',f'RV-ORD-{i+1:04}',f'RV-U{i+1:04}',100,-3))
 items.append(_entry('RV-R61','refund','RV-ORD-0061','RV-U0061',130,-2))
 b=ledger.ingest(s,items,'seed-batch-3-净收入实验对平账本',_U());s.commit()
 assert b.state=='success',(b.state,b.detail)
if __name__=='__main__':seed()
