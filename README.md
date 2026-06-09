# Novel Writer 小说创作插件

Novel Writer 会在用户要求 Bot 写小说、写故事、续写剧情或根据人设创作文艺内容时，调用框架 LLM 生成小说正文。若安装并启用可选插件 `forward_msg`，会优先通过合并转发消息发送；否则可按配置直接发送正文。

## 功能

- 根据 `config/core.toml` 中的 Bot 人设、背景故事和表达风格创作小说。
- 默认使用框架 `model_tasks.actor` 模型任务。
- 可在插件配置中指定 `config/model.toml` 里的模型名称。
- 支持配置温度、最大输出 token、默认最低字数、最低段落数。
- 可选配合 `forward_msg` 把长篇正文拆分为多个合并转发节点发送。
- 可通过管理员命令 `/novel` 直接生成一篇简短小说。
- 可通过配置开关完全禁用 `write_novel` Action 和 `/novel` 命令。

## 可选功能：合并转发

需要启用 `forward_msg` 插件，并提供以下 Service，才能优先通过合并转发发送小说：

```text
forward_msg:service:forward_msg_protocol
```

`forward_msg` 插件市场地址：<http://39.96.71.162/plugin/forward_msg>

`forward_msg` 是可选功能插件，不再作为强依赖阻塞 `novel_writer` 加载。如果未安装、未启用或发送失败，且 `fallback_to_direct_send = true`，插件会先提醒用户“小说内容过多可能导致刷屏”，然后把小说正文拆成多条普通消息直接发送。

## 触发方式

### Chatter 自动触发

当用户在聊天中表达以下意图时，默认 chatter 可调用本插件：

- “写小说”
- “写故事”
- “编故事”
- “创作小说”
- “续写剧情”
- “根据人设和背景写一段文学内容”

示例：

```text
@Bot 写一篇你和三月七在星穹列车上的日常小说，温柔一点，篇幅长一些。
```

### 管理员命令触发

管理员可以使用 `/novel` 直接生成一篇简短小说：

```text
/novel 写一篇赛博狐狸在雨夜守护城市的短篇小说
```

`/novel` 会复用 `write_novel` Action 的生成与发送逻辑；如果未填写要求，会按默认要求生成一篇简短小说。

## 配置

插件配置会生成在：

```text
config/plugins/novel_writer/config.toml
```

主要字段位于 `[writer]`：

| 字段 | 说明 |
| --- | --- |
| `enabled` | 是否启用插件；设为 `false` 时不会注册生成 Service、`write_novel` Action 和 `/novel` 命令。 |
| `model_name` | 自定义模型名称，填写 `config/model.toml` 中 `[[models]].name`；留空时使用 `model_tasks.actor`。 |
| `temperature` | 小说生成温度，数值越高越发散。 |
| `max_tokens` | 最大输出 token 数；过小会导致正文很短。 |
| `generation_timeout_seconds` | 单次小说生成尝试的完整超时时间，包含请求发送和响应正文读取。 |
| `generation_max_retries` | 小说生成失败或超时后的最大重试次数；0 表示不重试。 |
| `generation_retry_interval_seconds` | 小说生成失败或超时后再次重试前等待的秒数。 |
| `min_words` | 默认最低中文字数要求。 |
| `min_paragraphs` | 默认最低自然段数量要求。 |
| `fallback_to_direct_send` | 当 `forward_msg` 不可用或发送失败时是否改为直接发送正文；会先提醒刷屏风险。 |
| `max_words_per_message` | 合并转发单个 node 节点最大文本长度。 |
| `background_prompt_template` | 背景知识提示词模板。 |
| `novel_prompt_template` | 小说主提示词模板。 |

## 占位符

`background_prompt_template` 支持：

- `{background_story}`：替换为 CoreConfig `personality.background_story`。

`novel_prompt_template` 支持：

- `{bot_persona}`：替换为 Bot 昵称、别名、身份、核心人格、人格侧面、表达风格、安全准则、禁止行为和运行时上下文。
- `{background_prompt}`：替换为渲染后的背景知识提示词。
- `{background_story}`：替换为 CoreConfig `personality.background_story`。
- `{user_request}`：替换为用户本次小说创作要求。
- `{min_words}`：替换为 `writer.min_words`。
- `{min_paragraphs}`：替换为 `writer.min_paragraphs`。

## 注意事项

- `forward_msg` 是可选功能插件；安装后优先使用合并转发，未安装时可按配置直接发送正文。
- 如果生成或发送失败，错误会记录到 `novel_writer.action` 日志。
- 如果 LLM 请求长时间无响应，会在 120 秒后返回超时失败。
