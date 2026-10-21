'use strict';
// Esfera de ADI en WebGL (diseño aprobado por administración el 21/10/2026): esfera de energía formada por filamentos luminosos y velos
// translúcidos, sin contorno rígido, con interior oscuro, rosado neón y magenta arriba a la derecha, violeta y azul eléctrico abajo a la
// izquierda, un anillo brillante donde los hilos se acumulan en la silueta y resplandor exterior suave. Los hilos se calculan sobre una
// esfera 3D real (cara frontal y trasera más tenue) que gira despacio: no es una imagen ni un degradado. Los estados llegan del asistente
// real: nivel del micrófono, petición en curso, amplitud de la voz que suena y conexión. Sin dependencias: un sombreador propio pesa unos
// pocos KB; una biblioteca 3D completa no se justifica para un elemento de 60 px.
(()=>{
 const VERTEX='attribute vec2 p;void main(){gl_Position=vec4(p,0.,1.);}';
 const FRAGMENT=`precision highp float;
uniform vec2 uRes,uPointer;uniform float uTime,uFlow,uLevel,uBusy,uSpeak,uDim,uPress,uShock,uSteps,uHover,uListen,uError;
float hash(vec3 p){p=fract(p*.3183099+.1);p*=17.;return fract(p.x*p.y*p.z*(p.x+p.y+p.z));}
float noise(vec3 x){vec3 i=floor(x),f=fract(x);f=f*f*(3.-2.*f);
 return mix(mix(mix(hash(i),hash(i+vec3(1,0,0)),f.x),mix(hash(i+vec3(0,1,0)),hash(i+vec3(1,1,0)),f.x),f.y),
            mix(mix(hash(i+vec3(0,0,1)),hash(i+vec3(1,0,1)),f.x),mix(hash(i+vec3(0,1,1)),hash(i+vec3(1,1,1)),f.x),f.y),f.z);}
float fbm(vec3 p){float a=.5,s=0.;for(int i=0;i<3;i++){s+=a*noise(p);p=p*2.07+vec3(1.7,9.2,3.1);a*=.5;}return s;}
mat2 rot(float a){float c=cos(a),s=sin(a);return mat2(c,-s,s,c);}
// Hilos finos: tres familias de líneas sobre un campo de ruido deformado, cada una con otra orientación, entrelazadas y en movimiento lento.
// k: grosor según la resolución (en el botón de 60 px los hilos se engrosan para que sigan viéndose; en grande son finos).
float threads(vec3 q,float t,float k){
 float w=noise(q*1.1+vec3(0.,t*.05,t*.04)),v=noise(q*.75-vec3(t*.035,0.,1.7));
 float a=1.-abs(sin((q.y*1.6+q.x*.5+w*2.4)*4.6+t*.5)),b=1.-abs(sin((q.x*1.3-q.z*.9+v*2.2)*5.2-t*.42)),c=1.-abs(sin((q.z*1.8+q.y*.7-w*2.)*3.9+t*.31));
 // Hilos largos y suaves: una línea muy fina y brillante con su propio halo tenue.
 return pow(a,70.*k)+pow(b,80.*k)*.85+pow(c,55.*k)*.7+(pow(a,9.*k)+pow(b,10.*k)*.8+pow(c,8.*k)*.6)*.16;}
// Velos: cintas anchas y translúcidas que cruzan la esfera.
float veils(vec3 q,float t){float w=noise(q*.9-vec3(t*.05,0.,t*.06)),v=noise(q*1.4+vec3(2.1,t*.04,0.));
 return smoothstep(.45,1.,.5+.5*sin(q.y*2.2+q.x*1.1+w*3.4+t*.32))*(.55+.45*v)+smoothstep(.6,1.,.5+.5*sin(q.x*1.8-q.z*1.3+v*3.+t*.26))*.5;}
// Color según la dirección: azul eléctrico y cian abajo a la izquierda; violeta; magenta y rosado neón arriba a la derecha.
vec3 palette(vec3 q,float n){
 vec3 pink=vec3(1.,.16,.66),magenta=vec3(.9,.1,.88),violet=vec3(.5,.14,1.),blue=vec3(.1,.3,1.),cyan=vec3(.2,.74,1.);
 float k=clamp(.52+.55*(q.x*.6+q.y*.72)+(n-.5)*.55,0.,1.);
 vec3 c=mix(blue,violet,smoothstep(.12,.42,k));c=mix(c,magenta,smoothstep(.38,.64,k));c=mix(c,pink,smoothstep(.6,.92,k));
 return mix(c,cyan,smoothstep(.22,0.,k)*.65);}
void main(){
 vec2 uv=(gl_FragCoord.xy*2.-uRes)/min(uRes.x,uRes.y);
 float breath=.6*sin(uTime*1.25)+.4*sin(uTime*.79+1.7);
 float thick=clamp(min(uRes.x,uRes.y)/320.,.18,1.);
 float d=length(uv),ang=atan(uv.y,uv.x);vec2 dir=uv/max(d,1e-4);  // dir: ángulo sin el salto de atan (evita una costura a la izquierda)
 // Tamaño: respira despacio, rebota al tocarla, crece un poco con la voz real de ADI y con el volumen del micrófono.
 float R=.7*(1.+breath*.016+uPress*.06+uSpeak*.05+uLevel*.035);
 // Contorno orgánico: el borde ondula con ruido y, al escuchar o hablar, con ondas discretas.
 float edge=R*(1.+.075*(fbm(vec3(cos(ang)*1.7,sin(ang)*1.7,uFlow*.11))-.5)+uLevel*.03*sin(ang*7.+uTime*9.)+uSpeak*.025*sin(ang*4.-uTime*6.));
 float live=1.-uDim*.55;
 vec3 tone=palette(vec3(uv/max(d,1e-3)*.9,0.),.5);
 float out_=max(d-edge,0.);
 // Resplandor exterior suave (más rosado al escuchar y al hablar) y flecos de filamentos que se escapan del borde.
 float glow=exp(-out_*8.5)*(.42+.12*breath+uHover*.15+uListen*(.18+uLevel*.5)+uSpeak*.55+uBusy*.12)*live;
 vec3 col=mix(tone,vec3(1.,.3,.75),.35+uListen*.25)*glow*.55;float alpha=glow*.5;
 // Velos ondulados que se escapan del contorno, como llamas suaves y translúcidas (no un círculo rígido).
 if(d>edge*.85&&d<edge*1.3){float fr=noise(vec3(dir*1.6,out_*5.-uFlow*.35+uFlow*.08)),inner=smoothstep(edge*.85,edge,d);
  float fl=smoothstep(.42,.92,fr)*exp(-out_*10.)*inner;col+=mix(tone,vec3(1.,.22,.7),.4)*fl*.75*live;alpha+=fl*.45*live;
  float wisp=pow(1.-abs(sin(ang*4.+out_*16.+fr*6.)),22.)*exp(-out_*15.)*inner;col+=tone*wisp*.55*live;alpha+=wisp*.3*live;}
 // Onda al tocarla.
 if(uShock>0.){float ring=exp(-pow((d-edge-(1.-uShock)*.28)*26.,2.))*uShock*.45;col+=tone*ring;alpha+=ring*.6;}
 if(d<edge){
  float z=sqrt(max(edge*edge-d*d,0.));
  vec3 f=vec3(uv,z)/edge,b=vec3(uv,-z)/edge;
  // Giro lento de la esfera (sigue levemente al cursor): los hilos de la cara frontal y la trasera se cruzan y dan profundidad.
  float yaw=uFlow*.13+uPointer.x*(.35+uHover*.25),pitch=.3*sin(uTime*.06)+uPointer.y*(.25+uHover*.2);
  f.xz*=rot(yaw);f.yz*=rot(pitch);b.xz*=rot(yaw);b.yz*=rot(pitch);
  float rim=1.-z/edge,shell=pow(rim,1.7);
  float n=fbm(f*1.3+uFlow*.04);
  vec3 cf=palette(vec3(uv/edge,0.),n);
  float energy=1.+uSpeak*.9+uLevel*.8+uBusy*.25;
  float tf=threads(f,uFlow,thick),vf=veils(f,uFlow);
  // Interior oscuro, violeta casi negro, con la luz de los filamentos encima.
  vec3 c=mix(vec3(.035,.01,.08),vec3(.09,.02,.17),n)*(1.-rim*.3);
  c+=cf*(tf*(.55+1.7*shell)+vf*(.34+.75*shell))*energy;
  if(uSteps>5.5){float tb=threads(b,uFlow,thick),vb=veils(b,uFlow);c+=palette(vec3(-uv/edge,0.)*.7,n)*(tb*.5+vb*.22)*.55*energy;}
  // Anillo luminoso donde los hilos se acumulan en la silueta, con destellos blanco-rosados más intensos a la derecha.
  float band=exp(-pow((d/edge-.94)*8.,2.))*(.55+.7*fbm(vec3(dir*1.3,uFlow*.18+1.3)));
  c+=mix(cf,vec3(1.,.75,.95),.18)*band*(.85+uSpeak*.6+uListen*uLevel*.6);
  // Hilos que rodean el contorno, entrelazados con los demás.
  float circ=pow(1.-abs(sin(d/edge*36.+n*7.+noise(vec3(dir*1.5,uFlow*.1))*5.)),26.)*smoothstep(.6,.97,d/edge);
  c+=mix(cf,vec3(1.,.7,.95),.2)*circ*.75*energy;
  // Destellos: blanco-rosado arriba a la derecha y cian-blanco abajo a la izquierda, donde la luz se concentra en el borde.
  c+=vec3(1.,.72,.92)*band*smoothstep(.15,.95,(uv.x*.8+uv.y*.6)/edge)*.9;
  c+=vec3(.55,.9,1.)*band*smoothstep(.25,.95,-(uv.x*.75+uv.y*.65)/edge)*.7;
  c+=vec3(1.,.8,.95)*pow(min(tf,1.),3.)*shell*(.3+.35*smoothstep(-.2,.9,uv.x));
  // Escuchando: ondas que nacen en el borde y siguen el volumen real del micrófono.
  c+=cf*uListen*pow(.5+.5*sin(d/edge*26.-uTime*6.),6.)*(.18+uLevel*1.2)*rim;
  // Pensando: corrientes que se reorganizan girando alrededor del núcleo.
  c+=palette(f,n)*uBusy*pow(.5+.5*sin(ang*3.-uFlow*1.7+d/edge*9.+n*4.),4.)*smoothstep(.1,.6,d/edge)*(1.-shell)*.7;
  // Centro más oscuro y profundo; el color se concentra hacia el contorno, como en el diseño aprobado.
  c*=mix(.62,1.,smoothstep(.05,.75,rim))*live;
  float a=mix(.84,1.,rim)*smoothstep(edge,edge*.94,d);
  col=mix(col,c,a);alpha=mix(alpha,1.,a);
 }
 // Error: indicación discreta (tono apagado y rojizo), sin parpadeos fuertes.
 col=mix(col,vec3(dot(col,vec3(.3,.5,.2)))*vec3(1.,.55,.55),uError*.5);
 col=mix(col,vec3(dot(col,vec3(.3,.5,.2)))*vec3(.85,.8,.9),uDim*.6);
 col=col/(1.+col*.45);
 alpha=clamp(max(alpha,max(col.r,max(col.g,col.b))),0.,1.);
 gl_FragColor=vec4(col,alpha);
}`;
 function mount(host,read){
  // Interruptor de diagnóstico guardado en el navegador: «on» fuerza el modo 3D aunque el dibujo sea por software; «off» lo desactiva.
  let choice='';try{choice=localStorage.getItem('ordenes-pro:adi-3d')||'';}catch{}
  if(choice==='off')return null;if(choice==='on')window.__adiForceGL=true;
  const canvas=document.createElement('canvas');canvas.className='adi-orb-gl';canvas.setAttribute('aria-hidden','true');
  const options={alpha:true,premultipliedAlpha:true,antialias:false,depth:false,stencil:false,powerPreference:'low-power',failIfMajorPerformanceCaveat:!window.__adiForceGL};
  let gl=null;try{gl=canvas.getContext('webgl',options)||canvas.getContext('experimental-webgl',options);}catch{}
  // Sin aceleración gráfica real (dibujo por software) no se usa WebGL: queda la esfera CSS, que no carga el procesador.
  if(!gl)return null;
  if(!window.__adiForceGL){let renderer='';try{const info=gl.getExtension('WEBGL_debug_renderer_info');renderer=String(info?gl.getParameter(info.UNMASKED_RENDERER_WEBGL):gl.getParameter(gl.RENDERER));}catch{}
   if(/swiftshader|llvmpipe|softpipe|software|basic render/i.test(renderer)){try{gl.getExtension('WEBGL_lose_context')?.loseContext();}catch{}return null;}}
  const compile=(type,source)=>{const shader=gl.createShader(type);gl.shaderSource(shader,source);gl.compileShader(shader);if(!gl.getShaderParameter(shader,gl.COMPILE_STATUS)){gl.deleteShader(shader);return null;}return shader;};
  let program=null,buffer=null,uniforms={},frame=0,alive=true,started=performance.now();
  function build(){const vs=compile(gl.VERTEX_SHADER,VERTEX),fs=compile(gl.FRAGMENT_SHADER,FRAGMENT);if(!vs||!fs)return false;
   program=gl.createProgram();gl.attachShader(program,vs);gl.attachShader(program,fs);gl.linkProgram(program);gl.deleteShader(vs);gl.deleteShader(fs);if(!gl.getProgramParameter(program,gl.LINK_STATUS))return false;
   buffer=gl.createBuffer();gl.bindBuffer(gl.ARRAY_BUFFER,buffer);gl.bufferData(gl.ARRAY_BUFFER,new Float32Array([-1,-1,1,-1,-1,1,1,1]),gl.STATIC_DRAW);
   gl.useProgram(program);const at=gl.getAttribLocation(program,'p');gl.enableVertexAttribArray(at);gl.vertexAttribPointer(at,2,gl.FLOAT,false,0,0);
   for(const name of ['uRes','uTime','uFlow','uLevel','uBusy','uSpeak','uDim','uPress','uSteps','uPointer','uShock','uHover','uListen','uError'])uniforms[name]=gl.getUniformLocation(program,name);
   gl.disable(gl.DEPTH_TEST);gl.clearColor(0,0,0,0);return true;}
  if(!build())return null;
  host.append(canvas);
  // Calidad adaptable: menos resolución y menos pasos de trazado en teléfonos y equipos modestos; se reduce más si el dibujo va lento.
  const modest=(navigator.hardwareConcurrency&&navigator.hardwareConcurrency<=4)||(navigator.deviceMemory&&navigator.deviceMemory<=4)||matchMedia('(max-width:860px)').matches;
  let quality=modest?.8:1,steps=modest?6:9,slow=0;
  const still=matchMedia('(prefers-reduced-motion:reduce)');
  function resize(){const box=canvas.getBoundingClientRect(),ratio=Math.min(window.devicePixelRatio||1,2)*quality,width=Math.max(48,Math.round(box.width*ratio)),height=Math.max(48,Math.round(box.height*ratio));if(canvas.width!==width||canvas.height!==height){canvas.width=width;canvas.height=height;}gl.viewport(0,0,canvas.width,canvas.height);}
  // Valores suavizados: los estados entran y salen con transición, sin saltos.
  const mirrors=new Set();
  function mirror(target){const copy=document.createElement('canvas');copy.className='adi-orb-gl adi-orb-mirror';copy.setAttribute('aria-hidden','true');const context=copy.getContext('2d');if(!context)return null;target.append(copy);const entry={canvas:copy,context};mirrors.add(entry);lastDraw=0;schedule();return{destroy(){mirrors.delete(entry);copy.remove();}};}
  const smooth={level:0,busy:0,speak:0,dim:0,px:0,py:0,hover:0,listen:0,error:0};let last=performance.now(),lastDraw=0,flow=0;
  function draw(now){
   const state=read(),step=Math.min(.1,(now-last)/1000);last=now;
   const ease=(key,target,speed)=>{smooth[key]+=(target-smooth[key])*Math.min(1,step*speed);};
   ease('level',state.level||0,14);ease('px',state.px||0,3);ease('py',state.py||0,3);ease('hover',state.hover||state.attend?1:0,4);ease('busy',state.busy?1:0,3.5);ease('dim',state.dim?1:0,3);ease('listen',state.listening?1:0,5);ease('error',state.error?1:0,6);
   // Hablando: envolvente que sube con cada palabra que informa el motor de voz y decae entre ellas.
   const sinceBeat=(now-(state.beatAt||0))/1000,envelope=!state.speaking?0:state.voice!=null?.14+state.voice*.9:Math.max(.35,Math.exp(-sinceBeat*5.5));ease('speak',envelope,state.voice!=null?20:16);
   // Fase del flujo de los filamentos: se integra aquí para que acelerar al pensar, escuchar o hablar nunca produzca saltos.
   if(!(still.matches||state.still))flow+=step*(.55+smooth.busy*1.9+smooth.speak*.7+smooth.listen*.35+smooth.level*.9);
   const sincePress=(now-(state.pressAt||-1e9))/1000,press=sincePress<1.2?Math.exp(-sincePress*5.2)*Math.cos(sincePress*17):0;
   resize();gl.clear(gl.COLOR_BUFFER_BIT);gl.useProgram(program);
   gl.uniform2f(uniforms.uRes,canvas.width,canvas.height);gl.uniform1f(uniforms.uTime,(still.matches||state.still)?12:(now-started)/1000);
   gl.uniform1f(uniforms.uFlow,flow||8.);gl.uniform1f(uniforms.uLevel,smooth.level);gl.uniform1f(uniforms.uBusy,smooth.busy);gl.uniform1f(uniforms.uSpeak,smooth.speak);gl.uniform1f(uniforms.uDim,smooth.dim);gl.uniform1f(uniforms.uPress,press);gl.uniform1f(uniforms.uShock,sincePress<.9?1-sincePress/.9:0);gl.uniform2f(uniforms.uPointer,smooth.px,smooth.py);gl.uniform1f(uniforms.uHover,smooth.hover);gl.uniform1f(uniforms.uListen,smooth.listen);gl.uniform1f(uniforms.uError,smooth.error);gl.uniform1f(uniforms.uSteps,steps);
   gl.drawArrays(gl.TRIANGLE_STRIP,0,4);
   for(const copy of mirrors){const box=copy.canvas.getBoundingClientRect(),ratio=Math.min(window.devicePixelRatio||1,2),width=Math.max(24,Math.round(box.width*ratio)),height=Math.max(24,Math.round(box.height*ratio));if(copy.canvas.width!==width||copy.canvas.height!==height){copy.canvas.width=width;copy.canvas.height=height;}copy.context.clearRect(0,0,width,height);copy.context.drawImage(canvas,0,0,width,height);}}
  function loop(now){
   frame=0;if(!alive)return;
   const state=read(),active=state.busy||state.speaking||state.listening||state.error||(now-(state.pressAt||-1e9))<1300;
   // Con «movimiento reducido» apenas se redibuja; en reposo se limita a unos 30 cuadros por segundo para ahorrar batería y sube al reaccionar.
   const gap=(still.matches||state.still)?(active?120:600):(active?0:30);
   if(now-lastDraw>=gap){const before=performance.now();draw(now);lastDraw=now;
    const cost=performance.now()-before;slow=cost>9?slow+1:Math.max(0,slow-1);if(slow>40&&(steps>5||quality>.6)){steps=Math.max(5,steps-2);quality=Math.max(.6,quality-.15);slow=0;}}
   schedule();}
  let shown=true;const schedule=()=>{if(alive&&!frame&&!document.hidden&&(shown||mirrors.size))frame=requestAnimationFrame(loop);};
  const watch='IntersectionObserver' in window?new IntersectionObserver(entries=>{shown=entries[entries.length-1].isIntersecting;if(shown){last=performance.now();schedule();}}):null;watch?.observe(canvas);
  const onVisible=()=>{if(document.hidden){if(frame){cancelAnimationFrame(frame);frame=0;}}else{last=performance.now();schedule();}};
  const onLost=event=>{event.preventDefault();if(frame){cancelAnimationFrame(frame);frame=0;}};
  const onRestored=()=>{uniforms={};if(build())schedule();};
  document.addEventListener('visibilitychange',onVisible);canvas.addEventListener('webglcontextlost',onLost);canvas.addEventListener('webglcontextrestored',onRestored);
  // Al salir de la página se detiene el dibujo y se liberan el programa, el búfer y el contexto gráfico.
  function destroy(){if(!alive)return;alive=false;if(frame)cancelAnimationFrame(frame);frame=0;document.removeEventListener('visibilitychange',onVisible);watch?.disconnect();canvas.removeEventListener('webglcontextlost',onLost);canvas.removeEventListener('webglcontextrestored',onRestored);removeEventListener('pagehide',destroy);
   for(const copy of mirrors)copy.canvas.remove();mirrors.clear();try{gl.deleteBuffer(buffer);gl.deleteProgram(program);gl.getExtension('WEBGL_lose_context')?.loseContext();}catch{}canvas.remove();}
  addEventListener('pagehide',destroy);
  schedule();
  return {destroy,canvas,mirror,info:()=>({steps,quality,width:canvas.width,height:canvas.height,running:!!frame,mirrors:mirrors.size,shown,speak:smooth.speak,hover:smooth.hover})};
 }
 window.AdiOrb={mount};
})();
