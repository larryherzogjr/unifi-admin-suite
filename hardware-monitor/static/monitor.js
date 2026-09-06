(() => {
const $=s=>document.querySelector(s);let devices=[],type='all',status='all',last=0,busy=false;
const escape=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const offline=d=>['offline','unreachable'].includes(d.status);
function render(){
 const openDetails=new Set([...document.querySelectorAll('[data-device-key]')].filter(el=>el.querySelector('details')?.open).map(el=>el.dataset.deviceKey));
 const focusedType=document.activeElement?.dataset?.type;
 const query=$('#deviceSearch').value.trim().toLowerCase();
 const choices=['all',...new Set(devices.map(d=>d.type))];
 $('#filters').replaceChildren(...choices.map(t=>{const b=document.createElement('button');b.className='filter-btn';b.dataset.type=t;b.textContent=t==='all'?'All types':t;b.setAttribute('aria-pressed',String(t===type));b.onclick=()=>{type=t;render();};return b;}));
 const shown=devices.filter(d=>(type==='all'||d.type===type)&&(status==='all'||status==='offline'&&offline(d)||status==='online'&&d.status==='online')&&`${d.name} ${d.ip??''}`.toLowerCase().includes(query)).sort((a,b)=>Number(offline(b))-Number(offline(a))||String(a.name).localeCompare(String(b.name)));
 $('#grid').innerHTML=shown.map(d=>{
 const current=['online','offline','unreachable','unknown'].includes(d.status)?d.status:'unknown';
 let details=['ip','firmware','uptime','mac'].filter(k=>d[k]).map(k=>`<div><span class="label">${escape({ip:'IP',firmware:'Firmware',uptime:'Uptime',mac:'MAC'}[k])}</span> <span class="val">${escape(d[k])}</span></div>`).join('');
 let metrics='';for(const [key,label] of [['cpu','CPU'],['memory','Memory']]){if(typeof d[key]==='number'&&Number.isFinite(d[key])){const p=d[key];metrics+=`<div><span class="label">${label}</span> <span class="val">${Math.round(p)}%</span><span class="bar-bg" aria-hidden="true"><span class="bar-fill ${p>=90?'bad':p>=70?'warn':'ok'}" style="width:${Math.max(0,Math.min(100,p))}%"></span></span></div>`;}}
 if(d.temperature!=null)metrics+=`<div><span class="label">Temperature</span> <span class="val">${escape(d.temperature)}°C</span></div>`;
 if(d.storage)details+=`<div>Storage: ${escape(d.storage.totalGB)} GB${d.storage.usedPct!=null?' · '+escape(d.storage.usedPct)+'% used':''}</div>`;
 return `<article class="device-card ${current}" data-device-key="${escape(d.id||d.ip||d.name)}"><div class="device-header"><h2 class="device-name">${escape(d.name)}</h2><span class="badge ${current==='online'?'connected':current==='unknown'?'':'disconnected'}">${current[0].toUpperCase()+current.slice(1)}</span></div><p class="device-type">${escape(d.type)}${d.model?' · '+escape(d.model):''}</p><div class="device-details">${metrics}</div><details class="device-details-toggle"><summary>Device details</summary><div class="device-details">${details}</div></details>${d.error?`<p class="error-msg">${escape(d.error)}</p>`:''}</article>`;
 }).join('');
 document.querySelectorAll('[data-device-key]').forEach(el=>{el.querySelector('details').open=openDetails.has(el.dataset.deviceKey);});
 if(focusedType!==undefined)[...document.querySelectorAll('[data-type]')].find(b=>b.dataset.type===focusedType)?.focus();
 $('#noDevices').hidden=shown.length>0;$('#resultCount').textContent=`${shown.length} of ${devices.length} devices`;
 document.querySelectorAll('[data-status]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.status===status)));
}
async function get(url){const r=await fetch(url,{cache:'no-store',signal:AbortSignal.timeout(45000)});if(!r.ok)throw Error('Service unavailable');return r.json();}
async function refresh(){if(busy)return;busy=true;$('#refresh').disabled=true;$('#lastUpdated').textContent='Refreshing device health…';
 try{const data=await get('/api/snapshot');devices=data.devices||[];last=data.timestamp?data.timestamp*1000:0;$('#monitorError').hidden=true;
 $('#totalCount').textContent=data.total??devices.length;$('#onlineCount').textContent=data.online??devices.filter(d=>d.status==='online').length;$('#offlineCount').textContent=data.offline??devices.filter(offline).length;render();freshness();
 }catch{ $('#monitorError').hidden=false;$('#monitorError').textContent='Cannot refresh device health. Displayed readings may be outdated. Retry Refresh.';$('#lastUpdated').textContent=last?'Last successful snapshot: '+new Date(last).toLocaleTimeString():'No device data received yet.';}
 try{const a=await get('/api/alert-status');$('#alertStatus').textContent=a.enabled?`Email alerts enabled · Tracking ${a.tracked_devices} devices · ${Math.round(a.cooldown_seconds/60)} minute cooldown`:'Email alerts disabled. Contact your administrator to enable notifications.';}catch{$('#alertStatus').textContent='Email alert status unavailable.';}
 busy=false;$('#refresh').disabled=false;freshness();}
function freshness(){if(busy||!$('#monitorError').hidden)return;const stale=!last||Date.now()-last>65000;$('#lastUpdated').classList.toggle('stale',stale);const message=last?`${stale?'Stale snapshot · ':''}Updated ${new Date(last).toLocaleTimeString()} · checks every 30 seconds`:'Waiting for a timestamped device snapshot.';if($('#lastUpdated').textContent!==message)$('#lastUpdated').textContent=message;}
$('#refresh').onclick=refresh;$('#deviceSearch').oninput=render;
document.querySelectorAll('[data-status]').forEach(b=>b.onclick=()=>{status=b.dataset.status;render();});
$('#clearDevices').onclick=()=>{status='all';type='all';$('#deviceSearch').value='';render();};
const portal=new URL(location.href);portal.port='8080';portal.pathname='/';portal.search='';portal.hash='monitor';document.querySelectorAll('[data-portal-link]').forEach(a=>a.href=portal);
refresh();setInterval(refresh,30000);setInterval(freshness,1000);
})();
