using System.Diagnostics;
using System.IO;
using System.Text.Json;
using System.Text.RegularExpressions;
using Microsoft.Diagnostics.Runtime;

namespace Sts2Copilot;

public sealed class CardInfo
{
    public string Id { get; set; } = "";
    public string Name { get; set; } = "";
    public int Cost { get; set; }
    public bool CostsX { get; set; }
    public int Type { get; set; }
    public int Rarity { get; set; }
    public int Upgraded { get; set; }
    public bool Playable { get; set; }
    public int Damage { get; set; }
    public int Block { get; set; }
    public int Poison { get; set; }
    public int Hits { get; set; } = 1;
}

public sealed class EnemyInfo
{
    public string Id { get; set; } = "";
    public string Name { get; set; } = "";
    public int Hp { get; set; }
    public int MaxHp { get; set; }
    public int Block { get; set; }
    public string Intent { get; set; } = "";
    public int Damage { get; set; }
    public int Hits { get; set; }
}

public sealed class MapNodeInfo
{
    public int Col { get; set; }
    public int Row { get; set; }
    public int Type { get; set; }
    public string TypeName { get; set; } = "";
}

public sealed class MapEdgeInfo
{
    public int FromCol { get; set; }
    public int FromRow { get; set; }
    public int ToCol { get; set; }
    public int ToRow { get; set; }
}

public sealed class GameState
{
    public string GameVersion { get; set; } = "";
    public string Seed { get; set; } = "";
    public string Character { get; set; } = "";
    public string CurrentRoom { get; set; } = "";
    public string Encounter { get; set; } = "";
    public int Act { get; set; }
    public int Floor { get; set; }
    public int Ascension { get; set; }
    public int Hp { get; set; }
    public int MaxHp { get; set; }
    public int Block { get; set; }
    public int Gold { get; set; }
    public int Energy { get; set; }
    public int MaxEnergy { get; set; }
    public int Stars { get; set; }
    public int Turn { get; set; }
    public int Phase { get; set; }
    public int DrawCount { get; set; }
    public int DiscardCount { get; set; }
    public int DeckCount { get; set; }
    public int Round { get; set; }
    public int Side { get; set; }
    public bool InCombat { get; set; }
    public string? ValidationError { get; set; }
    public List<CardInfo> Hand { get; set; } = new();
    public List<CardInfo> DeckCards { get; set; } = new();
    public List<CardInfo> CardChoices { get; set; } = new();
    public int RewardGold { get; set; }
    public List<MapNodeInfo> MapChoices { get; set; } = new();
    public List<MapNodeInfo> MapNodes { get; set; } = new();
    public List<MapEdgeInfo> MapEdges { get; set; } = new();
    public int MapCol { get; set; }
    public int MapRow { get; set; }
    public int MapType { get; set; }
    public string MapTypeName { get; set; } = "";
    public List<EnemyInfo> Enemies { get; set; } = new();
    public List<string> Relics { get; set; } = new();
    public List<string> Potions { get; set; } = new();
}

/// <summary>
/// Read-only view of the running game through ClrMD. No writes, no injection.
/// </summary>
public sealed class MemoryReader : IDisposable
{
    private const string SupportedVersion = "0.107.1";
    private const string DefaultGameDir = @"D:\steam\steamapps\common\Slay the Spire 2";

    private DataTarget? _target;
    private ClrRuntime? _runtime;
    private ClrAppDomain? _domain;
    private ClrStaticField? _instanceField;
    private readonly Dictionary<string, Dictionary<string, string>> _loc = new();
    private string _dataDir = Path.Combine(DefaultGameDir, "data_sts2_windows_x86_64");

    public int Pid { get; private set; }
    public string? Error { get; private set; }
    public string GameVersion { get; private set; } = "";

