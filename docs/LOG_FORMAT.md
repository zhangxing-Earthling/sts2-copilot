# 对局日志格式（schema v2）

## 一个文件一局

从角色选完、`RunState` 出现开始，到角色死亡或换局为止，写入：

```
logs/runs/run_<runStartTime>_<seed>.jsonl
```

- `runStartTime` 来自游戏 `RunManager._startTime`，同一局在应用重启/重连后不变，因此会继续追加同一个文件。
- 换局会写 `run_end`（旧局）并创建新文件。
- 关程序/重连/回菜单写 `run_pause`，不会结束本局；下次轮询同一局会追加 `run_resume`。
- 复制日志按钮只复制当前 run 的绝对路径，不会拿“最新文件”猜。

## 顶层字段

每行一个 JSON：

| 字段 | 说明 |
|---|---|
| `v` | 日志 schema，当前 `2` |
| `ts` | 本地时间 ISO8601 |
| `type` | 事件类型 |
| `seq` | 本文件内递增序号（resume 时从已有行数继续） |
| `run_id` | `seed|runStartTime|character` |
| `session` | 本次应用进程的 8 位随机 id；用于区分重启前后的写入 |
| `game_version` | 游戏版本 |

`run_start` / `run_resume` 额外带 `schema`、`app_version`、完整 `state`。

## 事件类型

### `run_start` / `run_resume`

完整 `state`，包含种子、角色、难度、HP、金币、牌组、遗物、药水、当前幕/层、地图、战斗/事件/商店/营地/宝箱字段。

### `state_snapshot`

非战斗界面状态变化（地图、奖励、事件、商店、营地、宝箱、房间切换、牌组/遗物/金币变化）时写：

- `reason`: `attach` / `changed` / `heartbeat` / `death` / 其他；
- `screen`: `event` / `shop` / `rest` / `treasure` / `reward` / `map` / `combat` / `other`；
- `state`: 完整 `GameState`（事件页含 `EventVars`，即事件 `DynamicVars` 的 `Damage`/`MaxHp` 等基值）；
- `advice`: 当时的建议列表；
- `solver`: Python 求解器结构化结果（战斗时）。

### `heartbeat`

战斗内每 15 秒一条轻量记录：房间、遭遇、幕/层、HP、金币、牌组数、遗物、药水、是否战斗。

### `turn`

进入出牌阶段时：

- `state`: 完整手牌/敌人/能量/抽弃牌/牌组/遗物/药水/地图；
- `solver`: 最优序列、预计掉血、敌方剩余 HP、未建模牌、`partial`（只建模部分效果的牌）等；
- `advice`: 规则引擎输出。

### 战斗因果事件

| type | payload 关键字段 |
|---|---|
| `card_play` | `Id/Name/PlayIndex/PlayCount/AutoPlay/EnergySpent/StarsSpent/Target/TargetHp/TargetMaxHp` |
| `potion_use` | 药水、目标、目标 HP |
| `card_drawn` | 牌、是否手牌抽、来源 |
| `block_gained` | `Amount/Source/Receiver` |
| `damage_received` | `Amount/Blocked/Unblocked/Overkill/Source/Receiver/Dealer` |
| `power_received` | `Name/Amount/Source/Receiver` |

### `reward` / `reward_pick`

- `reward`: `CardChoices`、`RewardRelics`、`RewardPotions`、`RewardGold` 完整数据 + `advice`；
- `reward_pick`: 完整候选/选中卡牌、是否跳过、选后牌组。

### `map_pick`

`from` / `to` 坐标与类型、`choices`（当时的可选节点）。

### `run_pause` / `run_end`

- `run_pause`: 重连/关程序/菜单，带最后状态，可继续；
- `run_end`: 死亡/换局，带原因（`death` / `run_changed`）和最终完整状态。

## 分析建议

- 用 `run_start`/`run_resume` 确定本局起点和重启点；
- 用 `state_snapshot` 重建地图/事件/商店/营地/宝箱决策上下文；
- 用 `turn` + `solver` + `card_play`/`damage_received` 校准战斗；
- 用 `run_end` 对齐死亡回合；
- `session` 变化表示应用重启过，但 `run_id` 不变。
