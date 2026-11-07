/* Fluently settings: no dependencies, all network requests same-origin. */
(() => {
  'use strict';
  const qs = s => document.querySelector(s);
  const qsa = s => Array.from(document.querySelectorAll(s));
  let token = '';
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
      headers: { 'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json' },
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
    renderServer();
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
    state.free.order.forEach((ident, index) => {
      const provider = state.free.catalog.find(p => p.id === ident);
      if (!provider) return;
      const card = el('div', {class:'glass card free-provider'});
      const line = el('div', {class:'free-provider-line'});
      const title = el('div');
      title.append(el('h3', {}, provider.name));
      title.append(el('p', {}, provider.description));
      const toggle = el('label', {class:'free-toggle'});
      const checkbox = el('input', {type:'checkbox'});
      checkbox.checked = state.free.enabled.includes(ident);
      checkbox.addEventListener('change', () => {
        if (!checkbox.checked && state.free.enabled.length === 1 && state.free.enabled.includes(ident)) {
          checkbox.checked = true;
          message('至少保留一个免费翻译服务。', true);
          return;
        }
        state.free.enabled = checkbox.checked ?
          [...new Set([...state.free.enabled, ident])] :
          state.free.enabled.filter(x => x !== ident);
      });
      toggle.append(checkbox, el('span', {}, '启用'));
      const buttons = el('div', {class:'free-actions'});
      const up = el('button', {type:'button'}, '↑');
      const down = el('button', {type:'button'}, '↓');
      up.disabled = index === 0;
      down.disabled = index === state.free.order.length - 1;
      const move = offset => {
        const items = state.free.order;
        [items[index], items[index + offset]] = [items[index + offset], items[index]];
        renderFreeProviders();
      };
      up.addEventListener('click', () => move(-1));
      down.addEventListener('click', () => move(1));
      const test = el('button', {type:'button'}, '测试连接');
      const feedback = el('small', {class:'free-status'}, '尚未检测');
      test.addEventListener('click', async () => {
        if (!token) { message('请先解锁设置。', true); return; }
        // A disabled service can be tested without modifying saved preferences
        if (!state.free.enabled.includes(ident)) {
          feedback.textContent = '请先启用并保存该服务。';
          return;
        }
        test.disabled = true;
        feedback.textContent = '检测中…';
        const start = Date.now();
        try {
          const target = ident === 'apertiumFree' ? 'es' : 'zh';
          const data = await api('/fluently/api/free/translate', 'POST',
            {provider_id:ident, text:'Hello world.', source:'en', target});
          feedback.textContent = '连接正常 · ' + (Date.now() - start) + 'ms · ' + data.text.slice(0,45);
        } catch (error) { feedback.textContent = '失败：' + error.message; }
        finally { test.disabled = false; }
      });
      buttons.append(up, down, test);
      line.append(title, toggle, buttons);
      card.append(line, feedback);
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
  const connect = async () => {
    token = qs('#admin-token').value.trim();
    if (!token) { message('请输入管理员令牌。', true); return; }
    try {
      state = await api('/fluently/api/settings', 'GET');
      restore();
      message('已解锁管理设置。');
    } catch (error) { token = ''; message(error.message, true); }
  };
  qs('#connect').addEventListener('click', connect);
  qs('#admin-token').addEventListener('keydown', event => {
    if (event.key === 'Enter') connect();
  });
  qs('#save').addEventListener('click', async () => {
    if (!state) { message('请先解锁设置。', true); return; }
    try {
      const payload = collect();
      const response = await api('/fluently/api/settings', 'PUT', payload);
      state = response.settings;
      restore();
      message('设置已保存。界面与 AI 选项立即生效；服务端 LT_ 参数需重启后生效。');
    } catch (error) { message(error.message, true); }
  });
  qs('#add-provider').addEventListener('click', () => {
    if (!state) { message('请先解锁设置。', true); return; }
    if (state.ai.providers.length >= 12) { message('最多配置 12 个服务。', true); return; }
    state.ai.providers.push({
      id: newId(), name: '自定义服务', base_url: 'https://api.openai.com/v1',
      model: 'gpt-4o-mini', enabled: true,
    });
    renderProviders();
  });
  qsa('[data-tab]').forEach(button => button.addEventListener('click', () => {
    qsa('[data-tab]').forEach(node => node.classList.toggle('active', node === button));
    qsa('[data-panel]').forEach(node => node.classList.toggle('hidden', node.dataset.panel !== button.dataset.tab));
  }));
})();