    public bool Attach(int pid)
    {
        Dispose();
        Error = null;

        try
        {
            string gameDir = ResolveGameDir(pid);
            string? version = ReadGameVersion(gameDir);
            if (version == null)
            {
                Error = "找不到或无法解析 release_info.json";
                return false;
            }

            GameVersion = version;
            if (!string.Equals(version, SupportedVersion, StringComparison.Ordinal))
            {
                Error = $"游戏版本 {version} 不受支持（仅支持 {SupportedVersion}）";
                return false;
            }

            _dataDir = Path.Combine(gameDir, "data_sts2_windows_x86_64");
            _target = DataTarget.AttachToProcess(pid, false);
            _runtime = CreateRuntime(_target);
            _domain = _runtime.AppDomains.Length > 0 ? _runtime.AppDomains[0] : _runtime.SharedDomain;
            ClrModule? module = _runtime.EnumerateModules()
                .FirstOrDefault(m => m.Name.EndsWith("sts2.dll", StringComparison.OrdinalIgnoreCase));
            ClrType? runManager = module?.GetTypeByName("MegaCrit.Sts2.Core.Runs.RunManager");
            _instanceField = runManager?.StaticFields.FirstOrDefault(f => f.Name.Contains("Instance"));

            if (_instanceField == null)
            {
                Error = "找不到 RunManager.Instance";
                Dispose();
                return false;
            }

            LoadLocalization(module!);
            Pid = pid;
            return true;
        }
        catch (Exception ex)
        {
            Error = ex.Message;
            Dispose();
            return false;
        }
    }

    public GameState? Read()
    {
        if (_instanceField == null || _domain == null)
        {
            return null;
        }

        try
        {
            ClrObject runManager = _instanceField.ReadObject(_domain);
            ClrObject state = ReadObj(runManager, "<State>k__BackingField");
            if (state.IsNull)
            {
                return null;
            }

            GameState result = BuildState(state);
            result.GameVersion = GameVersion;
            ReadRewards(result, runManager);
            ReadMap(result, state);
            string? validation = Validate(result);
            if (validation != null)
            {
                result.ValidationError = validation;
                Error = validation;
            }

            return result;
        }
        catch (Exception ex)
        {
            Error = ex.Message;
            return null;
        }
    }

