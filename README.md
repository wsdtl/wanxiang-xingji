# 万象行纪

《万象行纪》是一款以无穷世界、界门登录和玩家历史为核心的多人异步 QQ 聊天文游。当前公共底座版本为
`public-foundation.v11`，已经建立真实世界身份、独立空间、跨世界角色档案和可反复游玩的玩家闭环。

玩家通过界门维系一具唯一化身，在独立世界中探险、战斗、收集装备并参与跨界灾厄。世界可以按当地
法则重构角色和资产的形态，但等级、所有权、战斗机制、铭刻与已经发生的历史不会被改写。

唯一化身建立后，玩家以“归航者”身份登记于归航公约。公约不统治具体世界，只负责跨界身份互认、
资产确权、归航市场、统一清算、归航库和跨界灾厄征召，为现有交易、税务与公共玩法提供共同主体。

当前正式业务及其状态所有权以
[业务框架与功能规划](game/features/业务框架与功能规划.md)和
`game/features/catalog.py` 的显式 `FeatureManifest` 为准；README 与各底座说明不再各自维护另一份完成度台账。

## 正式项目身份

- 正式名称：`万象行纪`
- 技术标识：`wanxiang_xingji`
- 权威数据库：`game/database/wanxiang_xingji.db`
- 唯一装配入口：`game.app`
- 项目根目录：`C:\Users\16841\Desktop\万象行纪`

旧开发项目不参与运行、导包、配置、测试或部署。Git 历史只承担工程追溯，不构成运行时兼容边界。

## 当前地基

- FastAPI 应用工厂与生命周期管理
- 服务端单实例保护
- 配置驱动的业务模块加载
- QQ 开放平台单机器人 Webhook 驱动器
- 用于测试和巡检的本地命令驱动器
- 公共命令上下文、依赖注入、命令守卫和显式回复目标
- 跨驱动 `message.Message` 文档、图片、图标和动作协议
- 协议与存储无关的 Gameplay 标签、属性、Effect、Ability、条件和 Trigger 规则内核
- 显式规则版本、Ruleset、逻辑时间、确定性随机源和标准失败码
- 任意数量、多历史版本的世界构筑投影目录
- 随机降临、跨世界角色档案与不复制资产的即时跃迁
- 战斗底座 `combat.foundation.v6`，由核心会话自动产生完整结构化轨迹
- 已封板的物品与物资底座 `inventory.foundation.v6`
- 已封板的角色、成长与等级关隘底座 `character.foundation.v5`
- 已封板的原子装配底座 `loadout.foundation.v2`
- 已封板的武器底座 `weapon.foundation.v4`
- 已封板的装备底座 `equipment.foundation.v4`
- 已封板的价值评估底座 `valuation.foundation.v2`
- 已封板的随机物品化底座 `itemization.foundation.v2`
- 已封板的临时队伍底座 `party.foundation.v1`
- 已封板的账号与归属底座 `account.foundation.v1`
- 已封板的经济账本底座 `economy.foundation.v1`
- 统一参考价、归航回收、归航市场、价格纠偏、归航库与环形号码彩票
- 已封板的统一奖励结算底座 `reward.foundation.v1`
- 已封板的权益凭证与兑付底座 `grant.foundation.v1`
- 已封板的持久化联合事务底座 `persistence.foundation.v8`
- 已封板的内容包统一组装底座 `content.foundation.v7`
- 已封板的时间与周期底座 `cycle.foundation.v1`
- 异步行动槽与生命周期底座 `action.foundation.v1`
- 已封板的铭刻底座 `inscription.foundation.v1`
- 已封板的掉落与保底底座 `loot.foundation.v1`
- 已封板的可信奖池、批量抽取与独立保底槽底座 `draw.foundation.v2`
- 已封板的世界空间与区域状态底座 `world.foundation.v4`
- 已封板的交换契约底座 `exchange.foundation.v1`
- 已封板的活动实例底座 `activity.foundation.v1`
- 已封板的组织与社会关系底座 `social.foundation.v1`
- 已封板的事实投影、通知与排名底座 `projection.foundation.v1`
- 伤害、治疗、护盾、控制、状态、干预器和复合数值公式
- 多目标、回合时间线、目标约束、动态参战和结构化战报事实
- 可堆叠物资、独立实例、容器、来源批次、预约托管和原子资产事务
- 物品消耗、Ability、角色资源、事务防重与 Outbox 的联合提交
- 五项角色核心值、显式成长曲线、永久特征和开放来源贡献
- 角色、装备、组织与场景贡献到 `RuleEntity` 的统一投影
- 一个武器槽、六个装备槽及与库存共同回滚的装卸事务
- 武器品质、显式等级表、经验成长和受约束随机属性
- 开放随机装备、分段套装能力、生成后品质和不可变生成凭据
- 单件内在价值、整套价值、边际价值和多维价值向量
- 多套配装保存与背包满载时的原子一键切换
- 队长、成员、站位、准备状态、社会邀请接力和战斗阵营投影
- QQ 多身份到稳定内部账号的自动归并、冲突保护和防重放
- SQLite 结构版本、CAS 聚合快照、数据库事务防重和 Outbox
- 货币、物品、角色与武器奖励的跨领域数据库联合提交
- 版本化内容包、依赖拓扑、隐藏引用审计、统一冻结和运行内容指纹
- 日、周、月、固定间隔和显式活动窗口，以及可重启的周期补偿工作队列
- 主行动、委托行动和即时行动的冻结快照、到期结算、领取、取消与中断
- 武器、装备和武器 Ability 的实例铭刻、原名投影与联合事务防重
- 永久事实日志、可归零重建的投影检查点、通知收件箱和不可变排名快照
- 掉落审计与保底、任意世界拓扑、交换冻结、活动参与和通用组织关系
- 注册式全服活动目录、首尾热点窗口、统一活动通栏和只读活动入口
- 每周两次的跨界灾厄、真实配装讨伐、跨界共享血量、贡献封榜和本期唯一遗羽
- 黄玄地天圣五档品质，以及小中大三档血气药和灵力药
- 七十四把多世界完整投影武器、独立战斗循环和统一目标白名单
- 毫秒级武器静态估值与约四秒完成的 9472 实例品质分布巡检
- 十二个装备底座族、六槽七十二个基础装备名和四十八种开放随机词条
- 十八套 `2/3/4` 件可混搭套装，以及与品质独立的随机套装印记和定向套装图纸
- QQ Markdown/按钮键盘与本地测试结果渲染器
- 回调签名、时间窗、请求体限制、有界队列、事件去重和安全重试
- 脱敏结构日志与真实 QQ 协议测试组件

