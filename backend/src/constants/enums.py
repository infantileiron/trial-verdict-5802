ROLES=('admin','analyst','viewer')
GROUPS=('A','B')
EVENT_KINDS=('exposure','activation')
STATES=('queued','running','done','failed')
ACTIONS=('publish_b','keep_a')
# 支付/退款流水类型
LEDGER_KINDS=('payment','refund')
# 单条流水处理状态：held=先到暂挂，posted=已记账，isolated=超额退款隔离
LEDGER_STATUSES=('held','posted','isolated')
# 对账批次状态
BATCH_STATES=('pending','success','failed')
