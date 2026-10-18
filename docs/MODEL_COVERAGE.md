# 模型目录与覆盖率

## 目标

`py/rules/data/catalog.json` 是从 **0.107.1 反编译源码**本地生成的模型目录，覆盖所有真实模型类：

| 类型 | 数量 |
|---|---:|
| 卡牌 | 578 |
| 遗物 | 298 |
| 能力（Power） | 260 |
| 药水 | 64 |
| 事件 | 68 |
| 遭遇 | 88 |

生成命令：

```powershell
python py\tools\build_catalog.py
```

目录只保存类名、构造参数、动态变量、效果命令、hook 名称和建模等级；**不保存反编译源码、游戏资源或本地化文本**。`ref/`、`dist/` 仍不提交。

## 建模等级

每个实体都有 `model.level`：

| 等级 | 含义 |
|---|---|
| `exact` | 当前求解器可直接计算其确定性效果 |
| `partial` | 目录/部分效果可用；抽牌、随机、条件、能力 hook 等未逐项计 |
| `catalog_only` | 有元数据，但不能用于精确战斗模拟 |

卡牌当前分布：

| 等级 | 数量 |
|---|---:|
| `exact` | 130 |
| `partial` | 421 |
| `catalog_only` | 27 |

这不是“只支持 130 张牌”：**所有 578 张牌都能进入奖励/商店评分和目录查询**；`exact` 仅表示能进入战斗 DFS 的精确即时模拟。`partial/catalog_only` 会在求解器输出中明确列出，不静默猜测。

## 已精确实现的机制

- 攻击/多段/全体/单体伤害、格挡、毒
- 力量、敏捷、虚弱、易伤、脆弱、Shrink
- 荆棘 `ThornsPower`（每次命中反伤）
- 紧勒 `StranglePower`（后续每张牌触发）
- `RavenousPower`（同伴死亡后强化+眩晕）
- `IntangiblePower`（每次伤害上限 1，毒也按 1 计）
- 回合结束手牌伤害（Beckon/Burn/Decay/Infection/Toxic/Wither 等；可被弃牌移除）
- `StrikeDummy` 对 Strike 牌 +3
- `Backflip` / `Finesse` 的格挡部分（抽牌列 `partial`）
- 格挡药水保命提示（+12 格挡）
- `ArtifactPower` 抵消下一次可见 debuff（毒/虚弱/易伤/脆弱/紧勒）
- `PaperPhrog` / `CrueltyPower` / `DebilitatePower` 的易伤/虚弱倍率修正
- `PenNib` 第 10 次攻击的 ×2（读取 `RelicCounters.PenNib`）
- `GremlinHorn` 击杀回 1 能量（抽 1 未计，partial）
- 玩家/敌人 `IntangiblePower`（每次伤害/毒上限 1）
- 即时力量/敏捷能力牌（`Inflame` / `Footwork`）
- `Fisticuffs` 的伤害转格挡（`TotalDamage + OverkillDamage`）
- 纯伤害 X 费牌（`Skewer` 等）按 `X=1..能量` 枚举段数；X 费复合效果仍降级
- 事件 `AbyssalBaths`：按 `EventVars` 的 `Damage` / `MaxHp` 计算每次净损失，致死/低血保护；其他事件按低血关键词降级（见 `docs/RULES.md`）

## 目录字段

卡牌：

```json
{
  "class": "Backflip",
  "id_snake": "BACKFLIP",
  "cost": 1,
  "type": "Skill",
  "rarity": "Common",
  "target": "self",
  "tags": [],
  "keywords": [],
  "vars": [{"key": "Block", "var": "BlockVar", "base": 5, "upgrade": 3}],
  "effects": [
    {"kind": "block", "amount": "Block", "target": "self"},
    {"kind": "draw", "amount": "Cards", "target": "self"}
  ],
  "model": {"level": "partial", "reasons": ["派生/牌堆/资源效果未逐项计"]}
}
```

遗物、能力、药水采用同样结构，分别记录 `hooks`、`type/stack`、`usage/target` 等。

## 为什么不是 585 个手写 if

卡牌效果顺序、目标、条件、随机数、生成牌、能力 hook 组合极多；逐张硬编码会不可维护且容易把“不知道”伪装成“知道”。本项目采用：

1. 源码自动抽取全量目录；
2. 通用 DFS 只处理已验证的即时效果；
3. 对每个实体保留 `model.level + reasons`；
4. 用实机日志校准后，把高频 `partial` 逐类提升为 `exact`。

这保证新增卡牌/遗物时先有数据，再按日志证据补模型，而不是静默猜测。
