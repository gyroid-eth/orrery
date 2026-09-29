#!/usr/bin/env node
'use strict';

const fs=require('fs');
const path=require('path');
const descriptor=require('../bridge/roster_descriptor.js');

const defaultFixture=path.join(__dirname,'fixtures','descriptor_telemetry_2026-08-06.json');
const fixture=path.resolve(process.argv[2]||defaultFixture);
const payload=JSON.parse(fs.readFileSync(fixture,'utf8'));
const agents=(payload.agents||[]).filter(agent=>
  (Boolean(agent.running)||agent.category==='agent')&&agent.category!=='warmup');
const names=descriptor.knownAgentNames(payload.agents||[]);

const classifications=agents.map(agent=>({
  name:agent.name,
  ...descriptor.classify(agent.task,names),
}));

if(process.argv.includes('--json')){
  process.stdout.write(JSON.stringify(classifications));
  process.exit(0);
}

const descriptors=agents.map(agent=>({
  agent,
  descriptor:descriptor.deriveRosterDescriptor(agent,agents),
}));
function includes(hay,needle){
  return String(hay).trim().toLocaleLowerCase().includes(
    String(needle).trim().toLocaleLowerCase());
}
function baselineDisplay(agent){
  let live=String(agent.live||'').replace(descriptor.GLYPH_STRIP,'').trim();
  if(live===agent.name)live='';
  return live||agent.task||agent.last_active_rel||'standing by';
}
function baselineHay(agent){
  return `${agent.name} ${agent.model||''} ${agent.provider||''} ${agent.cmd||''} ${agent.annot&&agent.annot.role||''} ${agent.task||''}`;
}
const baselineRows=agents.map(agent=>({agent,text:baselineDisplay(agent)}));
const baselineParity=baselineRows.filter(({agent,text})=>includes(baselineHay(agent),text)).length;
const baselineGroups=new Map();
for(const row of baselineRows)baselineGroups.set(row.text,(baselineGroups.get(row.text)||0)+1);
const baselineCollisionExposure=[...baselineGroups.values()].filter(count=>count>1)
  .reduce((total,count)=>total+count,0);
const baselineMaxCollision=Math.max(0,...baselineGroups.values());
const parity=descriptors.filter(({agent,descriptor:item})=>
  includes(item.tokens.join(' '),item.primary)&&item.tokens.includes(agent.name)).length;
const renderedTokenFailures=descriptors.filter(({agent,descriptor:item})=>{
  const expected=[agent.name,item.primary,item.secondary].filter(Boolean);
  return JSON.stringify(item.tokens)!==JSON.stringify(expected)||
    expected.some(token=>!includes(item.tokens.join(' '),token));
});
const specific=descriptors.filter(row=>row.descriptor.quality==='specific');
const groups=new Map();
for(const row of specific){
  const key=row.descriptor.primary;
  groups.set(key,(groups.get(key)||0)+1);
}
const collisionExposure=[...groups.values()].filter(count=>count>1)
  .reduce((total,count)=>total+count,0);
const maxCollision=Math.max(0,...groups.values());
const needsDescription=descriptors.filter(row=>row.descriptor.primary==='Needs description').length;

// A stable assignment must not inherit spinner/counter churn from live text.
const store=descriptor.createStableDescriptorStore();
const churnAgent={
  name:'TestCurie',task:'Awaiting canonical inbox task',live:'⠋ Implement roster descriptor 1m',
  annot:{role:'descriptor'},category:'agent',running:true,
};
const churnAgents=[churnAgent];
const first=JSON.stringify(store.get(churnAgent,churnAgents));
let churn=0;
for(const live of [
  '⠙ Implement roster descriptor 2m','⠹ Implement roster descriptor 5m',
  '✳ Polling repaint 8m','⠸ Polling repaint 11m','⠼ Polling repaint 15m',
]){
  churnAgent.live=live;
  if(JSON.stringify(store.get(churnAgent,churnAgents))!==first)churn+=1;
}

if(parity!==agents.length)throw new Error(`display-index parity ${parity}/${agents.length}`);
if(renderedTokenFailures.length){
  throw new Error(`rendered token failures: ${renderedTokenFailures.map(row=>row.agent.name).join(', ')}`);
}
if(baselineParity!==3||baselineCollisionExposure!==22||baselineMaxCollision!==13){
  throw new Error(`fixture baseline drifted: parity=${baselineParity}, exposure=${baselineCollisionExposure}, max=${baselineMaxCollision}`);
}
if(collisionExposure/specific.length>0.25){
  throw new Error(`specific collision exposure ${collisionExposure}/${specific.length}`);
}
if(maxCollision>3)throw new Error(`specific max collision group ${maxCollision}`);
if(churn!==0)throw new Error(`descriptor churn ${churn}`);

console.log(`fixture: ${fixture}`);
console.log(`baseline parity: ${baselineParity}/${agents.length}`);
console.log(`baseline collision exposure: ${baselineCollisionExposure}/${agents.length}`);
console.log(`baseline max collision group: ${baselineMaxCollision}`);
console.log(`display-index parity: ${parity}/${agents.length}`);
console.log(`specific collision exposure: ${collisionExposure}/${specific.length}`);
console.log(`specific max collision group: ${maxCollision}`);
console.log(`Needs description: ${needsDescription}/${agents.length}`);
console.log(`descriptor churn (15s replay): ${churn}`);