    private GameState BuildState(ClrObject state)
    {
        var result = new GameState
        {
            Seed = ReadStr(ReadObj(state, "<Rng>k__BackingField"), "<StringSeed>k__BackingField") ?? "",
            Act = ReadInt(state, "_currentActIndex") + 1,
            Floor = ReadInt(state, "<ActFloor>k__BackingField"),
            Ascension = ReadInt(state, "<AscensionLevel>k__BackingField")
        };

        List<ClrObject> players = ReadList(ReadObj(state, "_players"));
        if (players.Count == 0)
        {
            return result;
        }

        ClrObject player = players[0];
        ClrObject creature = ReadObj(player, "<Creature>k__BackingField");
        ClrObject character = ReadObj(player, "<Character>k__BackingField");
        ClrObject combatState = ReadObj(creature, "<CombatState>k__BackingField");

        result.Character = Localize("characters", Entry(character) ?? "", ".title");
        result.Encounter = Entry(ReadObj(combatState, "_encounter")) ?? "";
        List<ClrObject> rooms = ReadList(ReadObj(state, "_currentRooms"));
        if (rooms.Count > 0)
        {
            result.CurrentRoom = rooms[^1].Type?.Name.Split('.').Last() ?? "";
        }

        result.Hp = ReadInt(creature, "_currentHp");
        result.MaxHp = ReadInt(creature, "_maxHp");
        result.Block = ReadInt(creature, "_block");
        result.Gold = ReadInt(player, "_gold");
        result.DeckCount = Count(ReadObj(player, "<Deck>k__BackingField"));
        foreach (ClrObject card in ReadList(ReadObj(ReadObj(player, "<Deck>k__BackingField"), "_cards")))
        {
            result.DeckCards.Add(BuildCard(card, 0));
        }

        foreach (ClrObject relic in ReadList(ReadObj(player, "_relics")))
        {
            string? id = Entry(relic);
            if (!string.IsNullOrEmpty(id))
            {
                result.Relics.Add(Localize("relics", id, ".title"));
            }
        }

        foreach (ClrObject potion in ReadList(ReadObj(player, "_potionSlots")))
        {
            if (potion.IsNull)
            {
                continue;
            }

            string? id = Entry(potion);
            if (!string.IsNullOrEmpty(id))
            {
                result.Potions.Add(Localize("potions", id, ".title"));
            }
        }

        ClrObject pcs = ReadObj(player, "<PlayerCombatState>k__BackingField");
        if (!pcs.IsNull)
        {
            result.Turn = ReadInt(pcs, "<TurnNumber>k__BackingField");
            result.Phase = ReadInt(pcs, "_phase");
            result.Energy = ReadInt(pcs, "_energy");
            result.Stars = ReadInt(pcs, "_stars");
            result.MaxEnergy = ReadInt(player, "<MaxEnergy>k__BackingField");
            result.DrawCount = Count(ReadObj(pcs, "<DrawPile>k__BackingField"));
            result.DiscardCount = Count(ReadObj(pcs, "<DiscardPile>k__BackingField"));

            foreach (ClrObject card in ReadList(ReadObj(ReadObj(pcs, "<Hand>k__BackingField"), "_cards")))
            {
                result.Hand.Add(BuildCard(card, result.Energy));
            }
        }

        if (!combatState.IsNull)
        {
            result.InCombat = true;
            result.Round = ReadInt(combatState, "<RoundNumber>k__BackingField");
            result.Side = ReadInt(combatState, "<CurrentSide>k__BackingField");

            foreach (ClrObject enemy in ReadList(ReadObj(combatState, "_enemies")))
            {
                ClrObject monster = ReadObj(enemy, "<Monster>k__BackingField");
                ClrObject nextMove = ReadObj(monster, "<NextMove>k__BackingField");
                List<ClrObject> intents = ReadList(ReadObj(nextMove, "<Intents>k__BackingField"));

                var info = new EnemyInfo
                {
                    Id = Entry(monster) ?? "",
                    Hp = ReadInt(enemy, "_currentHp"),
                    MaxHp = ReadInt(enemy, "_maxHp"),
                    Block = ReadInt(enemy, "_block")
                };
                info.Name = Localize("monsters", info.Id, ".name");

                var names = new List<string>();
                foreach (ClrObject intent in intents)
                {
                    string name = intent.Type?.Name.Split('.').Last() ?? "?";
                    names.Add(IntentName(name.Replace("Intent", "")));
                    int damage = IntentDamage(intent, enemy, creature);
                    if (damage > 0)
                    {
                        info.Damage += damage;
                        info.Hits += Math.Max(1, ReadInt(intent, "_repeat"));
                    }
                }

                info.Intent = string.Join("/", names);
                result.Enemies.Add(info);
            }
        }

        return result;
    }

    private CardInfo BuildCard(ClrObject card, int energy)
    {
        (int cost, bool costsX) = CardCost(card);
        int type = ReadInt(card, "<Type>k__BackingField");
        string id = Entry(card) ?? "";
        Dictionary<string, decimal> vars = ReadVars(card);
        int damage = (int)(GetVar(vars, "Damage") + GetVar(vars, "CalculatedDamage") + GetVar(vars, "ExtraDamage"));
        int block = (int)(GetVar(vars, "Block") + GetVar(vars, "CalculatedBlock"));
        int poison = (int)(GetVar(vars, "PoisonPower") + GetVar(vars, "Poison"));
        int hits = Math.Max(1, (int)GetVar(vars, "Repeat"));

        return new CardInfo
        {
            Id = id,
            Name = Localize("cards", id, ".title"),
            Cost = cost,
            CostsX = costsX,
            Type = type,
            Rarity = ReadInt(card, "<Rarity>k__BackingField"),
            Upgraded = ReadInt(card, "_currentUpgradeLevel"),
            Playable = costsX ? energy > 0 : cost <= energy && type != 4 && type != 5,
            Damage = Math.Max(0, damage),
            Block = Math.Max(0, block),
            Poison = Math.Max(0, poison),
            Hits = hits
        };
    }

