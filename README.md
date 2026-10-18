# StS2 Copilot（外部只读版）

杀戮尖塔 2 的外部辅助程序。**不装 mod、不注入、不写内存、不改存档**，通过 ClrMD 只读游戏进程，因此不会影响成就。

> 当前仅支持游戏版本 **0.107.1**。版本不匹配会明确报错并拒绝连接，避免静默读错。

![全图路线 DP](docs/images/map-dp.png)

![卡牌奖励评分](docs/images/card-reward.png)

## 运行（一键启动）

双击 **`start.cmd`**，只会启动一个助手进程：

1. `Sts2Copilot.exe` 自动启动并接管本机 Python 规则服务，不需要单独开 Python
2. 自动连接游戏；如果游戏还在加载，会每 1.5 秒重试
3. 关闭助手时，自动启动的 Python 服务也会一起退出

也可以直接运行 `dist\Sts2Copilot\Sts2Copilot.exe`，行为相同。不会替你启动游戏。

状态栏出现 `py` 表示走 Python；`local` 表示没找到 Python，已回退到 C# 内置规则。需要指定 Python 时设置环境变量 `STS2_COPILOT_PYTHON`。

自包含发布，不需要安装 .NET 运行时。

## 当前功能

- **战斗**：HP/格挡/能量/星星/抽牌/弃牌/牌组、手牌（名称/费用/伤害/格挡/毒）、敌人 HP/格挡/意图
- **意图伤害**：按 `Hook.ModifyDamage` 还原——基础伤害 + 攻击者力量，再乘攻击者虚弱/玩家易伤，最后乘段数
- **全量模型目录**：源码生成 578 卡/298 遗物/260 能力/64 药水/68 事件/88 遭遇；所有实体有 `exact/partial/catalog_only` 建模等级，评分/查询不再只认识少数牌
- **战斗求解**：枚举本回合出牌顺序，按“斩杀 > 存活 > 最少掉血 > 敌方剩余 HP > 留能量”评分；支持力量/虚弱/易伤/脆弱/缩小（Shrink）/荆棘/紧勒/Ravenous/无实体/回合结束手牌伤害/StrikeDummy 等修正，输出每张牌的目标、格挡、敌方剩余 HP、预计掉血
- **同名敌人编号**：建议序列和敌人面板用 `#1/#2` 区分同名怪，避免不知道打哪只
- **出牌条件**：华丽收场只在抽牌堆为空时可用；未满足时标为不可用/未建模，不进入求解
- **未知牌降级**：X 费/能力/抽牌等未建模效果不猜，明确列出并回退旧粗算
- **三选一**：读三张候选，按稀有度/效果/费用/牌组密度/毒协同评分并推荐
- **地图**：读全图节点/边 + Boss，Python 做 HP 状态 DAG DP，输出推荐路线、预计结束 HP、评分；刚进幕/3 条起始路线时也读取 `StartingMapPoint` 的子节点并推荐
- **事件 / 先古之民**：读当前事件标题、描述和选项；锁定/遗物/风险关键词评分，推荐一个选项
- **商店**：读卡牌/无色/遗物/药水/删牌价格，按金币和卡牌评分推荐买得起的最优商品
- **营地**：读休息/锻造/挖掘等选项，低血优先回复，否则推荐锻造并给出升级目标
- **宝箱**：读遗物选择，按稀有度/评分推荐
- **中文名**：直接读游戏内存里的 `LocManager` 表
- **JSONL 日志**：`logs\runs\run_<runStartTime>_<种子>.jsonl`（一局一个文件，项目目录下，不在 C 盘）
- **版本锁 + 状态校验**：HP/能量/手牌/牌堆越界即停止建议，不静默读错
- **一键启动**：`start.cmd` / 单 exe 自动拉起 Python 规则服务，关闭时一起退出；没有 Python 自动降级
- **精确决策日志**：从 `CombatManager.History` 记录 `card_play` / `potion_use`（目标、费用、auto、回放序号），并记录 `reward_pick` / `map_pick`
- **因果日志**：记录抽牌、格挡来源、伤害结算、能力层数变化，供 DSH 解释预测误差
- **日志交接**：一键复制本局日志绝对路径 + 规则优化提示词，粘贴给 DSH；DSH 读取日志后直接优化规则代码，助手本身不调用 LLM

## 架构

