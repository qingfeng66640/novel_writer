# 使用方法

## 启用条件

Novel Writer 推荐配合 `forward_msg` 插件使用。请确保运行环境中已启用 `forward_msg`，并能提供：

```text
forward_msg:service:forward_msg_protocol
```

`forward_msg` 插件市场地址：<http://39.96.71.162/plugin/forward_msg>

`forward_msg` 是推荐依赖，不再强制阻塞插件加载。如果未安装、未启用或发送失败，且 `fallback_to_direct_send = true`，插件会先提醒用户“小说内容过多可能导致刷屏”，然后把小说正文拆成多条普通消息直接发送。

## 基本使用

在聊天中直接向 Bot 提出小说创作需求即可，例如：

```text
@Bot 写一篇你和三月七在星穹列车上的日常小说，温柔一点，篇幅长一些。
```

当默认 chatter 判断用户想让 Bot 写小说、写故事、续写剧情或根据人设创作文学内容时，会调用 `write_novel` Action。

## 配置位置

插件配置文件位于：

```text
config/plugins/novel_writer/config.toml
```

常用配置：

- `enabled`：是否启用插件。
- `model_name`：自定义模型名称，填写 `config/model.toml` 中 `[[models]].name` 的值；留空使用 `model_tasks.actor`。
- `temperature`：生成温度。
- `max_tokens`：最大输出 token 数。
- `min_words`：默认最低字数要求。
- `min_paragraphs`：默认最低段落数要求。
- `fallback_to_direct_send`：当 `forward_msg` 不可用或发送失败时是否改为直接发送正文；会先提醒刷屏风险。
- `max_words_per_message`：合并转发中单条 node 的最大文本长度。

## 输出方式

小说正文会拆分为多个 `forward_msg` 合并转发节点发送，不会由插件单独实现新的平台发送逻辑。

## 排错

如果没有收到小说，请检查日志中的 `novel_writer.action`：

- 是否开始执行 `write_novel`。
- LLM 请求是否超时。
- 生成正文长度是否为 0。
- `forward_msg` 服务是否可用。
- 合并转发发送是否成功。
