# State Schema

C# `GameState` 序列化为 **PascalCase** JSON，POST 到 Python `/advise`。

## 顶层

| 字段 | 类型 | 说明 |
|---|---|---|
| `GameVersion` | string | 例如 `0.107.1` |
| `Seed` | string | 对局种子 |
| `Character` | string | 本地化角色名 |
| `Act` / `Floor` / `Ascension` | int | 幕/层/难度 |
| `Hp` / `MaxHp` / `Block` / `Gold` | int | 资源 |
| `Energy` / `MaxEnergy` / `Stars` | int | 战斗资源 |
| `Turn` / `Phase` | int | 回合数 / `PlayerTurnPhase`（Play=3） |
| `InCombat` | bool | 是否战斗中 |
| `CurrentRoom` / `Encounter` | string | 房间类型 / 遭遇 id |
| `Hand` / `DeckCards` / `CardChoices` | CardInfo[] | 手牌 / 牌组 / 三选一 |
| `Enemies` | EnemyInfo[] | 敌人 |
| `PlayerPowers` | object | 玩家能力层数，例如 `{"StrengthPower":2}` |
| `Relics` / `Potions` | string[] | 本地化名称 |
| `MapChoices` | MapNodeInfo[] | 当前节点可走的下一层 |
| `MapNodes` | MapNodeInfo[] | 全图节点（含 Boss） |
| `MapEdges` | MapEdgeInfo[] | 全图有向边 |
| `MapCol` / `MapRow` / `MapType` / `MapTypeName` | int/string | 当前地图节点 |
| `RewardGold` | int | 未领取的奖励金币 |
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
| `Attacks` | 本回合每段攻击的 `BaseDamage` / `Hits` / `Damage` |

### EnemyAttackInfo

| 字段 | 说明 |
|---|---|
| `BaseDamage` | 修正前单段伤害 |
| `Hits` | 段数 |
| `Damage` | 当前修正后的总伤害（Base 经力量/虚弱/易伤） |

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
  "MapCol": 3, "MapRow": 1, "MapType": 5, "MapTypeName": "战斗",
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
  "source": "python"
}
```

`severity` 只允许 `info` / `good` / `warn` / `danger`。

## 校验规则

- `0 <= Hp <= MaxHp`，`MaxHp > 0`
- `0 <= Energy <= 20`，`0 <= MaxEnergy <= 20`
- 手牌 ≤ 10
- 抽牌/弃牌/牌组数量 ≥ 0
- 敌人 `0 <= Hp <= MaxHp`
