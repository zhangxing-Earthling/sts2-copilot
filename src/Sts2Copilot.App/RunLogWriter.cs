using System.Globalization;
using System.IO;
using System.Reflection;
using System.Text;
using System.Text.Encodings.Web;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace Sts2Copilot;

/// <summary>
/// Append-only JSONL for one complete run (character select -> death).
/// The file name is deterministic from the run start time + seed, so an app
/// restart during the same run resumes the same file instead of creating a
/// second one. State snapshots are event-driven; a small heartbeat keeps the
/// timeline alive while nothing changes.
/// </summary>
public sealed class RunLogWriter : IDisposable
{
    public const int SchemaVersion = 2;

    private static readonly JsonSerializerOptions Options = new()
    {
        Encoder = JavaScriptEncoder.UnsafeRelaxedJsonEscaping,
        DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull,
        WriteIndented = false
    };

    private readonly string _dir;
    private readonly string _sessionId = Guid.NewGuid().ToString("N")[..8];
    private StreamWriter? _writer;
    private string? _runKey;
    private string? _endedRunKey;
    private GameState? _lastState;
    private string _lastSnapshotKey = "";
    private DateTime _lastSnapshotAt = DateTime.MinValue;
    private DateTime _lastHeartbeatAt = DateTime.MinValue;
    private int _seq;

    public RunLogWriter(string? dir = null)
    {
        _dir = dir ?? AppPaths.RunsDir;
        Directory.CreateDirectory(_dir);
    }

    public string? CurrentPath { get; private set; }

    public bool IsOpen => _writer != null;

    public bool Ended { get; private set; }

    public int LastHp => _lastState?.Hp ?? -1;

    public void Start(GameState state) => EnsureRun(state);

    /// <summary>
    /// Ensures this poll belongs to the same run file. Called every poll; only
    /// opens a new file when the game's RunManager start time/seed changes.
    /// </summary>
    public void EnsureRun(GameState state)
    {
        if (string.IsNullOrWhiteSpace(state.Seed))
        {
            return;
        }

        string key = RunKey(state);
        if (_writer != null && string.Equals(key, _runKey, StringComparison.Ordinal))
        {
            _lastState = state;
            return;
        }

        if (_writer != null)
        {
            EndInternal("run_changed");
        }

        if (Ended && string.Equals(key, _endedRunKey, StringComparison.Ordinal))
        {
            return;
        }

        Close();
        _runKey = key;
        _lastState = state;
        _lastSnapshotKey = "";
        _lastSnapshotAt = DateTime.MinValue;
        _lastHeartbeatAt = DateTime.MinValue;
        Ended = false;

        string path = BuildPath(state);
        bool resumed = File.Exists(path) && new FileInfo(path).Length > 0;
        int existingLines = resumed ? CountLines(path) : 0;
        CurrentPath = path;
        var stream = new FileStream(path, resumed ? FileMode.Append : FileMode.Create, FileAccess.Write, FileShare.Read);
        _writer = new StreamWriter(stream, new UTF8Encoding(false)) { AutoFlush = true };
        _seq = existingLines;

        Write(new
        {
            v = SchemaVersion,
            schema = "sts2-copilot-run",
            ts = Now(),
            type = resumed ? "run_resume" : "run_start",
            seq = ++_seq,
            run_id = _runKey,
            session = _sessionId,
            app_version = AppVersion(),
            game_version = state.GameVersion,
            state
        });
    }

    public void Turn(GameState state, IReadOnlyList<Advice> advice, SolverSnapshot? solver)
    {
        _lastState = state;
        Write(new
        {
            v = SchemaVersion,
            ts = Now(),
            type = "turn",
            seq = ++_seq,
            run_id = _runKey,
            session = _sessionId,
            game_version = state.GameVersion,
            state,
            solver,
            advice
        });
    }

    /// <summary>
    /// Logs a full state snapshot when the non-combat screen changes, or at a
    /// modest heartbeat. Callers can force a snapshot by passing a reason.
    /// </summary>
    public void Snapshot(GameState state, IReadOnlyList<Advice> advice, SolverSnapshot? solver, string? reason = null)
    {
        _lastState = state;
        string key = SnapshotKey(state);
        bool changed = !string.Equals(key, _lastSnapshotKey, StringComparison.Ordinal);
        bool heartbeat = (DateTime.UtcNow - _lastSnapshotAt).TotalSeconds >= 10;
        if (!changed && !heartbeat && reason == null)
        {
            return;
        }

        _lastSnapshotKey = key;
        _lastSnapshotAt = DateTime.UtcNow;
        Write(new
        {
            v = SchemaVersion,
            ts = Now(),
            type = "state_snapshot",
            seq = ++_seq,
            run_id = _runKey,
            session = _sessionId,
            game_version = state.GameVersion,
            reason = reason ?? (changed ? "changed" : "heartbeat"),
            screen = Screen(state),
            state,
            solver,
            advice
        });
    }

