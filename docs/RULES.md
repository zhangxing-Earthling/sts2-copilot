# Rules

规则主实现：`py/rules/engine.py`。C# `Advisor.cs` 只是 Python 不可用时的降级回退。

## Rule ID

| ruleId | 条件 | severity |
|---|---|---|
| `state.invalid` | `ValidationError` 非空 | danger |
| `combat.solver` | 本回合最优出牌顺序 + 预计结果 | good/warn/danger |
| `combat.solver_detail` | 敌方剩余 HP、总攻击、格挡、结算后 HP | info |
| `combat.solver_assumptions` | 未计遗物/药水/抽牌/随机效果 | info |
| `combat.solver_unmodeled` | 未纳入求解的卡牌及原因 | info |
| `combat.solver_truncated` | 搜索达到时间/节点上限 | warn |
| `combat.solver_unavailable` | 无法精确求解，回退粗算 | info |
| `combat.lethal_available` | 旧粗算：最大攻击伤害 ≥ 敌方 HP+格挡 | good |
| `combat.no_attack` | 旧粗算：本回合 incoming = 0 | good |
| `combat.blocked` | 旧粗算：`Block >= incoming` | good |
| `combat.full_block` | 旧粗算：`Block + 最大格挡 >= incoming` | good |
| `combat.lethal_incoming` | 旧粗算：`incoming - Block >= Hp` | danger |
| `combat.incoming` | 旧粗算：有 incoming 且挡不满 | warn |
| `combat.block_plan` | 旧粗算：需要格挡且有可打格挡牌 | warn |
| `resources.hand` | 手牌/能量摘要 | info |
| `resources.waste` | 能量 > 0 但没有可打牌 | warn |
| `resources.free_cards` | 能量 = 0 但还有 0 费牌 | good |
| `potion.consider` | 掉血 ≥ MaxHp/3 且有药水 | warn |
| `reward.recommend` | 三选一最高分 | good |
| `reward.card_choice` | 三选一评分列表 | good |
| `reward.close_call` | 前两名分差 < 0.5 | info |
| `map.recommend` | 下一层最高分 | good |
| `map.route` | 下一层评分列表 | info |
| `run.overview` | 非战斗/非奖励/非地图 | info |

## 本回合出牌求解器（P1）

实现：`py/rules/combat.py`。`engine.py` 在战斗分支优先调用它；无法精确建模时回退到旧的集合背包粗算。

### 输入

- 手牌：`Cost` / `Damage` / `Block` / `Poison` / `Hits` / `Target` / `Vars`
- 玩家：`Hp` / `Block` / `Energy` / `PlayerPowers`
- 敌人：`Hp` / `Block` / `Attacks[]`（`BaseDamage`、`Hits`）/ `Powers`

### 搜索

状态：

```
(手牌集合, 能量, 自身格挡/HP/力量/敏捷/虚弱/易伤/脆弱,
 每个敌人的 HP/格挡/力量/虚弱/易伤/毒)
```

DFS + 记忆化；手牌 ≤10、能量 ≤4；上限 15000 节点 / 220ms。搜索超限时返回当前最优并标 `combat.solver_truncated`。

### 目标（字典序）

1. **斩杀**：所有敌人 HP 归零
2. **存活**：结算后 HP > 0
3. **最少掉血**
4. 敌方剩余 HP 更少
5. 剩余能量更多

因此“能斩杀”优先于“这回合不掉血”；不能斩杀时，优先不掉血，再考虑输出。

### 结算

- 出牌顺序逐张模拟；同卡默认先伤害后 debuff（符合 Bash/Neutralize 文本；未逐卡解析描述顺序）
- 攻击伤害：`floor((base + Strength) * Weak?0.75 * Vulnerable?1.5) * hits`
- 格挡：`floor((base + Dexterity) * Frail?0.75)`
- 敌人攻击：`floor((base + 敌人 Strength) * 敌人 Weak?0.75 * 玩家 Vulnerable?1.5) * hits`
- 毒在敌方回合开始结算，无视格挡；毒死敌人后该敌人本回合不攻击
- 敌人格挡逐段吸收；单体攻击目标死亡后停止后续段数
- `Survivor` 会尝试弃掉一张手牌（枚举弃牌选择）
- 目标类型：`AnyEnemy` 逐个目标枚举；`AllEnemies` 全体；`Self` 自己；`RandomEnemy` 不建模

