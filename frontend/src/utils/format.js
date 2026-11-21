export const pct=n=>(n*100).toFixed(2)+'%';export const pvalue=n=>n<.001?n.toExponential(2):n.toFixed(4);export const time=s=>s?new Date(s).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',hour12:false}):'—';
export const money=n=>(Number(n)||0).toLocaleString('zh-CN',{minimumFractionDigits:2,maximumFractionDigits:2});
export const pp=n=>(Number(n)||0).toFixed(2);
