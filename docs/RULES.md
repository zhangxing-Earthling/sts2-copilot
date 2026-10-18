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
| `combat.solver_partial` | 卡牌只建模了确定性部分（如后空翻格挡，抽牌未计） | warn |
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
| `potion.consider` | 预计掉血 ≥ MaxHp/3 且有药水 | warn |
| `potion.lethal` | 预测会致死且药水栏有药；优先判断伤害药水先杀，格挡药水只对可格挡伤害有效 | danger |
| `potion.use` | 本回合有药水能明确减少掉血/避免死亡/收尾时，给出具体药水与预计 HP | warn/danger |
| `potion.inventory` | 非战斗界面显示药水 3 格状态与最差药水 | info/warn |
| `potion.reward` | 战斗奖励药水：空位推荐拿；满 3 格时比较是否替换 | good/warn |
| `potion.discard` | 满 3 格且奖励药水更好时，明确丢弃哪一瓶 | warn |
| `reward.recommend` | 三选一最高分 | good |
| `reward.card_choice` | 三选一评分列表 | good |
| `reward.close_call` | 前两名分差 < 0.5 | info |
| `event.context` | 事件标题/描述（无选项时） | info |
| `event.recommend` | 事件/先古之民最高分选项；有致死/高风险时降为 warn | good / warn |
| `event.lethal` | 已知会致死的事件选项；排在推荐前 | danger |
| `event.no_option` | 所有选项锁定 | warn |
| `shop.recommend` | 买得起的最高分商品 | good |
| `shop.no_affordable` | 金币不足 | info |
| `shop.items` | 商品/价格/评分列表 | info |
| `rest.recommend` | 营地最高分选项 | good |
| `rest.smith_target` | 锻造推荐升级目标 | info |
| `rest.options` | 营地选项列表 | info |
| `treasure.recommend` | 宝箱遗物最高分 | good |
| `treasure.options` | 遗物选择列表 | info |
| `map.recommend` | 到 Boss 综合评分最高的下一步/路线 | good |
| `map.route` | 每个下一步的整条未来路径综合评分、HP、节点统计 | info |
| `map.close_call` | 前两名综合分差 < 0.5，提示“稳血线”与“贪收益”两种选择 | info |
| `run.overview` | 非战斗/非奖励/非地图 | info |

## 本回合出牌求解器（P1）

实现：`py/rules/combat.py`。`engine.py` 在战斗分支优先调用它；无法精确建模时回退到旧的集合背包粗算。

### 输入

- 手牌：`Cost` / `Damage` / `Block` / `Poison` / `Hits` / `Target` / `Vars`
- 玩家：`Hp` / `Block` / `Energy` / `PlayerPowers` / `RelicIds` / `RelicCounters`
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
- 建议序列中的升级牌用 `+` 标记（如 `打击+`、`防御+`），升级 2 级用 `+2`；弃牌提示同样带标记
- 攻击伤害：`floor((base + Strength + StrikeDummy?3) * Weak?0.75/.5 * Shrink?0.7 * Vulnerable?1.5+mods) * hits`
  - `StrikeDummy` 只在真正持有该遗物时 +3；本地化遗物名归一化后为空，不能把空串当成“持有”，否则所有打击都会被错误 +3
  - `Weak` 基础 0.75；攻击者持有 `DebilitatePower` 时为 0.5
  - `Vulnerable` 基础 1.5；`PaperPhrog` 使玩家 powered attack 的倍率 +0.25；`CrueltyPower` 再 +Amount/100；目标有 `DebilitatePower` 时倍率变为 `2*multiplier-1`
