/* Particle motion adapted from DesignBookmark's Dust delete.
   https://designbookmark.com/motion-src/dust-delete/index.html */
(function(root){
  'use strict';
  const reduced=matchMedia('(prefers-reduced-motion: reduce)');
  const grain=2;
  const lifetime=1.15;
  const effects=new Set();
  let scheduled=false;
  let settleMotion;

  function layoutMotion(){
    if(settleMotion||!CSS.supports('animation-timing-function','linear(0, 1)'))return settleMotion;
    // DesignBookmark's shared tokens.css --spring-settle (stiffness, damping).
    // https://designbookmark.com/motion-src/shared/tokens.css
    const frames=[0],state={value:0,velocity:0};
    do{
      root.OrreryPromptSpring.step(state,1,280,22,1/60);
      frames.push(Number(state.value.toFixed(4)));
    }while(Math.abs(1-state.value)>.002||Math.abs(state.velocity)>.02);
    frames.push(1);
    settleMotion={duration:(frames.length-1)*1000/60,easing:`linear(${frames.join(',')})`};
    return settleMotion;
  }

  function clipBounds(node,viewport){
    const box=node.getBoundingClientRect(),limit=viewport.getBoundingClientRect();
    const left=Math.floor(Math.max(0,box.left,limit.left));
    const top=Math.floor(Math.max(0,box.top,limit.top));
    const right=Math.ceil(Math.min(innerWidth,box.right,limit.right));
    const bottom=Math.ceil(Math.min(innerHeight,box.bottom,limit.bottom));
    return {left,top,width:right-left,height:bottom-top};
  }

  function paintRectangle(ctx,box,radius,color){
    ctx.fillStyle=color;
    ctx.beginPath();
    ctx.roundRect(box.left,box.top,box.width,box.height,radius);
    ctx.fill();
  }

  function drawSnapshot(ctx,node){
    const surface=node.querySelector('.session-label')||node;
    const style=getComputedStyle(surface),bounds=surface.getBoundingClientRect();
    const panel=style.getPropertyValue('--panel-2').trim()||style.color;
    const background=style.backgroundColor;
    paintRectangle(ctx,bounds,parseFloat(style.borderTopLeftRadius)||0,
      background==='rgba(0, 0, 0, 0)'?panel:background);
    const avatar=surface.querySelector('.face,.session-ava');
    if(avatar?.getClientRects().length){
      const box=avatar.getBoundingClientRect(),appearance=getComputedStyle(avatar);
      const portrait=avatar instanceof HTMLImageElement?avatar:avatar.querySelector('img');
      ctx.save();
      ctx.beginPath();
      ctx.ellipse(box.left+box.width/2,box.top+box.height/2,box.width/2,box.height/2,0,0,2*Math.PI);
      ctx.clip();
      ctx.fillStyle=appearance.color;
      ctx.globalAlpha=.24;
      ctx.fillRect(box.left,box.top,box.width,box.height);
      ctx.globalAlpha=1;
      if(portrait?.naturalWidth&&portrait.getClientRects().length
        &&new URL(portrait.currentSrc).origin===location.origin){
        ctx.drawImage(portrait,box.left,box.top,box.width,box.height);
      }else{
        ctx.fillStyle=appearance.color;
        ctx.font=`600 ${box.height*.48}px ${appearance.fontFamily}`;
        ctx.textBaseline='middle';ctx.textAlign='center';
        ctx.fillText(avatar.querySelector('.ini')?.textContent||'',box.left+box.width/2,box.top+box.height/2);
      }
      ctx.restore();
    }
    for(const label of surface.querySelectorAll('.cname,.roster-role,.roster-model,.session-name,.session-state')){
      if(!label.textContent||!label.getClientRects().length)continue;
      const box=label.getBoundingClientRect(),textStyle=getComputedStyle(label);
      if(!box.width)continue;
      ctx.fillStyle=textStyle.color;
      ctx.font=`${textStyle.fontWeight} ${textStyle.fontSize} ${textStyle.fontFamily}`;
      ctx.textBaseline='middle';
      ctx.fillText(label.textContent.trim(),box.left,box.top+box.height/2,box.width);
    }
  }

  function fragment(node,viewport){
    if(!node?.getClientRects().length||!viewport?.getClientRects().length)return;
    const {left,top,width,height}=clipBounds(node,viewport);
    if(width<=0||height<=0)return;
    const sample=document.createElement('canvas');
    sample.width=width;sample.height=height;
    const source=sample.getContext('2d',{willReadFrequently:true});
    if(!source)return;
    source.translate(-left,-top);
    let pixels;
    try{
      drawSnapshot(source,node);
      pixels=source.getImageData(0,0,width,height).data;
    }catch(_){return;}
    const canvas=document.createElement('canvas');
    const spaceLeft=Math.min(left,240),spaceAbove=Math.min(top,92);
    canvas.className='exit-dust';
    canvas.setAttribute('aria-hidden','true');
    canvas.style.left=(left-spaceLeft)+'px';canvas.style.top=(top-spaceAbove)+'px';
    canvas.width=width+spaceLeft+grain;
    canvas.height=height+spaceAbove+Math.min(72,Math.max(0,innerHeight-top-height));
    const context=canvas.getContext('2d');
    if(!context)return;
    const particles=[];
    for(let y=0;y<height;y+=grain){
      for(let x=0;x<width;x+=grain){
        const offset=(y*width+x)*4;
        if(pixels[offset+3]<25)continue;
        particles.push({
          x:x+spaceLeft,y:y+spaceAbove,offset,
          delay:.56*(1-x/width)+.16*Math.random()+.0012*Math.abs(y-height/2),
          horizontal:-50-150*Math.random(),vertical:-25-75*Math.random(),
        });
      }
    }
    if(!particles.length)return;
    const field=context.createImageData(canvas.width,canvas.height);
    document.body.appendChild(canvas);
    return {canvas,context,field,particles,pixels,began:performance.now()};
  }

  function draw(effect,elapsed){
    const {canvas,context,field,particles,pixels}=effect;
    const data=field.data,width=canvas.width,height=canvas.height;
    data.fill(0);
    for(let i=0;i<particles.length;i++){
      const {x,y,offset,delay,horizontal,vertical}=particles[i];
      const age=Math.max(0,elapsed-delay);
      if(age>=lifetime)continue;
      const px=Math.round(x+horizontal*age+Math.sin(age*4+i)*10*age);
      const py=Math.round(y+vertical*age+60*age*age);
      if(px<0||px+grain>width||py<0||py+grain>height)continue;
      const alpha=pixels[offset+3]*(1-age/lifetime);
      for(let row=0;row<grain;row++){
        let index=((py+row)*width+px)*4;
        for(let column=0;column<grain;column++,index+=4){
          data[index]=pixels[offset];data[index+1]=pixels[offset+1];
          data[index+2]=pixels[offset+2];data[index+3]=alpha;
        }
      }
    }
    context.putImageData(field,0,0);
  }

  function animateDust(now){
    scheduled=false;
    for(const effect of effects){
      const elapsed=(now-effect.began)/1000;
      if(reduced.matches||elapsed>1.98){effect.canvas.remove();effects.delete(effect);}
      else draw(effect,elapsed);
    }
    if(effects.size){scheduled=true;requestAnimationFrame(animateDust);}
  }

  function play(node,viewport){
    if(reduced.matches||document.hidden)return;
    const effect=fragment(node,viewport);
    if(!effect)return;
    draw(effect,0);effects.add(effect);
    if(!scheduled){scheduled=true;requestAnimationFrame(animateDust);}
  }

  root.OrreryExitDust=Object.freeze({play,layoutMotion});
})(window);