```
C# 客户端（只读内存 + 第二窗口 + 日志）
   │  自动启动并托管 rules/server.py
   │  POST http://127.0.0.1:8765/advise
   ▼
Python 规则服务（engine.py / combat.py / server.py）
   │  {"advice": [...], "source": "python"}
   ▼
C# 渲染；Python 不可用时回退本地 Advisor（状态栏 local）
```

详见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)。

## 日志

**一整局一个文件**：从角色选完（RunState 出现）到角色死亡，所有事件写入 `logs/runs/run_<runStartTime>_<seed>.jsonl`；应用重启/重连时按同一 `runStartTime + seed` 继续追加，不新建文件。复制按钮只复制当前 run 的文件路径。

| type | 内容 |
|---|---|
| `run_start` / `run_resume` | 种子、角色、难度、App/游戏版本、完整初始状态；重启继续同一文件 |
| `state_snapshot` | 非战斗界面（地图/奖励/事件/商店/营地/宝箱）变化时的完整状态 + 建议 + 求解器 |
| `heartbeat` | 战斗内 15 秒一次轻量状态（HP/金币/层数/遗物/药水） |
| `combat_start` | 楼层、房间、遭遇 |
| `turn` | 进入出牌阶段时的完整状态 + 结构化求解器预测 + 建议 |
| `card_play` / `potion_use` | 从 `CombatManager.History` 读取的精确卡牌/药水事件，带目标/费用/目标 HP |
| `card_drawn` | 抽牌：牌名、来源、是否手牌抽 |
| `block_gained` | 格挡来源：数值、卡牌/遗物、接收者 |
| `damage_received` | 伤害：总额/格挡/未格挡/溢出、来源、接收者 |
| `power_received` | 能力层数变化：能力 id、数值、施加者、接收者 |
| `reward` / `reward_pick` | 三选一候选/完整卡牌数据/推荐/选择/选后牌组 |
| `map_pick` | 地图节点选择，from/to + 当时的可选节点 |
| `history_duplicate` | History 游标回退被按对象地址去重时记录，正常日志不应出现 |
| `action` | 旧版推断出牌；仅当 History 完全不可读时回退 |
| `combat_end` | 战斗结束 HP |
| `run_pause` | 重连/关程序/回菜单，未结束本局；下次继续同一文件 |
| `run_end` | 角色死亡/换局，带最终完整状态 |

`card_play` / `potion_use` 来自游戏内 `CombatManager.History`，是精确事件；只有 History 完全读不到时，才回退到旧的 `action` 推断（两次轮询之间手牌减少的牌），因此新日志不会再出现同一张牌的重复记录。抽牌与出牌同时发生时，旧 `action` 可能漏记，精确事件不会。

完整字段说明见 [docs/LOG_FORMAT.md](docs/LOG_FORMAT.md)。

### 日志目录

所有日志默认在项目目录 `D:\sts2-ai-copilot\logs\`，不再写 `%APPDATA%`：

| 目录 | 内容 |
|---|---|
| `logs\runs\` | 对局 JSONL：`run_<runStartTime>_<种子>.jsonl`，一局一个文件 |
| `logs\app\` | 助手自身日志 `app.log` |
| `logs\archive\reviews\` | 历史 AI 复盘产物（旧功能，仅存档） |

可用环境变量 `STS2_COPILOT_LOG_DIR` 覆盖根目录。`logs/` 已在 `.gitignore` 中，不会提交。

### P1.5 校准

```powershell
python py\tools\calibrate.py --last 10
```

对比 `turn.solver.hpAfter` 与下一回合/战斗结束的实际 HP，输出 MAE、偏差、误差 ≤1 比例、是否按建议出牌、斩杀误报、最差回合和未建模牌频率。出牌匹配优先用精确 `card_play`，旧日志才回退到 `action.played`。

### 日志交接与规则优化

助手窗口底部只有 **日志交接** 面板：

- 点击「复制日志地址+提示词」会复制 `prompts/rule-optimize.md` 和本局日志的**绝对路径**（不复制 JSONL 全文）。
- 粘贴给 DSH 后，提示词要求它读取日志和仓库规则代码，直接修改 `py/rules/engine.py` / `combat.py`，并跑测试与校准。
- 助手本身不调用 DeepSeek、不需要 `DEEPSEEK_API_KEY`，也不会自动改代码或 push。

日志和提示词说明见 [docs/LOG_HANDOFF.md](docs/LOG_HANDOFF.md)。

## 代码结构

```
start.cmd           一键启动（发布后的 exe）
src/Sts2Copilot.App/
  MemoryState.cs    ClrMD 读取 + 本地化 + 版本锁/校验 + 地图/奖励/事件/商店/营地/宝箱
  Advisor.cs        C# 内置规则（Python 不可用时的回退）
  AdvisorClient.cs  POST /advise 到本地 Python 服务
  RulesServiceHost.cs 自动启动/复用/关闭 Python 规则服务
  AppPaths.cs       统一日志路径（logs/runs、logs/app）
  SolverSnapshot.cs 结构化求解器预测（turn 日志）
  RunLogWriter.cs   JSONL 落盘
  MainWindow.xaml*  第二窗口 UI
