using System.Diagnostics;
using System.IO;
using System.Windows;
using System.Windows.Threading;
using Clipboard = System.Windows.Clipboard;

namespace Sts2Copilot;

public partial class MainWindow : Window
{
    private readonly MemoryReader _reader = new();
    private readonly RunLogWriter _log = new();
    private readonly AdvisorClient _rules = new();
    private readonly DispatcherTimer _timer;
    private readonly DispatcherTimer _attachTimer;

    private bool _busy;
    private int _pid;
    private GameState? _previous;
    private string? _lastSeed;
    private long _lastRunStart;
    private int _lastTurn = -1;
    private string _lastFingerprint = "";
    private string _lastRewardKey = "";
    private List<CardInfo>? _rewardDeckBefore;
    private List<CardInfo> _rewardOptions = new();
    private bool _hasMapPosition;
    private int _lastMapCol;
    private int _lastMapRow;
    private string _lastMapType = "";
    private bool _inCombat;
    private bool _pendingTurn;
    private string _lastEncounter = "";
    private int _lastCombatHp;
    private int _lastCombatMaxHp;
    private int _lastHistoryDuplicates;

    public MainWindow()
    {
        InitializeComponent();
        _timer = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(250) };
        _timer.Tick += Timer_Tick;
        _attachTimer = new DispatcherTimer { Interval = TimeSpan.FromSeconds(1.5) };
        _attachTimer.Tick += (_, _) => Connect();
        Loaded += async (_, _) =>
        {
            StatusText.Text = "启动本地规则服务…";
            LogStatusText.Text = "复制日志地址 + 规则优化提示词给 DSH";
            if (!await App.RulesHost.EnsureRunningAsync())
            {
                App.Log("rules service unavailable: " + (App.RulesHost.Error ?? "unknown"));
            }

            Connect();
        };
    }

    private void ConnectButton_Click(object sender, RoutedEventArgs e)
    {
        Connect();
    }

    private void CopyLogBundle_Click(object sender, RoutedEventArgs e)
    {
        string? logPath = FindCurrentLogPath();
        if (string.IsNullOrWhiteSpace(logPath) || !File.Exists(logPath))
        {
            LogStatusText.Text = "没有可复制的对局日志";
            return;
        }

        if (new FileInfo(logPath).Length == 0)
        {
            LogStatusText.Text = "当前日志为空，先进入对局再复制";
            return;
        }

        string prompt = FindPromptFile("rule-optimize.md") is { } promptPath
            ? File.ReadAllText(promptPath)
            : "你是 StS2 Copilot 的开发代理。请读取下面的日志，直接优化 py/rules 下的规则/求解器，跑测试和校准；不要 push。";
        string bundle = prompt
                        + "\n\n## 本局日志\n\n路径：`"
                        + logPath
                        + "`\n\n请直接读取该文件，不要要求我粘贴全文。\n";

        try
        {
            try
            {
                Clipboard.SetText(bundle);
            }
            catch
            {
                Clipboard.Clear();
                Clipboard.SetText(bundle);
            }

            LogStatusText.Text = $"已复制提示词 + 本局日志：{Path.GetFileName(logPath)}（{new FileInfo(logPath).Length / 1024} KB）";
        }
        catch (Exception ex)
        {
            LogStatusText.Text = "复制到剪贴板失败：" + ex.Message;
        }
    }

    private string? FindCurrentLogPath()
    {
        string? path = _log.CurrentPath;
        return !string.IsNullOrWhiteSpace(path) && File.Exists(path) ? path : null;
    }

    private static string? FindPromptFile(string name)
    {
        string bundled = Path.Combine(AppContext.BaseDirectory, "prompts", name);
        if (File.Exists(bundled))
        {
            return bundled;
        }

        DirectoryInfo? dir = new DirectoryInfo(AppContext.BaseDirectory);
        for (int i = 0; i < 6 && dir != null; i++, dir = dir.Parent)
        {
            string candidate = Path.Combine(dir.FullName, "prompts", name);
            if (File.Exists(candidate))
            {
                return candidate;
            }
        }

        return null;
    }

    private void Connect()
    {
        _attachTimer.Stop();
        _timer.Stop();
        CloseLogForLifecycle("reconnect");
        _reader.Dispose();
        ResetTracking();

        Process? process = Process.GetProcessesByName("SlayTheSpire2")
            .OrderByDescending(p => p.StartTime)
            .FirstOrDefault();

        if (process == null)
        {
            StatusText.Text = "等待游戏启动…";
            LogText.Text = "未找到 Slay the Spire 2，启动游戏后会自动连接";
            _attachTimer.Start();
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
            CloseLogForLifecycle("process_exit");
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
                    CloseLogForLifecycle("left_run");
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
            SolverSnapshot? solver = pythonAdvice is { Count: > 0 } ? _rules.LastSolver : null;
            ProcessLog(state, advice, solver);
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

    private void ProcessLog(GameState state, IReadOnlyList<Advice> advice, SolverSnapshot? solver)
    {
        bool runChanged = !string.Equals(_lastSeed, state.Seed, StringComparison.Ordinal)
                          || _lastRunStart != state.RunStartTime;
        _log.EnsureRun(state);

        if (runChanged && _log.IsOpen && !string.IsNullOrWhiteSpace(state.Seed))
        {
            _lastSeed = state.Seed;
            _lastRunStart = state.RunStartTime;
            _lastTurn = -1;
            _previous = null;
            _lastFingerprint = "";
            _rewardDeckBefore = null;
            _rewardOptions = new();
            _hasMapPosition = false;
            _lastHistoryDuplicates = 0;
            _inCombat = false;
            _pendingTurn = false;
            _lastEncounter = "";
            _lastCombatHp = 0;
            _lastCombatMaxHp = 0;
            _lastRewardKey = "";
            LogText.Text = "日志：" + System.IO.Path.GetFileName(_log.CurrentPath ?? "");
            _log.Snapshot(state, advice, solver, "attach");
        }

        int historyDuplicates = _reader.HistoryDuplicatesSkipped;
        if (historyDuplicates > _lastHistoryDuplicates)
        {
            // The History cursor was rewound; entries are deduped by object
            // address. Surface it instead of silently duplicating card_play.
            _log.Event("history_duplicate", new
            {
                skipped = historyDuplicates - _lastHistoryDuplicates,
                total = historyDuplicates,
                state.Turn,
                state.Encounter
            });
            _lastHistoryDuplicates = historyDuplicates;
        }

        bool encounterChanged = _inCombat
            && !string.IsNullOrEmpty(state.Encounter)
            && !string.IsNullOrEmpty(_lastEncounter)
            && !string.Equals(state.Encounter, _lastEncounter, StringComparison.Ordinal);
        bool turnReset = _inCombat && _lastTurn > 0 && state.Turn > 0 && state.Turn < _lastTurn;
        if (encounterChanged || turnReset)
        {
            // CombatState can stay non-null between two fights, so InCombat alone
            // misses the boundary. Log the end with the last HP seen in the old
            // fight before starting the new one.
            _log.Event("combat_end", new { Hp = _lastCombatHp, MaxHp = _lastCombatMaxHp, Turn = _lastTurn });
            _inCombat = false;
            _pendingTurn = false;
            _previous = null;
            _lastFingerprint = "";
        }

        if (state.InCombat && !_inCombat)
        {
            _inCombat = true;
            _lastEncounter = state.Encounter;
            _lastCombatHp = state.Hp;
            _lastCombatMaxHp = state.MaxHp;
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

        if (!_hasMapPosition || state.MapCol != _lastMapCol || state.MapRow != _lastMapRow)
        {
            if (_hasMapPosition)
            {
                _log.MapPick(state, _lastMapCol, _lastMapRow, _lastMapType);
            }

            _lastMapCol = state.MapCol;
            _lastMapRow = state.MapRow;
            _lastMapType = state.MapTypeName;
            _hasMapPosition = true;
        }

        string rewardKey = string.Join(",", state.CardChoices.Select(c => c.Id));
        if (state.CardChoices.Count > 0 && !string.Equals(rewardKey, _lastRewardKey, StringComparison.Ordinal))
        {
            FinishRewardPick(state);
            _lastRewardKey = rewardKey;
            _rewardDeckBefore = state.DeckCards.ToList();
            _rewardOptions = state.CardChoices.ToList();
            _log.Reward(state, advice);
        }
        else if (state.CardChoices.Count == 0)
        {
            FinishRewardPick(state);
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
            bool loggedTurn = false;

            if (_pendingTurn)
            {
                _pendingTurn = false;
                _log.Turn(state, advice, solver);
                loggedTurn = true;
            }

            LogCombatEvents(state);

            if (!loggedTurn && _previous != null
                && !_reader.HistoryAvailable
                && state.CombatEvents.Count == 0
                && !string.Equals(fingerprint, _lastFingerprint, StringComparison.Ordinal))
            {
                List<CardInfo> played = DiffHand(_previous.Hand, state.Hand);
                _log.Action(state, _previous, played, played.Count > 0 ? "card_play" : "state_change");
            }

            _previous = state;
            _lastFingerprint = fingerprint;
        }
        else if (state.InCombat)
        {
            LogCombatEvents(state);
        }

        if (!state.InCombat && _inCombat)
        {
            LogCombatEvents(state);
            _inCombat = false;
            _pendingTurn = false;
            _lastEncounter = "";
            _lastCombatHp = 0;
            _lastCombatMaxHp = 0;
            _log.Event("combat_end", new { state.Hp, state.MaxHp, state.Turn });
        }

        if (state.InCombat)
        {
            _lastCombatHp = state.Hp;
            _lastCombatMaxHp = state.MaxHp;
            if (!string.IsNullOrEmpty(state.Encounter))
            {
                _lastEncounter = state.Encounter;
            }
        }

        if (!_log.IsOpen)
        {
            return;
        }

        if (state.Hp <= 0 && !string.IsNullOrWhiteSpace(state.Seed))
        {
            _log.Snapshot(state, advice, solver, "death");
            _log.End(state, "death");
            return;
        }

        if (state.InCombat)
        {
            _log.Heartbeat(state);
        }
        else
        {
            _log.Snapshot(state, advice, solver);
        }
    }

    private void LogCombatEvents(GameState state)
    {
        foreach (CombatEventInfo ev in state.CombatEvents)
        {
            _log.CombatEvent(state, ev);
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

        if (s.Enemies.Count == 0)
        {
            EnemyText.Text = "（无）";
        }
        else
        {
            var nameCounts = s.Enemies.GroupBy(e => e.Name).ToDictionary(g => g.Key, g => g.Count());
            var seen = new Dictionary<string, int>();
            EnemyText.Text = string.Join("\n", s.Enemies.Select(e =>
            {
                string name = e.Name;
                if (nameCounts.TryGetValue(e.Name, out int count) && count > 1)
                {
                    seen[e.Name] = seen.TryGetValue(e.Name, out int n) ? n + 1 : 1;
                    name = $"{e.Name}#{seen[e.Name]}";
                }

                string block = e.Block > 0 ? $" 挡{e.Block}" : "";
                string damage = e.Damage > 0 ? $"  攻 {e.Damage}" + (e.Hits > 1 ? $"×{e.Hits}" : "") : "";
                return $"{name}  {e.Hp}/{e.MaxHp}{block}{damage}  [{e.Intent}]";
            }));
        }

        bool hasEvent = s.InEvent || s.EventOptions.Count > 0;
        EventSeparator.Visibility = hasEvent ? Visibility.Visible : Visibility.Collapsed;
        EventLabel.Visibility = hasEvent ? Visibility.Visible : Visibility.Collapsed;
        EventText.Visibility = hasEvent ? Visibility.Visible : Visibility.Collapsed;
        if (hasEvent)
        {
            var lines = new List<string>();
            string title = string.IsNullOrWhiteSpace(s.EventTitle) ? s.EventId : s.EventTitle;
            if (!string.IsNullOrWhiteSpace(title))
            {
                lines.Add(title + (s.EventIsAncient ? "（先古之民）" : ""));
            }
            if (!string.IsNullOrWhiteSpace(s.EventDescription))
            {
                lines.Add(s.EventDescription);
            }

            foreach (EventOptionInfo option in s.EventOptions)
            {
                string mark = option.Locked ? "✕" : option.Proceed ? "→" : "•";
                string relic = string.IsNullOrWhiteSpace(option.RelicName) ? "" : $"  [遗物：{option.RelicName}]";
                lines.Add($"{mark} {option.Title}{relic}");
                if (!string.IsNullOrWhiteSpace(option.Description))
                {
                    lines.Add("   " + option.Description);
                }
            }

            EventText.Text = lines.Count == 0 ? "（无选项）" : string.Join("\n", lines);
        }

        bool hasFacility = s.InShop || s.InRestSite || s.InTreasure ||
                           s.ShopItems.Count > 0 || s.RestOptions.Count > 0 || s.RelicChoices.Count > 0;
        FacilitySeparator.Visibility = hasFacility ? Visibility.Visible : Visibility.Collapsed;
        FacilityLabel.Visibility = hasFacility ? Visibility.Visible : Visibility.Collapsed;
        FacilityText.Visibility = hasFacility ? Visibility.Visible : Visibility.Collapsed;
        if (hasFacility)
        {
            var lines = new List<string>();
            if (s.InShop)
            {
                FacilityLabel.Text = "商店";
                lines.Add($"金币 {s.Gold}");
                foreach (ShopItemInfo item in s.ShopItems)
                {
                    string kind = item.Kind switch
                    {
                        "relic" => "遗物",
                        "potion" => "药水",
                        "removal" => "服务",
                        "colorless" => "无色",
                        _ => "卡牌"
                    };
                    string state = item.Affordable ? "可买" : "金币不足";
                    lines.Add($"• [{kind}] {item.Name}  {item.Cost} 金（{state}）");
                }
            }
            else if (s.InRestSite)
            {
                FacilityLabel.Text = "营地";
                foreach (RestOptionInfo option in s.RestOptions)
                {
                    string mark = option.Enabled ? "•" : "✕";
                    string heal = option.HealAmount > 0 ? $"  回复 {option.HealAmount}" : "";
                    lines.Add($"{mark} {option.Title}{heal}");
                    if (!string.IsNullOrWhiteSpace(option.Description))
                    {
                        lines.Add("   " + option.Description);
                    }
                }
            }
            else if (s.InTreasure)
            {
                FacilityLabel.Text = "宝箱";
                if (s.RelicChoices.Count == 0)
                {
                    lines.Add("等待宝箱/遗物选择。");
                }

                foreach (RelicChoiceInfo relic in s.RelicChoices)
                {
                    lines.Add($"• {relic.Name}");
                    if (!string.IsNullOrWhiteSpace(relic.Description))
                    {
                        lines.Add("   " + relic.Description);
                    }
                }
            }

            FacilityText.Text = lines.Count == 0 ? "（无可用内容）" : string.Join("\n", lines);
        }

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

    private void FinishRewardPick(GameState state)
    {
        if (_rewardDeckBefore == null)
        {
            return;
        }

        List<CardInfo> picked = AddedCards(_rewardDeckBefore, state.DeckCards);
        _log.RewardPick(state, _rewardOptions, picked);
        _rewardDeckBefore = null;
        _rewardOptions = new();
    }

    private static List<CardInfo> AddedCards(IReadOnlyList<CardInfo> before, IReadOnlyList<CardInfo> after)
    {
        var counts = before.GroupBy(c => c.Id).ToDictionary(g => g.Key, g => g.Count());
        var added = new List<CardInfo>();
        foreach (CardInfo card in after)
        {
            if (counts.TryGetValue(card.Id, out int count) && count > 0)
            {
                counts[card.Id] = count - 1;
            }
            else
            {
                added.Add(card);
            }
        }

        return added;
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

    private void CloseLogForLifecycle(string reason)
    {
        if (_log.LastHp <= 0)
        {
            _log.End(reason);
        }
        else
        {
            _log.Pause(reason);
        }
    }

    private void ResetTracking()
    {
        _previous = null;
        _lastSeed = null;
        _lastRunStart = 0;
        _lastTurn = -1;
        _lastFingerprint = "";
        _lastRewardKey = "";
        _rewardDeckBefore = null;
        _rewardOptions = new();
        _hasMapPosition = false;
        _inCombat = false;
        _pendingTurn = false;
        _lastEncounter = "";
        _lastCombatHp = 0;
        _lastCombatMaxHp = 0;
        _lastHistoryDuplicates = 0;
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
        CloseLogForLifecycle("app_closed");
        _log.Dispose();
        _reader.Dispose();
        _rules.Dispose();
        base.OnClosed(e);
    }
}