    private void ReadRewards(GameState result, ClrObject runManager)
    {
        try
        {
            ClrObject sync = ReadObj(runManager, "<RewardsSetSynchronizer>k__BackingField");
            if (sync.IsNull)
            {
                return;
            }

            foreach (ClrObject playerState in ReadList(ReadObj(sync, "_rewardStates")))
            {
                List<ClrObject> stack = ReadList(ReadObj(playerState, "rewardsStack"));
                if (stack.Count == 0)
                {
                    continue;
                }

                ClrObject set = ReadObj(stack[^1], "set");
                if (set.IsNull)
                {
                    continue;
                }

                foreach (ClrObject reward in ReadList(ReadObj(set, "<Rewards>k__BackingField")))
                {
                    CollectReward(result, reward);
                }
            }
        }
        catch
        {
            // rewards are best-effort
        }
    }

    private void CollectReward(GameState result, ClrObject reward)
    {
        string type = reward.Type?.Name.Split('.').Last() ?? "";
        if (ReadBool(reward, "<SuccessfullySelected>k__BackingField"))
        {
            return;
        }

        if (type == "LinkedRewardSet")
        {
            foreach (ClrObject child in ReadList(ReadObj(reward, "_rewards")))
            {
                CollectReward(result, child);
            }

            return;
        }

        if (type == "CardReward")
        {
            foreach (ClrObject choice in ReadList(ReadObj(reward, "_cards")))
            {
                ClrObject card = ReadObj(choice, "_modifiedCard");
                if (card.IsNull)
                {
                    card = ReadObj(choice, "originalCard");
                }

                if (!card.IsNull)
                {
                    result.CardChoices.Add(BuildCard(card, 0));
                }
            }

            return;
        }

        if (type == "GoldReward")
        {
            result.RewardGold += ReadInt(reward, "<Amount>k__BackingField");
        }
    }

    private void ReadMap(GameState result, ClrObject state)
    {
        try
        {
            ClrObject map = ReadObj(state, "<Map>k__BackingField");
            if (map.IsNull)
            {
                return;
            }

            ClrObject gridObj = ReadObj(map, "<Grid>k__BackingField");
            if (gridObj.IsNull)
            {
                return;
            }

            ClrArray grid = gridObj.AsArray();
            int cols = grid.GetLength(0);
            int rows = grid.GetLength(1);
            List<(int col, int row)> visited = ReadCoordList(ReadObj(state, "_visitedMapCoords"));
            ClrObject current = ReadObj(map, "<StartingMapPoint>k__BackingField");

            if (visited.Count > 0)
            {
                (int col, int row) = visited[^1];
                if (col >= 0 && col < cols && row >= 0 && row < rows)
                {
                    current = grid.GetObjectValue(new[] { col, row });
                }
            }

            if (current.IsNull)
            {
                return;
            }

            (int curCol, int curRow) = ReadCoord(current);
            result.MapCol = curCol;
            result.MapRow = curRow;
            result.MapType = ReadInt(current, "<PointType>k__BackingField");
            result.MapTypeName = MapTypeName(result.MapType);

            var seenNodes = new HashSet<(int col, int row)>();
            var seenEdges = new HashSet<(int fromCol, int fromRow, int toCol, int toRow)>();

            void AddNode(ClrObject point)
            {
                if (point.IsNull)
                {
                    return;
                }

                (int col, int row) = ReadCoord(point);
                int type = ReadInt(point, "<PointType>k__BackingField");
                if (type == 0 || !seenNodes.Add((col, row)))
                {
                    return;
                }

                result.MapNodes.Add(new MapNodeInfo
                {
                    Col = col,
                    Row = row,
                    Type = type,
                    TypeName = MapTypeName(type)
                });
            }

            void AddEdge(int fromCol, int fromRow, ClrObject child)
            {
                if (child.IsNull)
                {
                    return;
                }

                (int toCol, int toRow) = ReadCoord(child);
                AddNode(child);
                if (seenEdges.Add((fromCol, fromRow, toCol, toRow)))
                {
                    result.MapEdges.Add(new MapEdgeInfo
                    {
                        FromCol = fromCol,
                        FromRow = fromRow,
                        ToCol = toCol,
                        ToRow = toRow
                    });
                }
            }

            AddNode(current);

            for (int col = 0; col < cols; col++)
            {
                for (int row = 0; row < rows; row++)
                {
                    ClrObject point = grid.GetObjectValue(new[] { col, row });
                    if (point.IsNull)
                    {
                        continue;
                    }

                    AddNode(point);
                    foreach (ClrObject child in ReadHashSet(ReadObj(point, "<Children>k__BackingField")))
                    {
                        AddEdge(col, row, child);
                    }
                }
            }

            ClrObject boss = ReadObj(map, "<BossMapPoint>k__BackingField");
            AddNode(boss);

            foreach (ClrObject child in ReadHashSet(ReadObj(current, "<Children>k__BackingField")))
            {
                (int col, int row) = ReadCoord(child);
                int type = ReadInt(child, "<PointType>k__BackingField");
                if (type == 0)
                {
                    continue;
                }

                result.MapChoices.Add(new MapNodeInfo
                {
                    Col = col,
                    Row = row,
                    Type = type,
                    TypeName = MapTypeName(type)
                });
            }
        }
        catch
        {
            // map is best-effort
        }
    }

