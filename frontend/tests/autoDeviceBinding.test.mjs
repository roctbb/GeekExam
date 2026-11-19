import test from 'node:test'
import assert from 'node:assert/strict'
import { createAutoDeviceBinding } from '../src/utils/autoDeviceBinding.js'
const settled = async () => { for(let i=0;i<30;i++) await Promise.resolve() }
const endpoint = {id:'proof',token:'opaque-once',url:'https://lan-409.guard.geekclass.ru:18766/v1/browser-proof'}
function setup(values={}) {
  const states=[], calls=[]
  const binding=createAutoDeviceBinding({start:async()=>({state:'ready',items:[endpoint]}),
    finish:async data=>{calls.push(data);return {state:'bound'}}, fetchLocal:async()=>({ok:true}),
    onChange:value=>states.push(value.state),schedule:()=>1,cancel:()=>{},...values})
  return {binding,states,calls}
}
test('first device is proved automatically without sending login credentials to LAN',async()=>{
  let request
  const s=setup({fetchLocal:async(url,options)=>{request={url,options};return {ok:true}}})
  s.binding.begin({client_id:'client',token:'secret-browser-credential'});await settled()
  assert.equal(request.options.credentials,'omit');assert.equal(request.options.redirect,'error')
  assert.deepEqual(JSON.parse(request.options.body),{token:'opaque-once'})
  assert.equal(s.calls[0].token,'secret-browser-credential');assert.equal(s.states.at(-1),'bound')
  s.binding.stop()
})
test('a fresh heartbeat can request proof again after a Wi-Fi reconnect', async () => {
  const {binding,calls} = setup()
  const credentials = {client_id:'client',token:'secret'}
  binding.begin(credentials); await settled()
  binding.begin(credentials); await settled()
  assert.equal(calls.length,1)
  binding.begin(credentials,true); await settled()
  assert.equal(calls.length,2)
  binding.stop()
})
test('lost local acknowledgement can be recovered using server proof state',async()=>{
  const s=setup({fetchLocal:async()=>{throw Error('ack lost')}})
  s.binding.begin({client_id:'client',token:'secret'});await settled()
  assert.equal(s.states.at(-1),'bound');s.binding.stop()
})
test('another device creates a visible conflict and never retries over the original',async()=>{
  let starts=0
  const s=setup({start:async()=>{starts++;return {state:'ready',items:[endpoint]}},finish:async()=>{throw {response:{data:{state:'different_device'}}}}})
  s.binding.begin({client_id:'c',token:'secret'});await settled();s.binding.retry();await settled()
  assert.equal(s.states.at(-1),'different_device');assert.equal(starts,1);s.binding.stop()
})
test('no endpoint, an invalid URL or a stopped attempt cannot produce a fake binding',async()=>{
  const absent=setup({start:async()=>({state:'unavailable',items:[]})})
  absent.binding.begin({client_id:'c',token:'secret'});await settled();assert.equal(absent.calls.length,0);absent.binding.stop()
  const invalid=setup({start:async()=>({state:'ready',items:[{...endpoint,url:'http://192.168.2.1/v1/browser-proof'}]})})
  invalid.binding.begin({client_id:'c',token:'secret'});await settled();assert.equal(invalid.calls.length,0);invalid.binding.stop()
  let resolve
  const stopped=setup({fetchLocal:()=>new Promise(done=>{resolve=done})})
  stopped.binding.begin({client_id:'c',token:'secret'});await settled();stopped.binding.stop();resolve({ok:true});await settled()
  assert.equal(stopped.calls.length,0)
})
test('several routers do not replace each others successful binding',async()=>{
  const s=setup({start:async()=>({state:'ready',items:[endpoint,{...endpoint,id:'proof-two'}]})})
  s.binding.begin({client_id:'c',token:'secret'});await settled();assert.equal(s.calls.length,1);s.binding.stop()
})
