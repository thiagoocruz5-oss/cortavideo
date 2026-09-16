const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname,'../static/app.js'),'utf8');
const requestSource = source.slice(source.indexOf('async function request('),source.indexOf('async function poll'));
function client(response) {
  const context = vm.createContext({fetch:async()=>response});
  vm.runInContext(requestSource,context);
  return context.request;
}
test('valid JSON succeeds', async()=>assert.equal((await client({ok:true,status:200,text:async()=>' {"id":"ok"} '})('/')).id,'ok'));
for (const body of ['', '<html>Bad gateway</html>', 'null']) {
  test(`invalid body ${body}`, async()=>assert.rejects(client({ok:false,status:502,text:async()=>body})('/'), /servidor/));
}
test('busy response keeps useful message', async()=>assert.rejects(client({ok:false,status:429,text:async()=>' {"message":"Aguarde"} '})('/'), /Aguarde/));
test('connection interruption handled', async()=>assert.rejects(client({text:async()=>{throw Error('network');}})('/'), /conexão/));
