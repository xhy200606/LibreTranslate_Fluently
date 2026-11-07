'use strict';
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const file=path.join(__dirname,'../../static/js/fluently_sentence_hover.js');
const js=fs.readFileSync(file,'utf8');
const sandbox={window:{}};
vm.runInNewContext(js,sandbox,{filename:file});
const {splitSentences,toUtf16Segments,fallbackGroups,mount}=sandbox.window.FluentlySentenceHover;
const texts = value => Array.from(splitSentences(value), x=>x.text);

test('detects English sentences without dragging selection',()=>{
  assert.deepEqual(texts('Hello world. Another sentence! Third one?'),[
    'Hello world.','Another sentence!','Third one?',
  ]);
});

test('preserves decimals and academic titles inside sentences',()=>{
  assert.deepEqual(texts('Dr. Smith used Fig. 8 and Eq. 3.14. The result improved.'),[
    'Dr. Smith used Fig. 8 and Eq. 3.14.','The result improved.',
  ]);
});

test('includes matching closing quotes in a hovered sentence',()=>{
  assert.deepEqual(texts('"Hello!" Next sentence.'),[
    '"Hello!"','Next sentence.',
  ]);
  assert.deepEqual(texts("He said 'yes.' Then left."),[
    "He said 'yes.'","Then left.",
  ]);
});

test('splits Chinese sentences and preserves sentence offsets',()=>{
  const text='第一句。第二句！第三句？';
  const sentences=splitSentences(text);
  assert.deepEqual(Array.from(sentences,x=>x.text),['第一句。','第二句！','第三句？']);
  for(const item of sentences) assert.equal(text.slice(item.start,item.end),item.text);
});

test('newline creates sentence boundaries without changing original text',()=>{
  const text='Line one.\n\nLine two.\r\nLine three.';
  assert.deepEqual(texts(text),['Line one.','Line two.','Line three.']);
});

test('converts server codepoint offsets into JS UTF-16 offsets',()=>{
  const input='😀Hello. 再见。';
  const items=[{start:0,end:7,text:'😀Hello.'},{start:8,end:11,text:'再见。'}];
  const result=toUtf16Segments(input,items);
  assert.equal(result[0].end,8);
  assert.equal(result[1].start,9);
  assert.equal(input.slice(result[1].start,result[1].end),'再见。');
});

test('falls back to local segmentation when server offsets are invalid',()=>{
  const text='One. Two.';
  const result=toUtf16Segments(text,[{start:999,end:1000,text:'injected'}]);
  assert.deepEqual(Array.from(result,x=>x.text),['One.','Two.']);
});

test('supports multiple source sentences mapping to one translation sentence',()=>{
  const groups=fallbackGroups([{}, {}, {}],[{}, {}]);
  assert.equal(groups.length,2);
  assert.deepEqual(Array.from(groups.flatMap(x=>x.source_ids)),[0,1,2]);
  assert.deepEqual(Array.from(groups.flatMap(x=>x.target_ids)),[0,1]);
});

test('supports one source sentence mapping to several translated sentences',()=>{
  const groups=fallbackGroups([{}],[{}, {}, {}]);
  assert.equal(groups.length,1);
  assert.deepEqual(Array.from(groups[0].target_ids),[0,1,2]);
});

test('disables correspondence groups for empty untranslated targets',()=>{
  assert.equal(fallbackGroups([{}],[]).length,0);
  assert.equal(fallbackGroups([],[]).length,0);
});

test('hover movement itself does not call AI translation APIs',()=>{
  const moveBlock=js.slice(js.indexOf('function onSourceMove('),
                            js.indexOf('function onSourceKey('));
  assert.ok(moveBlock.includes('sourceIndexAt'));
  assert.ok(moveBlock.includes('setHover'));
  assert.doesNotMatch(moveBlock,/\bfetch\s*\(|\/fluently\/api\/ai/);
  assert.equal(typeof mount,'function');
});
