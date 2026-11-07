# LibreTranslate Fluently

基于 [LibreTranslate](https://github.com/LibreTranslate/LibreTranslate)（AGPL-3.0）的内网翻译工作台。借鉴 [FluentRead](https://github.com/FluentRead/FluentRead) 的多服务配置思路，独立实现 Web UI。

## 多英文版本对照

每个卡片输入一个独立的英文版本（默认两个，可随时添加/删除，最多 24 个）。**全页仅使用一个翻译引擎**，分别翻译每个版本并并排比较中文表达与逻辑，而不是用多个翻译服务翻译同一段文字。

工具栏把原文语言、目标语言、翻译引擎、翻译按钮放在一行，所有控件垂直居中。首页不显示营销介绍，也不显示管理员令牌。

在原文文本框或译文区域选中文字后，弹出统一的划词卡片：上方为划词翻译；开启 AI 上下文解析后，下方结合当前版本全文解释用词和语境。可通过每张卡片的“逐句对照”检查句子结构匹配。

## Docker 内网部署（不需要管理员令牌）

~~~sh
git clone https://github.com/xhy200606/LibreTranslate_Fluently.git
cd LibreTranslate_Fluently
docker compose up -d --build
~~~

访问：
- 翻译工作台：http://<内网主机IP>:5000/fluently
- 设置中心：http://<内网主机IP>:5000/fluently/settings

此 Compose 默认不要求或传递 LT_SETTINGS_ADMIN_TOKEN。原有部署如果通过其他方式额外传入了此环境变量，需删除并重启容器。所有普通设置通过 GUI 修改；Docker 端口映射和反向代理配置仍需部署层处理。

**内网安全警告：** 免令牌意味着任何能访问该服务端口的人都可以更改配置并触发 AI 请求。务必将 5000 端口限制在可信局域网或 VPN，**不得直接暴露公网**；若多人使用，请通过反向代理加访问控制。已保存的第三方 API Key 不会在 GUI 读接口中明文返回，但仍有额度与费用风险。

## 默认翻译引擎

默认选择 **智能免费翻译池 · 均衡负载**，服务端调用 Bilibili 官方公开的 OpenAI 兼容 API：

- API：https://index-translate.bilibili.com/v1/chat/completions
- 模型：Index-Translate-35B-A3B
- 无需用户 API Key，非流式请求，关闭 thinking 输出，检查截断和空响应
- 官方参考：[bilibili/Index-Translate](https://github.com/bilibili/Index-Translate)

B站是翻译专用模型，AI 讲解不一定与通用 LLM 一样充分。可在设置中添加 OpenAI Chat Completions 兼容模型，划词解析优先使用已配置的通用模型。B站免费公共服务可能限流或变更。

## 免费翻译协议中心

16 路候选：B站、Microsoft Edge、Google、腾讯交互、火山、豆包网页、有道、金山词霸、Yandex、MyMemory、Reverso、Apertium、阿里网页、ModernMT、Lara、Lingvanex。

各服务以小卡片显示名称、状态、启停开关、单独测试及上下调整顺序。**一键探测全部并启用可用源**向各供应商发送固定的 “Hello world.” 测试句（不会传递你的英文稿件），并发最多 4 路；仅将实际测试目标语言与 GUI 默认目标语言匹配的成功来源自动保存为启用状态；没有匹配来源时保留原配置。Apertium 检测 en→es（成功仅代表西语可用，不会被误选用于默认中文目标），其他服务通常检测 en→zh。成功仅证明当时、该方向可用，并非无限量或长期可用保证。

免费池可启用自动换线；部分网页内部协议可能遇到访问限制或接口变更。

## GUI 与 API

设置中心允许调整：初始原文版本数量、默认引擎、语言、主题、字体、玻璃外观、AI 解析开关、AI 模型 API、提示词、免费源顺序/超时/冷却，以及已登记 LibreTranslate LT_ 参数（需要重启生效）。

主要 API：
- GET /fluently/api/public
- GET/PUT /fluently/api/settings
- GET /fluently/api/free/providers
- POST /fluently/api/free/probe （JSON: {"apply_available":true}）
- POST /fluently/api/free/translate
- POST /fluently/api/ai
- POST /fluently/api/align

保留上游 /translate、文件翻译及其它 REST API。数据保存在 Docker 的 fluently_data 命名卷；AI API 密钥仅保存在服务端，设置读取 API 只返回 has_api_key 标识。

## 测试与限制

离线测试覆盖：16 路探测的状态、B站请求结构、无令牌内网 GUI、跨源写入拒绝、分句对齐和输入验证。真实 Docker 构建、供应商实际连通性与浏览器交互仍需进行部署验收。匿名网页协议不是稳定保证的公共 API。

遵循 [LibreTranslate AGPL-3.0](LICENSE) 授权。FluentRead 仅为设计与功能参考。


## v4 · 自动分流、阅读卡片和 API 预设

### 默认均衡负载

新的默认翻译引擎为 **智能免费翻译池**，默认模式为 balanced。它按照 FluentRead 免费服务目录的基础权重、已观察到的成功率与响应速度计算预计分流比例，在可用节点中按权重随机挑选。失败时从剩余节点重试，不绕过冷却及语言支持限制。

设置中心可以看到每个已启用服务的预计分流百分比、历史选中次数与当前状态。预计权重不是实际流量份额。健康信息暂存每个 Gunicorn 工作进程内存中，重启后清零，不在进程间共享；启停数据仍通过 GUI 持久化。免费来源可能限流或变更，请务必在内网使用，并遵守各供应商的服务协议。

### 划词卡片

- 单词模式：上方显示中文译文，下方展示词典的词性、音标、英文释义与例句。
- 句子模式：显示译文、AI 大意、句法、用法、练习。句法分析按 FluentRead 约定的四列 Text / POS / Role / Meaning 提取语法片段，以可点击彩色卡片显示词性、句中作用与含义。AI 可能输出不完整结构，需人工确认。
- 解析可独立开关，使用独立选定的模型和学习提示词；其他英文版本的原文不会混入当前卡片上下文。
- 词典来源遵循 FluentRead 的六类：ECDICT 本地、网易有道、Free Dictionary API、Wiktionary REST、WiktAPI、Datamuse。自动模式优先本地 ECDICT，未命中后查在线词典。随项目保留 MIT 授权下的 ECDICT 常用 3,000 词条与原始授权说明，文件在 libretranslate/static/data/ecdict-core.LICENSE.md。词典参考项目为 https://github.com/skywind3000/ECDICT。

### AI 服务 API 预设

设置中心新增 29 种服务模板，包括 B站 Index-Translate（内置免 Key）、OpenAI、DeepSeek、通义、智谱、Kimi、豆包、Claude、Gemini、Azure OpenAI、OpenRouter、SiliconFlow、Groq、Mistral、Together、MiniMax、xAI、Ollama、LM Studio、NewAPI 等。

当前真正支持四种后台接口：OpenAI Chat Completions 兼容、Anthropic Messages、Gemini generateContent 和 Azure OpenAI Chat Completions。各模板包含名称、URL、协议与参考模型，但不赠送 API 密钥，也不保证模板中的模型版本仍可调用。FluentRead 特有的 Chrome 浏览器本地翻译、ChatGPT 订阅 OAuth、以及需要云服务签名的专业机器翻译 API 仍须单独适配；本项目不会把未接入的协议标为可用。

阅读卡片默认提示词按 FluentRead 的系统、大意、句法、用法、练习五类正文提供可编辑配置，保留学习程度、回答深度以及目标语言变量（to、learningLevel、explanationDepth）。提示词正文引自 FluentRead（GPL-3.0），许可证和来源说明随 third_party/FluentRead.NOTICE.md 保留；其它程序为本项目独立实现。

### 界面

首页移除了「英文版本对照」大标题和多余提示段落，收紧原文语言、目标语言、翻译引擎工具栏。普通消息提示改为顶部右侧浮层 Toast。Fluently SVG Logo 同时用于导航栏、设置界面与 favicon。

### 新增服务端 API

- GET /fluently/api/free/routing?source=en&target=zh — 获取预计权重与健康统计
- POST /fluently/api/dictionary — 单词查询；例：{"word":"curious","source":"auto"}
- POST /fluently/api/reading — 学习解析；例：{"text":"Every language offers.","context":"...","action":"grammar","target":"zh"}
- GET /fluently/api/reading/catalog — 阅读模型模板及词典目录

所有选中的词或句子及其必要上下文可能发送到配置的第三方词典/AI 服务。隐私优先时选用 ECDICT 本地词库和可信本地大模型。

第三方参考：[FluentRead](https://github.com/FluentRead/FluentRead)。词典来源 [ECDICT](https://github.com/skywind3000/ECDICT) 遵循 MIT，许可文件与数据同目录保留。上游 LibreTranslate 继续遵循 AGPL-3.0。