## 环境要求

- Windows 与 PowerShell
- Python 3.11 或更高版本
- 用于真实联调的 QQ 开放平台机器人应用
- 能转发到本地服务端口的公网 HTTPS 地址

## 初始化

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

至少需要在 `.env` 中填写：

```dotenv
SERVER_HOST=0.0.0.0
SERVER_PORT=8080
SERVER_SSL_CERTFILE=certs/example_bundle.pem
SERVER_SSL_KEYFILE=certs/example.key
QQ_BOT_APP_ID=机器人应用ID
QQ_BOT_SECRET=机器人密钥
DATABASE_PATH=game/database/wanxiang_xingji.db
```

`.env`、证书、私钥和机器人密钥禁止提交到 Git。

## 启动

Windows 本地启动：

```powershell
.\start.bat
```

Docker 或 Linux 容器启动：

```sh
sh ./start.sh
```

Dockerfile 可以使用：

```dockerfile
CMD ["sh", "./start.sh"]
```

`start.sh` 会统一使用项目根目录的 `.venv`；`.env` 仍然只是项目配置文件。首次启动时，脚本通过系统
Python 创建 `.venv` 并安装 `requirements.txt`，依赖完整安装后写入就绪标记；后续启动直接使用
`.venv/bin/python`。就绪标记包含依赖文件指纹；依赖发生变化或启动依赖缺失时会自动补装。安装中断不会
更新标记，下次启动会自动重试。可以通过环境变量 `PYTHON_BIN` 指定首次创建虚拟环境时使用的系统 Python
命令。

QQ 回调路径由 `QQ_EVENT_PATH` 配置，默认是 `/qq/events`：