- 格挡：`floor((base + Dexterity) * Frail?0.75)`
- 敌人攻击：`floor((base + 敌人 Strength) * 敌人 Weak?0.75/.5 * 玩家 Vulnerable?1.5) * hits`
- 敌人 `ArtifactPower`：抵消下一次可见 debuff（毒/虚弱/易伤/脆弱/紧勒），并消耗 1 层；同一张牌的多段 debuff 分别结算（玩家侧 Artifact 需要等敌人攻击附带的 debuff 意图可读后再接）
- `PenNib`：`RelicCounters.PenNib == 9` 时，本回合下一张攻击牌（多段则每段）伤害 ×2，之后计数归 0 并继续累加
- `GremlinHorn`（地精角）：每击杀一个敌人 +1 能量；抽 1 张牌未计，列为 partial
- 即时力量/敏捷能力牌（如 `Inflame`/`Footwork`）可出牌，并影响本回合后续攻击/格挡；其他能力牌仍不模拟本回合后续 hook
- `Fisticuffs`（拳斗）：造成伤害后获得 `TotalDamage + OverkillDamage` 点格挡（包括被格挡的伤害；用于正确判断低血时是否能活）
- X 费纯攻击（如 `Skewer`/串刺）：枚举 `X=1..当前能量`，每点能量增加一段伤害；X 费复合效果仍降级为未建模
- `ThornsPower`：每次攻击命中前对玩家造成 `Thorns` 点可格挡伤害；多段按段触发
- `IntangiblePower`：受到的每次伤害/毒结算上限为 1；玩家和敌人都支持
- 回合结束手牌伤害（`OnTurnEndInHand`，如 Beckon/Burn/Decay/Infection/Toxic/Wither）：不可格挡，计入回合结束；若被 `Survivor` 等弃掉则不计；玩家 `Intangible` 时每张牌最多 1
- `StranglePower`：紧勒造成 8 伤害并施加 2 层；之后每打出一张牌，对该敌人造成 2 点无视格挡伤害（紧勒自身不触发）
- `RavenousPower`：同伴死亡时，存活且带该能力的敌人 +Ravenous 力量，并眩晕跳过本回合攻击
- 毒在敌方回合开始结算，无视格挡；毒死敌人后该敌人本回合不攻击
- 敌人格挡逐段吸收；单体攻击目标死亡后停止后续段数
- `Survivor` 会尝试弃掉一张手牌（枚举弃牌选择）
- 目标类型：`AnyEnemy` 逐个目标枚举；`AllEnemies` 全体；`Self` 自己；`RandomEnemy` 不建模
- 同名敌人按出现顺序标 `#1/#2`（敌人面板与建议序列一致），避免“打哪只”歧义
- `GrandFinale`（华丽收场）只在抽牌堆为空（`DrawCount == 0`）时建模；否则列 `combat.solver_unmodeled` 原因“抽牌堆未空”
- `Backflip` / `Finesse` 只建模格挡，抽牌列入 `combat.solver_partial`，不再因为抽牌变量整张丢弃

### 已建模 / 未建模

已建模：攻击、格挡、毒、虚弱、易伤、脆弱、力量、敏捷、荆棘、紧勒、Ravenous 眩晕、StrikeDummy、PaperPhrog、PenNib、GremlinHorn、Cruelty、Debilitate、敌人 Artifact、玩家/敌人 Intangible、Fisticuffs 伤害转格挡、即时力量/敏捷能力牌、纯伤害 X 费牌，以及这些效果的组合。

未建模（会显示在 `combat.solver_unmodeled`，不猜测）：

- X 费复合效果牌（非纯攻击）
- 非即时能力牌（例如 DemonForm/Accuracy/WellLaidPlans 的后续 hook）
- 状态/诅咒/任务牌（回合结束手牌伤害已单独建模，其余未建模）
- 带未识别 `Vars` 的牌（例如抽牌、加费、随机效果）
- 随机目标
- 遗物（目前只建模 `StrikeDummy`/`PaperPhrog`/`PenNib`/`GremlinHorn`；其他计数器、Orichalcum 等未建模）、药水使用、抽牌顺序、敌人本回合攻击附带的 debuff 意图

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

## 事件 / 先古之民

`EventOptions` 从 `EventRoom.CanonicalEvent` / `EventSynchronizer._events[0]` 读取；当前选项优先 `_currentOptions`，为空时回退 `_generatedOptions`。

