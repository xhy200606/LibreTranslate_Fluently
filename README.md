# LibreTranslate Fluently

基于 [LibreTranslate](https://github.com/LibreTranslate/LibreTranslate)（AGPL-3.0）扩展的自托管多引擎翻译工作台。参考 [FluentRead](https://github.com/FluentRead/FluentRead) 的兼容 AI 翻译服务配置和上下文讲解思路。本项目独立实现 Web GUI，不复制 FluentRead 的源码。

## 功能

- 保留 LibreTranslate 原有 `/translate`、文件翻译和 REST API。
- 新增 `/fluently` 翻译工作台、`/fluently/settings` 可视化设置中心。
- 支持多个 OpenAI Chat Completions 兼容服务（包括 OpenAI、DeepSeek、Ollama、兼容网关等），每个服务分别配置 Base URL、模型、API Key、开关。
- 支持多路并排结果对比（1–6 个）、按句序粗略双语高亮、选中文字后由 AI 结合上下文讲解。
- 支持主题、液态玻璃、字号、翻译延迟、来源与目标语言、AI 提示词、温度、超时、最大 Token、全部已登记的 LT_ 服务端参数在 GUI 内配置。
- 兼容 LibreTranslate 原有 API。设置保存在本地 JSON，Docker 使用命名卷持久化。

## Docker 安装

```sh
git clone https://github.com/xhy200606/LibreTranslate_Fluently.git
cd LibreTranslate_Fluently
cp .env.example .env
# 编辑 .env：设置一个高强度的 LT_SETTINGS_ADMIN_TOKEN
docker compose up -d --build
```

打开 http://localhost:5000/fluently ，或 http://localhost:5000/fluently/settings 。

点击「管理授权」并输入 .env 中的管理员令牌，即可修改设置。令牌只保存在网页内存中；刷新页面后需重新输入。翻译工作台调用已配置的 AI 服务时也需输入令牌，避免公开部署时陌生人耗费 API 额度。

**重要：** Docker Compose 启动时设置 `LT_SETTINGS_ADMIN_TOKEN` 是必需的。配置保存在 `fluently_data` 数据卷中；删除数据卷会丢失设置。AI Key 不会通过设置读取接口返回，也不会写入浏览器 localStorage。请限制服务器和 Docker 数据卷的访问权限。

## 兼容 AI 端点

GUI 接收 API 服务器根地址（自动补 `/v1/chat/completions`）、`/v1` 地址（自动补 `/chat/completions`）或完整 Chat Completions 路径。例如：

| 提供商 | Base URL 示例 |
| --- | --- |
| OpenAI | `https://api.openai.com/v1` |
| DeepSeek | `https://api.deepseek.com` （如服务商路径不一致，请填完整路径） |
| Ollama | `http://host.docker.internal:11434/v1` |
| 自定义兼容网关 | `https://example.com/v1/chat/completions` |

请在服务商文档中确认接口路径、模型名与配额。当前 AI 适配器只支持非流式 Chat Completions，不支持原生 Gemini、Anthropic Messages、Responses API 的直接接入。测试连接会发送短文本，可能产生费用。

服务器主动请求第三方接口。默认限制非 HTTPS 远程地址、私有网络地址以及 HTTP 重定向，防止越权访问内网服务。需要部署局域网 Ollama 时，可设置 `LT_AI_ALLOW_PRIVATE_NETWORK=true`，仅在可信私有环境中使用。

## 设置生效范围

| 分类 | 生效方式 |
| --- | --- |
| UI、提示词、模型 API | 保存后，刷新翻译工作台即可更新，后续 AI 请求立即读取配置 |
| LT_ 服务器选项 | 写入持久化配置，下次容器或进程重启后生效 |
| Docker 端口映射、环境变量、存储、TLS 终止 | 仍需在 Docker/代理层配置；GUI 无法动态修改容器基础设施 |

原有 LibreTranslate 设置仍可以使用环境变量。GUI 保存的服务器覆盖项在 **下次启动时** 优先于对应环境变量；清空并保存即可恢复使用原有环境变量。请不要在公开互联网上直接暴露管理令牌。服务端重启后端口映射需要与新端口保持一致。

## API

- `GET /fluently/api/public`：只读公开 GUI 参数及启用的 AI 服务元信息，不返回密钥/地址。
- `GET /fluently/api/settings`：管理员认证，读取设置，敏感字段仅含 `has_api_key` 或 `configured` 标识。
- `PUT /fluently/api/settings`：管理员认证，保存 `ui`、`ai`、`server` 配置。
- `POST /fluently/api/ai`：管理员认证，支持 `translate`、`explain`、`test`。
- 管理员接口需请求头 `Authorization: Bearer <LT_SETTINGS_ADMIN_TOKEN>`。

## 原项目与授权

LibreTranslate © LibreTranslate contributors, [AGPL-3.0](LICENSE). 本项目遵循上游许可证。FluentRead 仅作为交互与接口设计参考，不表示本项目已获得其认证或具备浏览器扩展的所有功能。


## 免费翻译协议池（第二阶段）

Fluently 新增 16 路参考 FluentRead 公共协议资料独立编写的服务端适配器：Microsoft Edge、B站 Index-Translate、腾讯交互、火山、豆包网页、Google、有道、金山词霸、Yandex、MyMemory、Reverso、Apertium、阿里网页、ModernMT、Lara 与 Lingvanex。

在 **设置中心 → 免费翻译协议** 可启停、排序、调整超时和冷却、测试单个节点，选择“顺序回退”或“智能加速”。工作台可以单独选择任何已启用的免费服务，或通过“智能免费翻译池”自动换线。

支持按 Unicode 码点分块，MyMemory 按最多 500 UTF-8 字节分块，保留换行与前后空白。网页匿名协议可能随供应商更新而失效，成功初始化并不表示全部节点可用。部分协议（特别是豆包 SSE、Google 网页接口与词霸加密响应）需要真实联网验收；当前只提供代码级接入与独立状态提示，不保证每个地区都能连通。若被限制，应停用相关服务，不尝试绕过服务商验证或额度限制。

免费的含义是 **不需要为网页服务配置 API Key**，不意味着供应商保证免费、无限量或允许大规模自动访问。自建 Docker 部署仍需考虑第三方服务条款、文本隐私与出口网络。

## 句子对齐引擎

\`POST /fluently/api/align\` 支持对原文和译文的分句、原文字符偏移、动态规划结构对齐（1:1、1:2、2:1、2:2、1:3、3:1）与匹配置信度。启用“AI 语义对齐”后可使用第一条已启用的大模型对齐拆分、合并与语序调整，并校验每个句子索引的完整覆盖与唯一性。AI 失败时降级为结构对齐。

结构分数主要依靠相对长度、数字及专有词锚点，**不能验证语义正确**；跨语序复杂句需要 AI 语义对齐，也不能保证百分之百准确。当前高亮位于工作台“逐句对照”区域，并非编辑框中字符级联动。

管理接口（仍需管理员令牌）：
- \`GET /fluently/api/free/providers\`：服务目录与进程内健康状态
- \`POST /fluently/api/free/translate\`：指定免费服务（\`provider_id\`）或 \`freeAuto\` 自动换线
- \`POST /fluently/api/align\`：传入 \`source\`、\`target\` 与可选 \`mode: "ai"\`

服务池健康数据当前只保存在运行实例内存中；Gunicorn 多 worker 之间不共享统计，不保证跨重启恢复。免费节点的所有 HTTP 请求都不携带个人浏览器 Cookie；豆包仅使用单次请求取得的匿名访客参数。
