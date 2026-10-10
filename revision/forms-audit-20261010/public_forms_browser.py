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
 for width,height in [(1920,1080),(1440,1000),(1366,900),(1024,900),(768,1024),(390,844),(320,740)]:
  req(p+'/window/rect',{'width':width,'height':height})
  for name,url in [('login','/login'),('forgot','/forgot'),('reset','/reset?token=invalido'),('booking','/citas')]:
   req(p+'/url',{'url':'http://127.0.0.1:8018'+url});time.sleep(.2);inspect(name+'-'+str(width));shot(name+'-'+str(width))
 assert all(not x['overflow'] for x in checks),checks
 logs=req(p+'/log',{'type':'browser'});assert not [x for x in logs if x['level'] in ('SEVERE','WARNING')],logs
 (out/'public-forms-checks.json').write_text(json.dumps(checks,ensure_ascii=False,indent=2));print('PASS',len(checks),'public forms viewport checks')
finally:req(p,method='DELETE')