    private static (int col, int row) ReadCoord(ClrObject point)
    {
        ClrValueType coord = point.ReadValueTypeField("coord");
        return (coord.ReadField<int>("col"), coord.ReadField<int>("row"));
    }

    private static List<(int col, int row)> ReadCoordList(ClrObject list)
    {
        var result = new List<(int, int)>();
        if (list.IsNull)
        {
            return result;
        }

        try
        {
            ClrObject items = ReadObj(list, "_items");
            if (items.IsNull)
            {
                return result;
            }

            ClrArray array = items.AsArray();
            int size = ReadInt(list, "_size");
            for (int i = 0; i < size && i < array.Length; i++)
            {
                ClrValueType coord = array.GetStructValue(i);
                result.Add((coord.ReadField<int>("col"), coord.ReadField<int>("row")));
            }
        }
        catch
        {
            // ignore
        }

        return result;
    }

    private static List<ClrObject> ReadHashSet(ClrObject set)
    {
        var result = new List<ClrObject>();
        if (set.IsNull)
        {
            return result;
        }

        try
        {
            ClrObject entries = ReadObj(set, "_entries");
            if (entries.IsNull)
            {
                return result;
            }

            ClrArray array = entries.AsArray();
            int count = ReadInt(set, "_count");
            for (int i = 0; i < count && i < array.Length; i++)
            {
                ClrValueType entry = array.GetStructValue(i);
                ClrObject value;
                try
                {
                    value = entry.ReadObjectField("Value");
                }
                catch
                {
                    value = entry.ReadObjectField("value");
                }

                if (!value.IsNull)
                {
                    result.Add(value);
                }
            }
        }
        catch
        {
            // ignore
        }

        return result;
    }

    private static string MapTypeName(int type) => type switch
    {
        1 => "未知",
        2 => "商店",
        3 => "宝箱",
        4 => "营地",
        5 => "战斗",
        6 => "精英",
        7 => "Boss",
        8 => "远古",
        _ => "未定"
    };

    private static bool ReadBool(ClrObject obj, string field)
    {
        try
        {
            return obj.ReadField<bool>(field);
        }
        catch
        {
            return false;
        }
    }