    public void Heartbeat(GameState state)
    {
        _lastState = state;
        if ((DateTime.UtcNow - _lastHeartbeatAt).TotalSeconds < 15)
        {
            return;
        }

        _lastHeartbeatAt = DateTime.UtcNow;
        Write(new
        {
            v = SchemaVersion,
            ts = Now(),
            type = "heartbeat",
            seq = ++_seq,
            run_id = _runKey,
            session = _sessionId,
            room = state.CurrentRoom,
            encounter = state.Encounter,
            act = state.Act,
            floor = state.Floor,
            hp = state.Hp,
            max_hp = state.MaxHp,
            gold = state.Gold,
            deck_count = state.DeckCount,
            relics = state.Relics,
            potions = state.Potions,
            in_combat = state.InCombat
        });
    }

    public void CombatEvent(GameState state, CombatEventInfo ev)
    {
        _lastState = state;
        Write(new
        {
            v = SchemaVersion,
            ts = Now(),
            type = ev.Kind,
            seq = ++_seq,
            run_id = _runKey,
            session = _sessionId,
            game_version = state.GameVersion,
            turn = state.Turn,
            floor = state.Floor,
            encounter = state.Encounter,
            hp = state.Hp,
            gold = state.Gold,
            payload = ev
        });
    }

    public void RewardPick(GameState state, IReadOnlyList<CardInfo> options, IReadOnlyList<CardInfo> picked)
    {
        _lastState = state;
        Write(new
        {
            v = SchemaVersion,
            ts = Now(),
            type = "reward_pick",
            seq = ++_seq,
            run_id = _runKey,
            session = _sessionId,
            floor = state.Floor,
            gold = state.RewardGold,
            skipped = picked.Count == 0,
            options,
            picked,
            deck_after = state.DeckCards
        });
    }

    public void MapPick(GameState state, int fromCol, int fromRow, string fromType)
    {
        _lastState = state;
        Write(new
        {
            v = SchemaVersion,
            ts = Now(),
            type = "map_pick",
            seq = ++_seq,
            run_id = _runKey,
            session = _sessionId,
            floor = state.Floor,
            from = new { col = fromCol, row = fromRow, type = fromType },
            to = new { col = state.MapCol, row = state.MapRow, type = state.MapTypeName },
            choices = state.MapChoices
        });
    }

    public void Reward(GameState state, IReadOnlyList<Advice> advice)
    {
        _lastState = state;
        Write(new
        {
            v = SchemaVersion,
            ts = Now(),
            type = "reward",
            seq = ++_seq,
            run_id = _runKey,
            session = _sessionId,
            gold = state.RewardGold,
            choices = state.CardChoices,
            advice
        });
    }

    public void Action(GameState state, GameState previous, IReadOnlyList<CardInfo> played, string kind)
    {
        _lastState = state;
        Write(new
        {
            v = SchemaVersion,
            ts = Now(),
            type = "action",
            seq = ++_seq,
            run_id = _runKey,
            session = _sessionId,
            kind,
            turn = state.Turn,
            played = played.Select(c => new { id = c.Id, name = c.Name, cost = c.Cost }),
            energy_before = previous.Energy,
            energy_after = state.Energy,
            hand_before = previous.Hand,
            hand_after = state.Hand,
            potions_before = previous.Potions,
            potions_after = state.Potions
        });
    }

    public void Event(string type, object payload)
    {
        Write(new
        {
            v = SchemaVersion,
            ts = Now(),
            type,
            seq = ++_seq,
            run_id = _runKey,
            session = _sessionId,
            payload
        });
    }

    public void End(GameState state, string reason)
    {
        if (_writer == null)
        {
            return;
        }

        _lastState = state;
        Write(new
        {
            v = SchemaVersion,
            ts = Now(),
            type = "run_end",
            seq = ++_seq,
            run_id = _runKey,
            session = _sessionId,
            game_version = state.GameVersion,
            reason,
            state
        });
        Ended = true;
        _endedRunKey = _runKey;
        Close();
    }

    public void End(string reason)
    {
        if (_lastState != null)
        {
            End(_lastState, reason);
            return;
        }

        if (_writer == null)
        {
            return;
        }

        Write(new
        {
            v = SchemaVersion,
            ts = Now(),
            type = "run_end",
            seq = ++_seq,
            run_id = _runKey,
            session = _sessionId,
            reason
        });
        Ended = true;
        _endedRunKey = _runKey;
        Close();
    }

