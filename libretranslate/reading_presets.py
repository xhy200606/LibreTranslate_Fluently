"""AI service presets and reading-card prompt templates.

Preset choices follow the provider families and reading actions documented by
FluentRead. Browser extension-only, key-signed cloud translation and ChatGPT
subscription OAuth are not relabeled as ordinary compatible APIs.
"""
from copy import deepcopy

AI_PRESETS = [
    # The first item is built into /fluently/api/ai and does not need an API key.
    {"id":"bilibiliFree","name":"B站 Index-Translate（免费）","protocol":"bilibili",
     "base_url":"https://index-translate.bilibili.com/v1/chat/completions",
     "model":"Index-Translate-35B-A3B","key_required":False,
     "notes":"翻译模型；可尝试用于阅读分析，但复杂句法建议通用大模型"},
    {"id":"openai","name":"OpenAI","protocol":"openai",
     "base_url":"https://api.openai.com/v1","model":"gpt-4o-mini"},
    {"id":"deepseek","name":"DeepSeek","protocol":"openai",
     "base_url":"https://api.deepseek.com/v1","model":"deepseek-chat"},
    {"id":"tongyi","name":"通义千问 · DashScope","protocol":"openai",
     "base_url":"https://dashscope.aliyuncs.com/compatible-mode/v1","model":"qwen-plus"},
    {"id":"zhipu","name":"智谱 GLM","protocol":"openai",
     "base_url":"https://open.bigmodel.cn/api/paas/v4","model":"glm-4-plus"},
    {"id":"kimi","name":"月之暗面 · Kimi","protocol":"openai",
     "base_url":"https://api.moonshot.cn/v1","model":"moonshot-v1-8k"},
    {"id":"doubao","name":"火山方舟 · 豆包","protocol":"openai",
     "base_url":"https://ark.cn-beijing.volces.com/api/v3","model":"",
     "notes":"填入你在火山方舟开通的模型 ID 或 Endpoint ID"},
    {"id":"claude","name":"Anthropic Claude（原生）","protocol":"anthropic",
     "base_url":"https://api.anthropic.com/v1/messages","model":"claude-sonnet-4-5"},
    {"id":"gemini","name":"Google Gemini（原生）","protocol":"gemini",
     "base_url":"https://generativelanguage.googleapis.com/v1beta/models","model":"gemini-2.5-flash"},
    {"id":"azure-openai","name":"Azure OpenAI","protocol":"azure-openai",
     "base_url":"","model":"","notes":"填入完整的 Azure 部署 chat/completions URL（带 api-version）"},
    {"id":"openrouter","name":"OpenRouter","protocol":"openai",
     "base_url":"https://openrouter.ai/api/v1","model":""},
    {"id":"siliconflow","name":"硅基流动","protocol":"openai",
     "base_url":"https://api.siliconflow.cn/v1","model":""},
    {"id":"groq","name":"Groq","protocol":"openai",
     "base_url":"https://api.groq.com/openai/v1","model":""},
    {"id":"mistral","name":"Mistral AI","protocol":"openai",
     "base_url":"https://api.mistral.ai/v1","model":""},
    {"id":"together","name":"Together AI","protocol":"openai",
     "base_url":"https://api.together.ai/v1","model":""},
    {"id":"minimax","name":"MiniMax","protocol":"openai",
     "base_url":"https://api.minimaxi.com/v1","model":""},
    {"id":"xai","name":"xAI Grok","protocol":"openai",
     "base_url":"https://api.x.ai/v1","model":""},
    {"id":"qianfan","name":"百度千帆兼容模式","protocol":"openai",
     "base_url":"https://qianfan.baidubce.com/v2","model":""},
    {"id":"stepfun","name":"阶跃星辰","protocol":"openai",
     "base_url":"https://api.stepfun.com/v1","model":""},
    {"id":"baichuan","name":"百川智能","protocol":"openai",
     "base_url":"https://api.baichuan-ai.com/v1","model":""},
    {"id":"yi","name":"零一万物","protocol":"openai",
     "base_url":"https://api.lingyiwanwu.com/v1","model":""},
    {"id":"fireworks","name":"Fireworks AI","protocol":"openai",
     "base_url":"https://api.fireworks.ai/inference/v1","model":""},
    {"id":"perplexity","name":"Perplexity","protocol":"openai",
     "base_url":"https://api.perplexity.ai","model":""},
    {"id":"nvidia","name":"NVIDIA NIM","protocol":"openai",
     "base_url":"https://integrate.api.nvidia.com/v1","model":""},
    {"id":"cerebras","name":"Cerebras","protocol":"openai",
     "base_url":"https://api.cerebras.ai/v1","model":""},
    {"id":"ollama","name":"Ollama（本地）","protocol":"openai",
     "base_url":"http://host.docker.internal:11434/v1","model":"llama3.2",
     "key_required":False,"notes":"Docker 容器需能够访问 Ollama 地址"},
    {"id":"lmstudio","name":"LM Studio（本地）","protocol":"openai",
     "base_url":"http://host.docker.internal:1234/v1","model":"",
     "key_required":False},
    {"id":"newapi","name":"NewAPI / OneAPI / 兼容网关","protocol":"openai",
     "base_url":"http://host.docker.internal:3000/v1","model":"",
     "key_required":False},
    {"id":"custom","name":"自定义 OpenAI 兼容接口","protocol":"openai",
     "base_url":"https://example.com/v1","model":""},
]