```text
https://公网域名:端口/qq/events
```

同一项目只能运行一个服务实例。重复启动会被单实例锁拒绝，避免定时任务和消息队列重复执行。

## 加载模块

当前只自动加载框架初始化模块和可删除的协议测试组件：

```dotenv
ROUTER_MODULE_GROUPS=["auto", "组件测试"]
ROUTER_MODULES=["game.app"]
ROUTER_FOLDERS=[]
ROUTER_GROUPS=["game.cmd"]
ROUTER_CHILD_FOLDERS=[]
```

`game/cmd/` 是命令与 HTTP 接口总路由。`ROUTER_GROUPS=["game.cmd"]` 会注册总 HTTP 路由，并导入
各个中文二级组件完成消息命令注册；`组件测试/` 继续提供可删除的 QQ 现场联调能力。

当前正式命令是：

```text
帮助
帮助 分类或命令
归航公约
创建角色
创建角色 名称
我的角色
战斗面板
心情
心情 开启
心情 关闭
自动用药
自动用药 开启
自动用药 关闭
铭刻
铭刻 羽毛编号 目标编号 新名称
铭刻能力 羽毛编号 武器编号 能力序号 新名称
铭刻原名
铭刻原名 开启
铭刻原名 关闭
装配
装备 物品编号
卸下 槽位
配装
配装 0-5
纳戒 [页码]
武库
武库 部位 [页码]
背包 [页码]
查看 物品编号
使用 物品编号 [数量]
休息
结束休息
切磋 @对方
接受切磋 请求编号
拒绝切磋 请求编号
组队切磋 玩家
接受组队切磋 请求编号
拒绝组队切磋 请求编号
地图
地图 地点名称
行纪
行纪 世界名称
行纪 地点名称
行纪排行
行纪排行 世界名称
世界志
世界志 世界名称
世界志 世界名称 记录序号
探险
前往 地点
开始探险
停止探险
探险总结
回收 物品编号
批量回收 [部位] [品阶...]
回收战利品
二手 [部位] [页码]
上架 物品编号 价格
下架 M编号
购买 M编号
我的上架 [页码]
税务
彩票
购票 六位号码
中奖记录
跨界灾厄
讨伐灾厄
灾厄排行
抽奖
十连抽奖
抽奖奖池
抽奖记录
跃迁
跃迁 世界名称
```

未显式提供名称时使用消息携带的平台昵称。`game/cmd/角色/__init__.py` 只处理命令注册，实际业务与
回复放在同目录的 `service.py`；数据库联合提交和服务装配留在内部底座。

## 注册命令

正式游戏命令通过 `GameCommand` 注册，使同一回调被所有启用的消息驱动器消费。它已经统一了
`priority=100`、`block=True` 和游戏访问元数据，组件不需要重复声明：

```python
from ..command import GameCommand
from . import service


@GameCommand.handler(cmd="状态")
async def show_status(message: str = "") -> None:
    await service.show_status(message)
```

创建角色这类未建档用户也能使用的命令显式写 `access="public"`。玩家输入只声明 `message`；重复使用的
当前身份、当前角色和角色详情通过 `game.cmd.dependencies` 中的公共 `Depends` 按需注入。昵称、回复目标
和公共 `manager` 由组件服务读取当前消息上下文。QQ 与本地驱动器只在各自内部完成身份规整，组件仍然
只注册一次。

默认 `access="player"` 会由游戏角色守卫真实校验，未建档时统一返回创建入口。组件业务构造完
`message.Message` 后使用 `send_game_reply()` 发送，不重复读取 `client_id` 或直接调用驱动器。完整边界见
[正式游戏命令层](game/cmd/命令层说明.md)。

## 消息协议

业务必须构造 `message.Message`，不能直接返回 Markdown 字符串或平台 payload：

```python
from message import Action, M

reply = (
    M.document()
    .header("示例对象 Lv1")
    .inline_section("通知", "任务已完成", icon="system")
    .section("资源列表", icon="inventory")
    .row(("数量", 3), ("状态", "可用"))
    .action(Action("view", "查看", "查看 示例物品", behavior="send"))
    .build()
)

await manager.send(reply, client_id)
```

