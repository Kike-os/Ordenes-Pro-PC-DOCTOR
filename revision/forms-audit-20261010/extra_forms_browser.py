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
 asyncjs("return await api('/api/login',{login:'demo',password:'contraseña-segura-de-prueba'});")
 req(p+'/url',{'url':'http://127.0.0.1:8018/'});time.sleep(.6)
 for width,height in [(1920,1080),(1440,1000),(1366,900),(1024,900),(768,1024),(390,844),(320,740)]:
  req(p+'/window/rect',{'width':width,'height':height})
  for name,script in [('edit-client','await showClientForm(1);'),('edit-order-budget','await openOrderEditor(1,true);'),('technical-followup','await addOrderFollowUp(1);'),('device','await openRecord("devices");'),('maintenance-reschedule','rescheduleMaintenance({id:1,due_date:"2026-12-01"});')]:
   result=asyncjs(script+'return true;');assert result is True,(name,result);time.sleep(.08);inspect(name+'-'+str(width));shot(name+'-'+str(width));js("document.querySelector('dialog[open]').close();");time.sleep(.03)
  for module in ['settings','appointments','adi']:
   js('go('+json.dumps(module)+');');time.sleep(.35);inspect(module+'-'+str(width));shot(module+'-'+str(width))
  js("go('home');");time.sleep(.1)
 asyncjs('await showOrder();await chooseClient(1);return true;')
 js("document.getElementById('order-model').value='BORRADOR';")
 asyncjs('await showClientForm(null,true);return true;');assert js("return document.querySelectorAll('dialog[open]').length")==1
 js("requestCloseClient();");time.sleep(.1)
 assert js("return document.getElementById('order-dialog').open&&document.getElementById('order-model').value==='BORRADOR'")
 js("document.getElementById('order-dialog').close();")
 logs=req(p+'/log',{'type':'browser'});assert not logs,logs
 assert all(not x['overflow'] and x['modalInView'] and not x['modalOverflow'] and x['closeVisible'] and x['footerVisible'] and x['openCount']<=1 for x in checks),checks
 (out/'additional-forms-checks.json').write_text(json.dumps({'checks':checks,'draft_preserved':True,'console_errors':logs},ensure_ascii=False,indent=2));print('PASS',len(checks),'additional form viewport checks and nested draft preservation',flush=True)
finally:req(p,method='DELETE')
