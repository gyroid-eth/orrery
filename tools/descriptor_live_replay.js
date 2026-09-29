#!/usr/bin/env node
'use strict';

const http=require('http');
const https=require('https');
const descriptor=require('../bridge/roster_descriptor.js');

const url=process.argv[2]||'http://127.0.0.1:8791/telemetry/agents';
const durationMs=Number(process.env.DESCRIPTOR_REPLAY_MS||15000);
const intervalMs=Number(process.env.DESCRIPTOR_REPLAY_POLL_MS||3000);
const store=descriptor.createStableDescriptorStore();

function getJson(target){
  const client=target.startsWith('https:')?https:http;
  return new Promise((resolve,reject)=>{
    const request=client.get(target,{headers:{'Cache-Control':'no-cache'}},response=>{
      let body='';
      response.setEncoding('utf8');
      response.on('data',chunk=>{body+=chunk;});
      response.on('end',()=>{
        if(response.statusCode<200||response.statusCode>=300){
          reject(new Error(`HTTP ${response.statusCode}`));return;
        }
        try{resolve(JSON.parse(body));}catch(error){reject(error);}
      });
    });
    request.setTimeout(5000,()=>request.destroy(new Error('request timed out')));
    request.on('error',reject);
  });
}

function roster(payload){
  return (payload.agents||[]).filter(agent=>
    (Boolean(agent.running)||agent.category==='agent')&&agent.category!=='warmup');
}

function attach(agents){
  store.retain(agents.map(agent=>agent.name));
  agents.forEach(agent=>{agent.descriptor=store.get(agent,agents);});
  return agents;
}

function sleep(ms){return new Promise(resolve=>setTimeout(resolve,ms));}

(async()=>{
  const first=attach(roster(await getJson(url)));
  const prior=new Map(first.map(agent=>[agent.name,{
    assignment:descriptor.assignmentSignature(agent),
    value:JSON.stringify(agent.descriptor),
  }]));
  const changed=new Set();
  let polls=1,current=first;
  const deadline=Date.now()+durationMs;
  while(Date.now()<deadline){
    await sleep(Math.min(intervalMs,Math.max(0,deadline-Date.now())));
    current=attach(roster(await getJson(url)));polls+=1;
    for(const agent of current){
      const before=prior.get(agent.name);
      const assignment=descriptor.assignmentSignature(agent);
      const value=JSON.stringify(agent.descriptor);
      if(before&&before.assignment===assignment&&before.value!==value)changed.add(agent.name);
      prior.set(agent.name,{assignment,value});
    }
  }
  const parity=current.filter(agent=>
    agent.descriptor.tokens.join(' ').toLocaleLowerCase()
      .includes(agent.descriptor.primary.toLocaleLowerCase())).length;
  const specific=current.filter(agent=>agent.descriptor.quality==='specific');
  const groups=new Map();
  for(const agent of specific){
    const primary=agent.descriptor.primary;
    groups.set(primary,(groups.get(primary)||0)+1);
  }
  const collisions=[...groups.values()].filter(count=>count>1);
  console.log(`source: ${url}`);
  console.log(`polls: ${polls} over ${durationMs}ms`);
  console.log(`display-index parity: ${parity}/${current.length}`);
  console.log(`specific collision exposure: ${collisions.reduce((sum,count)=>sum+count,0)}/${specific.length}`);
  console.log(`specific max collision group: ${Math.max(0,...groups.values())}`);
  console.log(`Needs description: ${current.filter(agent=>agent.descriptor.primary==='Needs description').length}/${current.length}`);
  console.log(`descriptor churn: ${changed.size}`);
  if(changed.size)console.log(`churn agents: ${[...changed].join(', ')}`);
})().catch(error=>{console.error(error.stack||error);process.exitCode=1;});