评分是保守启发式：

- 锁定选项不可推荐；
- 遗物选项加权，稀有度越高越高；
- 标题/描述含「获得/遗物/稀有/升级/移除/最大生命/治疗/回复」加分；
- 含「失去/伤害/诅咒/中毒/掉血/减少/无法」减分；
- `Proceed`（继续）降权，避免把“离开”当最优。

在此之上有**致死/低血保护**：

- 已知事件 `AbyssalBaths` 用 `EventVars` 精确计算：每次浸浴 `+MaxHp` 当前/最大生命，再受 `Damage` 点不可格挡伤害；`Damage` 每次 +1，因此本次净损失 `Damage - MaxHp`。本次会死则输出 `event.lethal`（danger），绝不推荐；净损失超过 `max(3, 4% MaxHp)` 或剩余 HP ≤ `30% MaxHp` 时降权并推荐离开。
- 事件描述出现「死定了/必死/再泡下去/致命」等警告时，伤害选项直接按致死处理。
- 没有 `EventVars` 的旧日志/其他事件：伤害选项在当前 HP ≤ `40% MaxHp`（或 ≤8）时降权，避免在 A10 低血时继续赌事件。
- 推荐文本会写明预计净损失、剩余 HP 和下一次净损失；`event.lethal` 永远排在 `event.recommend` 之前。

只给出“推荐哪个选项”，不预测事件后续随机结果；先古之民页面同样按此评分。事件文本里的 `{Relic}` / `{Gold}` / `{HpLoss}` 会从 `LocString._variables` 替换；选项/事件描述缺失的 `DynamicVars`（如 `{Damage}` / `{MaxHp}`）由 C# 用 `EventVars` 填入数字，Python 同时用 `TextKey` 识别选项语义，不依赖中文标题。

## 药水管理

- 战斗内：只有在本回合明确“能少掉 ≥3 HP / 避免致死 / 药水伤害能收尾”时才输出 `potion.use`；普通小战斗不为了用而用。
- 失血/致死时优先比较当前药水的实际效果：格挡/金属化约 +7/+12 挡、缩小约 -30% 攻击、无形每段 1、伤害药水按 `ExplosiveAmpoule=10全体` / `FirePotion=20单体` / 其他读取目录 `Damage`。
- 非战斗界面始终给出 `potion.inventory`：显示 3 格占用、评分最高/最低；满 3 格时明确“奖励出现更高分药水先丢哪瓶”。
- 战斗奖励药水用 `RewardPotionIds` / `RewardPotions`：空位推荐拿最高分；满 3 格时只有奖励评分比当前最差高 0.2 才建议替换，并输出 `potion.discard`。
- 不把 `FairyInABottle` 等自动药水当普通战斗动作；不猜测未出现在目录中的药水效果。

## 商店 / 营地 / 宝箱

商店商品从 `MerchantInventory` 读取，价格取 `MerchantEntry._cost`：

- 卡牌用 `score_card`（含流派密度），无色牌 +0.3；
- 遗物固定 3.0；
- 药水 1.5，药水已满 3 个时 -2；
- 删牌服务：牌组里有诅咒/状态 2.5，否则 0.6；
- 只推荐 `Affordable=true` 的商品。

营地从 `RestSiteSynchronizer._restSites[0].options` 读取；HEAL 按实际回复量/最大生命评分，低血额外加分；SMITH 有可升级牌 2.0；DIG/LIFT 2.8；其余 1.5。锻造目标按 `score_card` 选最高分未升级牌。

宝箱从 `TreasureRoomRelicSynchronizer._currentRelics` 读取，遗物评分 `2.0 + rarity*0.5`；稀有度读不到时仍按顺序推荐。

## 地图 DP（P0）

