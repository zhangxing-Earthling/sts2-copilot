# Rules

规则主实现：`py/rules/engine.py`。C# `Advisor.cs` 只是 Python 不可用时的降级回退。

## Rule ID

| ruleId | 条件 | severity |
|---|---|---|
| `state.invalid` | `ValidationError` 非空 | danger |
| `combat.lethal_available` | 能量约束下最大攻击伤害 ≥ 敌方 HP+格挡 | good |
| `combat.no_attack` | 本回合 incoming = 0 | good |
| `combat.blocked` | `Block >= incoming` | good |
| `combat.full_block` | `Block + 最大格挡 >= incoming` | good |
| `combat.lethal_incoming` | `incoming - Block >= Hp` | danger |
| `combat.incoming` | 有 incoming 且挡不满 | warn |
| `combat.block_plan` | 需要格挡且有可打格挡牌 | warn |
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

## 地图评分

只看**下一层**：

| 类型 | 条件 | 分数 |
|---|---|---|
| 精英 | HP > 60% 且牌组 ≥ 15 | 3.0 |
| 精英 | 否则 | -2.0 |
| 营地 | HP < 60% | 2.6 |
| 营地 | 否则 | 1.0 |
| 商店 | 金币 ≥ 120 | 2.2 |
| 商店 | 否则 | 0.4 |
| 宝箱 | — | 2.0 |
| 战斗 | HP > 50% | 1.2 |
| 战斗 | 否则 | 0.6 |
| 未知 | — | 1.1 |

## 已知限制

- 没有读卡牌 `Tags`/`Keywords`，协同是粗粒度
- 没有全图 DAG DP，只看下一层
- 没有本回合出牌顺序求解器（只做集合背包）
- `reward_pick` / `map_pick` 尚未记录

## 新增规则

1. 在 `engine.py` 对应函数加分支
2. 返回 `ruleId` / `text` / `severity`
3. 数值建议写明“粗算”
4. 更新本文件
5. 用真实对局验证，再考虑加 C# 回退
