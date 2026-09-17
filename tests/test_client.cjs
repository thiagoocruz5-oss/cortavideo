const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname,'../static/app.js'),'utf8');
const requestSource = source.slice(source.indexOf('async function request('),source.indexOf('async function poll'));
function client(response) {
  const context = vm.createContext({AbortSignal,fetch:async()=>response});
  vm.runInContext(requestSource,context);
  return context.request;
}
test('valid JSON succeeds', async()=>assert.equal((await client({ok:true,status:200,text:async()=>' {"id":"ok"} '})('/')).id,'ok'));
for (const body of ['', '<html>Bad gateway</html>', 'null']) {
  test(`invalid body ${body}`, async()=>assert.rejects(client({ok:false,status:502,text:async()=>body})('/'), /servidor/));
}
test('busy response keeps useful message', async()=>assert.rejects(client({ok:false,status:429,text:async()=>' {"message":"Aguarde"} '})('/'), /Aguarde/));
test('connection interruption handled', async()=>assert.rejects(client({text:async()=>{throw Error('network');}})('/'), /conexão/));

// Exercita os handlers completos com elementos de DOM controlados.
function editor(start='243,73', end='293,26') {
  const elements = new Map();
  const buttons = [];
  function element(id) {
    if (!elements.has(id)) elements.set(id, {value:'', textContent:'', hidden:false, disabled:false,
      classList:{add(){},remove(){},toggle(){}},style:{}, dataset:{},
      append(){},replaceChildren(){},setAttribute(){},addEventListener(){},pause(){this.paused=true;},paused:true,currentTime:0});
    const item=elements.get(id);
    if (!Object.getOwnPropertyDescriptor(item,'value').set) {
      let value=item.value;
      Object.defineProperty(item,'value',{get:()=>value,set:next=>{value=String(next);}});
    }
    return item;
  }
  for (const id of ['start','end']) for (const delta of [-5,-1,1,5]) {
    buttons.push({dataset:{time:id,delta:String(delta)},disabled:false});
  }
  const calls=[];
  const context=vm.createContext({AbortSignal,document:{createElement:()=>({append(){},classList:{toggle(){}}}),getElementById:element,querySelectorAll:selector=>selector.includes('[data-time]')?buttons:[]},
    location:{search:''},URLSearchParams,fetch:async(url,options)=>{
      calls.push({url,options});
      const body=url==='/api/export'?{id:'exported'}:url==='/api/jobs/exported'?{status:'ready',url:'/media/done.mp4'}:{ffmpeg:true,ffprobe:true};
      return {ok:true,status:200,text:async()=>JSON.stringify(body)};
    }});
  vm.runInContext(source,context);
  vm.runInContext('job={duration:400,segments:[{}]}; current="source";',context);
  element('start').value=start; element('end').value=end; element('framing').value='80'; element('captions').checked=true;
  return {context,element,buttons,calls};
}
test('manual typing accepts comma and dot without rewriting the field',()=>{
  const {context:c,element:e}=editor();
  e('start').oninput(); assert.equal(e('start').value,'243,73'); assert.equal(e('video').currentTime,243.73);
  e('start').value='244.25'; e('start').oninput(); assert.equal(c.values().start,244.25);
  assert.match(e('duration').textContent,/49,01/); assert.equal(e('export').disabled,false);
});
test('empty and unfinished invalid text never seeks to zero or enables export',()=>{
  const {element:e}=editor(); e('video').currentTime=250;
  for(const text of ['', '-', ',', '1,2.3','Infinity','NaN','1e3']) {
    e('start').value=text; e('start').oninput(); assert.equal(e('start').value,text);
    assert.equal(e('video').currentTime,250); assert.equal(e('export').disabled,true);
  }
  e('start').value='243,'; e('start').oninput(); assert.equal(e('start').value,'243,');
  e('start').value='243,8'; e('start').oninput(); assert.equal(e('video').currentTime,243.8);
});
test('end edits update duration and show frame just before cut end',()=>{
  const {element:e}=editor('10','60'); e('end').value='59,5'; e('end').oninput();
  assert.equal(e('video').currentTime,59.45); assert.match(e('duration').textContent,/49,50/);
  assert.equal(e('download').hidden,true); assert.equal(e('finalPreview').hidden,true);
});
test('invalid boundaries and existing 30–60 second export rule are enforced',()=>{
  const {context:c}=editor();
  for(const [a,b] of [[-1,40],[350,401],[50,50],[51,50],[0,29.99],[0,60.01]]) assert.equal(c.timeState(a,b,400).valid,false);
  for(const [a,b] of [[0,30],[0,60],[350,400]]) assert.equal(c.timeState(a,b,400).valid,true);
});
test('all quick buttons use parsed decimals and update preview',()=>{
  for(const id of ['start','end']) for(const delta of [-5,-1,1,5]) {
    const {element:e,buttons}=editor('20,25','65,25');
    buttons.find(b=>b.dataset.time===id&&Number(b.dataset.delta)===delta).onclick();
    assert.equal(e(id).value,String((id==='start'?20.25:65.25)+delta).replace('.',','));
    assert.equal(e('export').disabled,false);
  }
});
test('quick controls clamp to video boundaries and cannot cross the other endpoint',()=>{
  const {context:c,element:e}=editor('0','400');
  c.stepTime('start',-5); assert.equal(c.values().start,0);
  c.stepTime('end',5); assert.equal(c.values().end,400);
  e('start').value='399'; c.stepTime('start',5); assert.equal(c.values().start,399.99);
  c.stepTime('end',-5); assert.ok(c.values().end>c.values().start);
});
test('quick controls cannot modify an export in progress',()=>{
  const {context:c,element:e}=editor(); vm.runInContext('exporting=true',c);
  c.stepTime('start',5); assert.equal(e('start').value,'243,73');
});
test('export sends numeric edited times, captions and chosen framing; restores controls',async()=>{
  const {element:e,calls,buttons}=editor();
  await e('export').onclick();
  const payload=JSON.parse(calls.find(call=>call.url==='/api/export').options.body);
  assert.deepEqual(payload,{id:'source',start:243.73,end:293.26,captions:true,position:.8});
  assert.equal(e('finalVideo').src,'/media/done.mp4'); assert.equal(e('download').hidden,false);
  assert.ok(buttons.every(b=>!b.disabled)); assert.equal(e('start').disabled,false);
});

