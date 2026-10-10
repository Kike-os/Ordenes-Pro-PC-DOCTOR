import urllib.request,urllib.error,json,base64,time
from pathlib import Path
out=Path('/home/admin-red/Work/ordenes-pro/revision/orders-module-20261010');out.mkdir(exist_ok=True)
base='http://127.0.0.1:9518'
def req(path,data=None,method=None):
 r=urllib.request.Request(base+path,data=None if data is None else json.dumps(data).encode(),headers={'Content-Type':'application/json'},method=method)
 try:
  with urllib.request.urlopen(r) as response:v=json.load(response)['value']
 except urllib.error.HTTPError as e:raise RuntimeError(e.read().decode())
 if isinstance(v,dict) and 'error' in v:raise RuntimeError(v)
 return v
sid=req('/session',{'capabilities':{'alwaysMatch':{'browserName':'chrome','goog:chromeOptions':{'binary':'/usr/bin/chromium','args':['--headless=new','--no-sandbox','--disable-dev-shm-usage','--user-data-dir=/tmp/ordenes-forms-chrome'],'prefs':{}},'goog:loggingPrefs':{'browser':'ALL'}}}})['sessionId'];p='/session/'+sid
checks=[]
def js(script):return req(p+'/execute/sync',{'script':script,'args':[]})
def asyncjs(script):return req(p+'/execute/async',{'script':'const done=arguments[arguments.length-1];(async()=>{'+script+'})().then(done).catch(e=>done({error:e.message,stack:e.stack}));','args':[]})
def shot(name):(out/(name+'.png')).write_bytes(base64.b64decode(req(p+'/screenshot')))
def inspect(name):
 data=js('''const d=document.querySelector('dialog[open]'),form=d?.querySelector('form'),r=d?.getBoundingClientRect();return {label:NAME,width:innerWidth,height:innerHeight,overflow:document.documentElement.scrollWidth>innerWidth,modal:d?.id||d?.className||'',modalInView:!r||(r.left>=-1&&r.right<=innerWidth+1&&r.top>=-1&&r.bottom<=innerHeight+1),modalOverflow:d?d.scrollWidth>d.clientWidth+1:false,closeVisible:d?[...d.querySelectorAll('[aria-label="Cerrar"],#close-dialog')].some(b=>{const a=b.getBoundingClientRect();return a.width>0&&a.top>=0&&a.right<=innerWidth&&a.bottom<=innerHeight}):true,footerVisible:d?[...d.querySelectorAll('footer')].every(f=>{const a=f.getBoundingClientRect();return a.bottom<=innerHeight+1}):true,openCount:document.querySelectorAll('dialog[open]').length};'''.replace('NAME',json.dumps(name)));checks.append(data);return data
