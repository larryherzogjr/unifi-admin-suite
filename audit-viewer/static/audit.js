(() => {
const $=s=>document.querySelector(s);const params=new URLSearchParams(location.search);let category=params.get('category')||'all';
if(!['all','camera','door'].includes(category))category='all';$('#search').value=params.get('q')||'';
function remember(){const url=new URL(location.href);url.searchParams.set('q',$('#search').value);url.searchParams.set('category',category);history.replaceState(null,'',url);}
function filter(){const query=$('#search').value.trim().toLowerCase(),cards=[...document.querySelectorAll('.entry-card')];let shown=0;
 cards.forEach(card=>{card.hidden=!((category==='all'||card.dataset.category===category)&&card.dataset.searchable.includes(query));if(!card.hidden)shown++;});
 $('#stats').textContent=`${shown} of ${cards.length} entries`;$('#noMatches').hidden=shown>0;
 document.querySelectorAll('[data-filter]').forEach(b=>{b.classList.toggle('active',b.dataset.filter===category);b.setAttribute('aria-pressed',String(b.dataset.filter===category));});remember();}
$('#search').oninput=filter;document.querySelectorAll('[data-filter]').forEach(b=>b.onclick=()=>{category=b.dataset.filter;filter();});
document.querySelectorAll('[data-days]').forEach(b=>b.onclick=()=>{remember();const url=new URL(location.href);url.searchParams.set('days',b.dataset.days);location.href=url;});
$('#auditRefresh').onclick=()=>location.reload();$('#clearAudit').onclick=()=>{$('#search').value='';category='all';filter();$('#search').focus();};
const portal=new URL(location.href);portal.port='8080';portal.pathname='/';portal.search='';portal.hash='audit';document.querySelectorAll('[data-portal-link]').forEach(a=>a.href=portal);
filter();
})();
