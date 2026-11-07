(() => {
  'use strict';
  const $ = selector => document.querySelector(selector);
  let config = {ui:{compare_count:3, highlight:true, deep_explain:true, target_language:'en'} ,ai:{providers:[]}};
  let languages = [];
  let timer = null;
  let responses = [];
  const msg = (value, error = false) => {
    $('#notice').textContent = value || '';
    $('#notice').classList.toggle('hidden', !value);
    $('#notice').classList.toggle('error', error);
  };
  const el = (tag, className, content) => {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (content != null) node.textContent = content;
    return node;
  };
  const post = async (url, body, authenticated = false) => {
    const headers = {'Content-Type':'application/json'};
    if (authenticated) headers.Authorization = 'Bearer ' + $('#token').value;
    const result = await fetch(url, {method:'POST', headers, body:JSON.stringify(body)});
    const payload = await result.json().catch(() => ({}));
    if (!result.ok) throw Error(payload.error || 'HTTP ' + result.status);
    return payload;
  };
  const split = text => (text.match(/[^。！？.!?\n]+[。！？.!?]?|\n+/g) || [])
    .map(s => s.trim()).filter(Boolean);
  const align = () => {
    const root = $('#alignment-grid');
    root.replaceChildren();
    if (!config.ui.highlight || !responses.length) {
      $('#alignment').classList.add('hidden');
      return;
    }
    const input = split($('#original').value);
    const translated = responses.filter(r => r.text).map(r => ({
      name:r.name, sentences:split(r.text),
    }));
    if (!input.length || !translated.length) return;
    const head = el('div', 'alignment-row');
    head.append(el('strong', '', '原文'));
    translated.forEach(r => head.append(el('strong', '', r.name)));
    root.append(head);
    input.forEach((source, index) => {
      const row = el('div', 'alignment-row');
      row.append(el('span', 'sentence', source));
      translated.forEach(r => row.append(el('span', 'sentence', r.sentences[index] || '—')));
      row.addEventListener('mouseenter', () => row.classList.add('highlighted'));
      row.addEventListener('mouseleave', () => row.classList.remove('highlighted'));
      root.append(row);
    });
    root.style.setProperty('--col-count', translated.length + 1);
    $('#alignment').classList.remove('hidden');
  };
  const renderResults = () => {
    const root = $('#results');
    root.replaceChildren();
    responses.forEach(r => {
      const card = el('article', 'glass translation-card');
      const top = el('div', 'card-heading');
      top.append(el('span', 'label-dot'));
      top.append(el('h2', '', r.name));
      top.append(el('span', 'card-info', r.model));
      const value = el('div', 'translated-output', r.error || r.text || '正在翻译…');
      if (r.error) value.classList.add('error-text');
      const bottom = el('div', 'card-footer');
      bottom.append(el('span', '', r.time ? r.time + ' ms' : ''));
      const copy = el('button', '', '复制译文');
      copy.disabled = !r.text;
      copy.addEventListener('click', () => navigator.clipboard.writeText(r.text).then(() => msg('已复制译文')).catch(() => msg('复制失败',true)));
      bottom.append(copy);
      card.append(top,value,bottom);
      root.append(card);
    });
    align();
  };
  const translate = async () => {
    const text = $('#original').value.trim();
    if (!text) return msg('请输入需要翻译的文字。', true);
    const limit = config.ui.compare_count;
    const enabled = config.ai.providers.filter(p => p.enabled).slice(0,limit);
    const jobs = enabled.map(p => ({id:p.id, name:p.name, model:p.model, text:''}));
    if (!jobs.length) jobs.push({id:'libretranslate',name:'LibreTranslate',model:'Argos',text:''});
    else if (jobs.length < limit) jobs.unshift({id:'libretranslate',name:'LibreTranslate',model:'Argos',text:''});
    responses = jobs;
    renderResults();
    msg('正在执行 ' + jobs.length + ' 路翻译…');
    const source = $('#source').value, target = $('#target').value;
    await Promise.all(jobs.map(async r => {
      const started = performance.now();
      try {
        if (r.id === 'libretranslate') {
          const result = await post('/translate', {
            q:text, source, target, format:'text', api_key:localStorage.getItem('api_key') || '',
          });
          r.text = result.translatedText;
        } else {
          const result = await post('/fluently/api/ai', {
            action:'translate', provider_id:r.id, text, source, target,
          }, true);
          r.text = result.text;
        }
        r.time = Math.round(performance.now() - started);
      } catch (error) { r.error = error.message; }
      renderResults();
    }));
    const successful = jobs.filter(r => r.text).length;
    msg('完成 ' + successful + '/' + jobs.length + ' 路翻译。' +
      (successful < jobs.length ? ' 请查看各卡片错误信息。' : ''), successful === 0);
  };
  const explain = async () => {
    if (!config.ui.deep_explain) return;
    const source = $('#original');
    const selection = source.value.slice(source.selectionStart, source.selectionEnd).trim();
    if (!selection || selection.length > 600) return;
    const provider = config.ai.providers.find(p => p.enabled);
    if (!provider) return msg('请先在设置中心添加 AI 翻译服务，再使用深度讲解。', true);
    $('#explanation').classList.remove('hidden');
    $('#selected-text').textContent = '「' + selection + '」';
    $('#explanation-output').textContent = '正在分析上下文与用法…';
    try {
      const response = await post('/fluently/api/ai', {
        action:'explain', provider_id:provider.id, text:selection, context:source.value,
        source:$('#source').value, target:$('#target').value,
      }, true);
      $('#explanation-output').textContent = response.text;
    } catch (error) { $('#explanation-output').textContent = error.message; }
  };
  const boot = async () => {
    try {
      const [uiRes, langRes] = await Promise.all([
        fetch('/fluently/api/public'), fetch('/languages'),
      ]);
      if (!uiRes.ok || !langRes.ok) throw Error('无法加载服务设置或语言列表。');
      config = await uiRes.json();
      languages = await langRes.json();
      for (const item of languages) {
        const optionSource = el('option','',item.name);
        optionSource.value = item.code;
        $('#source').append(optionSource);
        const optionTarget = el('option','',item.name);
        optionTarget.value = item.code;
        $('#target').append(optionTarget);
      }
      $('#source').value = config.ui.source_language || 'auto';
      $('#target').value = config.ui.target_language || 'en';
      if (!$('#target').value && languages.length) $('#target').value = languages[0].code;
      document.documentElement.dataset.theme = config.ui.theme;
      document.documentElement.dataset.glass = String(config.ui.glass);
      document.documentElement.style.fontSize = config.ui.font_size + 'px';
    } catch (error) { msg(error.message, true); }
  };
  $('#translate').addEventListener('click', translate);
  $('#original').addEventListener('input', () => {
    $('#count').textContent = $('#original').value.length + ' 字符';
    if (!config.ui.auto_translate) return;
    if (timer) clearTimeout(timer);
    timer = setTimeout(translate, config.ui.debounce_ms);
  });
  $('#original').addEventListener('mouseup', explain);
  $('#original').addEventListener('keyup', event => {
    if (event.key === 'Shift' || event.key.startsWith('Arrow')) explain();
  });
  $('#clear').addEventListener('click', () => {
    $('#original').value = '';
    $('#count').textContent = '0 字符';
    responses = [];
    renderResults();
    $('#explanation').classList.add('hidden');
    msg('');
  });
  $('#close-explanation').addEventListener('click', () => $('#explanation').classList.add('hidden'));
  boot();
})();
