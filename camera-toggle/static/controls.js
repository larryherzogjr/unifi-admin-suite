/* Shared by the portal and independently deployable camera/door services. */
(() => {
  const $ = (s, root=document) => root.querySelector(s);
  const $$ = (s, root=document) => [...root.querySelectorAll(s)];
  let refreshing=false, lastUpdate=Date.now(), refreshFailed=false, timerFailed=false;
  const busy=new Set();
  let noticeTimeout;
  function notice(message, error=false) {
    const box=$('#toast'); if(!box) return;
    clearTimeout(noticeTimeout); box.replaceChildren(document.createTextNode(message));
    box.className='toast show '+(error?'err':'ok'); box.setAttribute('role',error?'alert':'status');
    if(error){const close=document.createElement('button');close.textContent='Dismiss';close.onclick=()=>box.classList.remove('show');box.append(' ',close);}
    else noticeTimeout=setTimeout(()=>box.classList.remove('show'),6000);
  }
  async function request(url, data) {
    const response=await fetch(url,{cache:'no-store',signal:AbortSignal.timeout(45000),...(data===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)})});
    const result=await response.json();
    if(!response.ok || result.ok===false) throw Error(result.error || (result.failures?.length ? `${result.failures.length} devices could not be changed. Refresh to review their states.` : 'Service request failed. Try again.'));
    return result;
  }
  function filter(list) {
    const query=$('[data-search]',list).value.trim().toLowerCase(), chosen=$('[data-filter]',list).value;
    const cards=$$('[data-device]',list);let shown=0;
    const counts={all:cards.length,attention:0,offline:0,timers:0};
    cards.forEach(card=>{
      const attention=card.dataset.active==='false', offline=card.dataset.offline==='true', timer=!!card.dataset.deadline;
      counts.attention+=attention;counts.offline+=offline;counts.timers+=timer;
      card.classList.toggle('disconnected',offline);
      card.hidden=!(card.dataset.name.toLowerCase().includes(query)&&(chosen==='all'||chosen==='attention'&&attention||chosen==='offline'&&offline||chosen==='timers'&&timer));
      if(!card.hidden)shown++;
    });
    $$('[data-filter] option',list).forEach(opt=>{if(!opt.dataset.label)opt.dataset.label=opt.textContent;opt.textContent=`${opt.dataset.label} (${counts[opt.value]})`;});
    $('.section-summary',list).textContent=`${shown} of ${cards.length} ${list.dataset.kind}s · ${counts.attention} ${list.dataset.kind==='camera'?'in privacy':'unlocked'}`;
    const empty=$('.empty-state',list);empty.hidden=shown>0||!$('.service-error',list).hidden;
    empty.firstChild.textContent=cards.length?`No matching ${list.dataset.kind}s. `:`No ${list.dataset.kind}s available. `;
    const tab=$(`[data-panel="${list.dataset.kind}s"] .count`);if(tab)tab.textContent=counts.attention?`${counts.attention} ${list.dataset.kind==='camera'?'privacy':'unlocked'}`:cards.length;
  }
  function minutes(card){const value=$('[data-duration]',card).value;return Number(value==='custom'?$('[data-custom]',card).value:value);}
  function preview(card){const n=minutes(card), camera=card.closest('.control-list').dataset.kind==='camera';$('[data-custom-label]',card).hidden=$('[data-duration]',card).value!=='custom';$('[data-custom]',card).disabled=$('[data-duration]',card).value!=='custom';$('.time-preview',card).textContent=Number.isInteger(n)&&n>=1&&n<=480?`${camera?'Recording resumes':'Door locks'} about ${new Date(Date.now()+n*60000).toLocaleTimeString([], {hour:'numeric',minute:'2-digit'})} if started now.`:'Choose a whole number from 1 to 480 minutes.';}
  function key(card){return card.closest('.control-list').dataset.kind+':'+card.dataset.device;}
  function lockCard(card, locked){$$('button,input,select',card).forEach(el=>el.disabled=locked);card.setAttribute('aria-busy',String(locked));if(!locked)preview(card);}
  async function act(card, endpoint, data) {
    if(busy.has(key(card)))return;
    const list=card.closest('.control-list'), previousFocus=document.activeElement;busy.add(key(card));lockCard(card,true);
    const feedback=$('.card-feedback',card);feedback.className='card-feedback';feedback.setAttribute('role','status');feedback.textContent='Applying change…';
    try {
      await request(list.dataset.base+'/'+endpoint,{[list.dataset.kind+'_id']:card.dataset.device,reason:$('[data-reason]',card).value,...data});
      feedback.textContent='Command completed. Checking current state…';
      const updated=await refresh(card);
      const expected=endpoint==='toggle'?Boolean(data.enable??data.lock):endpoint==='cancel-timer';
      const confirmed=updated&&(card.dataset.active==='true')===expected;
      feedback.textContent=confirmed?'Change confirmed.':'Command completed; expected state is not yet verified. Use Refresh to check.';
      if(!confirmed)feedback.classList.add('error');
    } catch(error) {feedback.className='card-feedback error';feedback.setAttribute('role','alert');feedback.textContent=error.message;}
    finally {busy.delete(key(card));lockCard(card,false);filter(list);if(document.activeElement===document.body&&previousFocus?.isConnected&&!card.hidden)(previousFocus.closest('[hidden]')?$('[data-toggle]',card):previousFocus).focus();}
  }
  function labelActions(card){card.setAttribute('aria-label',card.dataset.name);$$('button',card).forEach(b=>b.setAttribute('aria-label',`${b.textContent.trim()} — ${card.dataset.name}`));}
  function bindCard(card) {
    labelActions(card);
    const list=card.closest('.control-list'), camera=list.dataset.kind==='camera';
    $('[data-disclose]',card).onclick=()=>{const options=$('.timed-options',card);options.hidden=!options.hidden;$('[data-disclose]',card).setAttribute('aria-expanded',String(!options.hidden));preview(card);if(!options.hidden)$('[data-duration]',card).focus();};
    $('[data-duration]',card).onchange=()=>preview(card);$('[data-custom]',card).oninput=()=>preview(card);
    $('form',card).onsubmit=e=>{e.preventDefault();const n=minutes(card);if(!Number.isInteger(n)||n<1||n>480){$('.card-feedback',card).textContent='Enter a whole number from 1 to 480 minutes.';return;}act(card,camera?'timed-off':'timed-unlock',{minutes:n});};
    $('[data-toggle]',card).onclick=()=>{const active=card.dataset.active==='true';if(active&&!confirm(`${camera?'Pause recording for':'Unlock'} ${card.dataset.name} without a countdown? Use ${camera?'Privacy for…':'Unlock for…'} for an automatic return.`))return;act(card,'toggle',{[camera?'enable':'lock']:!active});};
    $('[data-cancel]',card).onclick=()=>act(card,'cancel-timer',{});
    preview(card);
  }
  function bindList(list){
    $$('[data-device]',list).forEach(bindCard);
    $('[data-search]',list).oninput=()=>filter(list);$('[data-filter]',list).onchange=()=>filter(list);
    $('[data-clear]',list).onclick=()=>{$('[data-search]',list).value='';$('[data-filter]',list).value='all';filter(list);};
    const bulk=$('[data-bulk]',list);if(bulk)bulk.onclick=async()=>{
      if(busy.size||!confirm(`${bulk.textContent}? This affects all devices in this service and cancels their timers.`))return;
      const cards=$$('[data-device]',list);cards.forEach(c=>{busy.add(key(c));lockCard(c,true);});bulk.disabled=true;
      try{const result=await request(list.dataset.base+'/'+bulk.dataset.bulk,{});notice(`Command completed for ${result.changed??0} devices.`);}
      catch(error){notice(error.message,true);}
      finally{cards.forEach(c=>busy.delete(key(c)));await refresh();cards.forEach(c=>lockCard(c,false));bulk.disabled=false;}
    };
    filter(list);
  }
  async function timers(){
    const results=await Promise.all($$('.control-list').map(async list=>{
      const data=await request(list.dataset.base+'/timers');
      $$('[data-device]',list).forEach(card=>{const info=data[card.dataset.device];if(info?.remaining_sec>0)card.dataset.deadline=Date.now()+info.remaining_sec*1000;else delete card.dataset.deadline;$('.timer-display',card).hidden=!card.dataset.deadline;});filter(list);
    }));return results;
  }
  function tick(){
    $$('[data-deadline]').forEach(card=>{const left=Math.max(0,Math.ceil((Number(card.dataset.deadline)-Date.now())/1000));$('[data-countdown]',card).textContent=left?`${card.closest('.control-list').dataset.kind==='camera'?'Recording resumes':'Locks'} at ${new Date(Number(card.dataset.deadline)).toLocaleTimeString([], {hour:'numeric',minute:'2-digit'})} · ${Math.floor(left/60)}m ${left%60}s remaining`:'Timer elapsed — checking device state…';});
    $$('.timed-options:not([hidden])').forEach(el=>preview(el.closest('[data-device]')));
    const stale=Date.now()-lastUpdate>65000||refreshFailed||timerFailed;
    $$('.freshness').forEach(el=>{const failed=el.closest('.control-list')?.querySelector('.service-error:not([hidden])')||el.closest('.panel')?.querySelector('.error-box:not([hidden])');const updated=Number(el.dataset.updated)||lastUpdate;const localStale=stale||Date.now()-updated>65000;el.classList.toggle('stale',localStale||!!failed);const message=failed?'Service unavailable — displayed state may be outdated.':refreshFailed?'Refresh failed — displayed state may be outdated.':timerFailed?'Timer status unavailable — use Refresh to verify.':`${localStale?'Stale · ':''}Last refreshed ${new Date(updated).toLocaleTimeString()} · updates every 30 seconds`;if(el.textContent!==message)el.textContent=message;});
  }
  async function refresh(forceCard){
    if(refreshing)return false;refreshing=true;let valid=true;
    $$('[data-refresh]').forEach(b=>b.disabled=true);
    try {
      const response=await fetch(location.pathname+location.search,{cache:'no-store',signal:AbortSignal.timeout(45000)});if(!response.ok)throw Error('Service unavailable');
      const doc=new DOMParser().parseFromString(await response.text(),'text/html');
      for(const list of $$('.control-list')){
        const fresh=$$('.control-list',doc).find(n=>n.dataset.kind===list.dataset.kind);if(!fresh)throw Error('Unexpected response');
        const error=$('.service-error',fresh), target=$('.service-error',list);target.hidden=error.hidden;
        if(!error.hidden){valid=false;continue;}
        const incoming=$$('[data-device]',fresh), ids=new Set(incoming.map(c=>c.dataset.device));
        $$('[data-device]',list).forEach(card=>{if(!ids.has(card.dataset.device)&&!busy.has(key(card)))card.remove();});
        incoming.forEach(next=>{
          const existing=$$('[data-device]',list).find(c=>c.dataset.device===next.dataset.device);
          if(!existing){$('.item-list',list).append(next);bindCard(next);return;}
          if(busy.has(key(existing))&&existing!==forceCard)return;
          existing.dataset.name=next.dataset.name;existing.dataset.active=next.dataset.active;existing.dataset.offline=next.dataset.offline;existing.className=next.className;
          for(const selector of ['.item-name','.state-line','.item-meta'])$(selector,existing).replaceChildren(...$(selector,next).childNodes);
          $('[data-toggle]',existing).textContent=$('[data-toggle]',next).textContent;labelActions(existing);
        });filter(list);
      }
      for(const id of ['monitor','audit']){const old=$('#panel-'+id), next=$('#panel-'+id,doc);if(old&&next&&!old.contains(document.activeElement)){old.replaceChildren(...next.childNodes);$('.freshness',old).dataset.updated=Date.now();const count=$(`[data-panel="${id}"] .count`),newCount=$(`[data-panel="${id}"] .count`,doc);if(count&&newCount)count.textContent=newCount.textContent;}}
      try{await timers();timerFailed=false;}catch{timerFailed=true;valid=false;}
      lastUpdate=Date.now();refreshFailed=false;
    } catch(error){refreshFailed=true;valid=false;if(forceCard)notice('Could not refresh current device state. Retry Refresh.',true);}
    finally {refreshing=false;$$('[data-refresh]').forEach(b=>b.disabled=false);tick();}
    return valid;
  }
  document.addEventListener('click',e=>{if(e.target.closest('[data-refresh]'))refresh();});
  const tabs=$$('[role=tab]');function select(tab,focus=false){tabs.forEach(t=>{const on=t===tab;t.classList.toggle('active',on);t.setAttribute('aria-selected',String(on));t.tabIndex=on?0:-1;const panel=$('#panel-'+t.dataset.panel);panel.classList.toggle('active',on);panel.setAttribute('role','tabpanel');});history.replaceState(null,'','#'+tab.dataset.panel);if(focus)tab.focus();}
  tabs.forEach((tab,i)=>{tab.onclick=()=>select(tab);tab.onkeydown=e=>{let n;if(e.key==='ArrowRight')n=(i+1)%tabs.length;if(e.key==='ArrowLeft')n=(i+tabs.length-1)%tabs.length;if(e.key==='Home')n=0;if(e.key==='End')n=tabs.length-1;if(n!==undefined){e.preventDefault();select(tabs[n],true);}};});if(tabs.length)select(tabs.find(t=>t.dataset.panel===location.hash.slice(1))||tabs[0]);
  $$('[data-portal-link]').forEach(a=>{const url=new URL(location.href);url.port='8080';url.pathname='/';url.search='';url.hash='';a.href=url;});
  $$('.panel:not(:has(.control-list)) .freshness').forEach(el=>el.dataset.updated=lastUpdate);
  $$('.control-list').forEach(bindList);timers().catch(()=>{timerFailed=true;}).finally(tick);
  setInterval(tick,1000);setInterval(()=>{if(!busy.size)refresh();},30000);
})();
