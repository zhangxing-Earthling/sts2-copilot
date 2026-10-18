namespace Sts2Copilot;

public sealed record Advice(string RuleId, string Text, string Severity);

public static class Advisor
{
    public static List<Advice> Build(GameState state)
    {
        var list = new List<Advice>();

        if (state.ValidationError != null)
        {
            list.Add(new Advice("state.invalid", "状态校验失败：" + state.ValidationError, "danger"));
            return list;
        }

        if (state.CardChoices.Count > 0)
        {
            var ranked = state.CardChoices
                .Select(c => (card: c, score: ScoreCard(state, c)))
                .OrderByDescending(x => x.score)
                .ToList();

            var lines = new List<string>();
            if (state.RewardGold > 0)
            {
                lines.Add($"金币 +{state.RewardGold}");
            }

            foreach ((CardInfo card, double score) in ranked)
            {
                string cost = card.CostsX ? "X" : card.Cost.ToString();
                lines.Add($"{card.Name}（{cost}费）  评分 {score:F1}");
            }

            list.Add(new Advice("reward.recommend",
                $"推荐：{ranked[0].card.Name}（评分 {ranked[0].score:F1}）", "good"));
            list.Add(new Advice("reward.card_choice", "三选一：\n" + string.Join("\n", lines), "good"));
            if (ranked.Count >= 2 && ranked[0].score - ranked[1].score < 0.5)
            {
                list.Add(new Advice("reward.close_call", "前两名差距很小，按流派偏好选即可。", "info"));
            }

            return list;
        }

        if (!state.InCombat)
        {
            if (state.MapChoices.Count > 0)
            {
                var ranked = state.MapChoices
                    .Select(n => (node: n, score: MapScore(state, n)))
                    .OrderByDescending(x => x.score)
                    .ToList();
                list.Add(new Advice("map.recommend",
                    $"下一层推荐：{ranked[0].node.TypeName}（评分 {ranked[0].score:F1}）", "good"));
                list.Add(new Advice("map.route",
                    "下一层：\n" + string.Join("\n",
                        ranked.Select(x => $"{x.node.TypeName}（{x.node.Col},{x.node.Row}）  评分 {x.score:F1}")),
                    "info"));
                return list;
            }

            list.Add(new Advice(
                "run.overview",
                $"金币 {state.Gold} · 牌组 {state.DeckCount} 张 · 遗物 {state.Relics.Count} 件 · 药水 {state.Potions.Count} 瓶",
                "info"));
            return list;
        }

        int incoming = state.Enemies.Sum(e => e.Damage);
        int loss = Math.Max(0, incoming - state.Block);
        int enemyHp = state.Enemies.Sum(e => e.Hp + e.Block);

        var attacks = state.Hand
            .Where(c => c.Type == 1 && c.Damage > 0 && !c.CostsX && c.Cost <= state.Energy)
            .ToList();
        var blocks = state.Hand
            .Where(c => c.Block > 0 && !c.CostsX && c.Cost <= state.Energy)
            .ToList();

        (int maxDamage, List<CardInfo> lethalCards) = Best(attacks, state.Energy, c => c.Damage * Math.Max(1, c.Hits));
        (int maxBlock, List<CardInfo> blockCards) = Best(blocks, state.Energy, c => c.Block);

        bool canLethal = enemyHp > 0 && maxDamage >= enemyHp;

        if (incoming <= 0)
        {
            if (canLethal)
            {
                list.Add(new Advice("combat.lethal_available",
                    $"可斩杀（粗算 {maxDamage} ≥ 敌方 {enemyHp}）：{Names(lethalCards)}", "good"));
            }
            else
            {
                list.Add(new Advice("combat.no_attack", "敌方本回合没有攻击意图，可以全力输出。", "good"));
            }
        }
        else if (canLethal)
        {
            list.Add(new Advice("combat.lethal_available",
                $"可斩杀（粗算 {maxDamage} ≥ 敌方 {enemyHp}）：{Names(lethalCards)}", "good"));
            list.Add(new Advice("combat.incoming",
                $"不斩杀的话预计掉 {loss} 血（受 {incoming} / 挡 {state.Block}）。", "warn"));
        }
        else if (loss <= 0)
        {
            list.Add(new Advice("combat.blocked",
                $"格挡足够：受 {incoming} / 挡 {state.Block}，本回合不掉血。", "good"));
        }
        else if (state.Block + maxBlock >= incoming)
        {
            list.Add(new Advice("combat.full_block",
                $"可以全挡：{state.Block} + {maxBlock} ≥ {incoming}，推荐 {Names(blockCards)}。", "good"));
        }
        else if (loss >= state.Hp)
        {
            list.Add(new Advice("combat.lethal_incoming",
                $"致死风险：最多再挡 {maxBlock}，仍会掉 {loss - maxBlock}（HP {state.Hp}）。", "danger"));
        }
        else
        {
            list.Add(new Advice("combat.incoming",
                $"预计掉 {loss} 血；最优格挡可挡 {maxBlock}，剩 {Math.Max(0, loss - maxBlock)}。", "warn"));
        }

        if (loss > 0 && !canLethal && state.Block + maxBlock < incoming && maxBlock > 0)
        {
            list.Add(new Advice("combat.block_plan",
                $"优先格挡：{Names(blockCards)}（共 {maxBlock} 挡）。", "warn"));
        }

        list.Add(new Advice("resources.hand",
            $"手牌 {state.Hand.Count} 张，能量 {state.Energy}/{state.MaxEnergy}。", "info"));

        if (state.Energy > 0 && state.Hand.All(c => !c.Playable))
        {
            list.Add(new Advice("resources.waste", $"能量 {state.Energy} 点用不出去。", "warn"));
        }
        else if (state.Energy == 0)
        {
            var free = state.Hand.Where(c => c.Playable && c.Cost == 0).ToList();
            if (free.Count > 0)
            {
                list.Add(new Advice("resources.free_cards",
                    "能量已空，但还有 0 费牌可打：" + Names(free), "good"));
            }
        }

        if (state.Potions.Count > 0 && loss >= Math.Max(1, state.MaxHp / 3))
        {
            list.Add(new Advice("potion.consider", $"这回合伤害较高，背包里有 {state.Potions.Count} 瓶药水。", "warn"));
        }

        return list;
    }

