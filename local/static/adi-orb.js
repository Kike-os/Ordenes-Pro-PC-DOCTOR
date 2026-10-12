'use strict';
// Esfera 3D de ADI en WebGL. No es una imagen ni un degradado: cada píxel se calcula trazando un rayo contra una esfera de cristal
// (normal, reflexión de entorno, efecto Fresnel y refracción) y recorriendo su interior, donde giran una nube de energía, un núcleo
// y partículas luminosas. Los estados llegan del asistente real: nivel del micrófono, petición en curso, voz y conexión.
// Sin dependencias (un sombreador propio pesa unos pocos KB; una biblioteca 3D completa no se justifica para un elemento de 62 px).
(()=>{
 const VERTEX='attribute vec2 p;void main(){gl_Position=vec4(p,0.,1.);}';
 const FRAGMENT=`precision highp float;
uniform vec2 uRes,uPointer;uniform float uTime,uLevel,uBusy,uSpeak,uDim,uPress,uShock,uSteps;
const float R=.56;
float hash(vec3 p){p=fract(p*.3183099+.1);p*=17.;return fract(p.x*p.y*p.z*(p.x+p.y+p.z));}
float noise(vec3 x){vec3 i=floor(x),f=fract(x);f=f*f*(3.-2.*f);
 return mix(mix(mix(hash(i),hash(i+vec3(1,0,0)),f.x),mix(hash(i+vec3(0,1,0)),hash(i+vec3(1,1,0)),f.x),f.y),
            mix(mix(hash(i+vec3(0,0,1)),hash(i+vec3(1,0,1)),f.x),mix(hash(i+vec3(0,1,1)),hash(i+vec3(1,1,1)),f.x),f.y),f.z);}
float fbm(vec3 p){float a=.5,s=0.;for(int i=0;i<3;i++){s+=a*noise(p);p=p*2.03+7.1;a*=.5;}return s;}
mat2 rot(float a){float c=cos(a),s=sin(a);return mat2(c,-s,s,c);}
// Entorno de estudio que la superficie refleja: caja de luz superior, luz lateral y relleno. Deriva despacio y sigue levemente al cursor.
vec3 env(vec3 d){d.xz*=rot(uTime*.06+uPointer.x*.35);d.yz*=rot(uPointer.y*.25+.08*sin(uTime*.23));
 float top=smoothstep(.3,.95,d.y),box=smoothstep(.5,.9,d.y)*smoothstep(.8,.05,abs(d.x+.22)),side=smoothstep(.55,1.,d.x)*smoothstep(.65,-.25,abs(d.y-.08));
 vec3 c=mix(vec3(.15,.03,.11),vec3(.96,.58,.80),top*.72);c+=vec3(1.,.97,.99)*box*1.6+vec3(1.,.82,.93)*side*.5;
 c+=vec3(.74,.36,.92)*smoothstep(-.15,-.9,d.y)*.24;return c;}
void main(){
 vec2 uv=(gl_FragCoord.xy*2.-uRes)/min(uRes.x,uRes.y);
 // Levitación casi imperceptible y respiración asimétrica (dos ritmos que nunca coinciden).
 float breath=.6*sin(uTime*.83)+.4*sin(uTime*.31+1.7);
 uv.y-=.012*sin(uTime*.57)+.006*sin(uTime*.19+.6);uv.x-=.004*sin(uTime*.41+2.);
 float ang=atan(uv.y,uv.x);
 // El radio cambia de verdad: rebote elástico al toque, ondas de superficie y deformación suave al hablar o escuchar.
 float ripple=.004*sin(ang*4.+uTime*1.1)+.003*sin(ang*7.-uTime*.8+1.3);
 float rad=R*(1.+breath*.012+uPress*.07+ripple+uSpeak*(.022*sin(ang*3.+uTime*7.)+.014*sin(ang*5.-uTime*5.3))+uLevel*.02*sin(ang*6.+uTime*11.));
 float d=length(uv);
 vec3 pink=vec3(1.,.58,.81),pearl=vec3(1.,.88,.94),magenta=vec3(.86,.26,.61);
 float live=1.-uDim*.6;
 // Halo volumétrico discreto y onda expansiva al toque.
 float glow=exp(-(max(d-rad,0.))*8.)*(.19+.07*breath+uSpeak*.22+uLevel*.26+max(uPress,0.)*.25)*live;
 float ring=uShock>0.?exp(-pow((d-rad-(1.-uShock)*.34)*26.,2.))*uShock*.55:0.;
 vec3 col=pink*(glow+ring);float alpha=glow*.85+ring*.8;
 if(d<rad){
  vec3 n=vec3(uv/rad,0.);n.z=sqrt(max(1.-dot(n.xy,n.xy),0.));
  // Pequeñas ondas que recorren la superficie: perturban la normal y, con ella, los reflejos.
  vec3 sp=n*3.2+vec3(uTime*.17,-uTime*.11,uTime*.07);
  n=normalize(n+(vec3(noise(sp+vec3(.31,0.,0.)),noise(sp+vec3(0.,.31,0.)),0.)-.5)*(.085+uSpeak*.10+uLevel*.08));
  vec3 v=vec3(0.,0.,1.);
  float fres=pow(1.-max(n.z,0.),2.6);
  // Interior: el rayo se refracta al entrar en el cristal y recorre la esfera acumulando luz.
  vec3 rd=refract(-v,n,1./1.33);vec3 ro=vec3(uv/rad,sqrt(max(1.-dot(uv,uv)/(rad*rad),0.)));
  float tmax=max(-2.*dot(ro,rd),.05);
  vec3 acc=vec3(0.);float dens=0.;
  // Giros con frecuencias que no se repiten juntas: el flujo cambia de dirección sin ciclo evidente.
  float a1=uTime*.21+.6*sin(uTime*.047),a2=uTime*.13*sin(uTime*.031+1.)+uTime*.05,a3=.9*sin(uTime*.071)+uBusy*uTime*.9;
  vec3 centre=vec3(uPointer*.10,0.)+vec3(.03*sin(uTime*.37),.03*sin(uTime*.29+1.),.02*sin(uTime*.23));
  float core=.24+.03*breath+uLevel*.17*(.6+.4*sin(uTime*29.))+uSpeak*.09;
  float orbit=mix(.60,.18,uBusy),spin=uTime*(.45+uBusy*2.8);
  for(int i=0;i<10;i++){
   if(float(i)>=uSteps)break;
   float t=(float(i)+.5)/uSteps*tmax;vec3 q=ro+rd*t;
   vec3 w=q-centre;float r=length(w);
   w.xz*=rot(a1);w.xy*=rot(a2);w.yz*=rot(a3);
   // Filamentos de energía: crestas finas de ruido deformado que circulan dentro del cristal.
   vec3 warp=w*2.2+vec3(fbm(w*1.4+uTime*.09),fbm(w*1.4-uTime*.07+3.),0.)*1.3;
   float ridge=1.-abs(2.*noise(warp+vec3(0.,0.,uTime*.11))-1.);
   float fil=pow(ridge,mix(9.,5.,uBusy))*(1.-smoothstep(mix(.55,.38,uBusy),1.,r))*(.75+uBusy*1.3+uSpeak*.5);
   float cloud=smoothstep(.5,.95,fbm(w*1.7+vec3(0.,uTime*.08,0.)))*(1.-smoothstep(.2,.9,r));
   // Núcleo que cambia sutilmente de forma: su radio depende de la dirección.
   float shape=core*(1.+.22*noise(normalize(w+.001)*2.4+uTime*.33)-.11);
   float nucleus=exp(-r*r/(shape*shape))*1.55;
   float wave=uSpeak*smoothstep(0.,.9,sin(r*16.-uTime*9.)*.5+.5)*(1.-r)*.9;
   float sparks=0.;
   for(int k=0;k<5;k++){float fk=float(k);vec3 c=vec3(cos(spin*(1.+fk*.17)+fk*2.1),sin(spin*.7+fk*1.3)*.55,sin(spin*(1.+fk*.17)+fk*2.1))*orbit*(.75+.25*sin(fk*3.7));
    vec3 e=q-centre-c;sparks+=.0014/(dot(e,e)+.0014);}
   vec3 tint=mix(magenta,pearl,clamp(nucleus*.7+cloud*.5+fil*.6,0.,1.));
   acc+=(tint*(cloud*.42+wave)+mix(pink,vec3(1.),.55)*fil*1.25+pearl*nucleus*.8+vec3(1.,.95,.98)*sparks*.85)*(1.-dens);
   dens+=(cloud*.09+nucleus*.05+fil*.03);
  }
  acc*=tmax/uSteps*2.1;
  vec3 body=mix(vec3(.44,.07,.29),vec3(1.,.58,.82),smoothstep(.2,1.9,tmax));
  vec3 inner=body*.70+acc;
  // Superficie: reflejo del entorno, dos brillos especulares (el principal sigue al cursor) y filo de contraluz.
  vec3 L=normalize(vec3(-.55+uPointer.x*.35,.62+uPointer.y*.3,.56)),L2=normalize(vec3(.62,-.5,.6));
  vec3 refl=env(reflect(-v,n));
  float spec=pow(max(dot(reflect(-L,n),v),0.),72.)*1.5+pow(max(dot(reflect(-L2,n),v),0.),24.)*.22;
  float wrap=.62+.38*dot(n,L);
  col=inner*wrap*live+refl*(.17+fres*.9)*live+vec3(1.)*spec*live+magenta*fres*.22;
  col+=pearl*pow(max(dot(n,-L)*.5+.5,0.),5.)*(1.-fres)*.30*live;
  // Resplandor moderado de las zonas más luminosas, sin quemar el detalle.
  col+=pink*smoothstep(.75,1.6,dot(acc,vec3(.33)))*.12;
  col=mix(col,vec3(dot(col,vec3(.3,.5,.2)))*vec3(.82,.74,.80),uDim*.75);
  float edge=smoothstep(rad,rad-.018,d);
  alpha=mix(alpha,1.,edge);col=mix(pink*(glow+ring),col,edge);
 }
 gl_FragColor=vec4(col*alpha,alpha);
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
   for(const name of ['uRes','uTime','uLevel','uBusy','uSpeak','uDim','uPress','uSteps','uPointer','uShock'])uniforms[name]=gl.getUniformLocation(program,name);
   gl.disable(gl.DEPTH_TEST);gl.clearColor(0,0,0,0);return true;}
  if(!build())return null;
  host.append(canvas);
  // Calidad adaptable: menos resolución y menos pasos de trazado en teléfonos y equipos modestos; se reduce más si el dibujo va lento.
  const modest=(navigator.hardwareConcurrency&&navigator.hardwareConcurrency<=4)||(navigator.deviceMemory&&navigator.deviceMemory<=4)||matchMedia('(max-width:860px)').matches;
  let quality=modest?.8:1,steps=modest?6:9,slow=0;
  const still=matchMedia('(prefers-reduced-motion:reduce)');
  function resize(){const box=canvas.getBoundingClientRect(),ratio=Math.min(window.devicePixelRatio||1,2)*quality,width=Math.max(48,Math.round(box.width*ratio)),height=Math.max(48,Math.round(box.height*ratio));if(canvas.width!==width||canvas.height!==height){canvas.width=width;canvas.height=height;}gl.viewport(0,0,canvas.width,canvas.height);}
  // Valores suavizados: los estados entran y salen con transición, sin saltos.
  const smooth={level:0,busy:0,speak:0,dim:0,px:0,py:0};let last=performance.now(),lastDraw=0;
  function draw(now){
   const state=read(),step=Math.min(.1,(now-last)/1000);last=now;
   const ease=(key,target,speed)=>{smooth[key]+=(target-smooth[key])*Math.min(1,step*speed);};
   ease('level',state.level||0,14);ease('px',state.px||0,3);ease('py',state.py||0,3);ease('busy',state.busy?1:0,3.5);ease('dim',state.dim?1:0,3);
   // Hablando: envolvente que sube con cada palabra que informa el motor de voz y decae entre ellas.
   const sinceBeat=(now-(state.beatAt||0))/1000,envelope=state.speaking?Math.max(.35,Math.exp(-sinceBeat*5.5)):0;ease('speak',envelope,16);
   const sincePress=(now-(state.pressAt||-1e9))/1000,press=sincePress<1.2?Math.exp(-sincePress*5.2)*Math.cos(sincePress*17):0;
   resize();gl.clear(gl.COLOR_BUFFER_BIT);gl.useProgram(program);
   gl.uniform2f(uniforms.uRes,canvas.width,canvas.height);gl.uniform1f(uniforms.uTime,(still.matches||state.still)?12:(now-started)/1000);
   gl.uniform1f(uniforms.uLevel,smooth.level);gl.uniform1f(uniforms.uBusy,smooth.busy);gl.uniform1f(uniforms.uSpeak,smooth.speak);gl.uniform1f(uniforms.uDim,smooth.dim);gl.uniform1f(uniforms.uPress,press);gl.uniform1f(uniforms.uShock,sincePress<.9?1-sincePress/.9:0);gl.uniform2f(uniforms.uPointer,smooth.px,smooth.py);gl.uniform1f(uniforms.uSteps,steps);
   gl.drawArrays(gl.TRIANGLE_STRIP,0,4);}
  function loop(now){
   frame=0;if(!alive)return;
   const state=read(),active=state.busy||state.speaking||state.listening||(now-(state.pressAt||-1e9))<1300;
   // Con «movimiento reducido» apenas se redibuja; en reposo se limita a unos 30 cuadros por segundo para ahorrar batería y sube al reaccionar.
   const gap=(still.matches||state.still)?(active?120:600):(active?0:30);
   if(now-lastDraw>=gap){const before=performance.now();draw(now);lastDraw=now;
    const cost=performance.now()-before;slow=cost>9?slow+1:Math.max(0,slow-1);if(slow>40&&(steps>5||quality>.6)){steps=Math.max(5,steps-2);quality=Math.max(.6,quality-.15);slow=0;}}
   schedule();}
  const schedule=()=>{if(alive&&!frame&&!document.hidden)frame=requestAnimationFrame(loop);};
  const onVisible=()=>{if(document.hidden){if(frame){cancelAnimationFrame(frame);frame=0;}}else{last=performance.now();schedule();}};
  const onLost=event=>{event.preventDefault();if(frame){cancelAnimationFrame(frame);frame=0;}};
  const onRestored=()=>{uniforms={};if(build())schedule();};
  document.addEventListener('visibilitychange',onVisible);canvas.addEventListener('webglcontextlost',onLost);canvas.addEventListener('webglcontextrestored',onRestored);
  // Al salir de la página se detiene el dibujo y se liberan el programa, el búfer y el contexto gráfico.
  function destroy(){if(!alive)return;alive=false;if(frame)cancelAnimationFrame(frame);frame=0;document.removeEventListener('visibilitychange',onVisible);canvas.removeEventListener('webglcontextlost',onLost);canvas.removeEventListener('webglcontextrestored',onRestored);removeEventListener('pagehide',destroy);
   try{gl.deleteBuffer(buffer);gl.deleteProgram(program);gl.getExtension('WEBGL_lose_context')?.loseContext();}catch{}canvas.remove();}
  addEventListener('pagehide',destroy);
  schedule();
  return {destroy,canvas,info:()=>({steps,quality,width:canvas.width,height:canvas.height,running:!!frame})};
 }
 window.AdiOrb={mount};
})();
