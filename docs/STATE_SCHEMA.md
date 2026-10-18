# State Schema

C# `GameState` 序列化为 **PascalCase** JSON，POST 到 Python `/advise`。

## 顶层

| 字段 | 类型 | 说明 |
|---|---|---|
| `GameVersion` | string | 例如 `0.107.1` |
| `Seed` | string | 对局种子 |
| `RunStartTime` | long | 游戏 `RunManager._startTime`，用于一局一个日志文件 |
| `Character` | string | 本地化角色名 |
| `Act` / `Floor` / `Ascension` | int | 幕/层/难度 |
| `Hp` / `MaxHp` / `Block` / `Gold` | int | 资源 |
| `Energy` / `MaxEnergy` / `Stars` | int | 战斗资源 |
| `Turn` / `Phase` | int | 回合数 / `PlayerTurnPhase`（Play=3） |
| `InCombat` | bool | 是否战斗中 |
| `CurrentRoom` / `Encounter` | string | 房间类型 / 遭遇 id |
| `Hand` / `DeckCards` / `CardChoices` | CardInfo[] | 手牌 / 牌组 / 三选一 |
| `Enemies` | EnemyInfo[] | 敌人 |
| `CombatEvents` | CombatEventInfo[] | 本次读取新增的精确战斗事件（card_play/potion_use） |
| `PlayerPowers` | object | 玩家能力层数，例如 `{"StrengthPower":2}` |
| `Relics` / `Potions` | string[] | 本地化名称 |
| `RelicIds` / `PotionIds` | string[] | 游戏 id，供求解器识别 StrikeDummy/药水等 |
| `RelicCounters` | object | 需要计数的遗物状态，例如 `{"PenNib":9}`（第 10 次攻击前） |
| `MapChoices` | MapNodeInfo[] | 当前节点可走的下一层 |
| `MapNodes` | MapNodeInfo[] | 全图节点（含 Boss） |
| `MapEdges` | MapEdgeInfo[] | 全图有向边 |
| `MapCol` / `MapRow` / `MapTypeName` | int/string | 当前地图节点 |
| `RewardGold` | int | 未领取的奖励金币 |
| `RewardRelics` / `RewardPotions` | RelicChoiceInfo[] / string[] | 奖励中的遗物/药水 |
| `RewardPotionIds` | string[] | 奖励药水的游戏 id，和 `RewardPotions` 一一对应 |
| `InEvent` | bool | 是否在事件/先古之民页面 |
| `EventId` / `EventTitle` / `EventDescription` | string | 事件 id、标题、当前页描述 |
| `EventIsAncient` | bool | 是否先古之民事件 |
| `EventVars` | object | 事件 `DynamicVars` 基值，例如 `{"MaxHp":2,"Damage":14,"Heal":10}`；用于事件伤害/治疗建模 |
| `EventOptions` | EventOptionInfo[] | 当前事件选项 |
| `InShop` / `ShopItems` | bool / ShopItemInfo[] | 商店是否打开、商品（卡/遗物/药水/删牌） |
| `InRestSite` / `RestOptions` | bool / RestOptionInfo[] | 营地是否打开、休息/锻造等选项 |
| `InTreasure` / `RelicChoices` | bool / RelicChoiceInfo[] | 宝箱是否打开、遗物选择 |
| `ValidationError` | string? | 非空表示停止建议 |

## CardInfo

| 字段 | 说明 |
|---|---|
| `Id` | 内部 id，例如 `StrikeSilent` |
| `Name` | 中文名 |
| `Cost` / `CostsX` | 费用 / 是否 X 费 |
| `Type` | 1 Attack / 2 Skill / 3 Power / 4 Status / 5 Curse / 6 Quest |
| `Target` | `TargetType`：0 None / 1 Self / 2 AnyEnemy / 3 AllEnemies / 4 RandomEnemy |
| `Rarity` | 1 Basic / 2 Common / 3 Uncommon / 4 Rare / 5 Ancient |
| `Upgraded` | 升级等级 |
| `Playable` | 按当前能量粗判 |
| `Damage` / `Block` / `Poison` | 从 `DynamicVars` 读的基值 |
| `Hits` | 段数（`Repeat`，默认 1） |
| `Vars` | 全部 `DynamicVars` 基值，例如 `{"Damage":6}`、`{"WeakPower":1}` |

## EnemyInfo

| 字段 | 说明 |
|---|---|
| `Id` / `Name` | 内部 id / 中文名 |
| `Hp` / `MaxHp` / `Block` | 生命/格挡 |
| `Intent` | 本地化意图（攻击/防御/强化…） |
| `Damage` / `Hits` | 当前修正后的总伤害 / 总段数 |
| `Powers` | 能力层数，例如 `{"VulnerablePower":1}` |
| `Attacks` | 本回合每段攻击的 `BaseDamage` / `Hits` |

### EnemyAttackInfo

| 字段 | 说明 |
|---|---|
| `BaseDamage` | 修正前单段伤害 |
| `Hits` | 段数 |

## CombatEventInfo

| 字段 | 说明 |
|---|---|
| `Kind` | `card_play` / `potion_use` / `card_drawn` / `block_gained` / `damage_received` / `power_received` |
| `Id` / `Name` | 内部 id / 中文名（卡牌、药水、能力） |
| `Target` | 目标中文名；无目标为 null |
| `TargetHp` / `TargetMaxHp` | 目标当前/最大 HP，用于区分同名敌人 |
| `PlayIndex` / `PlayCount` | 第几次播放 / 总次数（Replay） |
| `AutoPlay` | 是否自动打出 |
| `EnergySpent` / `StarsSpent` | 实际消耗 |
| `Amount` | 格挡值/伤害总额/能力层数 |
| `Blocked` / `Unblocked` / `Overkill` | 伤害的格挡/未格挡/溢出 |
| `Source` / `Receiver` / `Dealer` | 来源（卡牌或遗物）、接收者、伤害施加者 |
| `FromHandDraw` | 是否从手牌抽（`card_drawn`） |

