/* Until the Reader motion lands, use the same substepped spring integration. */
(function(root){
  'use strict';
  function step(state,target,stiffness,damping,seconds){
    const dt=Math.min(seconds,1/30)/4;
    for(let i=0;i<4;i++){
      state.velocity+=(stiffness*(target-state.value)-damping*state.velocity)*dt;
      state.value+=state.velocity*dt;
    }
  }
  root.OrreryPromptSpring=Object.freeze({step});
})(window);
