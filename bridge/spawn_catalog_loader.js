/* Keep the last real catalog while transient failures recover in an open dialog. */
(function(root,factory){
  const api=factory();
  if(typeof module==='object'&&module.exports)module.exports=api;
  else root.SpawnCatalogLoader=api;
})(typeof globalThis!=='undefined'?globalThis:this,()=>({
  create({fetchCatalog,onState,isOpen,delays=[1000,3000,8000],pollDelay=30000,setTimer=setTimeout,clearTimer=clearTimeout}){
    let good=null,pending=null,timer=null,controller=null,epoch=0,failures=0;
    const clear=()=>{if(timer!==null){clearTimer(timer);timer=null;}};
    const publish=status=>onState({catalog:good,status});
    function refresh(){
      if(pending)return pending;
      clear();
      const run=++epoch;controller=new AbortController();
      const signal=controller.signal;
      pending=Promise.resolve().then(async()=>{
        let catalog;
        try{
          catalog=await fetchCatalog(signal);
          if(!catalog||catalog.ok===false||!Array.isArray(catalog.providers))throw Error('bad catalog');
        }catch(_){
          if(run!==epoch)return;
          failures++;
          const retry=isOpen();
          publish(good?'stale':!retry||failures>=3?'unavailable':'loading');
          if(retry)timer=setTimer(()=>{timer=null;return refresh();},delays[failures-1]??pollDelay);
          return;
        }finally{
          if(run===epoch)pending=null;
        }
        if(run!==epoch)return;
        good=catalog;failures=0;publish('ready');
      });
      publish(good?'stale':'loading');
      return pending;
    }
    function stop(){clear();epoch++;controller?.abort();controller=null;pending=null;failures=0;}
    return {refresh,stop};
  },
}));
