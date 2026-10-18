# Architecture

## 组件

| 组件 | 语言 | 职责 |
|---|---|---|
| `Sts2Copilot.App` | C# / WPF | 读内存、显示第二窗口、写 JSONL、自动拉起/调用规则服务；日志路径由 `AppPaths` 统一 |
| `py/rules` | Python | 战斗数学、本回合求解器、选牌评分、地图 DP |
| `py/tools` | Python | `calibrate.py` 校准；`digest.py` 日志分析（供 DSH 用） |
| `tools/clrdprobe` | C# | 调试探针，验证字段/地图/奖励 |
| `tools/decomp` | C# | 游戏更新后反编译 `sts2.dll` |

## 数据流

```
每 250ms:
  1. MemoryReader.Read()
       RunManager.Instance -> RunState
       -> Player / Creature / PlayerCombatState
       -> Hand / Deck / Relics / Potions / Map / Rewards / EventOptions / ShopItems / RestOptions / RelicChoices
  2. 校验 HP/能量/手牌/牌堆/敌人 HP
  3. POST /advise (GameState JSON)  -> Python
     超时 500ms；失败则 Advisor.Build() 本地回退
  4. UI 渲染 + RunLogWriter 记录事件
```

## 规则服务

- 地址：`http://127.0.0.1:8765`
- `GET /health` → `{"ok": true}`
- `POST /advise` → `{"advice": [{"ruleId","text","severity"}], "source":"python"}`
- 无状态；每次请求独立计算
- 只监听 `127.0.0.1`，不对外网开放

### 一键启动

`start.cmd` 只启动 `Sts2Copilot.exe`；C# 进程内部负责拉起和托管 Python，用户不需要分开启动。发布时 `py/rules/*.py` 会复制到 `dist/Sts2Copilot/rules/`，`prompts/*.md` 复制到 `prompts/`。`RulesServiceHost` 在窗口加载时：

1. 先探测 `/health`；已有服务则直接复用，不接管
2. 否则在 PATH 里找 `python.exe` / `py.exe`，隐藏启动 `rules/server.py`
3. 最多等约 4–5 秒；成功状态栏显示 `py`，失败则回退 `local`
4. 只有自己启动的服务会在 App 退出时杀进程；外部手动启动的不动

可用环境变量 `STS2_COPILOT_PYTHON` 指定 Python，`STS2_COPILOT_RULES_DIR` 指定规则目录，`STS2_COPILOT_RULES_URL` 改服务地址。单实例互斥锁防止重复启动多个助手；如果游戏尚未启动，窗口会每 1.5 秒重试连接。

## 本回合求解器

`py/rules/combat.py`：

```
GameState
  -> 只保留已建模牌（Cost/Damage/Block/Poison/Target/Vars）
  -> DFS + 记忆化，状态含手牌集合、能量、敌人 HP/格挡/能力
  -> 结算毒、敌人攻击、格挡、目标死亡
  -> 按“斩杀 > 存活 > 最少掉血 > 敌方 HP > 留能量”排序
  -> engine.py 输出 combat.solver* 建议
```

- 上限 15000 节点 / 220ms，低于 C# 500ms HTTP 超时
- 未知效果不猜：`combat.solver_unmodeled` 列出卡牌和原因
- 未建模牌过多或 Python 不可用时，`engine.py` 回退旧粗算

## 全量模型目录

`ref/sts2` 的反编译源码由 `py/tools/build_catalog.py` 解析，生成 `py/rules/data/catalog.json`：

- 578 卡牌、298 遗物、260 能力、64 药水、68 事件、88 遭遇；
- 每项包含构造参数、动态变量、源码效果命令、hook 和 `model.level`；
- `exact` = DFS 可精确模拟，`partial` = 部分效果/评分可用，`catalog_only` = 仅目录；
- `py/rules/catalog.py` 按 id/class 懒加载，`engine.py` 用它补卡牌标签/效果评分，`combat.py` 用它识别 Strike 标签与遗物；
- 发布时 `data/catalog.json` 随 csproj 复制到 `dist/Sts2Copilot/rules/data/`。

详见 [MODEL_COVERAGE.md](MODEL_COVERAGE.md)。生成物只含元数据，不含反编译源码/游戏资源。

## 日志

