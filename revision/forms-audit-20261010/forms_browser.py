import urllib.request,urllib.error,json,base64,time
from pathlib import Path
out=Path('/home/admin-red/Work/ordenes-pro/revision/forms-audit-20261010');out.mkdir(exist_ok=True)
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
 req(p+'/url',{'url':'http://127.0.0.1:8018/'})
 print('login',asyncjs("return await api('/api/login',{login:'demo',password:'contraseña-segura-de-prueba'});"),flush=True)
 req(p+'/url',{'url':'http://127.0.0.1:8018/'});time.sleep(.8)
 print('bootstrap',js("return {message:document.getElementById('dashboard-message').textContent,quick:typeof showClientForm,fields:!!document.getElementById('client-form')};"),flush=True)
 for width,height in [(1920,1080),(1440,1000),(1366,900),(1024,900),(768,1024),(390,844),(320,740)]:
  req(p+'/window/rect',{'width':width,'height':height});time.sleep(.15)
  inspect('dashboard-'+str(width));shot('dashboard-'+str(width))
  result=asyncjs('await showClientForm();return true;');print('client open',width,result,flush=True);time.sleep(.15)
  assert js("return document.getElementById('client-form').elements.document_type.value")=='cedula';inspect('client-natural-'+str(width));shot('client-natural-'+str(width))
  js("const f=document.getElementById('client-form');f.elements.client_type.value='empresa';f.elements.client_type.dispatchEvent(new Event('change'));f.elements.client.value='Empresa de prueba';f.elements.identification.value='1790016919001';f.elements.phone.value='0991234567';showClientStep(1);")
  inspect('client-location-'+str(width));shot('client-location-'+str(width))
  js('showClientStep(2);');inspect('client-summary-'+str(width));shot('client-summary-'+str(width))
  js("document.getElementById('client-dialog').close();");time.sleep(.05)
  print('order open',asyncjs('await showOrder();return true;'),flush=True)
  inspect('order-client-'+str(width));shot('order-client-'+str(width))
  checks.append(js("return {label:'next-requires-client',width:innerWidth,disabled:document.getElementById('wizard-next').disabled};"))
  print('choose',asyncjs("await chooseClient(1);wizardVisited=3;showWizardStep(1);return true;"),flush=True)
  inspect('order-equipment-'+str(width));shot('order-equipment-'+str(width))
  js('showWizardStep(2);');inspect('order-reception-'+str(width));shot('order-reception-'+str(width))
  js('showWizardStep(3);');inspect('order-summary-'+str(width));shot('order-summary-'+str(width))
  js("document.getElementById('order-dialog').close();resetReception();")
 logs=req(p+'/log',{'type':'browser'});assert not logs,logs;assert all(x.get('disabled',True) and not x.get('overflow',False) and x.get('modalInView',True) and not x.get('modalOverflow',False) and x.get('closeVisible',True) and x.get('footerVisible',True) and x.get('openCount',0)<=1 for x in checks),checks;print('browser logs',logs,flush=True)
 (out/'viewport-checks.json').write_text(json.dumps(checks,ensure_ascii=False,indent=2))
 print('CHECKS',json.dumps(checks,ensure_ascii=False),flush=True)
finally:req(p,method='DELETE')