    private static int IntentDamage(ClrObject intent, ClrObject attacker, ClrObject target)
    {
        int baseDamage = 0;
        ClrObject calc = ReadObj(intent, "<DamageCalc>k__BackingField");
        if (!calc.IsNull)
        {
            try
            {
                ClrDelegate del = calc.AsDelegate();
                ClrObject closure = del.GetDelegateTarget().TargetObject;
                if (!closure.IsNull && closure.Type != null)
                {
                    foreach (ClrInstanceField field in closure.Type.Fields)
                    {
                        if (field.Type?.Name != "System.Int32")
                        {
                            continue;
                        }

                        try
                        {
                            baseDamage = closure.ReadField<int>(field.Name);
                            break;
                        }
                        catch
                        {
                            // try next field
                        }
                    }
                }
            }
            catch
            {
                // static lambda: cannot read the captured value
            }
        }

        if (baseDamage <= 0)
        {
            return 0;
        }

        // Mirror Hook.ModifyDamage: additive (Strength), then multiplicative (Weak/Vulnerable).
        decimal damage = baseDamage + GetPowerAmount(attacker, "StrengthPower");
        if (GetPowerAmount(attacker, "WeakPower") > 0)
        {
            damage *= 0.75m;
        }

        if (GetPowerAmount(target, "VulnerablePower") > 0)
        {
            damage *= 1.5m;
        }

        int perHit = Math.Max(0, (int)damage);
        int repeat = Math.Max(1, ReadInt(intent, "_repeat"));
        return perHit * repeat;
    }

    private static int GetPowerAmount(ClrObject creature, string powerName)
    {
        foreach (ClrObject power in ReadList(ReadObj(creature, "_powers")))
        {
            string id = power.Type?.Name.Split('.').Last() ?? Entry(power) ?? "";
            if (id.Contains(powerName, StringComparison.OrdinalIgnoreCase))
            {
                return ReadInt(power, "_amount");
            }
        }

        return 0;
    }

    private static Dictionary<string, decimal> ReadVars(ClrObject card)
    {
        var result = new Dictionary<string, decimal>();
        try
        {
            ClrObject set = ReadObj(card, "_dynamicVars");
            ClrObject vars = ReadObj(set, "_vars");
            foreach ((ClrObject key, ClrObject value) in ReadDict(vars))
            {
                string? name = key.AsString(64);
                if (name == null)
                {
                    continue;
                }

                result[name] = ReadDecimal(value, "_baseValue");
            }
        }
        catch
        {
            // dynamic vars are best-effort
        }

        return result;
    }

    private static decimal GetVar(Dictionary<string, decimal> vars, string name)
    {
        return vars.TryGetValue(name, out decimal value) ? value : 0m;
    }

    private static decimal ReadDecimal(ClrObject obj, string field)
    {
        try
        {
            ClrValueType value = obj.ReadValueTypeField(field);
            int flags = value.ReadField<int>("_flags");
            ulong lo64 = value.ReadField<ulong>("_lo64");
            uint hi32 = value.ReadField<uint>("_hi32");
            int lo = (int)(lo64 & 0xFFFFFFFFUL);
            int mid = (int)(lo64 >> 32);
            bool negative = (flags & int.MinValue) != 0;
            byte scale = (byte)((flags >> 16) & 0xFF);
            return new decimal(lo, mid, (int)hi32, negative, scale);
        }
        catch
        {
            return 0m;
        }
    }

