(() => {
  'use strict';
  const $ = selector => document.querySelector(selector);
  let config = {
    ui: {compare_count: 2, theme:'system', glass:true, font_size:16, source_language:'en',
         target_language:'zh', default_engine:'bilibiliFree', highlight:true,
         deep_explain:true, auto_translate:false, debounce_ms:650, alignment_mode:'heuristic'},
    ai:{providers:[]}, free:{catalog:[],enabled:[]},
  };
  let versions = [];
  let nextId = 0;
  let selectionSequence = 0;
  let autoTimers = new Map();

  const textNode = (tag, className, text) => {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  };
  const status = (message, isError = false) => {
    const el = $('#notice');
    el.textContent = message || '';
    el.classList.toggle('hidden', !message);
    el.classList.toggle('error', isError);
  };
  async function post(path, body) {
    const response = await fetch(path, {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify(body),
      credentials:'same-origin',
      cache:'no-store',
    });
    let result;
    try { result = await response.json(); }
    catch (_) { throw new Error('接口未返回有效 JSON (HTTP ' + response.status + ')'); }
    if (!response.ok) {
      const details = Array.isArray(result.attempts) ?
        '；尝试：' + result.attempts.slice(0,3).map(x => x.id + '：' + x.error).join('、') : '';
      throw new Error((result.error || 'HTTP ' + response.status) + details);
    }
    return result;
  }
  const setAppearance = () => {
    document.documentElement.dataset.theme = config.ui.theme || 'system';
    document.documentElement.dataset.glass = String(config.ui.glass !== false);
    document.documentElement.style.fontSize = (config.ui.font_size || 16) + 'px';
  };
  const engineId = () => $('#engine').value;
  const providerById = id => (config.ai.providers || []).find(x => x.id === id && x.enabled);
  const freeEnabled = id => (config.free.enabled || []).includes(id);

  async function translateText(text, source, target) {
    const id = engineId();
    if (id === 'libretranslate') {
      const result = await post('/translate', {q:text,source,target,format:'text'});
      return {text:result.translatedText, provider:'LibreTranslate · Argos'};
    }
    if (id === 'freeAuto' || freeEnabled(id)) {
      const result = await post('/fluently/api/free/translate', {
        provider_id:id, text,source,target,
      });
      return {text:result.text, provider:result.provider_id || id};
    }
    const provider = providerById(id);
    if (!provider) throw new Error('翻译引擎尚未启用，请在设置中心重新选择。');
    const result = await post('/fluently/api/ai', {
      action:'translate',provider_id:id,text,source,target,
    });
    return {text:result.text, provider:provider.name};
  }

  function renderEngineOptions() {
    const select = $('#engine');
    select.replaceChildren();
    const list = [
      {id:'bilibiliFree',name:'B站 Index-Translate · 免费 AI'},
      {id:'freeAuto',name:'智能免费翻译池 · 自动换线'},
      ...config.free.catalog.filter(p => freeEnabled(p.id) && p.id !== 'bilibiliFree'),
      {id:'libretranslate',name:'LibreTranslate · Argos 本地'},
      ...config.ai.providers.filter(p => p.enabled),
    ];
    const seen = new Set();
    list.forEach(item => {
      if (seen.has(item.id)) return;
      if (item.id === 'bilibiliFree' && !freeEnabled(item.id)) return;
      seen.add(item.id);
      const opt = textNode('option','',item.name);
      opt.value = item.id;
      select.append(opt);
    });
    const preferred = config.ui.default_engine || 'bilibiliFree';
    if (seen.has(preferred)) select.value = preferred;
    else select.value = seen.has('freeAuto') ? 'freeAuto' : (list.find(x=>seen.has(x.id))?.id || '');
  }

  function setCardStatus(version, label, kind = '') {
    const element = document.querySelector('[data-version-id="' + version.id + '"] .translation-state');
    if (element) {
      element.textContent = label;
      element.dataset.state = kind;
    }
  }
  function updateOutput(version) {
    const card = document.querySelector('[data-version-id="' + version.id + '"]');
    if (!card) return;
    const output = card.querySelector('.version-output');
    output.textContent = version.error ? version.error :
      version.translated || (version.loading ? '正在翻译…' : '翻译结果将显示在这里');
    output.classList.toggle('error-text',Boolean(version.error));
    output.classList.toggle('placeholder',!version.translated && !version.error);
    setCardStatus(version, version.loading ? '翻译中' :
      version.error ? '失败' : version.translated ? '已翻译' : '未翻译',
      version.error ? 'error' : version.translated ? 'success' : '');
    card.querySelector('.copy-translation').disabled = !version.translated;
    card.querySelector('.align-toggle').disabled = !version.translated;
    card.querySelector('.word-count').textContent = version.text.length + ' 字符';
    card.querySelector('.translation-engine-name').textContent = version.provider || '';
  }

  function renderVersions() {
    const root = $('#versions');
    root.replaceChildren();
    $('#version-count').textContent = versions.length + ' 个版本';
    versions.forEach((version, index) => {
      const card = textNode('article','glass version-card');
      card.dataset.versionId = String(version.id);
      const head = textNode('div','version-head');
      const headerLeft = textNode('div','version-name');
      headerLeft.append(textNode('span','version-number',String(index + 1).padStart(2,'0')));
      headerLeft.append(textNode('h2','', '版本 ' + String.fromCharCode(65 + index % 26) +
        (index >= 26 ? '-' + (index + 1) : '')));
      const remove = textNode('button','remove-version','移除');
      remove.type = 'button';
      remove.disabled = versions.length === 1;
      remove.title = '移除此原文版本';
      remove.addEventListener('click', () => {
        if (versions.length <= 1) return;
        clearTimeout(autoTimers.get(version.id));
        versions = versions.filter(v => v.id !== version.id);
        selectionSequence++;
        $('#selection-popup').classList.add('hidden');
        renderVersions();
      });
      head.append(headerLeft, remove);

      const sourceArea = textNode('div','version-source');
      const sourceTitle = textNode('div','version-section-title');
      sourceTitle.append(textNode('strong','', '英文原文'));
      sourceTitle.append(textNode('span','word-count',version.text.length + ' 字符'));
      const textarea = document.createElement('textarea');
      textarea.className = 'version-input';
      textarea.setAttribute('aria-label','版本 '+(index+1)+' 原文');
      textarea.placeholder = '输入第 ' + (index+1) + ' 个英文表达版本…';
      textarea.spellcheck = false;
      textarea.value = version.text;
      textarea.addEventListener('input', () => {
        version.text = textarea.value;
        version.editRevision++;
        version.requestRevision++;
        version.loading = false;
        version.translated = '';
        version.error = '';
        version.provider = '';
        const alignment = card.querySelector('.version-alignment');
        alignment.classList.add('hidden');
        updateOutput(version);
        if (config.ui.auto_translate) {
          clearTimeout(autoTimers.get(version.id));
          autoTimers.set(version.id,setTimeout(() => translateVersion(version),config.ui.debounce_ms || 650));
        }
      });
      textarea.addEventListener('mouseup', event => showSelectedText(version, 'source', textarea, event));
      textarea.addEventListener('keyup', event => {
        if (event.key.startsWith('Arrow') || event.key === 'Shift') {
          showSelectedText(version,'source',textarea,null);
        }
      });
      sourceArea.append(sourceTitle,textarea);

      const translationArea = textNode('div','version-translation');
      const translationTitle = textNode('div','version-section-title');
      translationTitle.append(textNode('strong','', '译文 · 用于逻辑对照'));
      translationTitle.append(textNode('span','translation-state','未翻译'));
      const output = textNode('div','version-output placeholder','翻译结果将显示在这里');
      output.tabIndex = 0;
      output.addEventListener('mouseup', event => showSelectedText(version, 'target', output, event));
      translationArea.append(translationTitle,output);

      const footer = textNode('div','version-footer');
      const model = textNode('span','translation-engine-name','');
      const actions = textNode('div','version-actions');
      const alignment = textNode('button','align-toggle','逐句对照');
      alignment.type = 'button';
      alignment.disabled = !version.translated;
      alignment.addEventListener('click', () => toggleAlignment(version));
      const copy = textNode('button','copy-translation','复制译文');
      copy.type = 'button';
      copy.disabled = !version.translated;
      copy.addEventListener('click', async () => {
        try { await navigator.clipboard.writeText(version.translated); status('已复制版本 ' + (index + 1) + ' 的译文。'); }
        catch (_) { status('复制失败，请手动选中文本。',true); }
      });
      const translateButton = textNode('button','translate-one','翻译此版本');
      translateButton.type = 'button';
      translateButton.addEventListener('click', () => translateVersion(version));
      actions.append(alignment,copy,translateButton);
      footer.append(model,actions);
      const alignPanel = textNode('div','version-alignment hidden');
      card.append(head,sourceArea,translationArea,footer,alignPanel);
      root.append(card);
      updateOutput(version);
    });
  }

  function addVersion() {
    if (versions.length >= 24) { status('最多支持 24 个版本，避免页面过于拥挤。',true); return; }
    versions.push({id:++nextId,text:'',translated:'',error:'',loading:false,
      provider:'',editRevision:0,requestRevision:0});
    renderVersions();
    const last = $('#versions .version-card:last-child .version-input');
    if (last) last.focus();
  }

  async function translateVersion(version) {
    const text = version.text.trim();
    if (!text) {setCardStatus(version,'请先填写原文','error');return false;}
    const revision = version.editRevision;
    const requestRevision = ++version.requestRevision;
    version.loading = true;
    version.error = '';
    version.translated = '';
    version.provider = '';
    updateOutput(version);
    try {
      const translation = await translateText(text, $('#source').value, $('#target').value);
      if (!versions.includes(version) || revision !== version.editRevision ||
          requestRevision !== version.requestRevision) return false;
      if (!translation.text || !String(translation.text).trim()) throw new Error('翻译服务返回空译文。');
      version.translated = translation.text;
      version.provider = translation.provider;
      version.error = '';
      return true;
    } catch (error) {
      if (revision === version.editRevision && requestRevision === version.requestRevision) {
        version.error = error.message || '翻译失败';
      }
      return false;
    } finally {
      if (revision === version.editRevision && requestRevision === version.requestRevision) {
        version.loading = false;
        updateOutput(version);
      }
    }
  }

  async function translateAll() {
    const pending = versions.filter(version => version.text.trim());
    if (!pending.length) {status('请至少填写一个英文原文版本。',true);return;}
    $('#translate').disabled = true;
    status('正在使用同一个引擎翻译 ' + pending.length + ' 个英文版本…');
    let succeeded = 0;
    let cursor = 0;
    const work = async () => {
      while (cursor < pending.length) {
        const version = pending[cursor++];
        if (await translateVersion(version)) succeeded++;
      }
    };
    try {
      await Promise.all(Array.from({length:Math.min(2,pending.length)},work));
      status('完成 ' + succeeded + '/' + pending.length + ' 个版本。' +
        (succeeded < pending.length ? ' 请检查失败卡片。' : ''),succeeded === 0);
    } finally {$('#translate').disabled = false;}
  }

  async function toggleAlignment(version) {
    const card = document.querySelector('[data-version-id="' + version.id + '"]');
    if (!card || !version.translated) return;
    const container = card.querySelector('.version-alignment');
    if (!container.classList.contains('hidden')) {
      container.classList.add('hidden'); return;
    }
    container.classList.remove('hidden');
    container.replaceChildren(textNode('p','', '正在建立原文与译文的句子对应关系…'));
    const revision = version.editRevision;
    try {
      const result = await post('/fluently/api/align',{
        source:version.text,target:version.translated,
        mode:config.ui.alignment_mode || 'heuristic',
      });
      if (!versions.includes(version) || revision !== version.editRevision ||
          container.classList.contains('hidden')) return;
      container.replaceChildren();
      const meta = textNode('p','alignment-meta',
        result.method === 'ai' ? 'AI 语义对齐 · 结果需核对' : '结构句子对齐 · 可能存在错配');
      container.append(meta);
      for (const group of result.groups) {
        const row = textNode('div','version-alignment-row');
        row.append(textNode('div','',
          group.source_ids.map(i=>result.source[i]?.text || '').join(' ')));
        row.append(textNode('div','',
          group.target_ids.map(i=>result.target[i]?.text || '').join(' ')));
        row.title = '置信度：' + group.confidence;
        row.addEventListener('mouseenter',()=>row.classList.add('highlighted'));
        row.addEventListener('mouseleave',()=>row.classList.remove('highlighted'));
        container.append(row);
      }
    } catch (error) {
      container.replaceChildren(textNode('p','error-text','句子对齐不可用：' + error.message));
    }
  }

  function placePopup(event, host) {
    const popup = $('#selection-popup');
    const rect = host.getBoundingClientRect();
    const width = Math.min(390, window.innerWidth - 24);
    popup.style.width = width + 'px';
    const pointerX = event && event.clientX ? event.clientX : rect.left + rect.width/2;
    const pointerY = event && event.clientY ? event.clientY : rect.top + 45;
    const left = Math.max(12,Math.min(pointerX + 12,window.innerWidth - width - 12));
    const above = pointerY + 16 + 300 > window.innerHeight;
    const top = above ? Math.max(12,pointerY - Math.min(310,window.innerHeight-24)) :
      Math.max(12,pointerY + 14);
    popup.style.left = left + 'px';
    popup.style.top = top + 'px';
    popup.style.maxHeight = 'min(430px, calc(100vh - 24px))';
  }

  function showSelectedText(version, side, element, event) {
    let selected = '';
    if (side === 'source') {
      if (element.selectionStart === element.selectionEnd) return;
      selected = element.value.slice(element.selectionStart, element.selectionEnd).trim();
    } else {
      const selection = window.getSelection();
      if (!selection || selection.isCollapsed || !element.contains(selection.anchorNode) ||
          !element.contains(selection.focusNode)) return;
      selected = selection.toString().trim();
    }
    if (!selected) return;
    if (selected.length > 600) {
      status('单次划词不超过 600 个字符。',true);return;
    }
    const selectionId = ++selectionSequence;
    $('#selection-popup').classList.remove('hidden');
    $('#selection-original').textContent = selected;
    $('#selection-translation').textContent = '正在翻译…';
    $('#selection-ai-section').classList.toggle('hidden',!config.ui.deep_explain);
    $('#selection-analysis').textContent = config.ui.deep_explain ? '正在分析表达与上下文…' : '';
    placePopup(event,element);
    const from = side === 'source' ? $('#source').value : $('#target').value;
    const to = side === 'source' ? $('#target').value :
      ($('#source').value === 'auto' ? 'en' : $('#source').value);
    translateText(selected, from, to).then(result => {
      if (selectionId === selectionSequence)
        $('#selection-translation').textContent = result.text;
    }).catch(error => {
      if (selectionId === selectionSequence)
        $('#selection-translation').textContent = '翻译失败：' + error.message;
    });
    if (!config.ui.deep_explain) return;
    const preferred = providerById(engineId());
    const expert = preferred || config.ai.providers.find(p=>p.enabled);
    const providerId = expert ? expert.id : 'bilibiliFree';
    post('/fluently/api/ai', {
      action:'explain',provider_id:providerId,text:selected,
      context:version.text.slice(0,5000),source:from,target:to,
    }).then(result => {
      if (selectionId === selectionSequence)
        $('#selection-analysis').textContent = result.text;
    }).catch(error => {
      if (selectionId === selectionSequence)
        $('#selection-analysis').textContent = '暂时无法解析：' + error.message;
    });
  }

  function closeSelection() {
    selectionSequence++;
    $('#selection-popup').classList.add('hidden');
  }
  async function boot() {
    try {
      const settingsResponse = await fetch('/fluently/api/public',{cache:'no-store'});
      if (!settingsResponse.ok) throw new Error('无法加载翻译配置。');
      config = await settingsResponse.json();
      config.free = config.free || {catalog:[],enabled:[]};
      config.ai = config.ai || {providers:[]};
      setAppearance();
      const fallbackLanguages = [
        {code:'en',name:'英语'}, {code:'zh',name:'中文'},
        {code:'ja',name:'日语'}, {code:'fr',name:'法语'},
        {code:'de',name:'德语'}, {code:'es',name:'西班牙语'},
      ];
      let languages = fallbackLanguages;
      try {
        const result = await fetch('/languages');
        if (result.ok) {
          const response = await result.json();
          if (Array.isArray(response) && response.length) languages = response;
        }
      } catch (_) { /* The independent Bilibili API works without installed Argos models. */ }
      const codes = new Set();
      const allLanguages = [...languages,...fallbackLanguages].filter(item => {
        if (!item.code || codes.has(item.code)) return false;
        codes.add(item.code);return true;
      });
      for (const lang of allLanguages) {
        for (const id of ['source','target']) {
          const option = textNode('option','',lang.name);
          option.value = lang.code;
          $('#' + id).append(option);
        }
      }
      $('#source').value = config.ui.source_language || 'en';
      $('#target').value = config.ui.target_language || 'zh';
      if (!$('#source').value) $('#source').value = 'en';
      if (!$('#target').value) $('#target').value = 'zh';
      renderEngineOptions();
      const startCount = Math.min(24, Math.max(1,config.ui.compare_count || 2));
      for (let i = 0; i < startCount; i++) {
        versions.push({id:++nextId,text:'',translated:'',error:'',loading:false,
          provider:'',editRevision:0,requestRevision:0});
      }
      renderVersions();
    } catch (error) {status(error.message,true);}
  }
  const invalidateTranslations = () => {
    for (const version of versions) {
      version.editRevision++;
      version.translated = '';
      version.error = '';
      version.provider = '';
      version.loading = false;
      updateOutput(version);
      const card = document.querySelector('[data-version-id="' + version.id + '"]');
      card?.querySelector('.version-alignment')?.classList.add('hidden');
    }
    closeSelection();
    status('已更新语言或翻译引擎，点击「翻译并对照」重新翻译。');
  };
  for (const id of ['engine','source','target']) {
    $('#' + id).addEventListener('change',invalidateTranslations);
  }
  $('#translate').addEventListener('click',translateAll);
  $('#add-version').addEventListener('click',addVersion);
  $('#add-version-bottom').addEventListener('click',addVersion);
  $('#swap-language').addEventListener('click',()=>{
    const a=$('#source').value,b=$('#target').value;
    $('#source').value = b;
    $('#target').value = a === 'auto' ? 'en' : a;
    invalidateTranslations();
  });
  $('#close-selection').addEventListener('click',closeSelection);
  document.addEventListener('keydown',event=>{
    if (event.key === 'Escape') closeSelection();
  });
  document.addEventListener('mousedown',event=>{
    if (!$('#selection-popup').classList.contains('hidden') &&
        !$('#selection-popup').contains(event.target) &&
        !event.target.closest('.version-card')) closeSelection();
  });
  boot();
})();
