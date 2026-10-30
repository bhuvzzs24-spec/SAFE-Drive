/* Presentation-only enhancement. Analysis data and requests remain in app.js. */
(() => {
  'use strict';
  const root = document.documentElement;
  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)');
  const nav = document.querySelector('.product-nav');
  const toggle = document.getElementById('product-menu-toggle');
  const links = document.getElementById('product-navigation');
  const road = document.querySelector('.hero-road');
  const reveal = [...document.querySelectorAll('.reveal')];
  let observer = null, frame = null;

  function closeMenu(restoreFocus = false) {
    nav?.classList.remove('menu-open');
    toggle?.setAttribute('aria-expanded','false');
    toggle?.setAttribute('aria-label','Open product navigation');
    if (restoreFocus) toggle?.focus();
  }
  toggle?.addEventListener('click', () => {
    const open = !nav.classList.contains('menu-open');
    nav.classList.toggle('menu-open',open);
    toggle.setAttribute('aria-expanded',String(open));
    toggle.setAttribute('aria-label',open?'Close product navigation':'Open product navigation');
    if(open)links.querySelector('a')?.focus();
  });
  document.addEventListener('keydown', event => {
    if(!nav?.classList.contains('menu-open'))return;
    if(event.key==='Escape'){event.preventDefault();closeMenu(true);return;}
    if(event.key!=='Tab')return;
    const items=[toggle,...links.querySelectorAll('a')],first=items[0],last=items.at(-1);
    if(event.shiftKey && document.activeElement===first){event.preventDefault();last.focus();}
    else if(!event.shiftKey && document.activeElement===last){event.preventDefault();first.focus();}
  });
  document.addEventListener('click',event=>{if(nav?.classList.contains('menu-open') && !nav.contains(event.target))closeMenu();});
  window.matchMedia('(min-width: 761px)').addEventListener('change',event=>{if(event.matches)closeMenu();});

  document.querySelectorAll('[data-story-link]').forEach(link=>link.addEventListener('click',event=>{
    const section=document.getElementById(link.dataset.storyLink);
    if(!section)return;
    event.preventDefault();closeMenu();
    history.pushState(null,'',`#${section.id}`);
    section.scrollIntoView({behavior:reduced.matches?'auto':'smooth',block:'start'});
    const heading=section.querySelector('h2') || section;
    heading.tabIndex=-1;heading.focus({preventScroll:true});
  }));
  document.querySelectorAll('[data-focus-setting]').forEach(link=>link.addEventListener('click',()=>{
    const target=document.getElementById(link.dataset.focusSetting);
    if(!target)return;
    for(let parent=target.parentElement;parent;parent=parent.parentElement){if(parent.tagName==='DETAILS')parent.open=true;}
    target.scrollIntoView({behavior:reduced.matches?'auto':'smooth',block:'center'});
    target.focus({preventScroll:true});
  }));

  function showAll() { reveal.forEach(item=>item.classList.add('is-visible'));root.classList.remove('motion-enabled'); }
  if(!reduced.matches && 'IntersectionObserver' in window){
    try{
      observer=new IntersectionObserver(entries=>entries.forEach(entry=>{
        if(entry.isIntersecting){entry.target.classList.add('is-visible');observer.unobserve(entry.target);}
      }),{threshold:.08,rootMargin:'0px 0px -15px 0px'});
      reveal.forEach(item=>observer.observe(item));root.classList.add('motion-enabled');
    }catch(_){showAll();}
  }else showAll();
  function updateRoad(){
    frame=null;
    if(!road)return;
    const active=document.body.classList.contains('is-product') && !reduced.matches && window.innerWidth>960;
    road.style.transform=active?`translateY(${Math.min(42,Math.max(0,window.scrollY*.09))}px) scale(1.07)`:'';
  }
  function queueRoad(){if(frame==null)frame=requestAnimationFrame(updateRoad);}
  window.addEventListener('scroll',queueRoad,{passive:true});
  window.addEventListener('resize',queueRoad,{passive:true});
  reduced.addEventListener('change',()=>{if(reduced.matches){observer?.disconnect();showAll();}queueRoad();});
  document.addEventListener('safe-drive:navigate',()=>{closeMenu();queueRoad();});
  queueRoad();

  const status=document.getElementById('calibration-status'),summary=document.getElementById('calibration-summary');
  if(status && summary){
    const update=()=>{summary.textContent=status.dataset.state==='valid'?'Structure checked':status.dataset.state==='error'?'Needs attention':'Speed unavailable';};
    new MutationObserver(update).observe(status,{childList:true,subtree:true,attributes:true,attributeFilter:['data-state']});
    update();
  }
})();
