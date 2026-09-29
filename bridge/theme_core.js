(function(root,factory){
  const api=factory();
  if(typeof module==='object'&&module.exports)module.exports=api;
  if(root)root.OrreryThemeCore=api;
})(typeof globalThis!=='undefined'?globalThis:this,function(){
  'use strict';

  const clamp01=value=>Math.min(1,Math.max(0,value));
  const lerp=(a,b,value)=>a+clamp01(value)*(b-a);
  const hueDelta=(a,b)=>((b-a+540)%360)-180;
  const mixHue=(a,b,value)=>(a+hueDelta(a,b)*clamp01(value)+360)%360;

  const DARK_SEEDS=Object.freeze({
    canvas:Object.freeze({L:.15873,C:.00913,H:264.27}),
    panel:Object.freeze({L:.19034,C:.01122,H:260.65}),
    strong:Object.freeze({L:.21685,C:.01509,H:261.62}),
    elevated:Object.freeze({L:.24680,C:.01871,H:262.15}),
    terminal:Object.freeze({L:.15402,C:.00920,H:264.28}),
    primary:Object.freeze({L:.92334,C:.02141,H:85.95}),
    secondary:Object.freeze({L:.66497,C:.02312,H:85.96}),
    muted:Object.freeze({L:.47444,C:.01612,H:93.15}),
    accent:Object.freeze({L:.81420,C:.12890,H:75.80}),
    local:Object.freeze({L:.70914,C:.08583,H:179.83}),
    remote:Object.freeze({L:.70857,C:.12807,H:306.10}),
    delegate:Object.freeze({L:.70758,C:.10845,H:135.04}),
    alert:Object.freeze({L:.70795,C:.18434,H:27.69}),
    question:Object.freeze({L:.85564,C:.13791,H:208.39}),
    ansiBlue:Object.freeze({L:.70233,C:.06700,H:232.06}),
  });
  const WARM_PAPER_SEED=Object.freeze({
    canvas:Object.freeze({L:.95301,C:.01964,H:87.51}),
    depthScale:1.48,
    depthChroma:.145,
    depthHue:-34,
    terminalLift:.017,
  });

  function oklchToLinear({L,C,H}){
    const radians=H*Math.PI/180;
    const a=C*Math.cos(radians),b=C*Math.sin(radians);
    const l_=L+.3963377774*a+.2158037573*b;
    const m_=L-.1055613458*a-.0638541728*b;
    const s_=L-.0894841775*a-1.291485548*b;
    const l=l_**3,m=m_**3,s=s_**3;
    return [
      4.0767416621*l-3.3077115913*m+.2309699292*s,
      -1.2684380046*l+2.6097574011*m-.3413193965*s,
      -.0041960863*l-.7034186147*m+1.707614701*s,
    ];
  }
  function inGamut(linear){return linear.every(channel=>channel>=0&&channel<=1);}
  function encode(channel){
    const value=channel<=.0031308?12.92*channel:1.055*channel**(1/2.4)-.055;
    return Math.round(clamp01(value)*255);
  }
  function fit(color){
    let candidate={...color};
    let linear=oklchToLinear(candidate);
    if(!inGamut(linear)){
      let low=0,high=Math.max(0,color.C);
      for(let index=0;index<30;index+=1){
        const chroma=(low+high)/2;
        const probe={...color,C:chroma};
        if(inGamut(oklchToLinear(probe)))low=chroma;else high=chroma;
      }
      candidate={...color,C:low};linear=oklchToLinear(candidate);
    }
    return Object.freeze({oklch:Object.freeze(candidate),rgb:Object.freeze(linear.map(encode))});
  }
  function linearChannel(channel8){
    const channel=channel8/255;
    return channel<=.04045?channel/12.92:((channel+.055)/1.055)**2.4;
  }
  function relativeLuminance(rgb){
    const [r,g,b]=rgb.map(linearChannel);
    return .2126*r+.7152*g+.0722*b;
  }
  function contrast(a,b){
    const first=relativeLuminance(a),second=relativeLuminance(b);
    return (Math.max(first,second)+.05)/(Math.min(first,second)+.05);
  }
  function solveL(foreground,backgroundRgb,hardTarget,direction='darker'){
    const target=hardTarget+.02;
    const baseline=fit(foreground);
    if(contrast(baseline.rgb,backgroundRgb)>=target)return baseline;
    if(direction!=='darker')throw new Error('warm-paper light only solves darker foregrounds');
    let low=0,high=foreground.L,best=fit({...foreground,L:0});
    for(let index=0;index<32;index+=1){
      const lightness=(low+high)/2;
      const candidate=fit({...foreground,L:lightness});
      if(contrast(candidate.rgb,backgroundRgb)>=target){best=candidate;low=lightness;}
      else high=lightness;
    }
    return best;
  }
  const hex=rgb=>'#'+rgb.map(channel=>channel.toString(16).padStart(2,'0')).join('');
  const rgbChannels=rgb=>rgb.join(' ');
  const rgba=(rgb,alpha)=>`rgb(${rgbChannels(rgb)} / ${alpha})`;

  function deriveSurface(role){
    const dark=DARK_SEEDS[role];
    const depth=(dark.L-DARK_SEEDS.canvas.L)*WARM_PAPER_SEED.depthScale;
    const base=WARM_PAPER_SEED.canvas;
    const terminalLift=role==='terminal'?WARM_PAPER_SEED.terminalLift:0;
    return fit({
      L:Math.min(.985,base.L-depth+terminalLift),
      C:Math.max(0,base.C+WARM_PAPER_SEED.depthChroma*depth),
      H:(base.H+WARM_PAPER_SEED.depthHue*depth+360)%360,
    });
  }

  function deriveWarmPaperLightTheme(){
    const roles={
      canvas:deriveSurface('canvas'),panel:deriveSurface('panel'),
      strong:deriveSurface('strong'),elevated:deriveSurface('elevated'),
      terminal:deriveSurface('terminal'),
    };
    const darkest=roles.elevated.rgb;
    roles.primary=solveL(DARK_SEEDS.primary,darkest,12);
    roles.secondary=solveL(DARK_SEEDS.secondary,darkest,7);
    roles.muted=solveL(DARK_SEEDS.muted,darkest,4.5);
    roles.accent=solveL(DARK_SEEDS.accent,darkest,4.5);
    roles.local=solveL(DARK_SEEDS.local,darkest,4.5);
    roles.remote=solveL(DARK_SEEDS.remote,darkest,4.5);
    roles.delegate=solveL(DARK_SEEDS.delegate,darkest,4.5);
    roles.alert=solveL(DARK_SEEDS.alert,darkest,4.5);
    roles.question=solveL(DARK_SEEDS.question,darkest,4.5);
    roles.blue=solveL(DARK_SEEDS.ansiBlue,darkest,4.5);
    roles.control=solveL(DARK_SEEDS.muted,darkest,3);
    const bright=seed=>solveL({...seed,C:seed.C*1.18},darkest,4.5);
    roles.brightAlert=bright(DARK_SEEDS.alert);
    roles.brightDelegate=bright(DARK_SEEDS.delegate);
    roles.brightAccent=bright(DARK_SEEDS.accent);
    roles.brightBlue=bright(DARK_SEEDS.ansiBlue);
    roles.brightRemote=bright(DARK_SEEDS.remote);
    roles.brightLocal=bright(DARK_SEEDS.local);

    const cssVariables={
      '--bg':hex(roles.canvas.rgb),'--panel':hex(roles.panel.rgb),
      '--panel-2':hex(roles.strong.rgb),'--elev':hex(roles.elevated.rgb),
      '--ink':hex(roles.primary.rgb),'--ink-dim':hex(roles.secondary.rgb),
      '--ink-faint':hex(roles.muted.rgb),'--amber':hex(roles.accent.rgb),
      '--amber-glow':'transparent','--ln-local':hex(roles.local.rgb),
      '--ln-remote':hex(roles.remote.rgb),'--ln-delegate':hex(roles.delegate.rgb),
      '--theme-surface-terminal':hex(roles.terminal.rgb),
      '--theme-status-alert':hex(roles.alert.rgb),
      '--theme-status-question':hex(roles.question.rgb),
      '--theme-border-control':hex(roles.control.rgb),
      '--theme-focus-ring':hex(roles.accent.rgb),
      '--theme-ink-rgb':rgbChannels(roles.primary.rgb),
      '--theme-accent-rgb':rgbChannels(roles.accent.rgb),
      '--theme-local-rgb':rgbChannels(roles.local.rgb),
      /* The remaining two lineage hues, needed because the cockpit stylesheet
         now takes every alpha'd colour from these channels rather than writing
         the dark palette out by hand. */
      '--theme-remote-rgb':rgbChannels(roles.remote.rgb),
      '--theme-delegate-rgb':rgbChannels(roles.delegate.rgb),
      /* Google engine pill (Gemini / Antigravity) rides the solved blue. */
      '--eng-google':hex(roles.blue.rgb),
      '--theme-google-rgb':rgbChannels(roles.blue.rgb),
      '--theme-alert-rgb':rgbChannels(roles.alert.rgb),
      '--theme-question-rgb':rgbChannels(roles.question.rgb),
      '--hair':rgba(roles.primary.rgb,.16),'--hair-2':rgba(roles.primary.rgb,.08),
      '--theme-shadow-low':rgba(roles.primary.rgb,.12),
      '--theme-shadow-high':rgba(roles.primary.rgb,.08),
    };
    const terminalTheme=Object.freeze({
      background:hex(roles.terminal.rgb),foreground:hex(roles.primary.rgb),
      cursor:hex(roles.accent.rgb),cursorAccent:hex(roles.terminal.rgb),
      selectionBackground:rgba(roles.accent.rgb,.22),
      black:hex(roles.primary.rgb),brightBlack:hex(roles.muted.rgb),
      red:hex(roles.alert.rgb),brightRed:hex(roles.brightAlert.rgb),
      green:hex(roles.delegate.rgb),brightGreen:hex(roles.brightDelegate.rgb),
      yellow:hex(roles.accent.rgb),brightYellow:hex(roles.brightAccent.rgb),
      blue:hex(roles.blue.rgb),brightBlue:hex(roles.brightBlue.rgb),
      magenta:hex(roles.remote.rgb),brightMagenta:hex(roles.brightRemote.rgb),
      cyan:hex(roles.local.rgb),brightCyan:hex(roles.brightLocal.rgb),
      white:hex(roles.secondary.rgb),brightWhite:hex(roles.primary.rgb),
    });
    return Object.freeze({
      id:'warm-paper',mode:'light',roles:Object.freeze(roles),
      cssVariables:Object.freeze(cssVariables),terminalTheme,
    });
  }

  function contrastReport(theme=deriveWarmPaperLightTheme()){
    const background=theme.roles.elevated.rgb;
    const targets={primary:12,secondary:7,muted:4.5,accent:4.5,
      local:4.5,remote:4.5,delegate:4.5,alert:4.5,question:4.5,blue:4.5,
      brightAlert:4.5,brightDelegate:4.5,brightAccent:4.5,brightBlue:4.5,
      brightRemote:4.5,brightLocal:4.5,control:3};
    return Object.freeze(Object.fromEntries(Object.entries(targets).map(([role,target])=>{
      const ratio=contrast(theme.roles[role].rgb,background);
      return [role,Object.freeze({ratio,target,passes:ratio>=target})];
    })));
  }

  return Object.freeze({
    DARK_SEEDS,WARM_PAPER_SEED,clamp01,lerp,mixHue,fit,contrast,solveL,
    deriveWarmPaperLightTheme,contrastReport,hex,
  });
});