公共适配器管理器会拒绝 QQ 原生字典。平台原生 payload 只允许存在于驱动器内部和协议探针。

上例展示的是公共消息协议能力。正式 `game/cmd` 组件不能自行调用 `inline_section()` 或设置彩色 Header；
已建档玩家的人物头、全服活动通栏和个人提醒通栏由 `GameReplyComposer` 在 `send_game_reply()` 中统一生成。

## QQ 联调

启用 `组件测试.QQ协议测试` 后，群聊发送：

```text
@机器人 QQ协议测试
```

测试面板覆盖回调、即发、回填、引用、Markdown、图片和身份字段。完整操作方法见 [QQ 协议测试组件](组件测试/QQ协议测试/QQ协议测试说明.md)。

## 运行测试

```powershell
Get-ChildItem .test\*_test.py | Sort-Object Name | ForEach-Object {
  .venv\Scripts\python.exe -X utf8 -B $_.FullName
  if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
```

上线前静态审计工具与生产依赖分开安装：

```powershell
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.venv\Scripts\ruff.exe check game launch message auto main.py
.venv\Scripts\vulture.exe game launch message auto main.py --exclude .venv,__pycache__ --min-confidence 100
.venv\Scripts\python.exe -X utf8 .ops audit-extension --all
git diff --check
```

## 说明文档

- [《万象行纪》世界设定](design/万象行纪世界设定.md)
- [游戏核心边界](game/core/核心边界说明.md)
- [核心架构门禁](design/核心架构门禁说明.md)
- [代码结构与维护准则](design/代码结构与维护准则.md)
- [正式内容层](game/content/正式内容层说明.md)
- [具体游戏规则](game/rules/具体游戏规则说明.md)
- [业务框架与功能规划](game/features/业务框架与功能规划.md)
- [游戏应用装配](game/应用装配说明.md)
- [角色组件](game/cmd/角色/说明.md)
- [帮助组件](game/cmd/帮助/说明.md)
- [提醒组件](game/cmd/提醒/说明.md)
- [活动组件](game/cmd/活动/说明.md)
- [铭刻组件](game/cmd/铭刻/说明.md)
- [装配组件](game/cmd/装配/说明.md)
- [物品组件](game/cmd/物品/说明.md)
- [伙伴组件](game/cmd/伙伴/说明.md)
- [组队组件](game/cmd/组队/说明.md)
- [休息组件](game/cmd/休息/说明.md)
- [地图组件](game/cmd/地图/说明.md)
- [行纪组件](game/cmd/行纪/说明.md)
- [世界志组件](game/cmd/世界志/说明.md)
- [探险组件](game/cmd/探险/说明.md)
- [世界行纪正式业务](game/features/world_progress/说明.md)
- [世界志正式业务](game/features/world_lore/说明.md)
- [伙伴正式业务](game/features/companion/说明.md)
- [队伍正式业务](game/features/party/说明.md)
- [伙伴正式内容](game/content/catalog/companion/伙伴正式内容说明.md)
- [公共底座封板说明](design/公共底座封板说明.md)
- [核心封板基线](design/核心封板基线.md)
- [游戏设计宪章](design/游戏设计宪章.md)
- [Gameplay 规则内核](game/core/gameplay/规则内核说明.md)
- [战斗底座封板说明](game/core/gameplay/combat/战斗底座封板说明.md)
- [物品与物资底座说明](game/core/gameplay/inventory/物品与物资底座说明.md)
- [角色与成长底座说明](game/core/gameplay/character/角色与成长底座说明.md)
- [装配底座说明](game/core/gameplay/loadout/装配底座说明.md)
- [武器底座说明](game/core/gameplay/weapon/武器底座说明.md)
- [装备底座说明](game/core/gameplay/equipment/装备底座说明.md)
- [价值评估底座说明](game/core/gameplay/valuation/价值评估底座说明.md)
- [随机物品化底座说明](game/core/gameplay/itemization/随机物品化底座说明.md)
- [队伍底座说明](game/core/gameplay/party/队伍底座说明.md)
- [账号与归属底座说明](game/core/account/账号与归属底座说明.md)
- [经济账本底座说明](game/core/gameplay/economy/经济账本底座说明.md)
- [统一经济系统](game/rules/economy/经济系统说明.md)
- [统一奖励结算底座说明](game/core/gameplay/rewards/统一奖励结算底座说明.md)
- [权益凭证与兑付底座说明](game/core/gameplay/grants/权益凭证与兑付底座说明.md)
- [持久化联合事务底座说明](game/core/persistence/持久化联合事务底座说明.md)
- [内容包统一组装底座说明](game/core/gameplay/content/内容包统一组装底座说明.md)
- [时间与周期底座说明](game/core/gameplay/cycles/时间与周期底座说明.md)
- [异步行动底座说明](game/core/gameplay/actions/异步行动底座说明.md)
- [铭刻底座说明](game/core/gameplay/inscription/铭刻底座说明.md)
- [掉落与保底底座说明](game/core/gameplay/loot/掉落与保底底座说明.md)
- [世界空间与区域状态底座说明](game/core/gameplay/world/世界空间与区域状态底座说明.md)
- [交换契约底座说明](game/core/gameplay/exchange/交换契约底座说明.md)
- [活动实例与参与结算底座说明](game/core/gameplay/activities/活动实例与参与结算底座说明.md)
- [组织与社会关系底座说明](game/core/gameplay/social/组织与社会关系底座说明.md)
- [事实投影、通知与排名底座说明](game/core/gameplay/projections/事实投影通知与排名底座说明.md)
- [战斗内核](game/core/gameplay/combat/战斗内核说明.md)
- [战斗编排](game/core/gameplay/combat/战斗编排说明.md)
- [高级特效机制](game/core/gameplay/combat/高级特效机制说明.md)
- [公共消息协议](message/消息协议说明.md)
- [应用与通信架构](launch/架构说明.md)
- [通信驱动器接入模板](launch/adapter/驱动器模板.md)
- [QQ 驱动器](launch/adapter/qq/QQ驱动器说明.md)
- [QQ 协议测试组件](组件测试/QQ协议测试/QQ协议测试说明.md)

