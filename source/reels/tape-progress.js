/* Rewind tape inventory: the whole recording owns the amount, never a cue's local time. */
const RewindTapeProgress=(()=>{
  'use strict';
  const core=.58,capacity=1-core*core;
  function measure(cursor,start,end){
    const span=end-start;
    const progress=Number.isFinite(cursor)&&Number.isFinite(span)&&span>0?Math.max(0,Math.min(1,(cursor-start)/span)):0;
    const left=Math.sqrt(core*core+capacity*progress);
    const right=Math.sqrt(core*core+capacity*(1-progress));
    // The window is a restrained glimpse: even a full pack stays inside its own half.
    const windowScale=radius=>.5+.44*(radius-core)/(1-core);
    return {progress,left,right,windowLeft:windowScale(left),windowRight:windowScale(right)};
  }
  function create(element){
    let previous=null;
    return (cursor,start,end)=>{
      const value=measure(cursor,start,end),key=Math.round(value.progress*100000);
      if(key===previous)return;
      previous=key;
      element.style.setProperty('--left-pack',value.left.toFixed(6));
      element.style.setProperty('--right-pack',value.right.toFixed(6));
      element.style.setProperty('--window-left-tape',value.windowLeft.toFixed(6));
      element.style.setProperty('--window-right-tape',value.windowRight.toFixed(6));
      element.dataset.tapeProgress=value.progress.toFixed(6);
    };
  }
  return Object.freeze({measure,create});
})();
