# Roadmap

## 已完成

- [x] 外部只读内存读取（ClrMD），第二窗口
- [x] 版本锁 `0.107.1` + 状态校验
- [x] 中文名（`LocManager` 内存表）
- [x] 战斗规则 v1：致死/预计掉血/全挡/斩杀（粗算）
- [x] 意图伤害还原：力量、虚弱、易伤、多段
- [x] 卡牌奖励读取 + 评分 + 推荐
- [x] 地图当前节点 + 下一层评分
- [x] 全图 DAG 期望值 DP（节点/边 + Boss，HP 状态）
- [x] JSONL 日志（run/combat/turn/action/reward）
- [x] Python 规则服务 + C# 回退
- [x] P1 本回合出牌求解器 MVP（攻击/格挡/毒/弱/易伤/力量/敏捷；DFS + 记忆化；未知牌降级）
- [x] 全量模型目录：源码生成 578 卡/298 遗物/260 能力/64 药水/68 事件/88 遭遇，标记 exact/partial/catalog_only
- [x] 一键启动：`start.cmd` + 自动拉起/复用/关闭 Python 服务

## 下一步（按优先级）

### P1.5 实机校准

- [x] 在 `turn` 日志结构化记录求解器预测（序列/预计掉血/能量/未建模牌）
- [x] 校准脚本 `py/tools/calibrate.py`：对比预测 vs 下一回合/战斗结束实际 HP
- [x] 首轮实机修正：`ShrinkPower`（缩小甲虫）使攻击伤害 ×0.7，修复“建议可斩杀、实际没死”
- [x] 校准脚本识别战斗边界：旧日志缺 `combat_end` 时用遭遇变化判定新战斗，避免把正确斩杀误报成 `lethal_false`
- [ ] 跑真实对局，按 MAE/最差回合修模型
- [ ] 补遗物/药水/抽牌/敌人 buff 意图；把未建模牌逐步加入
- 验收：连续 20 场无随机战斗误差 ≤1；超时率 <1%
- 通过后，把求解器输出接到地图 DP 的掉血估计

### P2 决策落盘

- [x] `reward_pick`：对比选牌前后牌组
- [x] `map_pick`：对比当前地图坐标
- [x] `potion_use` / `card_play` 精确化：读 `CombatManager.History`
- [x] 实机验证 `card_play` 目标/费用/`EnergySpent` 与游戏内一致（2026-10-18）
- [x] 实机验证 `reward_pick` 选中与牌组 diff 一致（2026-10-18）；跳过路径待样本
- [x] 实机验证 `map_pick` 的 from/to 与地图移动一致（2026-10-18）
- [x] 修复 History 瞬时读失败导致 `card_play` 重放
- [x] 按 History entry 对象地址去重，游标异常回退时不再重复发事件
- [x] History 可读时禁用旧 `action` 回退，避免同一张牌重复记录
- [x] 修复 `CombatState` 跨战斗非空时漏记 `combat_end` / `combat_start`
- [x] 因果事件：`card_drawn` / `block_gained` / `damage_received` / `power_received`，用于解释预测误差
- [x] 修复 History 游标用 entry 地址判断重置：GC 移动对象会误判并重放整局
- [x] 同名敌人用 `#1/#2` 标注；`card_play`/`potion_use` 记录目标 HP
- [x] `GrandFinale`（华丽收场）只在抽牌堆为空时可出；求解器与 UI 都遵守
- [ ] 补 `potion_use`、`AutoPlay=true`、Replay（`PlayCount>1`）实机样本

### P3 规则优化交接（外部 DSH）

- [x] 日志统一到 `logs/runs`、`logs/app`；历史复盘归档 `logs/archive/reviews`
- [x] 助手「复制日志地址+提示词」：`prompts/rule-optimize.md` + 本局日志绝对路径
- [x] 提示词要求 DSH 直接读日志和 `py/rules/*.py`，按日志修改规则并跑 unittest/calibrate
- [x] 移除内置 AI 复盘：无模型选择、无 DeepSeek 调用、无 `DEEPSEEK_API_KEY` 依赖
- [x] 规则修改仍只留在本地，不自动 push
- [ ] 用 DSH 按日志完成一轮规则优化，保留 diff 与改动前后校准数据

### P4 非战斗界面

- [x] 事件/先古之民：读标题、描述、选项，按风险/遗物评分推荐
- [x] 地图起点：修复 `StartingMapPoint` 不在 Grid 时 `MapChoices` 为空，3 条起始路线也会推荐
- [x] 商店：读卡牌/无色/遗物/药水/删牌价格，推荐买得起的最优商品
- [x] 营地：读休息/锻造/挖掘等选项，低血优先回复，否则推荐锻造
- [x] 宝箱：读遗物选择，按稀有度/评分推荐
- [ ] P4 实机校准：商店购买组合、遗物强度、普通宝箱奖励

## 不做

- 自动打牌/输入注入
- 修改游戏内存或存档
- mod 形式
- 用 LLM 做实时战斗决策（延迟/成本/幻觉）
