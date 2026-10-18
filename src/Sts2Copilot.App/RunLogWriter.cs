using System.IO;
using System.Text;
using System.Text.Encodings.Web;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace Sts2Copilot;

/// <summary>
/// Append-only JSONL per run: state, advice, inferred actions.
/// </summary>
public sealed class RunLogWriter : IDisposable
{
    private static readonly JsonSerializerOptions Options = new()
    {
        Encoder = JavaScriptEncoder.UnsafeRelaxedJsonEscaping,
        DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull,
        WriteIndented = false
    };

    private readonly string _dir;
    private StreamWriter? _writer;
    private string? _seed;
    private int _seq;

    public RunLogWriter(string? dir = null)
    {
        _dir = dir ?? Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData),
            "Sts2Copilot",
            "runs");
        Directory.CreateDirectory(_dir);
    }

    public string? CurrentPath { get; private set; }

    public void Start(GameState state)
    {
        Close();
        _seq = 0;
        _seed = state.Seed;
        string stamp = DateTime.Now.ToString("yyyyMMdd_HHmmss");
        string safe = Sanitize(string.IsNullOrWhiteSpace(state.Seed) ? "unknown" : state.Seed);
        CurrentPath = Path.Combine(_dir, $"run_{stamp}_{safe}.jsonl");
        var stream = new FileStream(CurrentPath, FileMode.Create, FileAccess.Write, FileShare.Read);
        _writer = new StreamWriter(stream, new UTF8Encoding(false)) { AutoFlush = true };
        Event("run_start", state);
    }

    public void Turn(GameState state, IReadOnlyList<Advice> advice)
    {
        Write(new
        {
            v = 1,
            ts = Now(),
            type = "turn",
            seq = ++_seq,
            run_id = _seed,
            game_version = state.GameVersion,
            state,
            advice
        });
    }

    public void Reward(GameState state, IReadOnlyList<Advice> advice)
    {
        Write(new
        {
            v = 1,
            ts = Now(),
            type = "reward",
            seq = ++_seq,
            run_id = _seed,
            gold = state.RewardGold,
            choices = state.CardChoices,
            advice
        });
    }

    public void Action(GameState state, GameState previous, IReadOnlyList<CardInfo> played, string kind)
    {
        Write(new
        {
            v = 1,
            ts = Now(),
            type = "action",
            seq = ++_seq,
            run_id = _seed,
            kind,
            turn = state.Turn,
            played = played.Select(c => new { id = c.Id, name = c.Name, cost = c.Cost }),
            energy_before = previous.Energy,
            energy_after = state.Energy,
            hand_before = previous.Hand.Count,
            hand_after = state.Hand.Count,
            potions_before = previous.Potions,
            potions_after = state.Potions
        });
    }

    public void Event(string type, object payload)
    {
        Write(new
        {
            v = 1,
            ts = Now(),
            type,
            seq = ++_seq,
            run_id = _seed,
            payload
        });
    }

    public void End(string reason)
    {
        if (_writer == null)
        {
            return;
        }

        Event("run_end", new { reason });
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
        _writer?.Dispose();
        _writer = null;
    }

    public void Dispose()
    {
        Close();
    }
}
