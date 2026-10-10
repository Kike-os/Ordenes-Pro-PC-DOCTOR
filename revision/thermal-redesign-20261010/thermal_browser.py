import urllib.request,urllib.error,json,base64,time
from pathlib import Path
out=Path('/home/admin-red/Work/ordenes-pro/revision/thermal-redesign-20261010');out.mkdir(exist_ok=True)
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
 req(p+'/url',{'url':'http://127.0.0.1:8020/'})
 asyncjs("return await api('/api/login',{login:'demo',password:'contraseña-segura-de-prueba'});")
 req(p+'/url',{'url':'http://127.0.0.1:8020/'});time.sleep(.5)
 assert js("return !!document.querySelector('#order-form [name=technical_access]')")
 for width,height in [(1920,1080),(1440,1000),(1366,900),(1024,900),(768,1024),(390,844),(320,740)]:
  req(p+'/window/rect',{'width':width,'height':height})
  result=asyncjs('await showOrder();await chooseClient(1);wizardVisited=3;showWizardStep(2);return true;');assert result is True,result
  js("document.querySelector('#order-form .technical-access-fields').scrollIntoView({block:'start'});");time.sleep(.25);inspect('access-reception-'+str(width));shot('access-reception-'+str(width))
  assert js("return !!validateReception(Object.fromEntries(new FormData(document.getElementById('order-form'))),2).technical_access")
  js("const f=document.getElementById('order-form');f.querySelector('[name=technical_access][value=denied]').checked=true;f.querySelector('[name=technical_access]').dispatchEvent(new Event('change',{bubbles:true}));f.elements.access_confirmed.checked=true;")
  assert js("return !Object.keys(accessErrors(accessPayload(document.getElementById('order-form')))).length")
  js('showWizardStep(3);');inspect('terms-full-'+str(width));shot('terms-full-'+str(width))
  assert js("return document.querySelector('#terms-document-info .terms-full-text').textContent.length>0")
  js("document.getElementById('order-dialog').close();resetReception();")
  assert asyncjs("const {order}=await api('/api/orders/1');await openAccessAuthorization(order);return true;") is True
  inspect('additional-access-'+str(width));shot('additional-access-'+str(width));js("document.querySelector('dialog[open]').close();");time.sleep(.05)
 # Exercise a real frontend save and a subsequent scan, all in the isolated database.
 asyncjs('await showOrder();await chooseClient(1);return true;')
 js("const f=document.getElementById('order-form');f.elements.type.value='portatil';f.elements.model.value='PruebaUI1791640648104448233';f.elements.problem.value='Falla de prueba UI';f.elements.physical_condition.value='Sin golpes';f.querySelector('[name=technical_access][value=authorized]').checked=true;f.querySelector('[name=technical_access]').dispatchEvent(new Event('change',{bubbles:true}));f.elements.access_operating_system.checked=true;f.elements.access_confirmed.checked=true;f.elements.terms_accept.checked=true;wizardVisited=3;showWizardStep(3);")
 result=asyncjs("const f=document.getElementById('order-form');return validateReception(Object.fromEntries(new FormData(f)));");assert not result,result
 js("document.getElementById('order-form').requestSubmit();");time.sleep(1.5)
 assert js("return !document.getElementById('order-dialog').open"),js("return document.querySelector('#order-form .message').textContent")
 data=asyncjs("return await api('/api/orders?q=PruebaUI1791640648104448233');");assert len(data['rows'])==1,data;order=data['rows'][0]
 js("document.getElementById('receipt-dialog').close();document.getElementById('search').value="+json.dumps(order['code'])+";document.getElementById('global-search').requestSubmit();");time.sleep(.5)
 assert js("return location.hash.includes('id="+str(order['id'])+"')")
 asyncjs('await showDocumentPreview(' +str(order['id'])+ ',"thermal");return true;');time.sleep(.5)
 for attempt in range(40):
  if js("return [...document.querySelectorAll('#receipt-content button')].some(x=>x.textContent==='Imprimir en Epson de red')"):break
  time.sleep(.1)
 result=js("window.__nativeJobs=[];window.__browserPrintCalls=0;window.__originalFetch=window.fetch;window.fetch=async(url,options)=>{if(String(url).endsWith('/thermal-print')){window.__nativeJobs.push(JSON.parse(options.body));return new Response(JSON.stringify({ok:true,message:'TRABAJO SIMULADO'}),{status:200,headers:{'Content-Type':'application/json'}});}return window.__originalFetch(url,options);};document.querySelector('#receipt-content iframe').contentWindow.print=()=>window.__browserPrintCalls++;const b=[...document.querySelectorAll('#receipt-content button')].find(x=>x.textContent==='Imprimir en Epson de red');if(b)b.click();return !!b;");assert result
 time.sleep(.25);assert js("return window.__nativeJobs.length===1&&window.__browserPrintCalls===0")
 js("[...document.querySelectorAll('#receipt-content button')].find(x=>x.textContent==='Reimprimir otra copia').click();");time.sleep(.25)
 assert js("return window.__nativeJobs.length===2&&window.__nativeJobs[0].request_key!==window.__nativeJobs[1].request_key&&window.__browserPrintCalls===0")
 js("window.fetch=window.__originalFetch;document.getElementById('receipt-dialog').close();")
 logs=req(p+'/log',{'type':'browser'});assert not [x for x in logs if x['level']=='SEVERE'],logs
 assert all(not x['overflow'] and x['modalInView'] and not x['modalOverflow'] and x['closeVisible'] and x['footerVisible'] and x['openCount']<=1 for x in checks),checks
 (out/'browser-checks.json').write_text(json.dumps({'checks':checks,'ui_order_saved':True,'barcode_lookup_opened':True,'native_print_button_checked_without_physical_send':True,'logs':logs},ensure_ascii=False,indent=2));print('PASS',len(checks),'viewport checks; real frontend save and scanned-code lookup')
finally:req(p,method='DELETE')