C# 只在每次读取时放新增事件，不会重复发送整个历史。History 可读时这些事件是权威来源，C# 不再写推断 `action`；只有 History 完全不可读时才回退到 `action`。游标用已读数量 + 连续空列表判断重置，不用 entry 地址（GC 会移动对象）；地址去重只作为兜底诊断。

## EventOptionInfo

| 字段 | 说明 |
|---|---|
| `Index` | 选项顺序（0-based，与游戏一致） |
| `TextKey` | 选项本地化 key，例如 `ABYSSAL_BATHS.pages.ALL.options.LINGER`；用于不依赖中文标题识别选项语义 |
| `Title` / `Description` | 选项标题/描述（本地化；事件 `DynamicVars` 会填入数字） |
| `Locked` / `Proceed` | 是否锁定 / 是否是“继续”按钮 |
| `RelicId` / `RelicName` | 遗物选项的 id/中文名 |
| `RelicRarity` | 遗物稀有度（读不到时为 0） |

## ShopItemInfo

| 字段 | 说明 |
|---|---|
| `Index` | 商品顺序 |
| `Kind` | `card` / `colorless` / `relic` / `potion` / `removal` |
| `Name` / `Description` | 名称/描述 |
| `Cost` / `Affordable` | 价格 / 当前金币是否够 |
| `RelicId` / `RelicName` | 遗物 id/中文名 |
| `Card` | 卡牌详情（同 CardInfo） |

## RestOptionInfo

| 字段 | 说明 |
|---|---|
| `Index` / `OptionId` | 顺序 / `HEAL`、`SMITH`、`DIG` 等 |
| `Title` / `Description` | 本地化标题/描述 |
| `Enabled` | 是否可选 |
| `HealAmount` | HEAL 的回复量（基础 30% MaxHp） |

## RelicChoiceInfo

| 字段 | 说明 |
|---|---|
| `Index` / `Id` / `Name` | 顺序 / 遗物 id / 中文名 |
| `Description` | 遗物描述 |
| `Rarity` | 稀有度（读不到为 0） |

## MapNodeInfo

| 字段 | 说明 |
|---|---|
| `Col` / `Row` | 地图坐标 |
| `Type` | 1 未知 / 2 商店 / 3 宝箱 / 4 营地 / 5 战斗 / 6 精英 / 7 Boss / 8 远古 |
| `TypeName` | 中文名 |

## MapEdgeInfo

| 字段 | 说明 |
|---|---|
| `FromCol` / `FromRow` | 起点坐标 |
| `ToCol` / `ToRow` | 终点坐标 |

## 示例

```json
{
  "GameVersion": "0.107.1",
  "Seed": "XYTKRLKCWF",
  "Character": "静默猎手",
  "Act": 1, "Floor": 2, "Ascension": 0,
  "Hp": 67, "MaxHp": 70, "Block": 0, "Gold": 109,
  "Energy": 0, "MaxEnergy": 3, "Stars": 0,
  "Turn": 3, "Phase": 3, "InCombat": false,
  "Hand": [],
  "DeckCards": [{ "Id": "StrikeSilent", "Name": "打击", "Cost": 1, "Type": 1, "Target": 2, "Damage": 6, "Vars": { "Damage": 6 } }],
  "CardChoices": [],
  "Enemies": [],
  "PlayerPowers": { "StrengthPower": 2 },
  "Relics": ["蛇之戒指", "奥术卷轴"],
  "Potions": [],
  "MapChoices": [{ "Col": 3, "Row": 2, "Type": 1, "TypeName": "未知" }],
  "MapCol": 3, "MapRow": 1, "MapTypeName": "战斗",
  "RewardGold": 0,
  "ValidationError": null
}
```

## 响应

```json
{
  "advice": [
    { "ruleId": "combat.solver", "text": "最优顺序：打击→虫 → 打击→虫；可斩杀…", "severity": "good" },
    { "ruleId": "combat.solver_detail", "text": "敌方受击后剩 0 HP；…", "severity": "info" }
  ],
  "solver": {
    "version": 1,
    "sequence": ["打击→虫", "打击→虫"],
    "hpLoss": 0,
    "hpAfter": 70,
    "incoming": 8,
    "block": 0,
    "energyLeft": 0,
    "enemyHpLeft": 0,
    "damageDealt": 10,
    "poisonKills": 0,
    "lethal": true,
    "truncated": false,
    "modeled": 2,
    "unmodeled": ["刀扇"]
  },
  "source": "python"
}
```

`severity` 只允许 `info` / `good` / `warn` / `danger`。

### solver 字段

战斗回合有 `solver`；非战斗或无法求解时可能没有。`hpAfter` 是敌方行动后的预测 HP，校准脚本用它对比下一回合/战斗结束的实际 HP。`error` 非空表示本回合没有可评估预测。

## 校验规则

- `0 <= Hp <= MaxHp`，`MaxHp > 0`
- `0 <= Energy <= 20`，`0 <= MaxEnergy <= 20`
- 手牌 ≤ 10
- 抽牌/弃牌/牌组数量 ≥ 0
- 敌人 `0 <= Hp <= MaxHp`