所有日志在项目 `logs\` 下，按类型分类：

| 目录 | 内容 |
|---|---|
| `logs\runs\` | `run_<runStartTime>_<种子>.jsonl` 对局日志（一局一个文件） |
| `logs\app\` | `app.log` 助手自身日志 |
| `logs\archive\reviews\` | 历史 AI 复盘产物（旧功能，仅存档） |

`STS2_COPILOT_LOG_DIR` 可覆盖根目录；`logs/` 在 `.gitignore` 中。

对局日志：`D:\sts2-ai-copilot\logs\runs\run_<runStartTime>_<种子>.jsonl`，schema v2，完整字段见 [LOG_FORMAT.md](LOG_FORMAT.md)。

| type | 触发 |
|---|---|
| `run_start` / `run_resume` | 首次读到该局 / 应用重启或重连后继续同一文件，含完整状态 |
| `state_snapshot` | 非战斗界面变化（地图/奖励/事件/商店/营地/宝箱/牌组/金币等），含完整状态+建议+求解器；10 秒心跳 |
| `heartbeat` | 战斗内 15 秒一次轻量状态 |
| `combat_start` | 进入战斗 |
| `turn` | 进入出牌阶段（`Phase == 3`），含 `solver` 结构化预测 |
| `card_play` / `potion_use` | 从 `CombatManager.History` 读取的精确事件，带目标/费用/auto/回放序号/目标 HP |
| `card_drawn` / `block_gained` / `damage_received` / `power_received` | 因果事件：抽牌、格挡来源、伤害结算、能力层数变化 |
| `reward` / `reward_pick` | 三选一候选/完整卡牌数据/选择/选后牌组 |
| `map_pick` | 当前地图坐标变化，记录 from/to + 当时可选节点 |
| `history_duplicate` | History 游标回退时被对象地址去重跳过，用于诊断；正常日志不应出现 |
| `action` | 旧版推断事件；只有 History 完全不可读时才作为回退 |
| `combat_end` | 离开战斗；`CombatState` 跨战斗非空时由新战斗遭遇/回合回退推断 |
| `run_pause` | 重连/关程序/回菜单，未结束本局；下次继续同一文件 |
| `run_end` | 角色死亡/换局，带最终完整状态 |

`card_play` / `potion_use` 是权威事件。History 可读时 C# 不再写推断 `action`，否则 `CardPlayFinishedEntry` 比手牌变化晚，会同一张牌记两遍。History 读取失败或拿到短快照时只跳过本轮，不把游标归零；只有连续两次空列表/连续两次更短快照才判定为 `CombatHistory.Clear()`，避免重放历史。**不能用 entry 对象地址判断重置**：GC 会移动对象，地址变化会被误判成新历史。地址去重只作为兜底诊断，命中时写 `history_duplicate`。

`CombatState` 在两个战斗之间可能保持非空，单看 `InCombat` 会漏掉 `combat_end`。现在用“遭遇变化”或“回合数回退”补记上一场的结束与下一场的开始，HP 取上一场最后观察值。

## P1.5 校准

```powershell
python py\tools\calibrate.py --last 10
```

脚本把 `turn.solver.hpAfter` 与下一回合 `state.Hp`（或 `combat_end.Hp`）对比：

- MAE / 偏差 / 误差 ≤1 比例
- 是否按建议出牌：优先用精确 `card_play` 事件；旧日志没有时回退到 `action.played`
- 斩杀误报；旧日志缺 `combat_end` 时用遭遇变化识别新战斗，避免把正确斩杀算成误报；`lethal_false_followed` 只统计“按建议出牌后仍误报”的真模型误差
- 最差回合（带 `Encounter`，因为 `Turn` 会在每场战斗重置）
- 未建模牌频率

旧日志没有 `solver` 字段时计为 missing，不会当成 0 误差。

`--replay` 忽略日志里当时代码写入的 `solver`，用当前 `py/rules/combat.solve()` 重放每个 `turn.state` 再对比 HP。日志内嵌 solver 是旧代码的产物，规则改动只有用 replay 才能在同一批历史回合上量化；两次输出都保留 `mode` 字段。

## 日志交接与规则优化

```
MainWindow「复制日志地址+提示词」
  -> prompts/rule-optimize.md + 本局 JSONL 绝对路径
  -> 粘贴给 DSH
       -> DSH 读 logs/runs/*.jsonl + py/rules/*
       -> 跑 calibrate/digest
       -> 修改 engine.py / combat.py + tests
       -> unittest + calibrate 验证
       -> 改动留在本地，不自动 push
```

- 助手不调用 LLM、不需要 API key；只负责复制路径和提示词。
- DSH 按 `prompts/rule-optimize.md` 直接优化规则代码；助手不自动改代码或 push。
- 历史复盘产物在 `logs\archive\reviews`，不参与新流程。
- 详见 `docs/LOG_HANDOFF.md`。

## 线程与性能

- UI 线程只做渲染；内存读取和 HTTP 在 `Task.Run`
- 读一次约 0.5–2ms；普通规则 HTTP 本地 <10ms，战斗求解上限 220ms
- 250ms 轮询；`_busy` 防止重入

## 失败模式

| 情况 | 行为 |
|---|---|
| 游戏退出/应用关闭 | 停止轮询，写 `run_pause`；同一局下次打开继续同一文件 |
| 版本不匹配 | 拒绝连接，状态栏显示版本错误 |
| 状态校验失败 | 停止建议与记录，不静默继续 |
| Python 未安装/启动失败 | 自动回退 C# 规则，状态栏 `local` |
| Python 已手动启动 | 复用现有服务，退出时不关闭 |
| 重复启动助手 | 单实例互斥锁提示“已经在运行” |
| 找不到 DAC | 连接失败并显示错误 |

## 安全/合规

- 只读进程内存，不写、不注入、不模拟输入
- 不修改存档
- 不把游戏资源/反编译代码放进发布物
- API key 只从环境变量读，不落日志
