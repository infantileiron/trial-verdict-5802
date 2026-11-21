from sqlalchemy import Column,Integer,String,Float,JSON,Text,UniqueConstraint,ForeignKey,Index
from src.config.database import Base
class User(Base):
 __tablename__='users'
 id=Column(Integer,primary_key=True);email=Column(String(100),unique=True);password=Column(String(200));role=Column(String(20))
class Experiment(Base):
 __tablename__='experiments'
 id=Column(Integer,primary_key=True);code=Column(String(60),unique=True);name=Column(String(120));starts_at=Column(String(40));ends_at=Column(String(40));a_ratio=Column(Float);hypothesis=Column(Text)
class Event(Base):
 __tablename__='events'
 __table_args__=(UniqueConstraint('experiment_id','user_key','kind',name='uq_exp_user_kind'),)
 id=Column(Integer,primary_key=True);experiment_id=Column(Integer,ForeignKey('experiments.id'));user_key=Column(String(80));group=Column(String(1));kind=Column(String(20));occurred_at=Column(String(40))
class Decision(Base):
 __tablename__='decisions'
 id=Column(Integer,primary_key=True);experiment_id=Column(Integer,ForeignKey('experiments.id'));state=Column(String(20),default='queued');snapshot=Column(JSON);result=Column(JSON,nullable=True);error=Column(Text,default='');rationale=Column(Text,default='');action=Column(String(30),default='');published_by=Column(String(100),default='');published_at=Column(String(40),default='')
class LedgerEntry(Base):
 __tablename__='ledger_entries'
 __table_args__=(UniqueConstraint('external_id',name='uq_ledger_external_id'),Index('ix_ledger_order','order_id'),Index('ix_ledger_status','status'))
 # 支付与退款统一流水表，append-only，重复投递按 external_id 幂等丢弃
 id=Column(Integer,primary_key=True)
 external_id=Column(String(80));batch_id=Column(Integer,ForeignKey('recon_batches.id'))
 kind=Column(String(10));order_id=Column(String(80));user_key=Column(String(80));amount=Column(Float);occurred_at=Column(String(40));received_at=Column(String(40))
 # 归属在记账时解析：按订单首次支付的实验/组别；held 表示暂未解析，isolated 表示超额退款隔离
 experiment_id=Column(Integer,ForeignKey('experiments.id'),nullable=True);group=Column(String(1),nullable=True)
 status=Column(String(10),default='held');note=Column(String(300),default='')
 # 退款关联的原订单支付流水；posted 退款回冲原订单，isolated 退款不计净收入
 payment_entry_id=Column(Integer,ForeignKey('ledger_entries.id'),nullable=True);refunded_amount=Column(Float,nullable=True)
class ReconBatch(Base):
 __tablename__='recon_batches'
 id=Column(Integer,primary_key=True);source=Column(String(120),default='manual');state=Column(String(10),default='pending')
 total=Column(Integer,default=0);posted=Column(Integer,default=0);held=Column(Integer,default=0);isolated=Column(Integer,default=0);duplicates=Column(Integer,default=0)
 detail=Column(JSON);dup_detail=Column(JSON);error=Column(Text,default='');created=Column(String(40));updated=Column(String(40))
class Audit(Base):
 __tablename__='audits'
 id=Column(Integer,primary_key=True);actor=Column(String(100));action=Column(String(200));created=Column(String(40))