    private void LoadLocalization(ClrModule module)
    {
        try
        {
            _loc.Clear();
            ClrType? locManager = module.GetTypeByName("MegaCrit.Sts2.Core.Localization.LocManager");
            ClrStaticField? instance = locManager?.StaticFields.FirstOrDefault(f => f.Name.Contains("Instance"));
            if (instance == null || _domain == null)
            {
                return;
            }

            ClrObject manager = instance.ReadObject(_domain);
            ClrObject tables = ReadObj(manager, "_tables");
            string[] wanted = { "cards", "relics", "potions", "monsters", "characters" };

            foreach ((ClrObject key, ClrObject value) in ReadDict(tables))
            {
                string? table = key.AsString(64);
                if (table == null || !wanted.Contains(table))
                {
                    continue;
                }

                ClrObject translations = ReadObj(value, "_translations");
                var dict = new Dictionary<string, string>();
                foreach ((ClrObject itemKey, ClrObject itemValue) in ReadDict(translations))
                {
                    string? k = itemKey.AsString(128);
                    string? v = itemValue.AsString(1024);
                    if (k != null && v != null)
                    {
                        dict[k] = v;
                    }
                }

                _loc[table] = dict;
            }
        }
        catch (Exception ex)
        {
            Error = "loc: " + ex.Message;
        }
    }

    private string Localize(string table, string id, string suffix)
    {
        if (!string.IsNullOrEmpty(id) && _loc.TryGetValue(table, out Dictionary<string, string>? dict))
        {
            string key = ToUpperSnake(id) + suffix;
            if (dict.TryGetValue(key, out string? text) && !string.IsNullOrWhiteSpace(text))
            {
                return text;
            }
        }

        return Prettify(id);
    }

    private static string ToUpperSnake(string id)
    {
        return Regex.Replace(id, "(?<=[a-z0-9])(?=[A-Z])", "_").ToUpperInvariant();
    }

    private static List<(ClrObject key, ClrObject value)> ReadDict(ClrObject dict)
    {
        var result = new List<(ClrObject, ClrObject)>();
        if (dict.IsNull)
        {
            return result;
        }

        try
        {
            ClrObject entries = ReadObj(dict, "_entries");
            if (entries.IsNull)
            {
                return result;
            }

            ClrArray array = entries.AsArray();
            int count = ReadInt(dict, "_count");
            for (int i = 0; i < count && i < array.Length; i++)
            {
                ClrValueType entry = array.GetStructValue(i);
                result.Add((entry.ReadObjectField("key"), entry.ReadObjectField("value")));
            }
        }
        catch
        {
            // ignore
        }

        return result;
    }

    private static string ResolveGameDir(int pid)
    {
        try
        {
            string? exe = Process.GetProcessById(pid).MainModule?.FileName;
            if (!string.IsNullOrEmpty(exe))
            {
                return Path.GetDirectoryName(exe)!;
            }
        }
        catch
        {
            // fall back to the default install path
        }

        return DefaultGameDir;
    }

    private static string? ReadGameVersion(string gameDir)
    {
        try
        {
            string path = Path.Combine(gameDir, "release_info.json");
            if (!File.Exists(path))
            {
                return null;
            }

            using JsonDocument doc = JsonDocument.Parse(File.ReadAllText(path));
            if (!doc.RootElement.TryGetProperty("version", out JsonElement version))
            {
                return null;
            }

            string? raw = version.GetString();
            return raw?.TrimStart('v', 'V');
        }
        catch
        {
            return null;
        }
    }

    private static string? Validate(GameState state)
    {
        if (state.MaxHp <= 0 || state.Hp < 0 || state.Hp > state.MaxHp)
        {
            return "HP 越界";
        }

        if (state.MaxEnergy < 0 || state.MaxEnergy > 20 || state.Energy < 0 || state.Energy > 20)
        {
            return "能量越界";
        }

        if (state.Hand.Count > 10)
        {
            return "手牌超过 10 张";
        }

        if (state.DrawCount < 0 || state.DiscardCount < 0 || state.DeckCount < 0)
        {
            return "牌堆数量为负";
        }

        foreach (EnemyInfo enemy in state.Enemies)
        {
            if (enemy.MaxHp <= 0 || enemy.Hp < 0 || enemy.Hp > enemy.MaxHp)
            {
                return "敌人 HP 越界";
            }
        }

        return null;
    }

