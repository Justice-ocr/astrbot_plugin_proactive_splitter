# astrbot_plugin_proactive_splitter

<div align="center">
  <img src="logo.png" width="128" alt="astrbot_plugin_proactive_splitter logo">

  <p>语境感知主动消息、智能分段、Markdown 表格与数学公式转图片</p>

  <p>
    <a href="https://github.com/Justice-ocr/astrbot_plugin_proactive_splitter"><img src="https://img.shields.io/badge/GitHub-Repository-181717" alt="GitHub repository"></a>
    <img src="https://img.shields.io/badge/AstrBot-%3E%3D%204.10.2-orange" alt="AstrBot >= 4.10.2">
    <img src="https://img.shields.io/badge/License-AGPL--3.0-blue" alt="AGPL-3.0">
    <img src="https://img.shields.io/badge/Version-v1.6.1-brightgreen" alt="v1.6.1">
  </p>
</div>

## 项目定位

这是一个面向 AstrBot 的合并插件，组合了三类能力：

1. 根据私聊或群聊上下文主动发起消息。
2. 将普通 AI 回复和主动消息拆分为更自然的多条消息。
3. 在拆分前识别 Markdown 表格与数学公式，将其整体渲染为图片发送。

本项目基于以下仓库的功能与实现继续开发：