py/rules/
  engine.py         规则/数学核心（战斗、奖励、地图、事件、商店、营地、宝箱）
  catalog.py        全量模型目录查询/评分
  data/catalog.json 源码生成的 578 卡/298 遗物/260 能力/64 药水/68 事件/88 遭遇
  combat.py         本回合出牌 DFS/记忆化求解器
  server.py         127.0.0.1:8765 HTTP 服务
py/tools/           校准 calibrate.py；日志分析 digest.py
py/tests/           Python 单元测试（无游戏也能跑）
tools/clrdprobe/    调试探针（run / rewards / map / fields）
tools/decomp/       游戏更新后重新反编译
docs/               架构、schema、规则、路线图、ADR
prompts/            规则优化 / 规则 patch 提示词
```

## 开发 / AI 文档

- [.agent.md](.agent.md) — 代理开发指南（先读这个）
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — 组件与数据流
- [docs/STATE_SCHEMA.md](docs/STATE_SCHEMA.md) — GameState 字段
- [docs/LOG_FORMAT.md](docs/LOG_FORMAT.md) — 一局一个文件的 JSONL 日志格式
- [docs/MODEL_COVERAGE.md](docs/MODEL_COVERAGE.md) — 全量模型目录与 exact/partial 覆盖率
- [docs/RULES.md](docs/RULES.md) — ruleId、公式、限制
- [docs/ROADMAP.md](docs/ROADMAP.md) — 里程碑
- [docs/LOG_HANDOFF.md](docs/LOG_HANDOFF.md) — 日志交接与外部规则优化
- [docs/VERSIONING.md](docs/VERSIONING.md) — 版本锁与升级流程
- [docs/decisions/0001-external-memory-reading.md](docs/decisions/0001-external-memory-reading.md) — 为什么不做 mod/截图

## 已知限制

- 商店/营地/宝箱已做基础读取与推荐，但购买组合、遗物强度和普通宝箱奖励还需实机校准
- 商店价格取 `MerchantEntry._cost` 基础值，未计会员卡等 `ModifyMerchantPrice` 折扣；营地回复按基础 30% MaxHp，未计遗物加成
- 特殊意图（非 `DamageCalc` 闭包）可能显示 0 伤害
- History 不可读时仍回退到推断出牌；正常 0.107.1 版本用精确 `card_play`
- 卡牌描述、遗物计数器、能力层数还没显示
- 求解器覆盖攻击/格挡/毒/弱/易伤/脆弱/力量/敏捷/荆棘/紧勒/Ravenous/无实体/回合结束手牌伤害/StrikeDummy；X 费、能力、抽牌、随机目标会降级
- 求解器未计其他遗物、药水使用、抽牌顺序、敌人本回合的 buff/debuff 和 Artifact/Intangible 等特殊能力
- 地图掉血是期望值，不是按当前牌组模拟战斗
- 卡牌协同只到“攻击/格挡密度 + 毒”，没有 tag/关键词
- `AutoPlay=true`、Replay（`PlayCount>1`）和 `potion_use` 还没有实机样本，字段已按反编译源码读取

## 下一步

1. P1.5 实机校准：预测掉血 vs 实际，按 MAE/最差回合补遗物/药水/抽牌/敌人 buff
2. 补 `potion_use`、`AutoPlay`、Replay 的实机样本
3. 用 DSH 按日志优化规则：复制日志路径+提示词，改完跑测试/校准，不自动 push
4. P4 实机校准：商店购买组合、营地升级目标、宝箱遗物强度
