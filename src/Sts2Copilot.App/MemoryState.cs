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
    public int Target { get; set; }
    public int Rarity { get; set; }
    public int Upgraded { get; set; }
    public bool Playable { get; set; }
    public int Damage { get; set; }
    public int Block { get; set; }
    public int Poison { get; set; }
    public int Hits { get; set; } = 1;
    public Dictionary<string, double> Vars { get; set; } = new();
}

public sealed class EnemyAttackInfo
{
    public int BaseDamage { get; set; }
    public int Hits { get; set; } = 1;
}

public sealed class CombatEventInfo
{
    public string Kind { get; set; } = "";
    public string Id { get; set; } = "";
    public string Name { get; set; } = "";
    public string? Target { get; set; }
    public int? TargetHp { get; set; }
    public int? TargetMaxHp { get; set; }
    public int PlayIndex { get; set; }
    public int PlayCount { get; set; } = 1;
    public bool AutoPlay { get; set; }
    public int EnergySpent { get; set; }
    public int StarsSpent { get; set; }
    public decimal? Amount { get; set; }
    public int? Blocked { get; set; }
    public int? Unblocked { get; set; }
    public int? Overkill { get; set; }
    public string? Source { get; set; }
    public string? Receiver { get; set; }
    public string? Dealer { get; set; }
    public bool? FromHandDraw { get; set; }
}

public sealed class EventOptionInfo
{
    public int Index { get; set; }
    public string? TextKey { get; set; }
    public string Title { get; set; } = "";
    public string Description { get; set; } = "";
    public bool Locked { get; set; }
    public bool Proceed { get; set; }
    public string? RelicId { get; set; }
    public string? RelicName { get; set; }
    public int RelicRarity { get; set; }
}

public sealed class ShopItemInfo
{
    public int Index { get; set; }
    public string Kind { get; set; } = "";
    public string Name { get; set; } = "";
    public string Description { get; set; } = "";
    public int Cost { get; set; }
    public bool Affordable { get; set; }
    public string? RelicId { get; set; }
    public string? RelicName { get; set; }
    public string? PotionId { get; set; }
    public CardInfo? Card { get; set; }
}

public sealed class RestOptionInfo
{
    public int Index { get; set; }
    public string OptionId { get; set; } = "";
    public string Title { get; set; } = "";
    public string Description { get; set; } = "";
    public bool Enabled { get; set; }
    public int HealAmount { get; set; }
}

public sealed class RelicChoiceInfo
{
    public int Index { get; set; }
    public string Id { get; set; } = "";
    public string Name { get; set; } = "";
    public string Description { get; set; } = "";
    public int Rarity { get; set; }
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
    public Dictionary<string, int> Powers { get; set; } = new();
    public List<EnemyAttackInfo> Attacks { get; set; } = new();
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
    public long RunStartTime { get; set; }
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
    public bool InCombat { get; set; }
    public string? ValidationError { get; set; }
    public List<CardInfo> Hand { get; set; } = new();
    public List<CardInfo> DeckCards { get; set; } = new();
    public List<CardInfo> CardChoices { get; set; } = new();
    public List<RelicChoiceInfo> RewardRelics { get; set; } = new();
    public List<string> RewardPotions { get; set; } = new();
    public List<string> RewardPotionIds { get; set; } = new();
    public int RewardGold { get; set; }
    public List<MapNodeInfo> MapChoices { get; set; } = new();
    public List<MapNodeInfo> MapNodes { get; set; } = new();
    public List<MapEdgeInfo> MapEdges { get; set; } = new();
    public int MapCol { get; set; }
    public int MapRow { get; set; }
    public string MapTypeName { get; set; } = "";
    public bool InEvent { get; set; }
    public string EventId { get; set; } = "";
    public string EventTitle { get; set; } = "";
    public string EventDescription { get; set; } = "";
    public bool EventIsAncient { get; set; }
    public Dictionary<string, double> EventVars { get; set; } = new();
    public List<EventOptionInfo> EventOptions { get; set; } = new();
    public bool InShop { get; set; }
    public List<ShopItemInfo> ShopItems { get; set; } = new();
    public bool InRestSite { get; set; }
    public List<RestOptionInfo> RestOptions { get; set; } = new();
    public bool InTreasure { get; set; }
    public List<RelicChoiceInfo> RelicChoices { get; set; } = new();
    public List<EnemyInfo> Enemies { get; set; } = new();
    public List<CombatEventInfo> CombatEvents { get; set; } = new();
    public Dictionary<string, int> PlayerPowers { get; set; } = new();
    public List<string> Relics { get; set; } = new();
    public List<string> RelicIds { get; set; } = new();
    public Dictionary<string, int> RelicCounters { get; set; } = new();
    public List<string> Potions { get; set; } = new();
    public List<string> PotionIds { get; set; } = new();
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
    private ClrStaticField? _combatInstanceField;
    private int _historySeen;
    private int _historyEmptyPolls;
    private int _historyShortPolls;
    private bool _historyInitialized;
    private bool _historyAvailable;
    private readonly HashSet<ulong> _historyEmitted = new();
    private readonly Dictionary<string, Dictionary<string, string>> _loc = new();
    private string _dataDir = Path.Combine(DefaultGameDir, "data_sts2_windows_x86_64");