- [Justice-ocr/astrbot_plugin_proactive_chat](https://github.com/Justice-ocr/astrbot_plugin_proactive_chat)
- [DBJD-CR/astrbot_plugin_proactive_chat](https://github.com/DBJD-CR/astrbot_plugin_proactive_chat)
- [nuomicici/astrbot_plugin_splitter](https://github.com/nuomicici/astrbot_plugin_splitter)
- [luosheng520qaq/astrbot_plugin_nobrowser_markdown_to_pic](https://github.com/luosheng520qaq/astrbot_plugin_nobrowser_markdown_to_pic)
- [Whereis-Alice/astrbot_plugin_math_render](https://github.com/Whereis-Alice/astrbot_plugin_math_render)

当前仓库：[Justice-ocr/astrbot_plugin_proactive_splitter](https://github.com/Justice-ocr/astrbot_plugin_proactive_splitter)

## 功能概览

### 主动消息

- 分别配置私聊与群聊会话。
- 根据 AstrBot 对话历史、平台消息流水或两者混合生成主动消息。
- 支持自定义主动消息提示词和会话级差异配置。
- 支持免打扰时段、最小/最大触发间隔和最大未回复次数。
- 用户重新发言后自动清除未回复计数并重置相关任务。
- 持久化下次触发时间，AstrBot 重启后恢复仍有效的任务。
- 支持 TTS；可选择发送语音后是否继续发送文本。

### 语境感知调度

下一次主动消息不是只依靠固定随机时间。启用 `enable_contextual_timing` 后，插件按以下顺序生成调度计划：

1. 调用当前会话使用的 LLM，判断最近用户消息是否包含明确的时间语境。
2. LLM 不可用、超时或没有给出有效判断时，使用本地规则识别时间表达。
3. 都没有命中时，在配置的最小/最大间隔内随机选择。

本地规则可以识别的典型语境包括：

- `30 分钟后`、`2 小时后` 等明确延迟。
- 明天、明早。
- 勿扰、睡觉、晚安。
- 开会、上课、考试、工作。
- 通勤、开车、地铁、飞机。
- 吃饭、洗澡、看电影、打游戏、稍后再聊。

最终计划会记录调度策略、命中规则、原因和来源，并显示在管理端中。

### 智能分段

统一分段器同时处理：

- AstrBot 的普通 AI 回复。
- 本插件生成的主动消息。

普通回复使用 `unified_splitter_settings`；主动消息优先沿用对应会话的 `segmented_reply_settings`。

主要行为：

- 支持符号列表和正则表达式两种分段模式。
- 保护括号、引号、书名号等成对符号中的内容。
- 保护 Markdown 代码块和 `<think>...</think>` 块。
- 支持智能均分、最大段数、最短段长和保护词。
- 支持分段前清理、分段后清理、批量替换和反向替换。
- 支持线性、对数、随机和固定延迟。
- 可分别控制图片、At、表情和其他媒体组件的发送位置。
- 可在第一段引用原消息。
- 普通回复可逐段适配 AstrBot TTS。

### 表格与公式转图片

富内容识别发生在普通文本分段之前，因此表格和公式不会先被拆碎。

支持识别：

- 标准 Markdown 表格。
- `$...$` 和 `$$...$$`。
- `\(...\)` 和 `\[...\]`。
- `\begin{...} ... \end{...}` LaTeX 环境。
- `\frac`、`\sqrt`、`\sum`、`\int` 等常用 LaTeX 命令。

不会转图：QQ 能直接显示的 `∑`、`∫`、`π`、`≤`、`→`、`×`、上标/下标等 Unicode 字符，以及 `x = y`、`a + b`、`B650 / B850` 这类普通文本算式。

模型偶尔会输出缺少 `$` 定界符的 `\frac`、`\left`、`\lim` 等 LaTeX 源码，插件会在渲染前自动补齐定界符。单独成行的 `[` 与 `]` 包围明确 LaTeX 时，也会作为一个完整公式块处理，不会拆成多条消息。

示例：

```markdown
| 项目 | 数值 |
| --- | ---: |
| A | 10 |
| B | 20 |
```

```latex
$$
E = mc^2
$$
```

处理结果：

1. 复杂公式交给 MathJax 3 + Playwright 渲染，Markdown 表格交给 PillowMD 渲染。
2. 渲染成功后生成临时 PNG，并作为独立图片消息发送。
3. 渲染失败时保留为一个完整文本块，不再对其分段。

当公式字符占有效文本字符的比例达到配置阈值时，插件会把说明文字、公式和表格作为完整 Markdown 一起转图。长回复优先按公式块、表格、空行和段落边界拆成多张图，不会从公式中间截断。

代码围栏中的 `$`、数学符号和竖线不会触发表格或公式识别。

> 本功能是对模型输出文本进行模式识别，不是 OCR，不会读取图片中的表格或公式。

### 管理端

插件提供两套管理入口：

- 独立 WebUI，默认地址为 `http://127.0.0.1:4100/`。
- 支持该能力的 AstrBot 版本中，会注册原生 Plugin Page。

管理端可以：

- 查看运行状态、会话、计时器和 APScheduler 任务。
- 查看下次触发时间、未回复次数和语境调度原因。
- 明确显示因达到未回复次数上限而暂停的会话。
- 查看表格/公式转图的启用状态、渲染策略、累计成功/失败次数和最近错误。
- 立即触发、重新调度或取消任务。
- 编辑全部全局配置，包括统一分段、表格/公式转图、通知与遥测设置。
- 使用结构化列表增删文本查找/替换规则。
- 为单个会话保存差异配置。
- 查看插件文档和远程通知。

## 运行要求

- AstrBot `>= 4.10.2`
- Python `>= 3.10`
- 支持的平台：
  - aiocqhttp
  - qq_official
  - telegram
  - wecom
  - lark
  - dingtalk
  - kook

插件声明的额外依赖：

- `apscheduler>=3.10,<4.0`
- `aiofiles>=23.2`
- `fastapi>=0.110`
- `uvicorn>=0.29`
- Python 3.10 使用 `tomli>=2.0,<3.0`

## 安装

### 从仓库安装

在 AstrBot 插件管理器中使用以下仓库地址：

```text
https://github.com/Justice-ocr/astrbot_plugin_proactive_splitter
```

也可以将仓库克隆到 AstrBot 的插件目录：

```bash
cd data/plugins
git clone https://github.com/Justice-ocr/astrbot_plugin_proactive_splitter.git
```

安装依赖并重启 AstrBot：

```bash
pip install -r data/plugins/astrbot_plugin_proactive_splitter/requirements.txt
```

### 从旧插件升级

请停用或移除以下插件，避免多个 `on_decorating_result` 处理器同时接管消息：

- `astrbot_plugin_proactive_chat`
- `astrbot_plugin_splitter`

合并版仍使用原主动聊天插件的数据目录 `astrbot_plugin_proactive_chat`，因此已有的会话数据、任务数据和会话差异配置不需要手动迁移。

## 快速配置

### 1. 获取会话标识

推荐使用 AstrBot 的 `/sid` 命令获取完整 UMO。

常见格式：

```text
default:FriendMessage:123456789
default:GroupMessage:123456789
```

`session_list` 也能匹配规范化 UMO 或纯目标 ID，但完整 UMO 最明确。

### 2. 启用私聊主动消息

在 `friend_settings` 中：

1. 打开 `enable`。
2. 将目标 UMO 加入 `session_list`。
3. 设置 `schedule_settings.min_interval_minutes` 和 `max_interval_minutes`。
4. 按需设置 `quiet_hours` 和 `max_unanswered_times`。

默认私聊配置：

| 配置 | 默认值 | 作用 |
| --- | ---: | --- |
| `min_interval_minutes` | 30 | 最短主动消息间隔 |
| `max_interval_minutes` | 600 | 最长主动消息间隔 |
| `quiet_hours` | `1-7` | 免打扰时段 |
| `max_unanswered_times` | 4 | 连续未回复达到此值后暂停 |
| `enable_contextual_timing` | `true` | 使用 LLM/规则预测时间 |
| `contextual_timing_history_count` | 8 | 时间判断读取的最近消息数 |
| `contextual_timing_llm_timeout_seconds` | 15 | 时间判断 LLM 超时 |

### 3. 启用群聊主动消息

在 `group_settings` 中：

1. 打开 `enable`。
2. 将目标 UMO 加入 `session_list`。
3. 设置 `group_idle_trigger_minutes`。
4. 按需调整群聊提示词、上下文来源和调度范围。

群聊会在收到消息后重置沉默计时器；达到沉默时长后才进入主动消息流程。

### 4. 选择上下文来源

`context_settings.source_mode` 支持：

| 值 | 含义 |
| --- | --- |
| `conversation_history` | 使用 AstrBot 当前 LLM 对话历史 |
| `platform_message_history` | 使用平台最近的真实消息流水 |
| `hybrid` | 同时使用两者 |

还可以配置平台历史条数、是否包含 Bot 消息以及 Bot 标识符。

### 5. 配置普通回复分段

`unified_splitter_settings` 默认开启，且 `split_scope` 默认为 `llm_only`。

常用配置：

| 配置 | 默认值 | 作用 |
| --- | ---: | --- |
| `enable_split` | `true` | 启用普通回复分段 |
| `split_mode` | `simple` | `simple` 或 `regex` |
| `max_segments` | 7 | 普通文本最大段数 |
| `min_segment_length` | 10 | 最短分段字数 |
| `balanced_split_mode` | `true` | 尽量均衡各段长度 |
| `enable_reply` | `true` | 第一段引用原消息 |
| `delay_strategy` | `linear` | 段间延迟算法 |

### 6. 配置表格和公式转图

相关配置位于 `unified_splitter_settings`：

| 配置 | 默认值 | 作用 |
| --- | ---: | --- |
| `enable_rich_render` | `true` | 启用表格和公式转图 |
| `inject_rich_prompt` | `true` | 提示模型使用标准 Markdown/LaTeX |
| `rich_render_full_reply_math_ratio` | `45` | 公式占比达到该百分比时整回复转图；`0` 关闭 |
| `rich_render_full_reply_max_chars` | `1600` | 整回复转图时每张图片的目标最大字符数 |
| `rich_render_style_path` | 空 | 表格使用的 PillowMD 自定义样式目录 |
| `rich_render_font_size` | `25` | 图片正文字号 |
| `rich_render_width` | `1000` | 图片最大内容宽度（像素） |
| `rich_render_scale` | `2` | MathJax 图片清晰度倍率 |
| `rich_render_mathjax_cdn_url` | jsDelivr MathJax 3 | MathJax 脚本地址 |
| `rich_render_mathjax_timeout` | `20` | 单次公式渲染超时（秒） |
| `rich_render_mathjax_auto_install_browser` | `true` | 缺少 Chromium 时自动安装 |
| `rich_render_auto_page` | `false` | 表格长内容自动分页排版 |
| `rich_render_transparent_background` | `false` | 使用透明背景并移除装饰 |
| `rich_render_cache_ttl` | `180` | 临时 PNG 保留时间（秒） |

公式占比按回复中非空白字符计算，只有被识别为明确 LaTeX 的内容计入公式字符；QQ 可直接显示的普通算式和 Unicode 数学符号不计入。

MathJax 使用持久 Chromium 页面。首次缺少浏览器时会安装 `chromium-headless-shell`，下载量约 270 MB；Linux root/container 还会自动运行 `playwright install-deps chromium` 安装 `libnspr4` 等系统库。浏览器和 MathJax 加载完成后会持续复用。本机测试冷启动约 4 秒，热渲染复杂公式约 56-63 ms，实际耗时取决于机器和网络。

Linux 非 root 环境无法由插件自动安装系统包，需要在宿主机执行：

```bash
sudo python -m playwright install-deps chromium
python -m playwright install chromium-headless-shell
```

## 主动消息分段与普通回复分段的区别

| 消息来源 | 使用的配置 |
| --- | --- |
| 普通 AI 回复 | `unified_splitter_settings` |
| 主动消息 | 会话内的 `segmented_reply_settings` |

无论主动消息是否启用文本分段，表格和公式识别仍会先执行，以保证富内容不会被拆散。

主动消息中的 `words_count_threshold` 保留原插件语义：文本长度不超过阈值时允许分段，超过阈值时整段发送。

## 数据目录

插件继续使用：

```text
data/plugin_data/astrbot_plugin_proactive_chat/
```

主要文件包括：

- `session_data.json`：会话状态、未回复次数和调度信息。
- `session_overrides.json`：会话级差异配置。
- `notifications_cache.json`：通知缓存。
- `attachments/`：主动消息历史补写所需附件。

## 网络与隐私说明

以下功能可能产生外部网络请求：

### 语境调度和主动消息生成

最近消息和提示词会发送给当前会话配置的 LLM 提供商，这是生成主动消息和预测下次触发时间所必需的。

### 富内容转图

表格由 PillowMD 在本地渲染。公式由本地 Chromium 中的 MathJax 渲染，默认会从 `rich_render_mathjax_cdn_url` 加载 MathJax 脚本，因此首次加载会访问对应地址；公式正文不会提交给远程文转图 API。浏览器上下文会缓存脚本资源。

生成的临时图片会在 `rich_render_cache_ttl` 到期或插件停止时删除。

### 通知中心

`notification_settings.enabled` 默认为 `true`，插件会定期从远程通知服务拉取插件通知。可以关闭。

### 匿名遥测

`telemetry_config.enabled` 默认为 `true`。遥测包含启动、关闭、心跳、功能使用、配置统计和脱敏错误信息。

实现中会：

- 将会话列表替换为数量。
- 删除主动消息提示词。
- 脱敏 UMO、路径、Prompt 和常见密钥字段。
- 不主动上传消息正文。

不需要遥测时请关闭 `telemetry_config.enabled`。

## WebUI 安全

独立 WebUI 默认：

```text
host = 127.0.0.1
port = 4100
password = 空
```

默认仅监听本机。如果将 `host` 改为 `0.0.0.0`、`::` 或其他可远程访问地址，应同时：

1. 设置强密码。
2. 配置防火墙或反向代理访问控制。
3. 不要直接暴露到不可信网络。

## 已知边界

- 表格识别要求存在标准 Markdown 表头分隔行，例如 `| --- | --- |`。
- 行内公式所在的整行会渲染为图片，而不是只渲染 `$...$` 中的局部内容。
- 缺少 `$` / `$$` 的明确 LaTeX 命令会在渲染前自动补齐定界符。
- 只有明确的 LaTeX 语法和 Markdown 表格会触发转图；普通 Unicode 数学符号和文本算式保持原样发送。
- 表格效果取决于 PillowMD，复杂公式效果取决于 MathJax 3 的 TeX 支持。
- 无效命令（例如模型误写的 `\Ve`）仍需模型修正为有效 LaTeX，渲染器不会猜测命令含义。
- 首次公式渲染需要启动 Chromium 并加载 MathJax；后续复用持久页面。
- AstrBot 版本未提供 `register_web_api` 时，Plugin Page 后端不会注册，但独立 WebUI 和核心主动消息功能仍可使用。
- 只有 `session_list` 中明确配置的会话会启用主动消息；统一分段器的作用范围由自己的作用域、黑白名单和群聊开关控制。

## 开发与验证

仓库包含以下核心模块：

```text
main.py                         插件入口和 AstrBot 事件钩子
core/contextual_scheduler.py    LLM/规则/随机三级调度
core/chat_flow.py               主动消息主流程
core/message_sender.py          主动消息发送、TTS 和平台历史补写
core/rich_content.py            表格和公式识别
core/unified_splitter.py        普通/主动消息统一分段管线
core/web_admin_server.py        独立 WebUI 与 AstrBot Page API
pages/proactive-chat/           AstrBot Plugin Page
tests/                          富内容、分段和语境调度测试
```

基础检查：

```bash
python -m compileall -q .
pip install pytest
python -m pytest tests -q
node --check pages/proactive-chat/page-app.js
```

## 许可证与致谢

本项目使用 GNU Affero General Public License v3.0，详见 [LICENSE](LICENSE)。

来源与第三方说明见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。感谢主动聊天插件、Splitter 插件和 AstrBot 的原作者及贡献者。
