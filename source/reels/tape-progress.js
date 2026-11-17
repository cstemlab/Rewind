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
    const windowScale=radius=>(radius-core)/(1-core);
    return {progress,left,right,windowLeft:windowScale(left),windowRight:windowScale(right)};
  }
  function windowGeometry(cx,cy,width){
    const distance=cx<width/2?-cx:cx-width;
    return {cx,cy,coreRadius:distance+width*.06,fullRadius:distance+width*.26};
  }
  function alignWindow(element){
    const aperture=element.querySelector?.('.tape-window');
    if(!aperture)return;
    const metric=aperture.querySelector('.window-metric');
    const pairs=['left','right'].map(side=>({hub:element.querySelector('.'+side+'-coil .reel'),window:aperture.querySelector('.window-reel-'+side)}));
    // Convert the actual hub centres into the aperture's coordinates, including rotation.
    const sync=()=>{
      const matrix=metric.getScreenCTM(),width=parseFloat(getComputedStyle(metric).width);
      if(!matrix||!width)return;
      const inverse=matrix.inverse();
      let axisY=0;
      for(const pair of pairs){
        const bounds=pair.hub.getBoundingClientRect(),point=metric.createSVGPoint();
        point.x=bounds.x+bounds.width/2;point.y=bounds.y+bounds.height/2;
        const hub=point.matrixTransform(inverse),shape=windowGeometry(hub.x,hub.y,width);
        axisY+=shape.cy;
        const style=pair.window.style,diameter=2*shape.fullRadius;
        style.left=(shape.cx-shape.fullRadius)+'px';style.top=(shape.cy-shape.fullRadius)+'px';
        style.width=diameter+'px';style.height=diameter+'px';
        style.setProperty('--core-radius',shape.coreRadius+'px');style.setProperty('--full-radius',shape.fullRadius+'px');
      }
      aperture.style.setProperty('--window-axis-y',(axisY/pairs.length)+'px');
    };
    sync();
    if(typeof ResizeObserver!=='undefined'){
      const observer=new ResizeObserver(sync);
      [element,aperture,...pairs.map(pair=>pair.hub)].forEach(node=>observer.observe(node));
    }else window.addEventListener('resize',sync);
  }
  function create(element){
    alignWindow(element);
    let previous=null;
    return (cursor,start,end)=>{
      const value=measure(cursor,start,end),key=Math.round(value.progress*100000);
      if(key===previous)return;
      previous=key;
      element.style.setProperty('--left-pack',value.left.toFixed(6));
      element.style.setProperty('--right-pack',value.right.toFixed(6));
      element.style.setProperty('--window-left-amount',value.windowLeft.toFixed(6));
      element.style.setProperty('--window-right-amount',value.windowRight.toFixed(6));
      element.dataset.tapeProgress=value.progress.toFixed(6);
    };
  }
  return Object.freeze({measure,windowGeometry,create});
})();
