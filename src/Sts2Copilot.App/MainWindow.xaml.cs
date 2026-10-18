using System.Diagnostics;
using System.Windows;
using System.Windows.Threading;

namespace Sts2Copilot;

public partial class MainWindow : Window
{
    private readonly MemoryReader _reader = new();
    private readonly RunLogWriter _log = new();
    private readonly AdvisorClient _rules = new();
    private readonly DispatcherTimer _timer;

    private bool _busy;
    private int _pid;
    private GameState? _previous;
    private string? _lastSeed;
    private int _lastTurn = -1;
    private string _lastFingerprint = "";
    private string _lastRewardKey = "";
    private bool _inCombat;
    private bool _pendingTurn;

    public MainWindow()
    {
        InitializeComponent();
        _timer = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(250) };
        _timer.Tick += Timer_Tick;
        Loaded += (_, _) => Connect();
    }

    private void ConnectButton_Click(object sender, RoutedEventArgs e)
    {
        Connect();
    }

    private void Connect()
    {
        _timer.Stop();
        _log.End("reconnect");
        _reader.Dispose();
        ResetTracking();

        Process? process = Process.GetProcessesByName("SlayTheSpire2")
            .OrderByDescending(p => p.StartTime)
            .FirstOrDefault();

        if (process == null)
        {
            StatusText.Text = "未找到游戏进程";
            LogText.Text = "请先启动 Slay the Spire 2";
            return;
        }

        if (!_reader.Attach(process.Id))
        {
            StatusText.Text = "连接失败";
            LogText.Text = _reader.Error ?? "unknown";
            App.Log("attach failed: " + (_reader.Error ?? "unknown"));
            return;
        }

        App.Log($"attached pid={process.Id} version={_reader.GameVersion}");

        _pid = process.Id;
        StatusText.Text = $"PID {_pid} · {_reader.GameVersion}";
        LogText.Text = $"已连接 · 版本锁 {_reader.GameVersion} · 日志写入 {_log.CurrentPath ?? "等待开局"}";
        _timer.Start();
    }

    private async void Timer_Tick(object? sender, EventArgs e)
    {
        if (_busy)
        {
            return;
        }

        if (!ProcessExists(_pid))
        {
            _timer.Stop();
            _log.End("process_exit");
            StatusText.Text = "游戏已退出";
            return;
        }

        _busy = true;
        try
        {
            var started = Stopwatch.GetTimestamp();
            GameState? state = await Task.Run(() => _reader.Read());
            double ms = (Stopwatch.GetTimestamp() - started) * 1000.0 / Stopwatch.Frequency;

            if (state == null)
            {
                if (_lastSeed != null)
                {
                    _log.End("left_run");
                    ResetTracking();
                }

                RunText.Text = "等待进入对局…";
                HpText.Text = "---";
                EnergyText.Text = "";
                HandText.Text = "---";
                EnemyText.Text = "---";
                AdviceText.Text = _reader.Error ?? "菜单/加载中";
                MiscText.Text = "";
                StatusText.Text = $"PID {_pid} · {_reader.GameVersion} · {ms:F1} ms";
                return;
            }

            if (state.ValidationError != null)
            {
                StatusText.Text = $"校验失败 · {ms:F1} ms";
                AdviceText.Text = "状态校验失败：" + state.ValidationError;
                LogText.Text = "已停止建议与记录，避免读错数据；请重启游戏或更新适配";
                return;
            }

            List<Advice>? pythonAdvice = await _rules.GetAdviceAsync(state);
            List<Advice> advice = pythonAdvice is { Count: > 0 } ? pythonAdvice : Advisor.Build(state);
            ProcessLog(state, advice);
            UpdateUi(state, advice);

            StatusText.Text = $"PID {_pid} · {_reader.GameVersion} · {ms:F1} ms · {(pythonAdvice != null ? "py" : "local")}";
        }
        catch (Exception ex)
        {
            StatusText.Text = "读取异常";
            LogText.Text = ex.Message;
        }
        finally
        {
            _busy = false;
        }
    }

    private void ProcessLog(GameState state, IReadOnlyList<Advice> advice)
    {
        if (!string.Equals(_lastSeed, state.Seed, StringComparison.Ordinal))
        {
            if (_lastSeed != null)
            {
                _log.End("seed_changed");
            }

            _lastSeed = state.Seed;
            _lastTurn = -1;
            _previous = null;
            _lastFingerprint = "";
            _log.Start(state);
            LogText.Text = "日志：" + System.IO.Path.GetFileName(_log.CurrentPath ?? "");
        }

        if (state.InCombat && !_inCombat)
        {
            _inCombat = true;
            _lastTurn = -1;
            _pendingTurn = false;
            _previous = null;
            _lastFingerprint = "";
            _log.Event("combat_start", new
            {
                state.Floor,
                state.CurrentRoom,
                state.Encounter,
                state.Hp,
                state.MaxHp
            });
        }

        string rewardKey = string.Join(",", state.CardChoices.Select(c => c.Id));
        if (state.CardChoices.Count > 0 && !string.Equals(rewardKey, _lastRewardKey, StringComparison.Ordinal))
        {
            _lastRewardKey = rewardKey;
            _log.Reward(state, advice);
        }
        else if (state.CardChoices.Count == 0)
        {
            _lastRewardKey = "";
        }

        if (state.Turn != _lastTurn)
        {
            _lastTurn = state.Turn;
            _pendingTurn = true;
            _previous = null;
            _lastFingerprint = "";
        }

        if (state.InCombat && state.Phase == 3)
        {
            string fingerprint = Fingerprint(state);

            if (_pendingTurn)
            {
                _pendingTurn = false;
                _log.Turn(state, advice);
            }
            else if (_previous != null && !string.Equals(fingerprint, _lastFingerprint, StringComparison.Ordinal))
            {
                List<CardInfo> played = DiffHand(_previous.Hand, state.Hand);
                _log.Action(state, _previous, played, played.Count > 0 ? "card_play" : "state_change");
            }

            _previous = state;
            _lastFingerprint = fingerprint;
        }

        if (!state.InCombat && _inCombat)
        {
            _inCombat = false;
            _pendingTurn = false;
            _log.Event("combat_end", new { state.Hp, state.MaxHp, state.Turn });
        }
    }

    private void UpdateUi(GameState s, IReadOnlyList<Advice> advice)
    {
        string room = string.IsNullOrEmpty(s.Encounter) ? s.CurrentRoom : s.Encounter;
        RunText.Text = $"{s.Character} · 第 {s.Act} 幕 · 第 {s.Floor} 层 · 难度 {s.Ascension}" +
                       (string.IsNullOrEmpty(room) ? "" : $" · {room}");
        HpText.Text = $"HP {s.Hp}/{s.MaxHp}    格挡 {s.Block}    金币 {s.Gold}";

        string phase = s.Phase switch
        {
            0 => "无",
            1 => "回合开始",
            2 => "自动预出牌",
            3 => "出牌阶段",
            4 => "自动结束",
            5 => "回合结束",
            _ => s.Phase.ToString()
        };

        EnergyText.Text = s.InCombat
            ? $"能量 {s.Energy}/{s.MaxEnergy}    星星 {s.Stars}    抽牌 {s.DrawCount}    弃牌 {s.DiscardCount}    牌组 {s.DeckCount}    [{phase}]"
            : $"牌组 {s.DeckCount} 张";

        HandText.Text = s.Hand.Count == 0
            ? "（无）"
            : string.Join("\n", s.Hand.Select(c =>
            {
                string cost = c.CostsX ? "X" : c.Cost.ToString();
                string up = c.Upgraded > 0 ? "+" : "";
                string mark = c.Playable ? "  " : "✕ ";
                string effect = EffectText(c);
                return $"{mark}{c.Name}{up}  ({cost}){effect}";
            }));

        EnemyText.Text = s.Enemies.Count == 0
            ? "（无）"
            : string.Join("\n", s.Enemies.Select(e =>
            {
                string block = e.Block > 0 ? $" 挡{e.Block}" : "";
                string damage = e.Damage > 0 ? $"  攻 {e.Damage}" + (e.Hits > 1 ? $"×{e.Hits}" : "") : "";
                return $"{e.Name}  {e.Hp}/{e.MaxHp}{block}{damage}  [{e.Intent}]";
            }));

        bool hasMap = s.MapChoices.Count > 0;
        MapSeparator.Visibility = hasMap ? Visibility.Visible : Visibility.Collapsed;
        MapLabel.Visibility = hasMap ? Visibility.Visible : Visibility.Collapsed;
        MapText.Visibility = hasMap ? Visibility.Visible : Visibility.Collapsed;

        if (hasMap)
        {
            var ranked = s.MapChoices.OrderByDescending(n => Advisor.MapScore(s, n)).ToList();
            MapText.Text = $"当前：{s.MapTypeName}（{s.MapCol},{s.MapRow}）\n" +
                           string.Join("\n", ranked.Select(n =>
                               $"{n.TypeName}（{n.Col},{n.Row}）  评分 {Advisor.MapScore(s, n):F1}"));
        }

        bool hasReward = s.CardChoices.Count > 0;
        RewardSeparator.Visibility = hasReward ? Visibility.Visible : Visibility.Collapsed;
        RewardLabel.Visibility = hasReward ? Visibility.Visible : Visibility.Collapsed;
        RewardText.Visibility = hasReward ? Visibility.Visible : Visibility.Collapsed;

        if (hasReward)
        {
            var lines = new List<string>();
            if (s.RewardGold > 0)
            {
                lines.Add($"金币 +{s.RewardGold}");
            }

            foreach (CardInfo card in s.CardChoices.OrderByDescending(c => Advisor.ScoreCard(s, c)))
            {
                string cost = card.CostsX ? "X" : card.Cost.ToString();
                string effect = EffectText(card);
                lines.Add($"{card.Name}（{cost}费）{effect}  评分 {Advisor.ScoreCard(s, card):F1}");
            }

            RewardText.Text = string.Join("\n", lines);
        }

        AdviceText.Text = string.Join("\n", advice.Select(a => a.Text));
        AdviceText.Foreground = Advisor.Worst(advice) switch
        {
            "danger" => System.Windows.Media.Brushes.OrangeRed,
            "warn" => System.Windows.Media.Brushes.Goldenrod,
            "good" => System.Windows.Media.Brushes.LightGreen,
            _ => System.Windows.Media.Brushes.LightSteelBlue
        };

        MiscText.Text = "遗物：" + (s.Relics.Count == 0 ? "无" : string.Join("、", s.Relics)) +
                        "\n药水：" + (s.Potions.Count == 0 ? "无" : string.Join("、", s.Potions)) +
                        $"\n种子：{s.Seed}" +
                        $"\n日志：{System.IO.Path.GetFileName(_log.CurrentPath ?? "未开始")}";
    }

    private static string EffectText(CardInfo card)
    {
        var parts = new List<string>();
        if (card.Damage > 0)
        {
            parts.Add($"{card.Damage}" + (card.Hits > 1 ? $"×{card.Hits}" : "") + "伤");
        }

        if (card.Block > 0)
        {
            parts.Add($"{card.Block}挡");
        }

        if (card.Poison > 0)
        {
            parts.Add($"{card.Poison}毒");
        }

        return parts.Count == 0 ? "" : "  " + string.Join(" ", parts);
    }

    private static string Fingerprint(GameState s)
    {
        string hand = string.Join(",", s.Hand.Select(c => c.Id).OrderBy(x => x, StringComparer.Ordinal));
        string enemies = string.Join(",", s.Enemies.Select(e => $"{e.Id}:{e.Hp}:{e.Block}"));
        return $"{s.Turn}|{s.Energy}|{s.Hp}|{s.Block}|{hand}|{enemies}|{string.Join(",", s.Potions)}";
    }

    private static List<CardInfo> DiffHand(IReadOnlyList<CardInfo> before, IReadOnlyList<CardInfo> after)
    {
        var counts = after.GroupBy(c => c.Id).ToDictionary(g => g.Key, g => g.Count());
        var played = new List<CardInfo>();
        foreach (CardInfo card in before)
        {
            if (counts.TryGetValue(card.Id, out int count) && count > 0)
            {
                counts[card.Id] = count - 1;
            }
            else
            {
                played.Add(card);
            }
        }

        return played;
    }

    private void ResetTracking()
    {
        _previous = null;
        _lastSeed = null;
        _lastTurn = -1;
        _lastFingerprint = "";
        _lastRewardKey = "";
        _inCombat = false;
        _pendingTurn = false;
    }

    private static bool ProcessExists(int pid)
    {
        try
        {
            return !Process.GetProcessById(pid).HasExited;
        }
        catch
        {
            return false;
        }
    }

    private void Topmost_Changed(object sender, RoutedEventArgs e)
    {
        Topmost = (sender as System.Windows.Controls.CheckBox)?.IsChecked == true;
    }

    protected override void OnClosed(EventArgs e)
    {
        _timer.Stop();
        _log.End("app_closed");
        _log.Dispose();
        _reader.Dispose();
        _rules.Dispose();
        base.OnClosed(e);
    }
}