### 已建模 / 未建模

已建模：攻击、格挡、毒、虚弱、易伤、脆弱、力量、敏捷，以及这些效果的组合。

未建模（会显示在 `combat.solver_unmodeled`，不猜测）：

- X 费牌
- 能力牌（本回合收益）
- 状态/诅咒/任务牌
- 带未识别 `Vars` 的牌（例如抽牌、加费、随机效果）
- 随机目标
- 遗物、药水、抽牌顺序、敌人本回合的 buff/debuff 意图

### 验收

- 无随机因素时，预测掉血与实际误差 ≤1
- 序列合法：费用、目标、弃牌都满足
- 10 张手牌 / 4 能量在 220ms 内返回
- Python 不可用或没有可建模牌时，仍回退旧粗算，不崩溃

## 意图伤害

镜像 `Hook.ModifyDamage`：

```
damage = base
damage += StrengthPower(attacker)
damage *= WeakPower(attacker) > 0 ? 0.75 : 1
damage *= VulnerablePower(target) > 0 ? 1.5 : 1
perHit = (int)damage
total = perHit * repeat
```

未覆盖：PaperPhrog、Cruelty、Debilitate 等对易伤/虚弱倍率的修改。

## 卡牌评分

```
score = rarityBase
      + min(3, (Damage*Hits + Block + Poison*1.5) / (5*Cost))
      + 攻击密度不足 1.2
      + 格挡密度不足 1.2
      + 毒协同 0.5
      - 前期能力牌 1.2
      - 前期 3 费以上 1.0
      + 0 费 0.3
```

rarityBase：Rare 3.0 / Ancient 3.5 / Uncommon 2.0 / Common 1.2 / Basic 0.5。

## 地图 DP（P0）

C# 读完整地图图（`StandardActMap.Grid` 的所有节点 + `Children` 边 + Boss），放进 `MapNodes` / `MapEdges`；Python `_map_dp` 做记忆化 DAG 搜索。

状态：`(node, hp)`，从当前节点的每个子节点出发，走到 Boss。

转移：

```
hp' = min(MaxHp, hp - expectedLoss(node) + heal(node))
if hp' <= 0: 该路径无效
value(node, hp) = nodeReward(node) + riskPenalty(hp')
                + max(value(child, hp'))
```

期望掉血（按幕）：

| 类型 | Act 1 | Act 2 | Act 3 |
|---|---|---|---|
| 战斗 | 6 | 9 | 12 |
| 精英 | 20 | 28 | 35 |
| 未知 | 5 | 7 | 9 |
| 精英且牌组 < 15 | +8 | +8 | +8 |

收益：

| 类型 | 收益 |
|---|---|
| 精英 | 2.8 |
| 战斗 | 1.0 |
| 宝箱 | 1.8 |
| 营地 | 0.8（并回复 30% MaxHp） |
| 商店 | 金币 ≥ 120 时 1.0，否则 0.2 |
| 未知 | 0.9 |
| Boss | 0（终点） |

风险惩罚：

- `hp' < 15% MaxHp`：-5
- `hp' < 30% MaxHp`：-1.5

输出：

- `map.recommend`：推荐路线 + 预计结束 HP + 总评分
- `map.route`：第一层每个选项的 DP 分数、预计 HP、前 4 个节点

全图不可用时，回退到下一层启发式评分。

## 已知限制

- 求解器只覆盖已建模牌；能力牌、X 费、抽牌、随机目标会降级/排除
- 遗物、药水、敌人本回合的 buff/debuff 未计入（例如敌人加力量后再攻击）
- 毒/易伤/虚弱按标准规则模拟，未计 Artifact、Paper Phrog 等修正
- 没有读卡牌 `Tags`/`Keywords`，协同是粗粒度
- 地图掉血仍是**期望值**，不是用求解器逐场模拟
- `reward_pick` / `map_pick` 尚未记录

## 新增规则

1. 在 `engine.py` 对应函数加分支；卡牌求解效果加在 `combat.py`
2. 返回 `ruleId` / `text` / `severity`
3. 数值建议写明“粗算”或注明已建模范围
4. 给新卡牌效果加 `py/tests` 用例；未知效果必须降级，不能猜
5. 更新本文件
6. 用真实对局验证，再考虑加 C# 回退