function downloadClient(response) {
  const sourceHandler=source.slice(source.indexOf("$('download').onclick ="));
  const link={href:'/media/final.mp4?download=1',dataset:{},textContent:''};
  const clicks=[];const messages=[];
  const native={click(){clicks.push(this.href);},remove(){}};
  const context=vm.createContext({AbortSignal,fetch:async()=>{if(response instanceof Error)throw response;return response;},
    $:id=>id==='download'?link:{pause(){}},status:(text,error)=>messages.push({text,error}),
    document:{body:{append(){}},createElement:()=>native}});
  vm.runInContext(sourceHandler,context);
  return {link,clicks,messages};
}
test('download uses HEAD then native disk download without buffering MP4',async()=>{
  const {link,clicks,messages}=downloadClient({ok:true,status:200,headers:{get:key=>key==='Content-Type'?'video/mp4':'12345'}});
  await link.onclick({preventDefault(){}});
  assert.deepEqual(clicks,['/media/final.mp4?download=1']);
  assert.equal(link.textContent,'↓ Baixar vídeo');assert.match(messages[0].text,/Retomar/);
});
for(const response of [{ok:false,status:410},{ok:false,status:503},new TypeError('network'),Object.assign(new Error('timeout'),{name:'TimeoutError'})]) {
  test(`download failure ${response.status||response.name} is visible and retryable by user`,async()=>{
    const {link,clicks,messages}=downloadClient(response);
    await link.onclick({preventDefault(){}});
    assert.equal(clicks.length,0);assert.equal(messages[0].error,true);
    assert.equal(link.dataset.busy,'0');assert.equal(link.textContent,'↓ Baixar vídeo');
  });
}
test('poll retries GET after transient failure but never resubmits export',async()=>{
  const pollSource=source.slice(source.indexOf('async function poll('),source.indexOf('function clock('));
  let calls=0;const updates=[];
  const context=vm.createContext({request:async url=>{
    assert.equal(url,'/api/jobs/id');
    if(++calls<3)throw Object.assign(new Error('offline'),{retryable:true});
    return {status:'ready'};
  },setTimeout:fn=>fn()});
  vm.runInContext(pollSource,context);
  assert.equal((await context.poll('id',message=>updates.push(message))).status,'ready');
  assert.equal(calls,3);assert.equal(updates.length,2);
});

test('YouTube import opens the same local editor with title and unlocked inputs',async()=>{
  const {context:c,element:e}=editor();
  e('youtubeUrl').value='https://youtu.be/BaW_jenozKc';
  const calls=[];
  c.request=async(url,options)=>{calls.push({url,body:JSON.parse(options.body)});return {id:'youtube-job'};};
  c.poll=async()=>({status:'ready',duration:60,title:'Vídeo importado',segments:[],suggestions:[{start:0,end:45}],message:'Pronto'});
  await c.importYoutube({preventDefault(){}});
  assert.equal(calls[0].url,'/api/import/youtube');
  assert.equal(calls[0].body.url,'https://youtu.be/BaW_jenozKc');
  assert.equal(e('video').src,'/media/youtube-job/source.mp4');
  assert.equal(e('editor').hidden,false);assert.match(e('videoTitle').textContent,/Vídeo importado/);
  assert.equal(e('importYoutube').disabled,false);assert.equal(e('file').disabled,false);
  e('start').value='1,5';e('start').oninput();assert.equal(c.values().start,1.5);
});
test('YouTube failure restores both import choices and displays useful error',async()=>{
  const {context:c,element:e}=editor();e('youtubeUrl').value='https://invalid.test';
  c.request=async()=>{throw Error('URL não suportada');};
  await c.importYoutube({preventDefault(){}});
  assert.equal(e('status').textContent,'URL não suportada');
  assert.equal(e('file').disabled,false);assert.equal(e('importYoutube').disabled,false);
});
test('upload remains available and uses the original API and editor',async()=>{
  const {context:c,element:e}=editor();let route;
  c.request=async url=>{route=url;return {id:'uploaded'};};
  c.poll=async()=>({status:'ready',duration:60,segments:[],suggestions:[{start:0,end:45}],message:'Pronto'});
  await c.upload({name:'video.mp4',size:20});
  assert.equal(route,'/api/upload');assert.equal(e('video').src,'/media/uploaded/source.mp4');
  assert.equal(e('file').disabled,false);
});
test('seek controls navigate without modifying cut times or framing',()=>{
  const {context:c,element:e}=editor('10','60');
  e('video').currentTime=20;e('forward').onclick();assert.equal(e('video').currentTime,25);
  e('backward').onclick();assert.equal(e('video').currentTime,20);
  e('seek').value='390';e('seek').oninput();assert.equal(e('video').currentTime,390);
  c.seekVideo(500);assert.equal(e('video').currentTime,400);
  c.seekVideo(-1);assert.equal(e('video').currentTime,0);
  assert.equal(e('start').value,'10');assert.equal(e('end').value,'60');assert.equal(e('framing').value,'80');
});
