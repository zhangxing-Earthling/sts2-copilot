namespace Sts2Copilot;

/// <summary>
/// Structured one-turn solver prediction returned by the Python service.
/// Logged with each turn so calibration can compare prediction vs actual HP.
/// </summary>
public sealed class SolverSnapshot
{
    public int Version { get; set; }
    public string? Error { get; set; }
    public List<string> Sequence { get; set; } = new();
    public int HpLoss { get; set; }
    public int HpAfter { get; set; }
    public int Incoming { get; set; }
    public int Block { get; set; }
    public int EnergyLeft { get; set; }
    public int EnemyHpLeft { get; set; }
    public int DamageDealt { get; set; }
    public int PoisonKills { get; set; }
    public bool Lethal { get; set; }
    public bool Truncated { get; set; }
    public int Modeled { get; set; }
    public List<string> Unmodeled { get; set; } = new();
}
