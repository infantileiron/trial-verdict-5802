import math,hashlib,json
from datetime import datetime,timezone
from scipy.stats import norm,chi2,t
VERSION='two-proportion-srm-1.1'
LEGACY_VERSION='two-proportion-srm-1.0'
REV_VERSION='welch-net-revenue-1.0'
def calculate(snapshot):
 exp=snapshot['experiment'];events=snapshot['events']
 legacy='ledger' not in snapshot  # 历史激活裁决快照：维持原口径，不改写
 exposed={g:{e['user_key'] for e in events if e['group']==g and e['kind']=='exposure'} for g in ('A','B')}
 activated={g:{e['user_key'] for e in events if e['group']==g and e['kind']=='activation'}&exposed[g] for g in ('A','B')}
 n0,n1=[len(exposed[g]) for g in ('A','B')];c0,c1=[len(activated[g]) for g in ('A','B')]
 if min(n0,n1)<2:raise ValueError('每组至少需2名曝光用户，无法计算当前比例差异')
 p0,p1=c0/n0,c1/n1;delta=p1-p0;pooled=(c0+c1)/(n0+n1)
 se0=math.sqrt(pooled*(1-pooled)*(1/n0+1/n1))
 z=delta/se0 if se0 else 0.0;pv=float(2*norm.sf(abs(z))) if se0 else 1.0
 se=math.sqrt(p0*(1-p0)/n0+p1*(1-p1)/n1);margin=float(norm.ppf(.975))*se
 expected=[(n0+n1)*exp['a_ratio'],(n0+n1)*(1-exp['a_ratio'])]
 srm=sum((a-b)**2/b for a,b in zip([n0,n1],expected));srm_p=float(chi2.sf(srm,1))
 approximate=min(n0,n1)>=20 and min(c0,n0-c0,c1,n1-c1)>=5
 matured=datetime.now(timezone.utc)>=datetime.fromisoformat(exp['ends_at'])
 reasons=[]
 if not matured:reasons.append('实验未到预定结束时间，禁止提前发布')
 if srm_p<.01:reasons.append('SRM p<0.01，先排查随机分流与事件采集')
 if not approximate:reasons.append('每组至少20人且成功/失败各至少5人，当前不满足正态近似')
 out=dict(n_a=n0,n_b=n1,activated_a=c0,activated_b=c1,rate_a=p0,rate_b=p1,difference=delta,relative_lift=delta/p0 if p0 else None,z=z,p_value=pv,ci_low=max(-1,delta-margin),ci_high=min(1,delta+margin),srm_chi2=srm,srm_p=srm_p,expected_a=expected[0],expected_b=expected[1],matured=matured,approximation_valid=approximate,release_eligible=not reasons,block_reasons=reasons,significant_positive=delta>0 and pv<.05)
 checksum=hashlib.sha256(json.dumps(snapshot,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
 if legacy:
  # 历史激活裁决：保留原算法版本与门禁，不引入净收入口径，不改写
  out.update(version=LEGACY_VERSION,checksum=checksum,
   method='双侧双比例z检验；95%绝对提升Wald区间；SRM卡方df=1；曝光用户去重，激活为曝光子集；差异方向B−A（历史激活裁决，不含净收入）')
  return out
 # 新裁决：净收入只使用已对平账本（ledger.balanced=True），按参与者（曝光用户）平均
 rev=_revenue(snapshot,(n0,n1))
 if rev is None:raise ValueError('账本未对平或缺少支付流水，存在暂挂/隔离订单，阻止出裁决；先完成对账')
 # 净收入为负/无订单是上线B的专属阻因（与激活显著性一样独立于通用门禁），不阻断保留A
 out.update(net_revenue=rev,version=VERSION,checksum=checksum,
  method='双侧双比例z检验；95%绝对提升Wald区间；SRM卡方df=1；曝光用户去重，激活为曝光子集；差异方向B−A；净收入按订单首次支付归属，退款回冲原订单，Welch t检验比较两组人均净收入')
 return out
def _revenue(snapshot,exposed_counts):
 ledger=snapshot.get('ledger')
 if not ledger or not ledger.get('balanced'):return None
 rows=ledger['entries'];n0,n1=exposed_counts
 sum_net={g:0.0 for g in ('A','B')};orders={g:set() for g in ('A','B')};gross={g:0.0 for g in ('A','B')};refunded={g:0.0 for g in ('A','B')}
 # 参与者级净收入向量：曝光用户人均（无订单用户计0）
 per={g:{} for g in ('A','B')}
 for e in rows:
  if e['status']!='posted':continue
  g=e['group'];orders[g].add(e['order_id'])
  signed=e['amount'] if e['kind']=='payment' else -e['amount']
  sum_net[g]+=signed
  per[g][e['user_key']]=per[g].get(e['user_key'],0.0)+signed
  if e['kind']=='payment':gross[g]+=e['amount']
  else:refunded[g]+=e['amount']
 if not orders['A'] and not orders['B']:
  return {'has_revenue':False,'net_lift_positive':False,'ledger_version':ledger['version']}
 means={}
 for g,n in (('A',n0),('B',n1)):
  vals=list(per[g].values())+[0.0]*(n-len(per[g]))
  means[g]=sum(vals)/n
 var={}
 for g,n in (('A',n0),('B',n1)):
  m=means[g];vals=list(per[g].values())+[0.0]*(n-len(per[g]))
  var[g]=sum((x-m)**2 for x in vals)/(n-1) if n>1 else 0.0
 diff=means['B']-means['A']
 se2=var['A']/n0+var['B']/n1;se_r=math.sqrt(se2) if se2>0 else 0.0
 if se_r>0:
  df=se2**2/((var['A']/n0)**2/(n0-1)+(var['B']/n1)**2/(n1-1))
  tc=float(t.ppf(.975,df));tstat=diff/se_r;tp=float(2*t.sf(abs(tstat),df))
  lo,hi=diff-tc*se_r,diff+tc*se_r
 else:
  df=float('nan');tstat=0.0;tp=1.0;lo=hi=diff
 return {'has_revenue':True,'ledger_version':ledger['version'],
  'gross_a':round(gross['A'],2),'gross_b':round(gross['B'],2),
  'refunded_a':round(refunded['A'],2),'refunded_b':round(refunded['B'],2),
  'net_a':round(sum_net['A'],2),'net_b':round(sum_net['B'],2),
  'orders_a':len(orders['A']),'orders_b':len(orders['B']),
  'participants_a':n0,'participants_b':n1,
  'mean_net_a':round(means['A'],4),'mean_net_b':round(means['B'],4),
  'mean_difference':round(diff,4),'ci_low':round(lo,4),'ci_high':round(hi,4),
  't_stat':round(tstat,4),'p_value':round(tp,6),'df':None if math.isnan(df) else round(df,2),
  'net_lift_positive':diff>0,'method':REV_VERSION}