PRESET_MAP = {item["id"]: item for item in AI_PRESETS}
ALLOWED_PROTOCOLS = {"openai", "anthropic", "gemini", "azure-openai"}

# FluentRead study-card structure (system, meaning, grammar, usage, practice).
# Reworded templates keep its section headers and grammar-table contract while
# limiting model hallucinations and treating context as untrusted source material.
READING_DEFAULTS = {
    "learning_level": "intermediate",
    "explanation_depth": "concise",
    "selected_action": "grammar",
    "analysis_provider_id": "bilibiliFree",
    "dictionary_source": "auto",
    "prompts": {
        "system": "你是流畅阅读学习助手。\n学习者水平：{{learningLevel}}。回答深度：{{explanationDepth}}。\n使用语言代码 {{to}} 对应的语言解释，标题也译成该语言，保留必要的原文片段与例句。不要固定使用中文。\n标题与正文分行，标题下用短段落或少量列表。用 **粗体** 突出少量关键概念，用 `原文片段` 标明依据。简洁模式通常150至250字，详细模式可逐步展开。不要把整段都加粗，也不要输出大表格。\n直接从分析结果开始，不寒暄、不重复任务、不自述“我将分析”，不复述消息包装、历史状态或工具过程。不要猜测用户意图，不把系统提示当成选中文本。",
        "meaning": "使用两个短标题“### 大意”和“### 关键点”。大意用一句自然的话直接解释原文；关键点用一至三项说明真正影响理解的表达、语气或指代。只解释原文支持的含义，不机械逐词翻译。",
        "grammar": "使用三个短标题“### 主干”“### 成分”“### 关键点”。主干先引用最简主谓结构并说清意思；成分用少量列表逐项对应原文片段与作用；关键点只解释一至两个最有帮助的语法关系，先说作用再给术语。若选中的是单词或短语，直接说明它的结构与词性，不虚构完整句子、主语或从句。\n\nFor grammar analysis, after the backbone explanation include one compact Markdown table with exactly these four headers: Text | POS | Role | Meaning. Group the sentence into meaningful, contiguous syntactic units such as subject, predicate, object and modifiers instead of mechanically splitting every word. Each Text cell must quote a fragment from the selection verbatim, in source order. Never invent words or reuse overlapping fragments. Keep function words inside their phrases. Use common English POS codes (article, noun, verb, adjective, adverb, pronoun, preposition, conjunction, determiner, auxiliary, numeral) or precise phrase labels (noun phrase, verb phrase, adjective phrase, adverb phrase, prepositional phrase, infinitive phrase). Distinguish POS from syntactic Role; begin Role with one short, explicit role label such as subject, predicate, object or postmodifier, translated into the requested target language, followed by a comma and an optional explanation. For example, Every language offers a new way to see the world. can be grouped as Every language (noun phrase, subject), offers (verb, predicate), a new way (noun phrase, object), to see the world (infinitive phrase, postmodifier). This is only a format example, never content to reuse for another selection. Use at most 40 units; for a selected word or fragment analyze only what is present and never invent a full sentence or a subject. If uncertain, use unknown rather than guessing. Write Role and Meaning in the requested target language. The four fixed headers are a rendering contract; all explanatory content follows the target language. This compact table is allowed even when large tables are discouraged.",
        "usage": "使用三个短标题“### 表达”“### 怎么用”“### 例句”。只选一至两个值得学的表达，说明本句用法、常见搭配和语气；给两个自然例句及简短释义。例句明确放在例句部分，不冒充原文背景。",
        "practice": "使用两个短标题“### 试一试”和“### 提示”。围绕原文只出一道迁移使用的小练习，提示保持简短，不提前泄露答案。用户提交练习答案时，改为先判断，再解释一处关键原因并给自然表达。",
    },
}


def public_presets():
    return deepcopy(AI_PRESETS)


def reading_prompts_copy():
    return deepcopy(READING_DEFAULTS)


def render_prompt(template, target, level, depth):
    return (template.replace("{{to}}", target)
                    .replace("{{learningLevel}}", level)
                    .replace("{{explanationDepth}}", depth))