    private ClrRuntime CreateRuntime(DataTarget target)
    {
        ClrInfo info = target.ClrVersions.OrderByDescending(v => v.Version).First();
        string? dac = Directory.Exists(_dataDir)
            ? Directory.EnumerateFiles(_dataDir, "mscordaccore_amd64_amd64_*.dll").FirstOrDefault()
              ?? Directory.EnumerateFiles(_dataDir, "mscordaccore.dll").FirstOrDefault()
            : null;

        return dac != null ? info.CreateRuntime(dac, true) : info.CreateRuntime();
    }

    private static ClrObject ReadObj(ClrObject obj, string field)
    {
        if (obj.IsNull)
        {
            return default;
        }

        try
        {
            ClrObject value = obj.ReadObjectField(field);
            return value.IsNull ? default : value;
        }
        catch
        {
            return default;
        }
    }

    private static string? ReadStr(ClrObject obj, string field)
    {
        if (obj.IsNull)
        {
            return null;
        }

        try
        {
            return obj.ReadStringField(field, 256);
        }
        catch
        {
            return null;
        }
    }

    private static int ReadInt(ClrObject obj, string field)
    {
        if (obj.IsNull)
        {
            return -1;
        }

        try
        {
            return obj.ReadField<int>(field);
        }
        catch
        {
            try
            {
                ClrValueType value = obj.ReadValueTypeField(field);
                return value.ReadField<int>("value__");
            }
            catch
            {
                return -1;
            }
        }
    }

    private static string? Entry(ClrObject model)
    {
        if (model.IsNull)
        {
            return null;
        }

        try
        {
            ClrValueType id = model.ReadValueTypeField("<Id>k__BackingField");
            return id.ReadStringField("<Entry>k__BackingField", 128);
        }
        catch
        {
            return model.Type?.Name.Split('.').Last();
        }
    }

    private static List<ClrObject> ReadList(ClrObject obj)
    {
        var result = new List<ClrObject>();
        if (obj.IsNull)
        {
            return result;
        }

        try
        {
            if (obj.Type?.IsArray == true)
            {
                ClrArray array = obj.AsArray();
                for (int i = 0; i < array.Length; i++)
                {
                    result.Add(array.GetObjectValue(i));
                }

                return result;
            }

            ClrObject items = obj.ReadObjectField("_items");
            if (items.IsNull)
            {
                return result;
            }

            ClrArray itemsArray = items.AsArray();
            int size = obj.ReadField<int>("_size");
            for (int i = 0; i < size && i < itemsArray.Length; i++)
            {
                result.Add(itemsArray.GetObjectValue(i));
            }
        }
        catch
        {
            // ignore
        }

        return result;
    }

    private static int Count(ClrObject pile)
    {
        return pile.IsNull ? 0 : ReadList(ReadObj(pile, "_cards")).Count;
    }

    private static (int cost, bool costsX) CardCost(ClrObject card)
    {
        try
        {
            ClrObject energy = card.ReadObjectField("_energyCost");
            return (energy.ReadField<int>("_base"), energy.ReadField<bool>("<CostsX>k__BackingField"));
        }
        catch
        {
            return (-1, false);
        }
    }

    private static string Prettify(string id)
    {
        if (string.IsNullOrEmpty(id))
        {
            return "";
        }

        return Regex.Replace(id, "(?<=[a-z0-9])(?=[A-Z])", " ");
    }

    private static string IntentName(string name) => name switch
    {
        "SingleAttack" => "攻击",
        "MultiAttack" => "多段攻击",
        "Defend" => "防御",
        "Buff" => "强化",
        "Debuff" => "削弱",
        "Status" => "状态",
        "Stun" => "眩晕",
        "Sleep" => "睡眠",
        "Escape" => "逃跑",
        "Heal" => "治疗",
        "Summon" => "召唤",
        "Hidden" => "未知",
        _ => name
    };

    public void Dispose()
    {
        _runtime?.Dispose();
        _target?.Dispose();
        _runtime = null;
        _target = null;
        _instanceField = null;
        _domain = null;
    }
}