try:
 req(p+'/url',{'url':'http://127.0.0.1:8021/'})
 print(asyncjs("return await api('/api/login',{login:'demo',password:'contraseña-segura-de-prueba'});"),flush=True)
 req(p+'/url',{'url':'http://127.0.0.1:8021/#orders'});req(p+'/refresh',{});time.sleep(.7)
 print(js("return {url:location.href,page:document.body.dataset.page,text:document.body.innerText.slice(0,250)}"),flush=True)
 for width,height in [(1920,1080),(1440,1000),(1366,900),(1024,900),(768,1024),(390,844),(320,740)]:
  req(p+'/window/rect',{'width':width,'height':height});js("document.querySelector('.control-center').scrollTop=0;window.scrollTo(0,0);");time.sleep(.25)
  inspect('orders-'+str(width));shot('orders-'+str(width))
  shape=js("const v=document.getElementById('view-module'),fields=[...v.querySelectorAll('.orders-search input,.order-filters input,.order-filters select,#module-add')].filter(x=>x.type!=='checkbox').map(x=>x.getBoundingClientRect());return {searchCount:v.querySelectorAll('form[role=search]').length,activeCount:v.querySelectorAll('[name=active]').length,filterCards:v.querySelectorAll('.orders-filter-card').length,controlsWithinWidth:fields.every(r=>r.left>=0&&r.right<=innerWidth),rowSelects:v.querySelectorAll('.order-row-actions select').length,actions:[...v.querySelector('.order-row-actions').children].map(x=>x.textContent),header:v.querySelector('.order-table th').textContent};")
  assert shape['controlsWithinWidth'] and shape['searchCount']==1 and shape['activeCount']==1 and shape['filterCards']==1 and shape['rowSelects']==0 and shape['header']=='Orden' and shape['actions']==['Ver orden','Imprimir ticket','Más acciones'],shape
  js("window.__trigger=document.querySelector('.orders-more-trigger');window.__trigger.scrollIntoView({block:'center'});");time.sleep(.15);js("window.__trigger.click();");time.sleep(.1)
  menu=js("const m=document.querySelector('.orders-action-menu:popover-open'),r=m.getBoundingClientRect();return {inView:r.left>=0&&r.right<=innerWidth&&r.top>=0&&r.bottom<=innerHeight,items:[...m.querySelectorAll('button')].map(x=>x.textContent),overflow:m.scrollWidth>m.clientWidth};")
  assert menu['inView'] and not menu['overflow'] and 'Cambiar estado' in menu['items'],menu
  shot('orders-menu-'+str(width));checks.append({'label':'menu-'+str(width),'width':width,**menu,**shape})
  js("document.querySelector('.orders-action-menu:popover-open').dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}));");assert js("return !document.querySelector('.orders-action-menu:popover-open')&&document.activeElement===window.__trigger")
 # Open another menu after the first, then verify keyboard focus navigation.
 js("document.querySelectorAll('.orders-more-trigger')[1].click();");assert js("return !!document.querySelector('.orders-action-menu:popover-open')")
 js("document.querySelector('.orders-action-menu:popover-open').dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowDown',bubbles:true}));");assert js("return document.activeElement.textContent==='Cambiar estado'")
 js("document.querySelector('.orders-action-menu:popover-open').hidePopover();document.querySelector('.orders-pagination button:last-child').click();");time.sleep(.4)
 assert js("return document.querySelector('.orders-pagination span').textContent==='Página 2 de 2'&&document.querySelectorAll('.order-table tbody tr').length===5")
 # Apply state filter, clear it, and retain a separate free-text query.
 js("const f=document.querySelector('.order-filters');f.elements.status.value='entregado';f.elements.active.checked=false;f.requestSubmit();");time.sleep(.4)
 assert js("return document.querySelector('.result-count').textContent==='1 registro'&&document.querySelectorAll('.order-table tbody tr').length===1")
 js("document.querySelector('.orders-filter-actions button:last-child').click();");time.sleep(.4)
 assert js("return document.querySelector('.result-count').textContent==='55 registros'")
 js("const f=document.querySelector('.orders-search');f.elements.q.value='ORD-QA-48';f.requestSubmit();");time.sleep(.4)
 assert js("return document.querySelector('.result-count').textContent==='1 registro'")
 js("const f=document.querySelector('.order-filters');f.elements.active.checked=true;f.requestSubmit();");time.sleep(.4)
 assert js("return location.hash.includes('active=1')&&location.hash.includes('q=ORD-QA-48')")
 js("document.querySelector('.orders-filter-actions button:last-child').click();");time.sleep(.4)
 assert js("return !location.hash.includes('active=')&&location.hash.includes('q=ORD-QA-48')")
 # Change state through its secondary action and save using the existing backend.
 js("document.querySelector('.orders-more-trigger').click();[...document.querySelectorAll('.orders-action-menu:popover-open button')].find(x=>x.textContent==='Cambiar estado').click();");time.sleep(.1)
 assert js("return !!document.querySelector('dialog[open] .orders-status-form')")
 js("const f=document.querySelector('dialog[open] .orders-status-form');f.elements.status.value='reparacion';f.requestSubmit();");time.sleep(.5)
 assert js("return !document.querySelector('dialog[open]')&&document.querySelector('.order-table .status-label').dataset.status==='reparacion'")
 # History action navigates to the real history section, then scanning opens the same order.
 order=asyncjs("return (await api('/api/orders?q=ORD-QA-48')).rows[0];")
 js("document.querySelector('.orders-more-trigger').click();[...document.querySelectorAll('.orders-action-menu:popover-open button')].find(x=>x.textContent==='Ver historial').click();");time.sleep(.4)
 assert js("return document.activeElement.id==='order-history'")
 js("go('orders');");time.sleep(.4)
 js("const f=document.querySelector('.orders-search');f.elements.q.value="+json.dumps(order['code'])+";f.requestSubmit();");time.sleep(.4)
 assert js("return location.hash.includes('id="+str(order['id'])+"')")
 # Existing clients module retains its own layout, and technician actions obey permissions.
 js("go('clients');");time.sleep(.4);assert js("return !document.getElementById('view-module').classList.contains('orders-list-view')")
 asyncjs("await api('/api/logout',{});return true;")
 logs=req(p+'/log',{'type':'browser'});assert not [x for x in logs if x['level']=='SEVERE'],logs
 assert all(not x.get('overflow',False) for x in checks),checks
 (out/'browser-checks.json').write_text(json.dumps({'checks':checks,'functional':['pagination','status_filter','clear_keeps_search','active_filter','saved_status','history_focus','scanned_code','client_layout_preserved'],'logs':logs},ensure_ascii=False,indent=2));print('PASS seven widths, action menus and 8 functional checks',flush=True)
finally:req(p,method='DELETE')