    public int Pid { get; private set; }
    public string? Error { get; private set; }
    public string GameVersion { get; private set; } = "";

    /// <summary>
    /// True when CombatManager.History could be read on the last poll. When true,
    /// card_play/potion_use are authoritative and the old inferred `action` fallback
    /// must not run; when false, History is unavailable and the fallback is all we have.
    /// </summary>
    public bool HistoryAvailable => _historyAvailable;

    /// <summary>Number of History entries skipped because their address was already emitted.</summary>
    public int HistoryDuplicatesSkipped { get; private set; }

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

            ClrType? combatManager = module?.GetTypeByName("MegaCrit.Sts2.Core.Combat.CombatManager");
            _combatInstanceField = combatManager?.StaticFields.FirstOrDefault(f => f.Name.Contains("Instance"));
            _historySeen = 0;
            _historyEmptyPolls = 0;
            _historyShortPolls = 0;
            _historyInitialized = false;
            _historyAvailable = false;
            _historyEmitted.Clear();
            HistoryDuplicatesSkipped = 0;

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
            result.RunStartTime = ReadLong(runManager, "_startTime");
            ReadRewards(result, runManager);
            ReadMap(result, state);
            ReadEvent(result, runManager, state);
            ReadShop(result, runManager, state);
            ReadRestSite(result, runManager, state);
            ReadTreasure(result, runManager, state);
            ReadCombatEvents(result);
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
        result.PlayerPowers = ReadPowers(creature);
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
                result.RelicIds.Add(id);
                if (string.Equals(id, "PenNib", StringComparison.Ordinal))
                {
                    int attacks = ReadInt(relic, "<AttacksPlayed>k__BackingField");
                    if (attacks < 0)
                    {
                        attacks = ReadInt(relic, "_attacksPlayed");
                    }

                    if (attacks >= 0)
                    {
                        result.RelicCounters[id] = attacks % 10;
                    }
                }
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
                result.PotionIds.Add(id);
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
                result.Hand.Add(BuildCard(card, result.Energy, result.DrawCount));
            }
        }

        if (!combatState.IsNull)
        {
            result.InCombat = true;

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
                    Block = ReadInt(enemy, "_block"),
                    Powers = ReadPowers(enemy)
                };
                info.Name = Localize("monsters", info.Id, ".name");

                var names = new List<string>();
                foreach (ClrObject intent in intents)
                {
                    string name = intent.Type?.Name.Split('.').Last() ?? "?";
                    names.Add(IntentName(name.Replace("Intent", "")));
                    (int baseDamage, int repeat) = IntentParts(intent);
                    int damage = IntentDamage(baseDamage, repeat, enemy, creature);
                    if (damage > 0)
                    {
                        info.Damage += damage;
                        info.Hits += repeat;
                        info.Attacks.Add(new EnemyAttackInfo
                        {
                            BaseDamage = baseDamage,
                            Hits = repeat
                        });
                    }
                }

                info.Intent = string.Join("/", names);
                result.Enemies.Add(info);
            }
        }

        return result;
    }

    private CardInfo BuildCard(ClrObject card, int energy, int drawCount = int.MaxValue)
    {
        (int cost, bool costsX) = CardCost(card);
        int type = ReadInt(card, "<Type>k__BackingField");
        string id = Entry(card) ?? "";
        Dictionary<string, decimal> vars = ReadVars(card);
        int damage = (int)(GetVar(vars, "Damage") + GetVar(vars, "CalculatedDamage") + GetVar(vars, "ExtraDamage"));
        int block = (int)(GetVar(vars, "Block") + GetVar(vars, "CalculatedBlock"));
        int poison = (int)(GetVar(vars, "PoisonPower") + GetVar(vars, "Poison"));
        int hits = Math.Max(1, (int)GetVar(vars, "Repeat"));
        bool playable = type != 4 && type != 5 && (costsX ? energy > 0 : cost >= 0 && cost <= energy);
        if (id == "GrandFinale" && drawCount > 0)
        {
            // CardModel.IsPlayable: draw pile must be empty.
            playable = false;
        }

        return new CardInfo
        {
            Id = id,
            Name = Localize("cards", id, ".title"),
            Cost = cost,
            CostsX = costsX,
            Type = type,
            Target = ReadInt(card, "<TargetType>k__BackingField"),
            Rarity = ReadInt(card, "<Rarity>k__BackingField"),
            Upgraded = ReadInt(card, "_currentUpgradeLevel"),
            Playable = playable,
            Damage = Math.Max(0, damage),
            Block = Math.Max(0, block),
            Poison = Math.Max(0, poison),
            Hits = hits,
            Vars = vars.ToDictionary(kv => kv.Key, kv => (double)kv.Value)
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
            return;
        }

        if (type == "RelicReward")
        {
            ClrObject relic = ReadObj(reward, "_relic");
            if (!relic.IsNull)
            {
                string id = Entry(relic) ?? "";
                result.RewardRelics.Add(new RelicChoiceInfo
                {
                    Index = result.RewardRelics.Count,
                    Id = id,
                    Name = Localize("relics", id, ".title"),
                    Description = CleanLocText(Localize("relics", id, ".description")),
                    Rarity = Math.Max(0, ReadInt(relic, "<Rarity>k__BackingField"))
                });
            }

            return;
        }

        if (type == "PotionReward")
        {
            ClrObject potion = ReadObj(reward, "<Potion>k__BackingField");
            if (!potion.IsNull)
            {
                string id = Entry(potion) ?? "";
                result.RewardPotions.Add(Localize("potions", id, ".title"));
                result.RewardPotionIds.Add(id);
            }
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
                    ClrObject visitedPoint = grid.GetObjectValue(new[] { col, row });
                    // At the start of an act the visited coordinate can be the
                    // starting point at row 0, which is not stored in Grid.
                    // Keep StartingMapPoint instead of overwriting it with null.
                    if (!visitedPoint.IsNull)
                    {
                        current = visitedPoint;
                    }
                }
            }

            if (current.IsNull)
            {
                return;
            }

            (int curCol, int curRow) = ReadCoord(current);
            result.MapCol = curCol;
            result.MapRow = curRow;
            result.MapTypeName = MapTypeName(ReadInt(current, "<PointType>k__BackingField"));

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

    private void ReadEvent(GameState result, ClrObject runManager, ClrObject state)
    {
        try
        {
            List<ClrObject> rooms = ReadList(ReadObj(state, "_currentRooms"));
            if (rooms.Count == 0)
            {
                return;
            }

            ClrObject room = rooms[^1];
            if (!string.Equals(room.Type?.Name.Split('.').Last(), "EventRoom", StringComparison.Ordinal))
            {
                return;
            }

            result.InEvent = true;
            ClrObject canonical = ReadObj(room, "<CanonicalEvent>k__BackingField");
            ClrObject synchronizer = ReadObj(runManager, "<EventSynchronizer>k__BackingField");
            List<ClrObject> events = ReadList(ReadObj(synchronizer, "_events"));
            ClrObject local = events.Count > 0 ? events[0] : canonical;
            string id = Entry(local) ?? Entry(canonical) ?? "";
            result.EventId = id;
            result.EventTitle = string.IsNullOrEmpty(id) ? "" : Localize("events", id, ".title");
            result.EventIsAncient = local.Type?.Name.Contains("AncientEventModel", StringComparison.Ordinal) == true;

            Dictionary<string, decimal> eventVars = ReadVars(local);
            foreach ((string name, decimal value) in eventVars)
            {
                result.EventVars[name] = (double)value;
            }

            string description = LocStringText(ReadObj(local, "<Description>k__BackingField"), eventVars);
            if (string.IsNullOrWhiteSpace(description) && !string.IsNullOrEmpty(id))
            {
                description = Localize("events", id, ".pages.INITIAL.description");
            }
            result.EventDescription = description;

            List<ClrObject> options = ReadList(ReadObj(local, "_currentOptions"));
            if (options.Count == 0)
            {
                options = ReadList(ReadObj(local, "_generatedOptions"));
            }

            int index = 0;
            foreach (ClrObject option in options)
            {
                if (option.IsNull)
                {
                    continue;
                }

                ClrObject relic = ReadObj(option, "<Relic>k__BackingField");
                string relicId = Entry(relic) ?? "";
                ClrObject descriptionLoc = ReadObj(option, "<Description>k__BackingField");
                string title = LocStringText(ReadObj(option, "<Title>k__BackingField"), eventVars);
                string optionDescription = LocStringText(descriptionLoc, eventVars);
                int relicRarity = Math.Max(0, ReadInt(relic, "<Rarity>k__BackingField"));

                if (string.IsNullOrWhiteSpace(title) && !string.IsNullOrEmpty(relicId))
                {
                    title = Localize("relics", relicId, ".title");
                }

                string relicName = string.IsNullOrEmpty(relicId) ? "" : Localize("relics", relicId, ".title");
                if (string.IsNullOrEmpty(relicName))
                {
                    relicName = LocVariableTextByName(descriptionLoc, "Relic");
                }

                result.EventOptions.Add(new EventOptionInfo
                {
                    Index = index++,
                    TextKey = ReadStr(option, "<TextKey>k__BackingField"),
                    Title = title,
                    Description = optionDescription,
                    Locked = ReadBool(option, "<IsLocked>k__BackingField"),
                    Proceed = ReadBool(option, "<IsProceed>k__BackingField"),
                    RelicId = string.IsNullOrEmpty(relicId) ? null : relicId,
                    RelicName = string.IsNullOrEmpty(relicName) ? null : relicName,
                    RelicRarity = relicRarity
                });
            }
        }
        catch
        {
            // event is best-effort
        }
    }

    private string LocStringText(ClrObject locString, IReadOnlyDictionary<string, decimal>? extraVars = null)
    {
        if (locString.IsNull)
        {
            return "";
        }

        string table = ReadStr(locString, "<locTable>P") ?? "";
        string key = ReadStr(locString, "<locEntryKey>P") ?? "";
        if (string.IsNullOrEmpty(key))
        {
            return "";
        }

        if (_loc.TryGetValue(table, out Dictionary<string, string>? dict))
        {
            if (dict.TryGetValue(key, out string? text) && !string.IsNullOrWhiteSpace(text))
            {
                return CleanLocText(FormatLocVariables(text, locString, extraVars));
            }

            if (dict.TryGetValue(key.ToUpperInvariant(), out text) && !string.IsNullOrWhiteSpace(text))
            {
                return CleanLocText(FormatLocVariables(text, locString, extraVars));
            }
        }

        return Prettify(key);
    }

    private string FormatLocVariables(string text, ClrObject locString, IReadOnlyDictionary<string, decimal>? extraVars = null)
    {
        foreach ((ClrObject key, ClrObject value) in ReadDict(ReadObj(locString, "_variables")))
        {
            string? name = key.AsString(64);
            if (string.IsNullOrEmpty(name))
            {
                continue;
            }

            string replacement = LocVariableText(value);
            if (!string.IsNullOrEmpty(replacement))
            {
                text = text.Replace("{" + name + "}", replacement);
            }
        }

        if (extraVars != null)
        {
            foreach ((string name, decimal value) in extraVars)
            {
                text = Regex.Replace(
                    text,
                    "\\{" + Regex.Escape(name) + "(?::[^}]*)?\\}",
                    value.ToString("0.##"));
            }
        }

        return text;
    }

    private string LocVariableText(ClrObject value)
    {
        if (value.IsNull)
        {
            return "";
        }

        string type = value.Type?.Name ?? "";
        try
        {
            if (type.Contains("LocString", StringComparison.Ordinal))
            {
                return LocStringText(value);
            }

            if (type == "System.String")
            {
                return value.AsString(512) ?? "";
            }

            if (value.IsBoxedValue)
            {
                if (type == "System.Decimal")
                {
                    return value.ReadBoxedValue<decimal>().ToString("0.##");
                }

                if (type == "System.Int32")
                {
                    return value.ReadBoxedValue<int>().ToString();
                }

                if (type == "System.Int64")
                {
                    return value.ReadBoxedValue<long>().ToString();
                }

                if (type == "System.Double")
                {
                    return value.ReadBoxedValue<double>().ToString("0.##");
                }

                if (type == "System.Boolean")
                {
                    return value.ReadBoxedValue<bool>() ? "是" : "否";
                }
            }

            if (type.Contains("RelicModel", StringComparison.Ordinal))
            {
                string id = Entry(value) ?? "";
                return string.IsNullOrEmpty(id) ? "" : Localize("relics", id, ".title");
            }
        }
        catch
        {
            // Best-effort: leave the placeholder for CleanLocText to remove.
        }

        return "";
    }

    private string LocVariableTextByName(ClrObject locString, string name)
    {
        foreach ((ClrObject key, ClrObject value) in ReadDict(ReadObj(locString, "_variables")))
        {
            if (string.Equals(key.AsString(64), name, StringComparison.Ordinal))
            {
                return LocVariableText(value);
            }
        }

        return "";
    }

    private static string CleanLocText(string text)
    {
        if (string.IsNullOrWhiteSpace(text))
        {
            return "";
        }

        // Event text uses BBCode-like tags and SmartFormat placeholders. We
        // cannot call the game's formatter, so strip tags and keep readable
        // labels for the common placeholders.
        text = text.Replace("{Relic}", "遗物")
                   .Replace("{Gold}", "?")
                   .Replace("{HpLoss}", "?");
        text = Regex.Replace(text, @"\[/?[a-zA-Z0-9_=#.\-]+\]", "");
        text = Regex.Replace(text, @"\{[^}]+\}", "");
        return text.Trim();
    }

    private void ReadShop(GameState result, ClrObject runManager, ClrObject state)
    {
        try
        {
            List<ClrObject> rooms = ReadList(ReadObj(state, "_currentRooms"));
            if (rooms.Count == 0 || !string.Equals(rooms[^1].Type?.Name.Split('.').Last(), "MerchantRoom", StringComparison.Ordinal))
            {
                return;
            }

            result.InShop = true;
            List<ClrObject> inventories = ReadList(ReadObj(rooms[^1], "<Inventories>k__BackingField"));
            if (inventories.Count == 0)
            {
                return;
            }

            ClrObject inventory = inventories[0];
            int index = 0;

            void AddCard(ClrObject entry, string kind)
            {
                ClrObject creation = ReadObj(entry, "<CreationResult>k__BackingField");
                if (creation.IsNull)
                {
                    return;
                }

                ClrObject card = ReadObj(creation, "_modifiedCard");
                if (card.IsNull)
                {
                    card = ReadObj(creation, "originalCard");
                }

                if (card.IsNull)
                {
                    return;
                }

                CardInfo info = BuildCard(card, 0);
                int cost = Math.Max(0, ReadIntInherited(entry, "_cost"));
                result.ShopItems.Add(new ShopItemInfo
                {
                    Index = index++,
                    Kind = kind,
                    Name = info.Name + (info.Upgraded > 0 ? "+" : ""),
                    Description = CleanLocText(Localize("cards", info.Id, ".description")),
                    Cost = cost,
                    Affordable = cost <= result.Gold,
                    Card = info
                });
            }

            foreach (ClrObject entry in ReadList(ReadObj(inventory, "_characterCardEntries")))
            {
                AddCard(entry, "card");
            }

            foreach (ClrObject entry in ReadList(ReadObj(inventory, "_colorlessCardEntries")))
            {
                AddCard(entry, "colorless");
            }

            foreach (ClrObject entry in ReadList(ReadObj(inventory, "_relicEntries")))
            {
                ClrObject relic = ReadObj(entry, "<Model>k__BackingField");
                if (relic.IsNull)
                {
                    continue;
                }

                string id = Entry(relic) ?? "";
                int cost = Math.Max(0, ReadIntInherited(entry, "_cost"));
                result.ShopItems.Add(new ShopItemInfo
                {
                    Index = index++,
                    Kind = "relic",
                    Name = Localize("relics", id, ".title"),
                    Description = CleanLocText(Localize("relics", id, ".description")),
                    Cost = cost,
                    Affordable = cost <= result.Gold,
                    RelicId = id,
                    RelicName = Localize("relics", id, ".title")
                });
            }

            foreach (ClrObject entry in ReadList(ReadObj(inventory, "_potionEntries")))
            {
                ClrObject potion = ReadObj(entry, "<Model>k__BackingField");
                if (potion.IsNull)
                {
                    continue;
                }

                string id = Entry(potion) ?? "";
                int cost = Math.Max(0, ReadIntInherited(entry, "_cost"));
                result.ShopItems.Add(new ShopItemInfo
                {
                    Index = index++,
                    Kind = "potion",
                    Name = Localize("potions", id, ".title"),
                    Description = CleanLocText(Localize("potions", id, ".description")),
                    Cost = cost,
                    Affordable = cost <= result.Gold,
                    PotionId = id
                });
            }

            ClrObject removal = ReadObj(inventory, "<CardRemovalEntry>k__BackingField");
            if (!removal.IsNull && !ReadBool(removal, "<Used>k__BackingField"))
            {
                int cost = Math.Max(0, ReadIntInherited(removal, "_cost"));
                result.ShopItems.Add(new ShopItemInfo
                {
                    Index = index,
                    Kind = "removal",
                    Name = "删牌服务",
                    Description = "删除牌组中的一张牌",
                    Cost = cost,
                    Affordable = cost <= result.Gold
                });
            }
        }
        catch
        {
            // shop is best-effort
        }
    }

    private void ReadRestSite(GameState result, ClrObject runManager, ClrObject state)
    {
        try
        {
            List<ClrObject> rooms = ReadList(ReadObj(state, "_currentRooms"));
            if (rooms.Count == 0 || !string.Equals(rooms[^1].Type?.Name.Split('.').Last(), "RestSiteRoom", StringComparison.Ordinal))
            {
                return;
            }

            result.InRestSite = true;
            ClrObject synchronizer = ReadObj(runManager, "<RestSiteSynchronizer>k__BackingField");
            List<ClrObject> restSites = ReadList(ReadObj(synchronizer, "_restSites"));
            if (restSites.Count == 0)
            {
                return;
            }

            List<ClrObject> options = ReadList(ReadObj(restSites[0], "options"));
            int index = 0;
            foreach (ClrObject option in options)
            {
                if (option.IsNull)
                {
                    continue;
                }

                string type = option.Type?.Name.Split('.').Last() ?? "";
                string optionId = type.Replace("RestSiteOption", "").ToUpperInvariant();
                if (string.IsNullOrEmpty(optionId))
                {
                    optionId = type.ToUpperInvariant();
                }

                string title = Localize("rest_site_ui", "OPTION_" + optionId, ".name");
                string description = Localize("rest_site_ui", "OPTION_" + optionId, ".description");
                bool smithEnabled = type != "SmithRestSiteOption" ||
                                    result.DeckCards.Any(card => card.Upgraded == 0 && card.Type != 4 && card.Type != 5);
                int heal = optionId == "HEAL" ? (int)(result.MaxHp * 0.3) : 0;

                result.RestOptions.Add(new RestOptionInfo
                {
                    Index = index++,
                    OptionId = optionId,
                    Title = title,
                    Description = CleanLocText(description),
                    Enabled = type == "SmithRestSiteOption" ? smithEnabled : true,
                    HealAmount = heal
                });
            }
        }
        catch
        {
            // rest site is best-effort
        }
    }

    private void ReadTreasure(GameState result, ClrObject runManager, ClrObject state)
    {
        try
        {
            List<ClrObject> rooms = ReadList(ReadObj(state, "_currentRooms"));
            if (rooms.Count == 0 || !string.Equals(rooms[^1].Type?.Name.Split('.').Last(), "TreasureRoom", StringComparison.Ordinal))
            {
                return;
            }

            result.InTreasure = true;
            ClrObject synchronizer = ReadObj(runManager, "<TreasureRoomRelicSynchronizer>k__BackingField");
            List<ClrObject> relics = ReadList(ReadObj(synchronizer, "_currentRelics"));
            int index = 0;
            foreach (ClrObject relic in relics)
            {
                if (relic.IsNull)
                {
                    continue;
                }

                string id = Entry(relic) ?? "";
                result.RelicChoices.Add(new RelicChoiceInfo
                {
                    Index = index++,
                    Id = id,
                    Name = Localize("relics", id, ".title"),
                    Description = CleanLocText(Localize("relics", id, ".description")),
                    Rarity = Math.Max(0, ReadInt(relic, "<Rarity>k__BackingField"))
                });
            }
        }
        catch
        {
            // treasure is best-effort
        }
    }

    private void ReadCombatEvents(GameState result)
    {
        if (_combatInstanceField == null || _domain == null)
        {
            _historyAvailable = false;
            return;
        }

        try
        {
            ClrObject manager = _combatInstanceField.ReadObject(_domain);
            ClrObject history = ReadObj(manager, "<History>k__BackingField");
            _historyAvailable = !manager.IsNull && !history.IsNull;
            if (!_historyAvailable)
            {
                return;
            }

            if (!TryReadList(ReadObj(history, "_entries"), out List<ClrObject> entries))
            {
                // A transient read failure must not look like a cleared list,
                // otherwise the next poll replays every entry as a new event.
                return;
            }

            if (entries.Count == 0)
            {
                // CombatHistory.Clear() empties the list only at combat start/end.
                // Require two consecutive empty reads so one bad snapshot cannot
                // rewind the cursor and duplicate card_play events.
                _historyEmptyPolls++;
                if (_historySeen == 0 || _historyEmptyPolls >= 2)
                {
                    _historySeen = 0;
                    _historyShortPolls = 0;
                    _historyInitialized = true;
                    _historyEmitted.Clear();
                }

                return;
            }

            _historyEmptyPolls = 0;
            if (!_historyInitialized)
            {
                // App started mid-combat: skip history that happened before attach.
                // Mark those entries as already seen so a later cursor rewind
                // cannot emit pre-attach plays as new events.
                foreach (ClrObject entry in entries)
                {
                    if (entry.Address != 0)
                    {
                        _historyEmitted.Add(entry.Address);
                    }
                }

                _historyInitialized = true;
                _historySeen = entries.Count;
                return;
            }

            if (entries.Count < _historySeen)
            {
                // Shorter snapshot: usually the game is mutating the List. Do not
                // rewind immediately; after two shorter polls treat it as a new
                // combat whose history does not start with an observed empty list.
                _historyShortPolls++;
                if (_historyShortPolls < 2)
                {
                    return;
                }

                _historySeen = 0;
                _historyShortPolls = 0;
                _historyEmitted.Clear();
            }
            else
            {
                _historyShortPolls = 0;
            }

            // Do not compare entry[0].Address here: the GC can move objects and
            // the address would look like a new history, replaying every entry.
            for (; _historySeen < entries.Count; _historySeen++)
            {
                ulong address = entries[_historySeen].Address;
                if (address == 0)
                {
                    continue;
                }

                if (!_historyEmitted.Add(address))
                {
                    // The cursor can be rewound by a mutable-list snapshot; the
                    // entry object itself is unique, so never emit it twice.
                    HistoryDuplicatesSkipped++;
                    continue;
                }

                try
                {
                    CombatEventInfo? ev = ParseCombatEvent(entries[_historySeen]);
                    if (ev != null)
                    {
                        result.CombatEvents.Add(ev);
                    }
                }
                catch
                {
                    // Skip a malformed entry and keep later events flowing.
                }
            }
        }
        catch
        {
            _historyAvailable = false;
            // history is best-effort; inferred actions remain the fallback
        }
    }

    /// <summary>
    /// Read List&lt;T&gt; with an explicit success flag. ReadList swallows errors and
    /// returns an empty list, which is indistinguishable from a genuine empty list.
    /// </summary>
    private static bool TryReadList(ClrObject obj, out List<ClrObject> result)
    {
        result = new List<ClrObject>();
        if (obj.IsNull)
        {
            return false;
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

                return true;
            }

            ClrObject items = obj.ReadObjectField("_items");
            if (items.IsNull)
            {
                return false;
            }

            ClrArray itemsArray = items.AsArray();
            int size = obj.ReadField<int>("_size");
            if (size < 0 || size > itemsArray.Length)
            {
                // The game is mutating the list while we read it.
                return false;
            }

            for (int i = 0; i < size; i++)
            {
                result.Add(itemsArray.GetObjectValue(i));
            }

            return true;
        }
        catch
        {
            return false;
        }
    }

    private CombatEventInfo? ParseCombatEvent(ClrObject entry)
    {
        string type = entry.Type?.Name.Split('.').Last() ?? "";
        if (type == "CardPlayFinishedEntry")
        {
            ClrObject play = ReadObj(entry, "<CardPlay>k__BackingField");
            ClrObject card = ReadObj(play, "<Card>k__BackingField");
            string id = Entry(card) ?? "";
            if (string.IsNullOrEmpty(id))
            {
                return null;
            }

            var ev = new CombatEventInfo
            {
                Kind = "card_play",
                Id = id,
                Name = Localize("cards", id, ".title"),
                PlayIndex = Math.Max(0, ReadInt(play, "<PlayIndex>k__BackingField")),
                PlayCount = Math.Max(1, ReadInt(play, "<PlayCount>k__BackingField")),
                AutoPlay = ReadBool(play, "<IsAutoPlay>k__BackingField")
            };

            ClrObject target = ReadObj(play, "<Target>k__BackingField");
            if (!target.IsNull)
            {
                ev.Target = CreatureName(target);
                ev.TargetHp = ReadInt(target, "_currentHp");
                ev.TargetMaxHp = ReadInt(target, "_maxHp");
            }

            ClrValueType resources = play.ReadValueTypeField("<Resources>k__BackingField");
            ev.EnergySpent = resources.ReadField<int>("<EnergySpent>k__BackingField");
            ev.StarsSpent = resources.ReadField<int>("<StarsSpent>k__BackingField");
            return ev;
        }

        if (type == "PotionUsedEntry")
        {
            ClrObject potion = ReadObj(entry, "<Potion>k__BackingField");
            string id = Entry(potion) ?? "";
            if (string.IsNullOrEmpty(id))
            {
                return null;
            }

            var ev = new CombatEventInfo
            {
                Kind = "potion_use",
                Id = id,
                Name = Localize("potions", id, ".title")
            };
            ClrObject target = ReadObj(entry, "<Target>k__BackingField");
            if (!target.IsNull)
            {
                ev.Target = CreatureName(target);
                ev.TargetHp = ReadInt(target, "_currentHp");
                ev.TargetMaxHp = ReadInt(target, "_maxHp");
            }

            return ev;
        }

        if (type == "CardDrawnEntry")
        {
            ClrObject card = ReadObj(entry, "<Card>k__BackingField");
            string id = Entry(card) ?? "";
            if (string.IsNullOrEmpty(id))
            {
                return null;
            }

            return new CombatEventInfo
            {
                Kind = "card_drawn",
                Id = id,
                Name = Localize("cards", id, ".title"),
                Receiver = CreatureLabel(ReadObj(entry, "<Actor>k__BackingField")),
                FromHandDraw = ReadBool(entry, "<FromHandDraw>k__BackingField")
            };
        }

        if (type == "BlockGainedEntry")
        {
            ClrObject cardPlay = ReadObj(entry, "<CardPlay>k__BackingField");
            string source = "relic/other";
            if (!cardPlay.IsNull)
            {
                string cardName = CardLabel(ReadObj(cardPlay, "<Card>k__BackingField"));
                if (!string.IsNullOrEmpty(cardName))
                {
                    source = cardName;
                }
            }

            return new CombatEventInfo
            {
                Kind = "block_gained",
                Amount = Math.Max(0, ReadInt(entry, "<Amount>k__BackingField")),
                Source = source,
                Receiver = CreatureLabel(ReadObj(entry, "<Actor>k__BackingField"))
            };
        }

        if (type == "DamageReceivedEntry")
        {
            ClrObject result = ReadObj(entry, "<Result>k__BackingField");
            int blocked = Math.Max(0, ReadInt(result, "<BlockedDamage>k__BackingField"));
            int unblocked = Math.Max(0, ReadInt(result, "<UnblockedDamage>k__BackingField"));
            int overkill = Math.Max(0, ReadInt(result, "<OverkillDamage>k__BackingField"));
            ClrObject cardSource = ReadObj(entry, "<CardSource>k__BackingField");
            ClrObject dealer = ReadObj(entry, "<Dealer>k__BackingField");
            string source = !cardSource.IsNull
                ? CardLabel(cardSource)
                : (!dealer.IsNull ? CreatureLabel(dealer) : "环境");

            return new CombatEventInfo
            {
                Kind = "damage_received",
                Amount = blocked + unblocked,
                Blocked = blocked,
                Unblocked = unblocked,
                Overkill = overkill,
                Source = source,
                Receiver = CreatureLabel(ReadObj(entry, "<Actor>k__BackingField")),
                Dealer = dealer.IsNull ? null : CreatureLabel(dealer)
            };
        }

        if (type == "PowerReceivedEntry")
        {
            ClrObject power = ReadObj(entry, "<Power>k__BackingField");
            string id = Entry(power) ?? "";
            if (string.IsNullOrEmpty(id))
            {
                return null;
            }

            ClrObject applier = ReadObj(entry, "<Applier>k__BackingField");
            return new CombatEventInfo
            {
                Kind = "power_received",
                Id = id,
                Name = Localize("powers", id, ".title"),
                Amount = ReadDecimal(entry, "<Amount>k__BackingField"),
                Source = applier.IsNull ? null : CreatureLabel(applier),
                Receiver = CreatureLabel(ReadObj(entry, "<Actor>k__BackingField"))
            };
        }

        return null;
    }

    private string CardLabel(ClrObject card)
    {
        string id = Entry(card) ?? "";
        return string.IsNullOrEmpty(id) ? "" : Localize("cards", id, ".title");
    }

    private string CreatureLabel(ClrObject creature)
    {
        if (creature.IsNull)
        {
            return "";
        }

        ClrObject monster = ReadObj(creature, "<Monster>k__BackingField");
        if (!monster.IsNull)
        {
            string id = Entry(monster) ?? "";
            return Localize("monsters", id, ".name");
        }

        ClrObject player = ReadObj(creature, "<Player>k__BackingField");
        if (!player.IsNull)
        {
            ClrObject character = ReadObj(player, "<Character>k__BackingField");
            string id = Entry(character) ?? "";
            return string.IsNullOrEmpty(id) ? "玩家" : Localize("characters", id, ".title");
        }

        return CreatureName(creature);
    }

    private string CreatureName(ClrObject creature)
    {
        ClrObject monster = ReadObj(creature, "<Monster>k__BackingField");
        if (!monster.IsNull)
        {
            string id = Entry(monster) ?? "";
            return Localize("monsters", id, ".name");
        }

        return creature.Type?.Name.Split('.').Last() ?? "?";
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

    private static (int baseDamage, int repeat) IntentParts(ClrObject intent)
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

                        // Property-based lambdas (e.g. WaterfallGiant's
                        // () => CurrentPressureGunDamage) target the monster
                        // itself, and its metadata lists const fields before the
                        // instance ones. Reading a const (_endCombatBgmFlag = 5)
                        // made that intent look like a 5-damage attack while the
                        // real hit was 20/25. Only instance data can be damage.
                        if (IsStaticField(field))
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

        return (baseDamage, Math.Max(1, ReadInt(intent, "_repeat")));
    }

    private static bool IsStaticField(ClrInstanceField field)
    {
        try
        {
            return (field.Attributes & System.Reflection.FieldAttributes.Static) != 0;
        }
        catch
        {
            return false;
        }
    }

    private static int IntentDamage(int baseDamage, int repeat, ClrObject attacker, ClrObject target)
    {
        if (baseDamage <= 0)
        {
            return 0;
        }

        // Mirror Hook.ModifyDamage: additive (Strength, Vigor), then
        // multiplicative (Weak/Vulnerable). VigorPower is additive damage on the
        // next powered attack and is consumed after it.
        decimal damage = baseDamage + GetPowerAmount(attacker, "StrengthPower")
            + GetPowerAmount(attacker, "VigorPower");
        if (GetPowerAmount(attacker, "WeakPower") > 0)
        {
            damage *= 0.75m;
        }

        if (GetPowerAmount(target, "VulnerablePower") > 0)
        {
            damage *= 1.5m;
        }

        return Math.Max(0, (int)damage) * repeat;
    }

    private static Dictionary<string, int> ReadPowers(ClrObject creature)
    {
        var result = new Dictionary<string, int>();
        foreach (ClrObject power in ReadList(ReadObj(creature, "_powers")))
        {
            string id = power.Type?.Name.Split('.').Last() ?? Entry(power) ?? "";
            if (!string.IsNullOrEmpty(id))
            {
                result[id] = ReadInt(power, "_amount");
            }
        }

        return result;
    }

    private static int GetPowerAmount(ClrObject creature, string powerName)
    {
        foreach ((string id, int amount) in ReadPowers(creature))
        {
            if (id.Contains(powerName, StringComparison.OrdinalIgnoreCase))
            {
                return amount;
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
            string[] wanted = { "cards", "relics", "potions", "monsters", "characters", "events", "powers", "rest_site_ui" };

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

    private static long ReadLong(ClrObject obj, string field)
    {
        if (obj.IsNull)
        {
            return 0;
        }

        try
        {
            return obj.ReadField<long>(field);
        }
        catch
        {
            return 0;
        }
    }

    private static int ReadIntInherited(ClrObject obj, string field)
    {
        if (obj.IsNull)
        {
            return -1;
        }

        for (ClrType? type = obj.Type; type != null; type = type.BaseType)
        {
            ClrInstanceField? instanceField = type.GetFieldByName(field);
            if (instanceField == null)
            {
                continue;
            }

            try
            {
                return obj.ReadField<int>(instanceField);
            }
            catch
            {
                try
                {
                    ClrValueType value = obj.ReadValueTypeField(instanceField);
                    return value.ReadField<int>("value__");
                }
                catch
                {
                    return -1;
                }
            }
        }

        return -1;
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
            if (!energy.IsNull)
            {
                int cost = energy.ReadField<int>("_base");
                bool costsX = energy.ReadField<bool>("<CostsX>k__BackingField");
                if (cost < 0)
                {
                    cost = card.ReadField<int>("<CanonicalEnergyCost>k__BackingField");
                }

                return (cost, costsX);
            }
        }
        catch
        {
            // fall through to the canonical cost
        }

        try
        {
            return (card.ReadField<int>("<CanonicalEnergyCost>k__BackingField"), false);
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
