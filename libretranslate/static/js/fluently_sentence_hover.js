/* Fluently sentence-hover linkage.
 * The original textarea remains editable and selectable. An invisible,
 * typography-matched mirror locates the sentence under the pointer; only
 * translucent rectangles are painted above it. Translation uses native
 * inline spans so copied text and selection still work normally.
 */
(() => {
  'use strict';

  function splitSentences(text) {
    if (typeof text !== 'string' || !text) return [];
    const parts = [];
    let start = 0;
    const push = end => {
      const raw = text.slice(start, end);
      const prefix = raw.length - raw.trimStart().length;
      const body = raw.trim();
      if (body) {
        const from = start + prefix;
        parts.push({id:parts.length,start:from,end:from+body.length,text:body});
      }
      start = end;
    };
    for (let i=0; i<text.length; i++) {
      const char=text[i], following=text[i+1] || '';
      if (char === '\n' || char === '\r') {
        push(i);
        if (char === '\r' && following === '\n') {i++;start=i+1;}
        else start=i+1;
      } else if ('。！？!?'.includes(char)) {
        if (!following || /[\s"'”’）)\u3400-\u9fff]/u.test(following)) {
          let end=i+1;
          while (end<text.length && /["'”’）)\]}]/u.test(text[end])) end++;
          push(end);
          i=end-1;
        }
      } else if (char === '.') {
        const previous=text[i-1] || '';
        if (/\d/.test(previous) && /\d/.test(following)) continue;
        // Keep common English abbreviations within their sentences.
        const before=text.slice(Math.max(0,i-14),i+1);
        if (/\b(?:Mr|Mrs|Ms|Dr|Prof|Sr|Jr|vs|Fig|Eq|Ref|Sec|al|Vol|No|e\.g|i\.e)\.$/i.test(before)) continue;
        if (!following || /\s|["'”’)\]}]/u.test(following)) {
          let end=i+1;
          while (end<text.length && /["'”’）)\]}]/u.test(text[end])) end++;
          push(end);
          i=end-1;
        }
      }
    }
    push(text.length);
    return parts;
  }

  // Python alignment offsets count Unicode scalar values, whereas JS slice()
  // counts UTF-16 code units (emoji/supplementary CJK occupy two code units).
  function toUtf16Segments(text, items) {
    const offsets=[0];
    for (const char of text) offsets.push(offsets[offsets.length-1]+char.length);
    if (!Array.isArray(items)) return splitSentences(text);
    const segments=[];
    for (const item of items) {
      const start=offsets[item.start], end=offsets[item.end];
      if (!Number.isInteger(start) || !Number.isInteger(end) || start>=end ||
          text.slice(start,end)!==item.text) return splitSentences(text);
      segments.push({id:segments.length,start,end,text:item.text});
    }
    return segments;
  }

  function fallbackGroups(src, tgt) {
    if (!src.length || !tgt.length) return [];
    const groups=[];
    if (src.length >= tgt.length) {
      for (let j=0;j<tgt.length;j++) groups.push({
        source_ids:[],target_ids:[j],confidence:0,
      });
      for (let i=0;i<src.length;i++) {
        const j=Math.min(tgt.length-1,Math.floor((i+.5)*tgt.length/src.length));
        groups[j].source_ids.push(i);
      }
    } else {
      for (let i=0;i<src.length;i++) groups.push({
        source_ids:[i],target_ids:[],confidence:0,
      });
      for (let j=0;j<tgt.length;j++) {
        const i=Math.min(src.length-1,Math.floor((j+.5)*src.length/tgt.length));
        groups[i].target_ids.push(j);
      }
    }
    return groups;
  }

  function appendSentenceNodes(root, text, sentences, className) {
    const fragment=document.createDocumentFragment();
    let cursor=0;
    sentences.forEach((part,index) => {
      if (part.start<cursor || part.end>text.length || part.start>=part.end) return;
      if (part.start>cursor) fragment.append(document.createTextNode(text.slice(cursor,part.start)));
      const span=document.createElement('span');
      span.className=className;
      span.dataset.sentenceIndex=String(index);
      span.textContent=text.slice(part.start,part.end);
      fragment.append(span);
      cursor=part.end;
    });
    if (cursor<text.length) fragment.append(document.createTextNode(text.slice(cursor)));
    root.replaceChildren(fragment);
  }

  function mount({input,output,enabled}) {
    if (!input || !output) throw new Error('Sentence hover: missing source or translation');
    const parent=input.parentNode;
    const editor=document.createElement('div');
    editor.className='version-source-editor';
    parent.insertBefore(editor,input);
    editor.append(input);
    const mirror=document.createElement('div');
    mirror.className='source-sentence-mirror';
    mirror.setAttribute('aria-hidden','true');
    const paint=document.createElement('div');
    paint.className='source-sentence-highlights';
    paint.setAttribute('aria-hidden','true');
    editor.append(mirror,paint);

    let source='',target='',srcSegments=[],tgtSegments=[],groups=[];
    let active=null, hoverRects=null, generation=0, destroyed=false;
    let alignmentMethod='approximate';

    const mirrorStyles=[
      'fontFamily','fontSize','fontWeight','fontStyle','fontVariant','lineHeight',
      'letterSpacing','wordSpacing','textAlign','textIndent','tabSize',
      'paddingTop','paddingRight','paddingBottom','paddingLeft',
      'borderTopWidth','borderRightWidth','borderBottomWidth','borderLeftWidth',
      'boxSizing','wordBreak','overflowWrap','textTransform','direction',
    ];
    function syncMirror() {
      if (destroyed) return;
      const styles=window.getComputedStyle(input);
      mirrorStyles.forEach(key=>{mirror.style[key]=styles[key];});
      mirror.style.width=input.offsetWidth+'px';
      mirror.style.height=input.offsetHeight+'px';
      hoverRects=null;
      if (active) drawActive();
    }
    function makeRects() {
      if (hoverRects) return hoverRects;
      hoverRects=[];
      for (const span of mirror.querySelectorAll('[data-sentence-index]')) {
        const range=document.createRange();
        range.selectNodeContents(span);
        const id=Number(span.dataset.sentenceIndex);
        for (const rect of range.getClientRects()) {
          if (rect.width>0 && rect.height>0) hoverRects.push({id,rect});
        }
      }
      return hoverRects;
    }
    function sourceIndexAt(x,y) {
      const bounds=input.getBoundingClientRect();
      if (x<bounds.left || x>bounds.right || y<bounds.top || y>bounds.bottom) return -1;
      for (const {id,rect} of makeRects()) {
        if (x>=rect.left-1 && x<=rect.right+1 &&
            y>=rect.top-1 && y<=rect.bottom+1) return id;
      }
      return -1;
    }
    function clearPaint() {
      paint.replaceChildren();
      for (const span of output.querySelectorAll('.hover-translation-sentence.is-matched')) {
        span.classList.remove('is-matched');
      }
    }
    function drawActive() {
      clearPaint();
      if (!active || enabled?.()===false) return;
      const {side,index}=active;
      let sources=[],targets=[];
      const group=groups.find(g=>(side==='source' ? g.source_ids : g.target_ids).includes(index));
      if (group) {
        sources=group.source_ids;
        targets=group.target_ids;
      } else if (side==='source') sources=[index];
      else targets=[index];
      const wrapRect=editor.getBoundingClientRect();
      const sourceRect=input.getBoundingClientRect();
      const wanted=new Set(sources);
      for (const {id,rect} of makeRects()) {
        if (!wanted.has(id)) continue;
        const left=Math.max(rect.left,sourceRect.left);
        const right=Math.min(rect.right,sourceRect.right);
        const top=Math.max(rect.top,sourceRect.top);
        const bottom=Math.min(rect.bottom,sourceRect.bottom);
        if (right<=left || bottom<=top) continue;
        const box=document.createElement('span');
        box.className='source-sentence-highlight';
        box.style.left=(left-wrapRect.left)+'px';
        box.style.top=(top-wrapRect.top)+'px';
        box.style.width=(right-left)+'px';
        box.style.height=(bottom-top)+'px';
        paint.append(box);
      }
      for (const span of output.querySelectorAll('.hover-translation-sentence')) {
        span.classList.toggle('is-matched',targets.includes(Number(span.dataset.sentenceIndex)));
      }
      output.dataset.alignmentQuality=alignmentMethod;
    }
    function setHover(side,index) {
      if (enabled?.()===false || index<0) {clearHover();return;}
      if (active?.side===side && active.index===index) return;
      active={side,index};
      drawActive();
    }
    function clearHover() {
      if (!active) return;
      active=null;
      clearPaint();
    }
    function onSourceMove(event) {
      if (event.pointerType==='touch' || event.buttons) return;
      const index=sourceIndexAt(event.clientX,event.clientY);
      setHover('source',index);
    }
    function onTargetMove(event) {
      if (event.pointerType==='touch' || event.buttons) return;
      const element=event.target.closest?.('.hover-translation-sentence');
      setHover('target',element ? Number(element.dataset.sentenceIndex) : -1);
    }
    function onSourceKey(event) {
      if (!['ArrowLeft','ArrowRight','ArrowUp','ArrowDown','Home','End'].includes(event.key))
        return;
      const position=input.selectionStart;
      const index=srcSegments.findIndex(s=>position>=s.start && position<=s.end);
      setHover('source',index);
    }
    function onLayout() {
      syncMirror();
    }
    input.addEventListener('pointermove',onSourceMove);
    input.addEventListener('pointerleave',clearHover);
    input.addEventListener('keyup',onSourceKey);
    input.addEventListener('scroll',onLayout);
    output.addEventListener('pointermove',onTargetMove);
    output.addEventListener('pointerleave',clearHover);
    window.addEventListener('resize',onLayout);

    function update(nextSource,nextTarget) {
      if (destroyed) return;
      nextSource=typeof nextSource==='string' ? nextSource : '';
      nextTarget=typeof nextTarget==='string' ? nextTarget : '';
      if (source===nextSource && target===nextTarget) return;
      source=nextSource;
      target=nextTarget;
      const requestId=++generation;
      clearHover();
      srcSegments=splitSentences(source);
      tgtSegments=splitSentences(target);
      groups=fallbackGroups(srcSegments,tgtSegments);
      alignmentMethod='approximate';
      appendSentenceNodes(mirror,source,srcSegments,'source-sentence');
      if (target) appendSentenceNodes(output,target,tgtSegments,'hover-translation-sentence');
      syncMirror();
      // Hover itself never invokes AI or a third-party translator. This local
      // alignment request is performed once when a translated version changes.
      if (!source.trim() || !target.trim() || enabled?.()===false) return;
      fetch('/fluently/api/align',{
        method:'POST',credentials:'same-origin',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify({source,target,mode:'heuristic'}),
      }).then(async response=>{
        if (!response.ok) throw new Error('Sentence alignment unavailable');
        return response.json();
      }).then(result=>{
        if (destroyed || requestId!==generation || !Array.isArray(result.groups)) return;
        const from=toUtf16Segments(source,result.source);
        const to=toUtf16Segments(target,result.target);
        if (!from.length || !to.length ||
            from.length!==result.source.length || to.length!==result.target.length) return;
        const valid=result.groups.every(g=>
          Array.isArray(g.source_ids) && Array.isArray(g.target_ids) &&
          g.source_ids.every(i=>Number.isInteger(i)&&i>=0&&i<from.length) &&
          g.target_ids.every(i=>Number.isInteger(i)&&i>=0&&i<to.length));
        if (!valid) return;
        const sameOffsets=(a,b)=>a.length===b.length &&
          a.every((part,index)=>part.start===b[index].start && part.end===b[index].end);
        const sourceChanged=!sameOffsets(srcSegments,from);
        const targetChanged=!sameOffsets(tgtSegments,to);
        srcSegments=from;
        tgtSegments=to;
        groups=result.groups;
        alignmentMethod='heuristic';
        // Preserve a native text selection when sentence boundaries are
        // unchanged. Replacing translation spans would clear the selection.
        if (sourceChanged) appendSentenceNodes(mirror,source,srcSegments,'source-sentence');
        if (targetChanged) appendSentenceNodes(output,target,tgtSegments,'hover-translation-sentence');
        syncMirror();
      }).catch(()=>{
        // Positional, approximate sentence linkage stays usable offline.
      });
    }
    function destroy() {
      if (destroyed) return;
      destroyed=true;
      generation++;
      input.removeEventListener('pointermove',onSourceMove);
      input.removeEventListener('pointerleave',clearHover);
      input.removeEventListener('keyup',onSourceKey);
      input.removeEventListener('scroll',onLayout);
      output.removeEventListener('pointermove',onTargetMove);
      output.removeEventListener('pointerleave',clearHover);
      window.removeEventListener('resize',onLayout);
      clearHover();
    }
    return {update,syncLayout:onLayout,destroy};
  }
  window.FluentlySentenceHover={mount,splitSentences,toUtf16Segments,fallbackGroups};
})();
