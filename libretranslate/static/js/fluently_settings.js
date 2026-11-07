/* Fluently settings: no dependencies, all network requests same-origin. */
(() => {
  'use strict';
  const qs = s => document.querySelector(s);
  const qsa = s => Array.from(document.querySelectorAll(s));
  const probeResults = new Map();
  let state = null;
  const message = (text, error = false) => {
    qs('#notice').textContent = text;
    qs('#notice').classList.toggle('hidden', !text);
    qs('#notice').classList.toggle('error', error);
    qs('#status').textContent = error ? '操作失败' : (text ? '已更新' : '');
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
    renderFreeProviders();
    document.documentElement.dataset.theme = state.ui.theme || 'system';
    document.documentElement.dataset.glass = String(state.ui.glass !== false);
    renderServer();
  };
  const renderDefaultEngineOptions = () => {
    const select = qs('#default-engine');
    select.replaceChildren();
    const options = [
      {id:'bilibiliFree',name:'B站 Index-Translate · 免费 AI'},
      {id:'freeAuto',name:'智能免费池 · 自动换线'},
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
      state.ui.default_engine : 'bilibiliFree';
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
      const toolbar = el('div', {class: 'provider-toolbar'});
      const enabled = el('input', {type: 'checkbox'});
      enabled.checked = provider.enabled !== false;
      enabled.addEventListener('change', () => { provider.enabled = enabled.checked; });
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
      });
      heading.append(title,enabled);
      const diagnostic = probeResults.get(ident);
      const detail = el('p',{class:'probe-result'});
      detail.textContent = diagnostic ?
        (diagnostic.available ? '● 可用 · '+diagnostic.latency_ms+' ms' +
           (diagnostic.preview ? ' · '+diagnostic.preview.slice(0,38) : '') :
           '● 不可用 · '+(diagnostic.error || '请求失败')) :
        '● 尚未探测';
      detail.classList.toggle('available',Boolean(diagnostic?.available));
      detail.classList.toggle('unavailable',Boolean(diagnostic && !diagnostic.available));
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
          probeResults.set(ident,{available:true,latency_ms:Date.now()-started,preview:result.text});
        } catch(error) {
          probeResults.set(ident,{available:false,error:error.message,latency_ms:Date.now()-started});
        } finally {renderFreeProviders();}
      });
      actions.append(up,down,test);
      card.append(heading,detail,actions);
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
          base_url: p.base_url, enabled: p.enabled !== false};
        if (p.api_key) out.api_key = p.api_key;
        if (p.clear_api_key) out.clear_api_key = true;
        return out;
      }),
      translation_prompt: qs('#translation-prompt').value,
      explanation_prompt: qs('#explanation-prompt').value,
      temperature: Number(qs('#temperature').value),
      timeout: Number(qs('#ai-timeout').value),
      max_tokens: Number(qs('#max-tokens').value),
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
      qs('#status').textContent = '设置已加载';
    } catch(error) {
      message('无法加载设置：'+error.message+'。内网免令牌模式请删除 LT_SETTINGS_ADMIN_TOKEN 环境变量。',true);
    }
  };
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
      renderFreeProviders();
      renderDefaultEngineOptions();
      qs('#probe-summary').textContent=result.available_count+'/'+result.total_count+' 个可用';
      message(result.applied ?
        '探测完成：已保存并启用 '+result.available_count+' 个可用来源，不可用来源已停用。':
        '全部检测失败，已保留原启用列表。请检查服务器网络或供应商访问状态。',
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
      message('设置已保存。界面与 AI 选项立即生效；服务端 LT_ 参数需重启后生效。');
    } catch (error) { message(error.message, true); }
  });
  qs('#add-provider').addEventListener('click', () => {
    if (!state) { message('设置尚未加载。', true); return; }
    if (state.ai.providers.length >= 12) { message('最多配置 12 个服务。', true); return; }
    state.ai.providers.push({
      id: newId(), name: '自定义服务', base_url: 'https://api.openai.com/v1',
      model: 'gpt-4o-mini', enabled: true,
    });
    renderProviders();
    renderDefaultEngineOptions();
  });
  qsa('[data-tab]').forEach(button => button.addEventListener('click', () => {
    qsa('[data-tab]').forEach(node => node.classList.toggle('active', node === button));
    qsa('[data-panel]').forEach(node => node.classList.toggle('hidden', node.dataset.panel !== button.dataset.tab));
  }));
  load();
})();