    public static double ScoreCard(GameState state, CardInfo card)
    {
        double score = card.Rarity switch
        {
            4 => 3.0,
            5 => 3.5,
            3 => 2.0,
            2 => 1.2,
            1 => 0.5,
            _ => 0.5
        };

        int cost = Math.Max(1, card.Cost);
        int effect = card.Damage * Math.Max(1, card.Hits) + card.Block + (int)(card.Poison * 1.5);
        score += Math.Min(3.0, effect / (5.0 * cost));

        int deckSize = Math.Max(1, state.DeckCards.Count);
        int attacks = state.DeckCards.Count(c => c.Type == 1);
        int blocks = state.DeckCards.Count(c => c.Block > 0);

        if (card.Type == 1 && attacks * 1.0 / deckSize < 0.4)
        {
            score += 1.2;
        }

        if (card.Block > 0 && blocks * 1.0 / deckSize < 0.3)
        {
            score += 1.2;
        }

        if (card.Type == 3 && state.Act <= 1 && state.Floor <= 6)
        {
            score -= 1.2;
        }

        if (card.Poison > 0 && state.DeckCards.Count(c => c.Poison > 0) >= 2)
        {
            score += 0.5;
        }

        if (card.Cost >= 3 && state.Act <= 1)
        {
            score -= 1.0;
        }

        if (card.Cost == 0)
        {
            score += 0.3;
        }

        return score;
    }

    public static double MapScore(GameState state, MapNodeInfo node)
    {
        double hp = state.Hp / (double)Math.Max(1, state.MaxHp);
        int deck = state.DeckCards.Count;

        return node.Type switch
        {
            6 => hp > 0.6 && deck >= 15 ? 3.0 : -2.0,
            4 => hp < 0.6 ? 2.6 : 1.0,
            2 => state.Gold >= 120 ? 2.2 : 0.4,
            3 => 2.0,
            5 => hp > 0.5 ? 1.2 : 0.6,
            1 => 1.1,
            _ => 0.0
        };
    }

    private static (int value, List<CardInfo> cards) Best(List<CardInfo> cards, int energy, Func<CardInfo, int> value)
    {
        if (cards.Count == 0)
        {
            return (0, new List<CardInfo>());
        }

        if (cards.Count > 12)
        {
            cards = cards.Take(12).ToList();
        }

        int best = 0;
        int bestMask = 0;
        int n = cards.Count;

        for (int mask = 0; mask < (1 << n); mask++)
        {
            int cost = 0;
            int total = 0;
            for (int i = 0; i < n; i++)
            {
                if ((mask & (1 << i)) == 0)
                {
                    continue;
                }

                cost += Math.Max(0, cards[i].Cost);
                total += value(cards[i]);
            }

            if (cost <= energy && total > best)
            {
                best = total;
                bestMask = mask;
            }
        }

        var chosen = new List<CardInfo>();
        for (int i = 0; i < n; i++)
        {
            if ((bestMask & (1 << i)) != 0)
            {
                chosen.Add(cards[i]);
            }
        }

        return (best, chosen);
    }

    private static string Names(IEnumerable<CardInfo> cards)
    {
        string text = string.Join("、", cards.Select(c => c.Name));
        return string.IsNullOrEmpty(text) ? "（无）" : text;
    }

    public static string Worst(IEnumerable<Advice> advice)
    {
        var list = advice.ToList();
        if (list.Any(a => a.Severity == "danger"))
        {
            return "danger";
        }

        if (list.Any(a => a.Severity == "warn"))
        {
            return "warn";
        }

        return list.Any(a => a.Severity == "good") ? "good" : "info";
    }
}
