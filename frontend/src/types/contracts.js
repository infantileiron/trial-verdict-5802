/** @typedef {{id:number,code:string,name:string,starts_at:string,ends_at:string,a_ratio:number,hypothesis:string,ledger_balanced:boolean,held_count:number,isolated_count:number,net_a:number,net_b:number}} Experiment */
/** @typedef {{id:number,experiment_id:number,user_key:string,group:'A'|'B',kind:'exposure'|'activation',occurred_at:string}} TrialEvent */
/** @typedef {{id:number,experiment_id:number,state:string,result:object,snapshot:object,rationale:string,action:string,published_at:string}} Decision */
/** @typedef {{id:number,external_id:string,batch_id:number,kind:'payment'|'refund',order_id:string,user_key:string,amount:number,status:'held'|'posted'|'isolated',note:string}} LedgerEntry */
/** @typedef {{id:number,source:string,state:'pending'|'success'|'failed',total:number,posted:number,held:number,isolated:number,duplicates:number,detail:array}} ReconBatch */
export const CONTRACT_VERSION='2.0';
