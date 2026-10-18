# Prompt: 规则 Patch 审核

> 用途：把规则修改建议变成可审核、可回滚的 patch。
> 由外部 DSH/人工使用；助手不再内置复盘或自动改规则。

## 输入

- 当前规则版本 `rules_version`
- 规则优化输出的 `patches[]`
- 最近 N 局的指标（胜率、每幕掉血、精英胜率、金币效率）

## 输出

```json
{
  "accepted": [
    {
      "rule_id": "map.elite_risk",
      "op": "update",
      "before": "hp > 0.6 && deck >= 15",
      "after": "hp > 0.72 && deck >= 17",
      "reason": "最近 5 局 Act1 精英平均掉血 38，阈值偏低",
      "evidence_event_ids": ["evt_0012", "evt_0042"],
      "risk": "low|medium|high",
      "rollback": "revert patch id"
    }
  ],
  "rejected": [
    {
      "rule_id": "combat.lethal",
      "reason": "样本不足 / 无法验证 / 与现有规则冲突"
    }
  ]
}
```

## 审核门槛

- 至少 3 个独立 `event_id` 支持
- 不能只基于 1 局
- 改动必须能用现有日志回放验证
- 每条 patch 必须可回滚
- 高风险的规则（致死/精英）先 shadow 模式跑，不直接生效

## 禁止

- 直接改 `engine.py`
- 一次改超过 2 条规则
- 用“感觉更强”作为理由