只有项目根目录保留入口文件 `README.md`；其他说明文档的文件名、正文、代码注释和使用说明全部使用中文。

## 架构边界

- `game/` 统一收纳公共游戏核心、具体游戏产品和本地游戏数据库。
- `game/core/` 是公共游戏核心的唯一命名空间，对外导入路径为 `game.core`。
- `message/` 是协议中立地基，不能导入 `launch`、QQ 驱动器或业务包。
- `game/core/gameplay/` 是规则中立地基，不能导入 `launch`、`message`、数据库或具体玩法。
- `game/core/account/` 是平台协议中立的账号与归属地基，不能导入 `launch`、QQ 驱动、数据库或 Gameplay。
- `game/core/persistence/` 可以适配领域快照，但领域包不能反向导入持久化实现。
- `game/content/` 只承载稳定名录、世界皮肤和统一装配，只能依赖 Gameplay 公共契约。
- `game/rules/` 只保存跨组件复用的英文具体游戏规则，不放中文组件业务文件。
- `game/features/` 保存正式业务用例和联合事务，不能导入命令、消息协议或持久化实现。
- `game/app.py` 只负责组装、稳定转发和启动生命周期，禁止直接开启业务工作单元或注册业务定时任务。
- `game/cmd/` 承接命令与对应组件入口；二级组件的 `service.py` 负责命令，`jobs.py` 负责定时触发，真正业务仍归 `features`。
- 只有 `game/cmd/` 的二级组件目录使用中文；Python 文件名和代码标识符统一使用英文。
- `组件测试/` 只存放可删除的联调与协议测试，禁止依赖游戏代码。
- `launch/` 只负责应用运行与通信基础设施，不能导入游戏业务包。
- 未来业务组件通过 `MessageHandler` 注册命令，通过公共 `manager` 发送统一消息对象。
- 平台身份、原始事件、原生 payload 和发送目标只能存在于对应驱动器包内。
- 脱离当前消息上下文发送时必须提供明确 `ReplyTarget`，框架不会根据历史消息猜测目标。
