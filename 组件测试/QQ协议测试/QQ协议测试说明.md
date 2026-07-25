# QQ 协议测试组件

该组件用于真实 QQ 客户端联调，不承载修仙业务。菜单、事件报告和图片均使用根级 `message/` 公共协议生成，再由 QQ 驱动器翻译。

组件只记录 payload 字段结构和身份短指纹，不记录完整 OpenID、机器人密钥或原始载荷。

## 启用

在项目根目录 `.env` 的普通模块列表中加入：

```dotenv
ROUTER_MODULE_GROUPS=["auto", "组件测试"]
```

重启服务后，启动日志应出现：

```text
QQ webhook 已就绪 ... exact=1
```

## 打开面板

私聊发送：

```text
QQ协议测试
```

群聊发送：

```text
@机器人 QQ协议测试
```

## 操作顺序

1. 点击“回调”，确认收到 `INTERACTION_CREATE` 并完成按钮 ACK。
2. 点击“即发”，确认客户端自动发送命令。
3. 点击“回填”，在输入框补充内容后手动发送。
4. 点击“引用”，确认事件带有引用消息结构。
5. 点击“Markdown”，确认统一富文本结构正常。
6. 点击“图片”，确认上传和媒体消息发送正常。
7. 点击“身份”，比较私聊和群聊身份短指纹。

## 预期日志

回调成功应依次看到：

```text
QQ webhook 已接收 type=按钮
QQ 命令命中 message=QQ协议测试 回调
QQ 按钮回调已确认
QQ 回复已发送 msg_type=2
```

图片成功应看到：

```text
QQ 图片上传成功
QQ 回复已发送 msg_type=7
```

## 离线验证

```powershell
.venv\Scripts\python.exe -X utf8 -B .test\qq_protocol_component_test.py
```

该测试检查公共动作、稳定按钮 ID、QQ keyboard 翻译、测试图片和脱敏摘要。

## 边界

- 本组件可以读取 QQ 私有事件，因为它就是协议探针。
- 正式业务组件不得照搬该组件对 QQ 私有 Depends 的使用方式。
- 正式回复必须使用 `message.Message`。
- 原生 QQ payload 只用于验证平台新增能力，不得扩散为业务接口。