    /// <summary>
    /// Closes the file without ending the run (reconnect, app close, menu).
    /// A later poll of the same run reopens the same file and appends run_resume.
    /// </summary>
    public void Pause(string reason)
    {
        if (_writer == null)
        {
            return;
        }

        Write(new
        {
            v = SchemaVersion,
            ts = Now(),
            type = "run_pause",
            seq = ++_seq,
            run_id = _runKey,
            session = _sessionId,
            reason,
            state = _lastState
        });
        Close();
    }

    private void EndInternal(string reason)
    {
        if (_writer == null)
        {
            return;
        }

        Write(new
        {
            v = SchemaVersion,
            ts = Now(),
            type = "run_end",
            seq = ++_seq,
            run_id = _runKey,
            session = _sessionId,
            reason,
            state = _lastState
        });
        Close();
    }

    private void Write(object record)
    {
        if (_writer == null)
        {
            return;
        }

        try
        {
            _writer.WriteLine(JsonSerializer.Serialize(record, Options));
            _writer.Flush();
            _writer.BaseStream.Flush();
        }
        catch (Exception ex)
        {
            App.Log("log write failed: " + ex.Message);
        }
    }

    private static string RunKey(GameState state)
    {
        return Sanitize(state.Seed) + "|" + state.RunStartTime.ToString(CultureInfo.InvariantCulture) + "|" + Sanitize(state.Character);
    }

    private string BuildPath(GameState state)
    {
        string seed = Sanitize(string.IsNullOrWhiteSpace(state.Seed) ? "unknown" : state.Seed);
        string stamp = state.RunStartTime > 0
            ? state.RunStartTime.ToString(CultureInfo.InvariantCulture)
            : DateTime.Now.ToString("yyyyMMdd_HHmmss");
        return Path.Combine(_dir, $"run_{stamp}_{seed}.jsonl");
    }

    private static string Screen(GameState state)
    {
        if (state.InEvent) return "event";
        if (state.InShop) return "shop";
        if (state.InRestSite) return "rest";
        if (state.InTreasure) return "treasure";
        if (state.CardChoices.Count > 0) return "reward";
        if (state.MapChoices.Count > 0) return "map";
        return state.InCombat ? "combat" : "other";
    }

    private static string SnapshotKey(GameState state)
    {
        static string Cards(IEnumerable<CardInfo> cards) =>
            string.Join(",", cards.Select(c => c.Id + ":" + c.Upgraded));

        var options = string.Join(";", state.EventOptions.Select(o =>
            $"{o.Title}/{o.Locked}/{o.Proceed}/{o.RelicName}"));
        var shop = string.Join(";", state.ShopItems.Select(i =>
            $"{i.Kind}:{i.Name}:{i.Cost}:{i.Affordable}"));
        var rest = string.Join(";", state.RestOptions.Select(o =>
            $"{o.OptionId}:{o.Enabled}:{o.HealAmount}"));
        var relics = string.Join(";", state.RelicChoices.Select(r => $"{r.Id}:{r.Rarity}"));
        var map = string.Join(";", state.MapChoices.Select(n => $"{n.Col},{n.Row},{n.Type}"));
        return string.Join("|",
            state.CurrentRoom,
            state.Encounter,
            state.Act,
            state.Floor,
            state.MapCol,
            state.MapRow,
            state.MapTypeName,
            state.Hp,
            state.MaxHp,
            state.Gold,
            state.RewardGold,
            string.Join(",", state.CardChoices.Select(c => c.Id)),
            string.Join(";", state.RewardRelics.Select(r => r.Id)),
            string.Join(";", state.RewardPotions),
            state.MapNodes.Count,
            state.MapEdges.Count,
            state.EventId,
            state.EventDescription,
            options,
            shop,
            rest,
            relics,
            map,
            Cards(state.DeckCards),
            string.Join(",", state.Relics),
            string.Join(",", state.Potions));
    }

    private static int CountLines(string path)
    {
        try
        {
            using var reader = new StreamReader(path, Encoding.UTF8);
            int count = 0;
            while (reader.ReadLine() != null)
            {
                count++;
            }

            return count;
        }
        catch
        {
            return 0;
        }
    }

    private static string AppVersion()
    {
        try
        {
            return Assembly.GetExecutingAssembly().GetName().Version?.ToString() ?? "";
        }
        catch
        {
            return "";
        }
    }

    private static string Now() => DateTimeOffset.Now.ToString("o");

    private static string Sanitize(string value)
    {
        var sb = new StringBuilder(value.Length);
        foreach (char c in value)
        {
            sb.Append(char.IsLetterOrDigit(c) || c == '-' || c == '_' ? c : '_');
        }

        return sb.ToString();
    }

    private void Close()
    {
        try
        {
            _writer?.Flush();
            _writer?.BaseStream.Flush();
        }
        catch
        {
            // best-effort
        }

        _writer?.Dispose();
        _writer = null;
    }

    public void Dispose()
    {
        Close();
    }
}
