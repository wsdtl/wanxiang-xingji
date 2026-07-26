# QQ 通信驱动器

本目录实现单机器人 QQ 开放平台通信协议。驱动器负责回调验签、事件规整、身份选择、排队去重、命令匹配、按钮确认、消息翻译和 OpenAPI 调用。

业务组件不能导入本目录的原生 payload 来构造正式回复。正式输出统一使用根级 `message/` 协议。

## 配置

项目根目录 `.env` 至少需要：

```dotenv
QQ_EVENT_PATH=/qq/events
QQ_EVENT_SIGNATURE_REQUIRED=true
QQ_BOT_APP_ID=机器人应用ID
QQ_BOT_SECRET=机器人密钥
```

服务还需要正确的 `SERVER_HOST`、`SERVER_PORT` 和 HTTPS 证书路径。QQ 开放平台填写的回调地址格式为：

```text
https://公网域名:端口/qq/events
```

生产环境必须保持 `QQ_EVENT_SIGNATURE_REQUIRED=true`。

## 入站流程

```text
POST /qq/events
  -> 限制请求类型和大小
  -> op=13 地址验证
  -> 普通事件签名与时间窗校验
  -> 原始事件规整
  -> 身份选择
  -> 有界队列与去重
  -> 命令匹配
  -> 业务回调
```

普通事件签名使用原始 HTTP 字节，不能对 JSON 重新序列化后验签。签名时间戳必须位于五分钟窗口内，避免合法请求被长期重放。

Webhook 请求体上限为 1 MiB，且 `Content-Type` 必须是 `application/json`。

## 身份字段

| 字段 | 含义 |
| --- | --- |
| `user_openid` | 私聊用户身份，群聊事件可能为空 |
| `member_openid` | 群成员身份，私聊事件可能为空 |
| `actor_openid` | 当前操作者统一身份，也是业务 `client_id` |
| `group_openid` | 群聊发送目标 |
| `sender_name` | QQ 事件实际携带的昵称或用户名，平台未下发时为空 |

私聊优先选择 `user_openid`，群聊优先选择 `member_openid`。字段必须分别保留，不能再次把群成员身份塞进 `user_openid`。

QQ 驱动器会把这些字段一次性转换为公共 `MessageIdentity`：群聊主身份是群成员，私聊主身份是
用户，行为人身份作为别名保留。正式业务读取公共身份，不需要注册 QQ 专用命令。

`sender_name` 只读取 QQ payload 中明确存在的 `username`、`nickname` 或 `nick`。QQ 群事件常常只
提供 OpenID，此时业务必须接受空值，不能把 OpenID 展示成玩家名称。

日志只记录身份短指纹，完整 OpenID 不进入普通运行日志。

## 回复流程

业务发送 `message.DocumentMessage` 或 `message.ImageMessage` 后，QQ 渲染器执行以下转换：

```text
公共 Message
  -> 统一 Markdown 结构
  -> 公共 Action 转 QQ keyboard
  -> QQ 原生 payload
  -> 有界发送队列
  -> OpenAPI
```

`launch.adapter.qq.payload` 是驱动器内部构造工具，只用于平台能力实现和协议探针。

## 按钮映射

| 公共行为 | QQ action.type | 结果 |
| --- | --- | --- |
| `link` | `0` | 打开链接 |
| `callback` | `1` | 产生 `INTERACTION_CREATE`，立即派发 `button_data` 中的命令 |
| `send` | `2` | `enter=true`；私聊自动发送，群聊只填入输入框 |
| `fill` | `2` | 填入输入框但不自动发送 |

每个按钮必须携带稳定且唯一的 `id`。真实 QQ 回调的命令位于 `d.data.resolved.button_data`，按钮 ID 位于 `d.data.resolved.button_id`。

正式业务中，完整命令的有边框按钮统一使用 `callback`，需要玩家继续输入参数时
使用 `fill`。不能用 `send` 表达跨私聊、群聊一致的“点击立即执行”。

回调事件会进入独立 ACK 队列，并调用 `/interactions/{interaction_id}` 完成确认。

## 发送重试

- `401` 只清理并刷新一次访问令牌。
- `429` 遵守 `Retry-After`，最多执行有限次数重试。
- `500/502/503/504` 仅对可安全重放的请求重试。
- 建连失败仅对可安全重放的请求重试。
- 没有 `msg_id/event_id` 的主动推送不会自动重试，避免重复发送。
- 图片上传和按钮 ACK 可安全重放。

公共 `send()` 返回“已进入发送队列”，最终 OpenAPI 结果通过结构化日志记录。

## 联调组件

群聊发送：

```text
@机器人 QQ协议测试
```

测试面板覆盖回调、即发、回填、引用、Markdown、图片和身份上下文。操作方法见 `组件测试/QQ协议测试/QQ协议测试说明.md`。

## 测试

```powershell
.venv\Scripts\python.exe -X utf8 -B .test\qq_driver_test.py
.venv\Scripts\python.exe -X utf8 -B .test\qq_event_normalization_test.py
.venv\Scripts\python.exe -X utf8 -B .test\qq_signature_test.py
.venv\Scripts\python.exe -X utf8 -B .test\qq_http_flow_test.py
.venv\Scripts\python.exe -X utf8 -B .test\qq_openapi_retry_test.py
.venv\Scripts\python.exe -X utf8 -B .test\qq_protocol_component_test.py
```

修改事件字段、按钮协议、签名、队列或发送重试后，必须运行对应测试并使用真实 QQ 客户端完成至少一次消息和回调验证。
