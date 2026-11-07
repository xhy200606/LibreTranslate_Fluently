/* Fluently settings: no dependencies, all network requests same-origin. */
(() => {
  'use strict';
  const qs = s => document.querySelector(s);
  const qsa = s => Array.from(document.querySelectorAll(s));
  const probeResults = new Map();
  let state = null;
  let routingData = null;
  let toastTimer = null;
  const message = (text, error = false) => {
    const toast = qs('#notice');
    clearTimeout(toastTimer);
    toast.textContent = text || '';
    toast.classList.toggle('hidden',!text);
    toast.classList.toggle('error',error);
    qs('#status').textContent = error ? '保存失败' : (text ? '设置已更新' : '');
    if (text) toastTimer=setTimeout(()=>toast.classList.add('hidden'),4100);
  };
  const api = async (path, method, body) => {
    const response = await fetch(path, {
      method, cache: 'no-store',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'same-origin',
      body: body ? JSON.stringify(body) : undefined,
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.error || 'HTTP ' + response.status);
    return data;
  };
  const el = (tag, attributes, text) => {
    const node = document.createElement(tag);
    Object.entries(attributes || {}).forEach(([key, value]) => {
      if (key === 'class') node.className = value;
      else node.setAttribute(key, value);
    });
    if (text != null) node.textContent = text;
    return node;
  };
  const field = (label, value, type = 'text') => {
    const wrapper = el('label', {class: 'input-stack'}, label);
    const input = el('input', {type, placeholder: label});
    input.value = value == null ? '' : value;
    wrapper.append(input);
    return {wrapper, input};
  };
  const restore = () => {
    if (!state) return;
    renderDefaultEngineOptions();
    qsa('[data-ui]').forEach(input => {
      const value = state.ui[input.dataset.ui];
      if (input.type === 'checkbox') input.checked = value;
      else input.value = value;
    });
    qs('#translation-prompt').value = state.ai.translation_prompt;
    qs('#explanation-prompt').value = state.ai.explanation_prompt;
    qs('#temperature').value = state.ai.temperature;
    qs('#ai-timeout').value = state.ai.timeout;
    qs('#max-tokens').value = state.ai.max_tokens;
    qsa('[data-free]').forEach(input => {input.value = state.free[input.dataset.free];});
    renderProviders();
    renderPresetOptions();
    renderReadingSettings();
    renderFreeProviders();
    document.documentElement.dataset.theme = state.ui.theme || 'system';
    document.documentElement.dataset.glass = String(state.ui.glass !== false);
    renderServer();
  };
  const renderDefaultEngineOptions = () => {
    const select = qs('#default-engine');
    select.replaceChildren();
    const options = [
      {id:'freeAuto',name:'智能免费池 · '+(state.free?.mode === 'sequential' ? '顺序回退' : '均衡负载')},
      {id:'bilibiliFree',name:'B站 Index-Translate · 免费 AI'},
      ...state.free.catalog.filter(p => state.free.enabled.includes(p.id) && p.id !== 'bilibiliFree'),
      {id:'libretranslate',name:'LibreTranslate · Argos'},
      ...state.ai.providers.filter(p=>p.enabled),
    ];
    const existing = new Set();
    options.forEach(item => {
      if (existing.has(item.id)) return;
      existing.add(item.id);
      const opt = el('option', {value:item.id}, item.name);
      select.append(opt);
    });
    select.value = existing.has(state.ui.default_engine) ?
      state.ui.default_engine : 'freeAuto';
  };

  const renderPresetOptions = () => {
    const select=qs('#provider-preset');
    const previous=select.value;
    select.replaceChildren();
    (state.ai_presets || []).forEach(preset=>{
      const option=el('option',{value:preset.id},preset.name +
        (preset.protocol === 'bilibili' ? ' · 内置免费服务' : ' · '+preset.protocol));
      select.append(option);
    });
    if ((state.ai_presets||[]).some(p=>p.id===previous)) select.value=previous;
  };
  const renderReadingSettings = () => {
    const reading=state.ai.reading;
    const select=qs('#reading-provider');
    select.replaceChildren();
    const options=[
      {id:'bilibiliFree',name:'B站 Index-Translate · 免费'},
      ...state.ai.providers.filter(p=>p.enabled),
    ];
    options.forEach(option=>select.append(el('option',{value:option.id},option.name)));
    select.value=options.some(p=>p.id===reading.analysis_provider_id) ?
      reading.analysis_provider_id : 'bilibiliFree';
    qs('#dictionary-source').replaceChildren();
    (state.dictionary_sources || []).forEach(source=>{
      qs('#dictionary-source').append(el('option',{value:source.id},source.name));
    });
    qs('#dictionary-source').value=reading.dictionary_source;
    qs('#learning-level').value=reading.learning_level;
    qs('#explanation-depth').value=reading.explanation_depth;
    qsa('[data-reading-prompt]').forEach(input=>{
      input.value=reading.prompts[input.dataset.readingPrompt] || '';
    });
  };

  const refreshRouting = async () => {
    if (!state) return;
    try {
      routingData=await api('/fluently/api/free/routing?source='+
        encodeURIComponent(state.ui.source_language)+'&target='+
        encodeURIComponent(state.ui.target_language),'GET');
      renderFreeProviders();
    } catch(error) {message('分流权重无法读取：'+error.message,true);}
  };
  const BASE_WEIGHTS={
    microsoft:5,bilibiliFree:2,transmart:3,volcengineFree:3,
    doubaoWeb:1,google:3,youdaoFree:3,icibaFree:3,
    yandexFree:2,myMemory:1,reversoFree:1,apertiumFree:1,
    alibabaFree:3,modernMtFree:2,laraFree:2,lingvanexFree:2,
  };
  const currentWeights = () => {
    if (!state) return {};
    const enabled=state.free.enabled;
    const raw={};
    for (const id of state.free.order) {
      if (!enabled.includes(id)) {raw[id]=0;continue;}
      if (routingData?.health?.[id]?.cooldown > 0) {raw[id]=0;continue;}
      if (id==='apertiumFree' &&
          ['zh','zh-tw','ja','ko'].includes(state.ui.target_language)) {raw[id]=0;continue;}
      raw[id]=(routingData?.weights?.[id] || BASE_WEIGHTS[id] || 1);
    }
    const total=Object.values(raw).reduce((a,b)=>a+b,0);
    if (!total) return Object.fromEntries(Object.keys(raw).map(k=>[k,0]));
    // Largest remainder keeps the displayed proportions summing to 100%.
    const fractions=Object.entries(raw).map(([id,value])=>{
      const exact=value*1000/total;
      return {id,units:Math.floor(exact),rest:exact-Math.floor(exact)};
    });
    let missing=1000-fractions.reduce((a,b)=>a+b.units,0);
    fractions.sort((a,b)=>b.rest-a.rest);
    for (const item of fractions) {if (!missing) break;item.units++;missing--;}
    return Object.fromEntries(fractions.map(i=>[i.id,i.units/10]));
  };

  const newId = () => 'service_' + Math.random().toString(36).slice(2, 12);
  const renderProviders = () => {
    const root = qs('#providers-list');
    root.replaceChildren();
    state.ai.providers.forEach((provider, index) => {
      const card = el('article', {class: 'glass card provider'});
      const heading = el('div', {class: 'provider-head'});
      heading.append(el('h3', {}, provider.name || '自定义 AI 服务'));
      const deleteButton = el('button', {class: 'danger', type: 'button'}, '移除');
      deleteButton.addEventListener('click', () => {
        state.ai.providers.splice(index, 1);
        renderProviders();
        renderReadingSettings();
      });
      heading.append(deleteButton);
      card.append(heading);
      const fields = el('div', {class: 'two-columns'});
      const refs = [
        ['名称', 'name', 'text'],
        ['模型 ID', 'model', 'text'],
        ['Base URL', 'base_url', 'url'],
        ['新的 API Key（留空保留原密钥）', 'api_key', 'password'],
      ];
      for (const [label, key, type] of refs) {
        const item = field(label, key === 'api_key' ? '' : provider[key], type);
        item.input.autocomplete = 'off';
        item.input.addEventListener('input', () => { provider[key] = item.input.value; });
        fields.append(item.wrapper);
      }
      card.append(fields);
      const protocol=el('label',{class:'provider-protocol'},'接口协议');
      const protocolSelect=el('select',{'aria-label':'接口协议'});
      for (const [value,label] of [
        ['openai','OpenAI Chat Completions'],['anthropic','Anthropic Messages'],
        ['gemini','Gemini generateContent'],['azure-openai','Azure OpenAI'],
      ]) protocolSelect.append(el('option',{value},label));
      protocolSelect.value=provider.protocol||'openai';
      protocolSelect.addEventListener('change',()=>provider.protocol=protocolSelect.value);
      protocol.append(protocolSelect);
      card.append(protocol);
      const toolbar = el('div', {class: 'provider-toolbar'});
      const enabled = el('input', {type: 'checkbox'});
      enabled.checked = provider.enabled !== false;
      enabled.addEventListener('change', () => { provider.enabled = enabled.checked; renderReadingSettings(); });
      const toggle = el('label', {}, '启用该服务');
      toggle.prepend(enabled);
      toolbar.append(toggle);
      if (provider.has_api_key) toolbar.append(el('small', {}, '密钥已保存（不可查看）'));
      const clear = el('button', {type: 'button'}, '清除密钥');
      clear.addEventListener('click', () => { provider.clear_api_key = true; provider.has_api_key = false; message('已标记清除密钥，点击保存后生效。'); });
      toolbar.append(clear);
      const test = el('button', {type: 'button'}, '测试连接');
      test.addEventListener('click', async () => {
        try {
          test.disabled = true;
          const result = await api('/fluently/api/ai', 'POST', {action:'test', text:'你好', provider_id:provider.id});
          message('连接成功：' + result.model + ' → ' + result.text);
        } catch (error) { message(error.message, true); }
        finally { test.disabled = false; }
      });
      toolbar.append(test);
      card.append(toolbar, el('p', {class: 'hint'}, '修改服务参数后先保存，再运行连接测试。'));
      root.append(card);
    });
  };

  const renderFreeProviders = () => {
    const root = qs('#free-providers-list');
    root.replaceChildren();
    if (!state.free || !state.free.catalog) return;
    const weights=currentWeights();
    qs('#free-enabled-count').textContent='已启用 '+state.free.enabled.length+' 个';
    const effectiveTotal=Object.values(weights).reduce((a,b)=>a+b,0);
    qs('#free-weight-total').textContent='当前权重合计 '+effectiveTotal.toFixed(1)+'%';
    state.free.order.forEach((ident,index) => {
      const provider = state.free.catalog.find(p => p.id === ident);
      if (!provider) return;
      const card = el('article',{class:'glass free-source-card'});
      const heading = el('div',{class:'free-source-head'});
      const title = el('div',{class:'free-source-title'});
      title.append(el('strong',{},provider.name));
      title.append(el('p',{},provider.description));
      const enabled = el('input',{type:'checkbox', 'aria-label':'启用 ' + provider.name});
      enabled.checked = state.free.enabled.includes(ident);
      enabled.addEventListener('change', () => {
        if (!enabled.checked && state.free.enabled.length === 1) {
          enabled.checked = true;
          message('至少保留一个启用的翻译数据源。',true);
          return;
        }
        state.free.enabled = enabled.checked ?
          [...new Set([...state.free.enabled,ident])] :
          state.free.enabled.filter(x=>x!==ident);
        renderDefaultEngineOptions();
        renderFreeProviders();
      });
      heading.append(title,enabled);
      const diagnostic = probeResults.get(ident);
      const detail = el('p',{class:'probe-result'});
      detail.textContent = diagnostic ?
        (diagnostic.available ? '● 可用 · '+diagnostic.latency_ms+' ms · '+(diagnostic.tested_direction || 'en→zh') +
           (diagnostic.preview ? ' · '+diagnostic.preview.slice(0,38) : '') :
           '● 不可用 · '+(diagnostic.error || '请求失败')) :
        '● 尚未探测';
      detail.classList.toggle('available',Boolean(diagnostic?.available));
      detail.classList.toggle('unavailable',Boolean(diagnostic && !diagnostic.available));
      const health=routingData?.health?.[ident];
      if (!diagnostic && health && health.cooldown>0)
        detail.textContent='● 恢复中 · '+health.cooldown+' 秒后重新尝试';
      else if (!diagnostic && health && health.success_count>0)
        detail.textContent='● 近期成功 '+health.success_count+' 次';
      const share=el('div',{class:'free-share'});
      share.append(el('span',{},'预计分流 '+Number(weights[ident]||0).toFixed(1)+'%'));
      if (health?.selections) share.append(el('span',{},'池内已选 '+health.selections+' 次'));
      const bar=el('div',{class:'weight-track'});
      const fill=el('span',{class:'weight-fill'});
      fill.style.width=(weights[ident]||0)+'%';
      bar.append(fill);
      const actions = el('div',{class:'free-source-actions'});
      const up = el('button',{type:'button','aria-label':'前移 '+provider.name},'↑');
      const down = el('button',{type:'button','aria-label':'后移 '+provider.name},'↓');
      up.disabled = index === 0;
      down.disabled = index === state.free.order.length-1;
      const move = n => {
        const items = state.free.order;
        [items[index],items[index+n]] = [items[index+n],items[index]];
        renderFreeProviders();
      };
      up.addEventListener('click',()=>move(-1));
      down.addEventListener('click',()=>move(1));
      const test = el('button',{type:'button'},'单独检测');
      test.addEventListener('click',async()=>{
        if (!state.free.enabled.includes(ident)) {
          detail.textContent='请先启用并保存此服务，或使用上方一键探测。'; return;
        }
        test.disabled = true;
        detail.textContent='连接检测中…';
        const started=Date.now();
        try {
          const result=await api('/fluently/api/free/translate','POST',{
            provider_id:ident, text:'Hello world.', source:'en',
            target:ident==='apertiumFree' ? 'es' : 'zh',
          });
          probeResults.set(ident,{available:true,latency_ms:Date.now()-started,
            preview:result.text,tested_direction:'en→'+(ident==='apertiumFree'?'es':'zh')});
        } catch(error) {
          probeResults.set(ident,{available:false,error:error.message,latency_ms:Date.now()-started});
        } finally {await refreshRouting();}
      });
      actions.append(up,down,test);
      card.append(heading,detail,share,bar,actions);
      root.append(card);
    });
  };
  const renderServer = () => {
    const root = qs('#server-groups');
    root.replaceChildren();
    const labels = { network:'网络与部署', security:'安全与 API Key', limits:'限流与配额', frontend:'原版前端', models:'语言模型', operations:'性能与运维' };
    Object.entries(labels).forEach(([group, title]) => {
      const entries = state.server.filter(x => x.group === group);
      if (!entries.length) return;
      const card = el('div', {class: 'glass card'});
      card.append(el('h3', {}, title));
      for (const option of entries) {
        const row = el('div', {class: 'field-row'});
        const desc = el('div');
        desc.append(el('strong', {}, 'LT_' + option.name));
        desc.append(el('p', {}, '默认值：' + (option.secret ? '隐藏' : JSON.stringify(option.default)) + ' · 需重启'));
        row.append(desc);
        let input;
        if (option.type === 'bool') {
          input = el('select');
          [['', '继承默认值'], ['true', '启用'], ['false', '关闭']].forEach(([value, label]) => {
            const selectOption = el('option', {value}, label);
            input.append(selectOption);
          });
          input.value = option.value == null ? '' : String(option.value);
        } else {
          input = el('input', {type: option.secret ? 'password' : option.type === 'int' ? 'number' : 'text'});
          input.placeholder = option.secret ? (option.configured ? '已设置；留空保持不变' : '未设置') : '留空恢复默认';
          input.value = option.value == null ? '' : option.value;
        }
        input.dataset.server = option.name;
        if (option.secret) input.dataset.secret = '1';
        row.append(input);
        card.append(row);
      }
      root.append(card);
    });
  };
  const collect = () => {
    const ui = {};
    qsa('[data-ui]').forEach(input => {
      ui[input.dataset.ui] = input.type === 'checkbox' ? input.checked :
        input.type === 'number' ? Number(input.value) : input.value;
    });
    const ai = {
      providers: state.ai.providers.map(p => {
        const out = {id: p.id, name: p.name, model: p.model,
          base_url: p.base_url, enabled: p.enabled !== false,
          protocol:p.protocol||'openai',service_id:p.service_id||'custom'};
        if (p.api_key) out.api_key = p.api_key;
        if (p.clear_api_key) out.clear_api_key = true;
        return out;
      }),
      translation_prompt: qs('#translation-prompt').value,
      explanation_prompt: qs('#explanation-prompt').value,
      temperature: Number(qs('#temperature').value),
      timeout: Number(qs('#ai-timeout').value),
      max_tokens: Number(qs('#max-tokens').value),
      reading: { ...state.ai.reading,
        analysis_provider_id:qs('#reading-provider').value,
        dictionary_source:qs('#dictionary-source').value,
        learning_level:qs('#learning-level').value,
        explanation_depth:qs('#explanation-depth').value,
        prompts:Object.fromEntries(qsa('[data-reading-prompt]').map(input=>[
          input.dataset.readingPrompt,input.value,
        ])),
      },
    };
    const server = {};
    qsa('[data-server]').forEach(input => {
      const field = state.server.find(s => s.name === input.dataset.server);
      if (field.secret && !input.value) return;
      server[field.name] = !input.value ? null : field.type === 'bool' ?
        input.value === 'true' : field.type === 'int' ? Number(input.value) : input.value;
    });
    const free = {...state.free};
    delete free.catalog;
    qsa('[data-free]').forEach(input => {
      free[input.dataset.free] = input.type === 'number' ? Number(input.value) : input.value;
    });
    return {ui, ai, server, free};
  };
  const load = async () => {
    try {
      state = await api('/fluently/api/settings','GET');
      restore();
      await refreshRouting();
      qs('#status').textContent = '设置已加载';
    } catch(error) {
      message('无法加载设置：'+error.message+'。内网免令牌模式请删除 LT_SETTINGS_ADMIN_TOKEN 环境变量。',true);
    }
  };
  qs('[data-free="mode"]').addEventListener('change', () => {
    if (state) { state.free.mode=qs('[data-free="mode"]').value;
      renderDefaultEngineOptions(); }
  });
  qs('#default-engine').addEventListener('change', () => {
    if (state) state.ui.default_engine = qs('#default-engine').value;
  });
  qs('#probe-all').addEventListener('click',async()=>{
    if (!state) {message('尚未加载设置。',true);return;}
    const button=qs('#probe-all');
    button.disabled=true;
    button.textContent='探测进行中…';
    qs('#probe-summary').textContent='正在检测全部 16 个来源（可能需要若干秒）';
    try {
      const result=await api('/fluently/api/free/probe','POST',{apply_available:true});
      result.results.forEach(item=>probeResults.set(item.id,item));
      state.free.enabled=result.enabled;
      await refreshRouting();
      renderDefaultEngineOptions();
      qs('#probe-summary').textContent=result.available_count+'/'+result.total_count+' 个可用 · '+result.eligible_count+' 个符合目标语言';
      message(result.applied ?
        '探测完成：已保存并启用 '+result.eligible_count+' 个与默认目标语言匹配的来源。':
        '没有适合默认目标语言的已通过检测来源，已保留原启用列表。',
        !result.applied);
    } catch(error) {
      qs('#probe-summary').textContent='检测失败';
      message(error.message,true);
    } finally {
      button.disabled=false;
      button.textContent='重新探测并启用可用源';
    }
  });
  qs('#save').addEventListener('click', async () => {
    if (!state) { message('设置尚未加载。', true); return; }
    try {
      const payload = collect();
      const response = await api('/fluently/api/settings', 'PUT', payload);
      state = response.settings;
      restore();
      await refreshRouting();
      message('设置已保存。服务器启动参数需重启后生效。');
    } catch (error) { message(error.message, true); }
  });
  qs('#add-provider').addEventListener('click', () => {
    if (!state) {message('设置尚未加载。',true);return;}
    if (state.ai.providers.length >= 32) {message('最多配置 32 个 AI 服务。',true);return;}
    const preset=state.ai_presets.find(p=>p.id===qs('#provider-preset').value);
    if (!preset) return;
    if (preset.protocol==='bilibili') {
      state.ai.reading.analysis_provider_id='bilibiliFree';
      renderReadingSettings();
      message('B站免费 API 已内置，现已选为阅读模型；保存后生效。');
      return;
    }
    const newService={
      id:newId(),name:preset.name,base_url:preset.base_url,
      model:preset.model,protocol:preset.protocol,
      service_id:preset.id,enabled:true,
    };
    state.ai.providers.push(newService);
    renderProviders();
    renderReadingSettings();
    renderDefaultEngineOptions();
    message('已添加服务模板，请检查模型、URL 与 API Key 后保存。');
  });
  qs('#reset-reading-prompts').addEventListener('click',()=>{
    if (!state) return;
    state.ai.reading.prompts={...state.reading_defaults.prompts};
    renderReadingSettings();
    message('已恢复阅读卡片提示词，点击保存后生效。');
  });
  qsa('[data-demo-mode]').forEach(button=>button.addEventListener('click',()=>{
    qsa('[data-demo-mode]').forEach(b=>b.classList.toggle('active',b===button));
    const demo=qs('#reading-demo');
    demo.replaceChildren();
    if (button.dataset.demoMode==='word') {
      demo.append(el('strong',{},'curious'),el('p',{},'好奇的；求知欲强的'));
      const meta=el('div',{class:'dictionary-meta'});
      meta.append(el('span',{class:'dictionary-pos'},'形容词 · adj.'),
        el('span',{},'/ˈkjʊəriəs/'));
      demo.append(meta,el('p',{},'Eager to know or learn something.'));
    } else {
      demo.append(el('strong',{},'Every language offers a new way to see the world.'),
        el('p',{},'每一种语言，都带来一种看世界的新方式。'));
      const chips=el('div',{class:'analysis-structure'});
      for (const part of ['Every language · 主语','offers · 谓语','a new way · 宾语','to see the world · 后置定语'])
        chips.append(el('span',{class:'demo-chip'},part));
      demo.append(chips);
    }
  }));
  qsa('[data-tab]').forEach(button => button.addEventListener('click', () => {
    qsa('[data-tab]').forEach(node => node.classList.toggle('active', node === button));
    qsa('[data-panel]').forEach(node => node.classList.toggle('hidden', node.dataset.panel !== button.dataset.tab));
  }));
  load();
})();