C# 读完整地图图（`StandardActMap.Grid` 的所有节点 + `Children` 边 + Boss），放进 `MapNodes` / `MapEdges`；Python `_map_dp` 做记忆化 DAG 搜索。**下一步的评分不是只看当前节点**，而是从该节点一直算到 Boss 的整条最优路径；即使当前节点不在 `MapNodes` 里（幕起点/先古节点），也用 `MapChoices` 作为根继续向后看。

状态：`(node, hp, 前一个节点类型, 已走精英数)`。

转移：

```
loss = 节点期望掉血（A10 战斗/精英 ×1.30）
hp_after = min(MaxHp, hp - loss + 营地实际回复)
path_penalty = 精英叠加 / 连续精英 / 精英后营地 / 低血精英
value = nodeReward + path_penalty + riskPenalty(hp_after)
        + max(value(child, hp_after, nodeType, eliteCount+是否精英))
到 Boss：value = -bossPenalty(进入 Boss 时 HP)
```

- 精英叠加：第 2 个精英 -2，第 3 个 -4；连续精英额外 -3；精英后营地 +0.8；营地后精英 +0.5；精英后 HP <40% 额外 -1。
- Boss 前安全线：Act 1 基础 55%，每幕 +5%；A10 再 +15 个百分点（Act 3 封顶 80%），低于安全线按差值 ×40 惩罚。这样不会为了多拿精英遗物把 Boss 前 HP 压到危险线。
- 下一步列表显示：`综合评分`、`HP→x/y`、路径中的精英/营地/商店/宝箱数量、前 6 个节点；推荐文本给出到 Boss 的完整路径和最终 HP。
- 全图/Boss 不可用但仍有 `MapNodes`/`MapEdges` 时，`_map_lookahead` 做最多 6 步局部前瞻，输出会标注“局部前瞻”；连局部图都没有才回退下一层 `map_score`。

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
- 到 Boss 时低于安全线：按差值 ×40（A10 安全线更高）

输出：

- `map.recommend`：到 Boss 的完整推荐路线、预计结束 HP/比例、精英/营地/宝箱数量、综合评分
- `map.route`：**每个下一步选项的整条未来路径综合评分**、预计 HP、路径统计、前 6 个节点

全图不可用时，先用局部前瞻；连局部图都没有才回退下一层启发式，不会把只有当前节点的分数说成“综合”。

## 已知限制

- 求解器只覆盖已建模牌；非即时能力牌、X 费复合效果、抽牌、随机目标会降级/排除
- 伤害修正已支持 `StrengthPower` / `WeakPower` / `VulnerablePower` / `ShrinkPower` / `PaperPhrog` / `PenNib` / `CrueltyPower` / `DebilitatePower`；其他遗物/附魔/能力修正未计入
- 遗物只建模 `StrikeDummy` / `PaperPhrog` / `PenNib` / `GremlinHorn`；药水只给独立建议，不进入本回合 DFS；抽牌顺序、敌人本回合攻击附带的 debuff 未计入
- 毒/易伤/虚弱/紧勒已计 `ArtifactPower`，玩家/敌人 `IntangiblePower` 已计；其他特殊能力（Buffer、Thorns 玩家侧、Plating 回合结束等）仍未逐项建模
- 卡牌 `Tags` / `Keywords` 已从 `catalog.json` 读取，用于打击/消耗/保留等粗粒度协同；但不会解析每张牌的完整条件文本
- 地图掉血仍是**期望值**（按幕 + A10 系数缩放），不是用求解器逐场模拟；精英具体遭遇/遗物联动未知
- `reward_pick` / `map_pick` / `potion_use` 已记录；事件只对 `AbyssalBaths` 做精确伤害模型，其余事件是启发式

## 新增规则

1. 在 `engine.py` 对应函数加分支；卡牌求解效果加在 `combat.py`
2. 返回 `ruleId` / `text` / `severity`
3. 数值建议写明“粗算”或注明已建模范围
4. 给新卡牌效果加 `py/tests` 用例；未知效果必须降级，不能猜
5. 更新本文件
6. 用真实对局验证，再考虑加 C# 回退
