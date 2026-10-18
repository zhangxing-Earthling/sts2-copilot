using System.Reflection;
using Microsoft.Diagnostics.Runtime;

if (args.Length > 0 && args[0] == "reflect")
{
    foreach (string name in new[] { "Microsoft.Diagnostics.Runtime.ClrDelegate", "Microsoft.Diagnostics.Runtime.ClrDelegateTarget" })
    {
        Type? type = typeof(ClrRuntime).Assembly.GetType(name);
        Console.WriteLine($"===== {name} =====");
        if (type == null)
        {
            Console.WriteLine("  <not found>");
            continue;
        }

        foreach (MemberInfo member in type.GetMembers(BindingFlags.Public | BindingFlags.Instance | BindingFlags.Static | BindingFlags.DeclaredOnly)
                     .OrderBy(m => m.Name))
        {
            Console.WriteLine("  " + member);
        }
    }

    return 0;
}

if (args.Length >= 3 && args[0] == "fields")
{
    int pid = int.Parse(args[1]);
    string typeName = args[2];
    using DataTarget target = DataTarget.AttachToProcess(pid, false);
    ClrRuntime runtime = CreateRuntime(target);
    ClrModule? module = FindGameModule(runtime);
    if (module == null)
    {
        Console.WriteLine("sts2.dll not found");
        return 2;
    }

    ClrType? type = module.GetTypeByName(typeName);
    if (type == null)
    {
        Console.WriteLine("type not found: " + typeName);
        return 3;
    }

    Console.WriteLine($"type {type.Name} mt=0x{type.MethodTable:X}");
    foreach (ClrInstanceField field in type.Fields)
    {
        Console.WriteLine($"  field {field.Name} : {field.Type?.Name}");
    }

    foreach (ClrStaticField field in type.StaticFields)
    {
        Console.WriteLine($"  static {field.Name} : {field.Type?.Name}");
    }

    return 0;
}

if (args.Length >= 2 && args[0] == "loc")
{
    int pid = int.Parse(args[1]);
    using DataTarget target = DataTarget.AttachToProcess(pid, false);
    ClrRuntime runtime = CreateRuntime(target);
    ClrAppDomain domain = runtime.AppDomains.Length > 0 ? runtime.AppDomains[0] : runtime.SharedDomain;
    ClrModule? module = FindGameModule(runtime);
    if (module == null)
    {
        Console.WriteLine("sts2.dll not found");
        return 2;
    }

    ClrType? locManagerType = module.GetTypeByName("MegaCrit.Sts2.Core.Localization.LocManager");
    ClrStaticField? instanceField = locManagerType?.StaticFields.FirstOrDefault(f => f.Name.Contains("Instance"));
    if (instanceField == null)
    {
        Console.WriteLine("LocManager.Instance not found");
        return 3;
    }

    ClrObject locManager = instanceField.ReadObject(domain);
    ClrObject tables = ReadObj(locManager, "_tables");
    Console.WriteLine($"tables null={tables.IsNull}");
    foreach ((ClrObject key, ClrObject value) in ReadDict(tables))
    {
        string? name = key.AsString(64);
        Console.WriteLine($"TABLE {name}");
        if (name != "cards")
        {
            continue;
        }

        ClrObject translations = ReadObj(value, "_translations");
        Console.WriteLine($"  translations null={translations.IsNull}");
        int shown = 0;
        foreach ((ClrObject cardKey, ClrObject cardValue) in ReadDict(translations))
        {
            Console.WriteLine($"  {cardKey.AsString(128)} = {cardValue.AsString(128)}");
            if (++shown >= 8)
            {
                break;
            }
        }
    }

    return 0;
}

if (args.Length >= 4 && args[0] == "locsearch")
{
    int pid = int.Parse(args[1]);
    string tableName = args[2];
    string needle = args[3];
    using DataTarget target = DataTarget.AttachToProcess(pid, false);
    ClrRuntime runtime = CreateRuntime(target);
    ClrAppDomain domain = runtime.AppDomains.Length > 0 ? runtime.AppDomains[0] : runtime.SharedDomain;
    ClrModule? module = FindGameModule(runtime);
    ClrType? locManagerType = module?.GetTypeByName("MegaCrit.Sts2.Core.Localization.LocManager");
    ClrStaticField? instanceField = locManagerType?.StaticFields.FirstOrDefault(f => f.Name.Contains("Instance"));
    if (instanceField == null)
    {
        Console.WriteLine("LocManager.Instance not found");
        return 3;
    }

    ClrObject locManager = instanceField.ReadObject(domain);
    ClrObject tables = ReadObj(locManager, "_tables");
    foreach ((ClrObject key, ClrObject value) in ReadDict(tables))
    {
        if (key.AsString(64) != tableName)
        {
            continue;
        }

        ClrObject translations = ReadObj(value, "_translations");
        int shown = 0;
        foreach ((ClrObject cardKey, ClrObject cardValue) in ReadDict(translations))
        {
            string? k = cardKey.AsString(128);
            if (k == null || !k.Contains(needle, StringComparison.OrdinalIgnoreCase))
            {
                continue;
            }

            Console.WriteLine($"{k} = {cardValue.AsString(256)}");
            if (++shown >= 30)
            {
                break;
            }
        }
    }

    return 0;
}

if (args.Length >= 2 && args[0] == "cardvars")
{
    int pid = int.Parse(args[1]);
    using DataTarget target = DataTarget.AttachToProcess(pid, false);
    ClrRuntime runtime = CreateRuntime(target);
    ClrAppDomain domain = runtime.AppDomains.Length > 0 ? runtime.AppDomains[0] : runtime.SharedDomain;
    ClrModule? module = FindGameModule(runtime);
    ClrType? runManagerType = module?.GetTypeByName("MegaCrit.Sts2.Core.Runs.RunManager");
    ClrStaticField? instanceField = runManagerType?.StaticFields.FirstOrDefault(f => f.Name.Contains("Instance"));
    if (instanceField == null)
    {
        Console.WriteLine("RunManager.Instance not found");
        return 3;
    }

    ClrObject state = ReadObj(instanceField.ReadObject(domain), "<State>k__BackingField");
    if (state.IsNull)
    {
        Console.WriteLine("NO_RUN");
        return 0;
    }

    ClrObject player = ReadList(ReadObj(state, "_players"))[0];
    ClrObject pcs = ReadObj(player, "<PlayerCombatState>k__BackingField");
    List<ClrObject> cards = ReadList(ReadObj(ReadObj(pcs, "<Hand>k__BackingField"), "_cards"));
    if (cards.Count == 0)
    {
        Console.WriteLine("NO_CARDS");
        return 0;
    }

    foreach (ClrObject card in cards)
    {
    Console.WriteLine($"card {Entry(card)} type={card.Type?.Name}");
    if (card.Type != null)
    {
        foreach (ClrInstanceField field in card.Type.Fields)
        {
            if (field.Name.Contains("dynamic", StringComparison.OrdinalIgnoreCase))
            {
                Console.WriteLine($"  field {field.Name} : {field.Type?.Name}");
            }
        }
    }

    ClrObject set = ReadObj(card, "_dynamicVars");
    ClrObject vars = ReadObj(set, "_vars");
    Console.WriteLine($"  vars count={ReadInt(vars, "_count")}");
    foreach ((ClrObject key, ClrObject value) in ReadDict(vars))
    {
        string? name = key.AsString(64);
        try
        {
            ClrValueType dec = value.ReadValueTypeField("_baseValue");
            Console.WriteLine($"    {name} = {Dec(dec)}");
        }
        catch (Exception ex)
        {
            Console.WriteLine($"    {name} err {ex.Message}");
        }
    }
    }

    return 0;
}

if (args.Length >= 2 && args[0] == "rewards")
{
    int pid = int.Parse(args[1]);
    using DataTarget target = DataTarget.AttachToProcess(pid, false);
    ClrRuntime runtime = CreateRuntime(target);
    ClrAppDomain domain = runtime.AppDomains.Length > 0 ? runtime.AppDomains[0] : runtime.SharedDomain;
    ClrModule? module = FindGameModule(runtime);
    ClrType? runManagerType = module?.GetTypeByName("MegaCrit.Sts2.Core.Runs.RunManager");
    ClrStaticField? instanceField = runManagerType?.StaticFields.FirstOrDefault(f => f.Name.Contains("Instance"));
    if (instanceField == null)
    {
        Console.WriteLine("RunManager.Instance not found");
        return 3;
    }

    ClrObject runManager = instanceField.ReadObject(domain);
    ClrObject sync = ReadObj(runManager, "<RewardsSetSynchronizer>k__BackingField");
    Console.WriteLine($"sync null={sync.IsNull} type={sync.Type?.Name}");
    foreach (ClrObject state in ReadList(ReadObj(sync, "_rewardStates")))
    {
        List<ClrObject> stack = ReadList(ReadObj(state, "rewardsStack"));
        Console.WriteLine($"state stack={stack.Count}");
        if (stack.Count == 0)
        {
            continue;
        }

        ClrObject set = ReadObj(stack[^1], "set");
        Console.WriteLine($"set null={set.IsNull} type={set.Type?.Name}");
        foreach (ClrObject reward in ReadList(ReadObj(set, "<Rewards>k__BackingField")))
        {
            DumpReward(reward, 1);
        }
    }

    return 0;
}


if (args.Length >= 2 && args[0] == "map")
{
    int pid = int.Parse(args[1]);
    using DataTarget target = DataTarget.AttachToProcess(pid, false);
    ClrRuntime runtime = CreateRuntime(target);
    ClrAppDomain domain = runtime.AppDomains.Length > 0 ? runtime.AppDomains[0] : runtime.SharedDomain;
    ClrModule? module = FindGameModule(runtime);
    ClrType? runManagerType = module?.GetTypeByName("MegaCrit.Sts2.Core.Runs.RunManager");
    ClrStaticField? instanceField = runManagerType?.StaticFields.FirstOrDefault(f => f.Name.Contains("Instance"));
    if (instanceField == null) { Console.WriteLine("no RunManager"); return 3; }
    ClrObject state = ReadObj(instanceField.ReadObject(domain), "<State>k__BackingField");
    if (state.IsNull) { Console.WriteLine("NO_RUN"); return 0; }
    ClrObject map = ReadObj(state, "<Map>k__BackingField");
    Console.WriteLine($"map type={map.Type?.Name}");
    if (map.Type != null)
    {
        foreach (ClrInstanceField f in map.Type.Fields)
        {
            string val;
            try
            {
                ClrObject o = map.ReadObjectField(f.Name);
                val = o.IsNull ? "null" : (o.Type?.Name ?? "?");
            }
            catch (Exception ex)
            {
                val = "err:" + ex.Message;
            }
            Console.WriteLine($"  FIELD {f.Name} : {f.Type?.Name} = {val}");
        }
    }
    ClrObject start = ReadObj(map, "<StartingMapPoint>k__BackingField");
    Console.WriteLine($"start null={start.IsNull}");
    ClrObject gridObj = ReadObj(map, "<Grid>k__BackingField");
    ClrArray grid = gridObj.AsArray();
    Console.WriteLine($"grid rank={grid.Rank} len0={grid.GetLength(0)} len1={grid.GetLength(1)}");
    List<(int col, int row)> visited = ReadCoordList(ReadObj(state, "_visitedMapCoords"));
    Console.WriteLine("visited=" + string.Join(";", visited.Select(v => $"{v.col},{v.row}")));
    ClrObject current = start;
    if (visited.Count > 0)
    {
        var (col, row) = visited[^1];
        current = grid.GetObjectValue(new[] { col, row });
    }
    Console.WriteLine($"current null={current.IsNull} type={current.Type?.Name}");
    if (current.IsNull) return 0;
    ClrValueType cc = current.ReadValueTypeField("coord");
    Console.WriteLine($"current coord={cc.ReadField<int>("col")},{cc.ReadField<int>("row")} pointType={ReadInt(current, "<PointType>k__BackingField")}");
    foreach (ClrObject child in ReadHashSet(ReadObj(current, "<Children>k__BackingField")))
    {
        ClrValueType ch = child.ReadValueTypeField("coord");
        Console.WriteLine($"child {ch.ReadField<int>("col")},{ch.ReadField<int>("row")} type={ReadInt(child, "<PointType>k__BackingField")}");
    }
    int nodeCount = 0, edgeCount = 0;
    for (int c = 0; c < grid.GetLength(0); c++)
    {
        for (int r = 0; r < grid.GetLength(1); r++)
        {
            ClrObject p = grid.GetObjectValue(new[] { c, r });
            if (p.IsNull) continue;
            nodeCount++;
            edgeCount += ReadHashSet(ReadObj(p, "<Children>k__BackingField")).Count;
        }
    }
    Console.WriteLine($"grid nodes={nodeCount} edges={edgeCount}");
    ClrObject boss = ReadObj(map, "<BossMapPoint>k__BackingField");
    if (!boss.IsNull)
    {
        ClrValueType bc = boss.ReadValueTypeField("coord");
        Console.WriteLine($"boss coord={bc.ReadField<int>("col")},{bc.ReadField<int>("row")} type={ReadInt(boss, "<PointType>k__BackingField")}");
    }
    return 0;
}

if (args.Length >= 2 && args[0] == "run")
{
    int pid = int.Parse(args[1]);
    using DataTarget target = DataTarget.AttachToProcess(pid, false);
    ClrRuntime runtime = CreateRuntime(target);
    ClrAppDomain domain = runtime.AppDomains.Length > 0 ? runtime.AppDomains[0] : runtime.SharedDomain;
    ClrModule? module = FindGameModule(runtime);
    if (module == null)
    {
        Console.WriteLine("sts2.dll not found");
        return 2;
    }

    ClrType? runManagerType = module.GetTypeByName("MegaCrit.Sts2.Core.Runs.RunManager");
    ClrStaticField? instanceField = runManagerType?.StaticFields.FirstOrDefault(f => f.Name.Contains("Instance"));
    if (instanceField == null)
    {
        Console.WriteLine("RunManager.Instance not found");
        return 3;
    }

    ClrObject runManager = instanceField.ReadObject(domain);
    ClrObject state = ReadObj(runManager, "<State>k__BackingField");
    if (state.IsNull)
    {
        Console.WriteLine("NO_RUN");
        return 0;
    }

    ClrObject rng = ReadObj(state, "<Rng>k__BackingField");
    string seed = ReadStr(rng, "<StringSeed>k__BackingField") ?? "";

    Console.WriteLine($"RUN seed={seed} act={ReadInt(state, "_currentActIndex") + 1} floor={ReadInt(state, "<ActFloor>k__BackingField")} asc={ReadInt(state, "<AscensionLevel>k__BackingField")}");

    List<ClrObject> players = ReadList(ReadObj(state, "_players"));
    foreach (ClrObject player in players)
    {
        ClrObject creature = ReadObj(player, "<Creature>k__BackingField");
        ClrObject character = ReadObj(player, "<Character>k__BackingField");
        ClrObject pcs = ReadObj(player, "<PlayerCombatState>k__BackingField");
        ClrObject deck = ReadObj(player, "<Deck>k__BackingField");

        Console.WriteLine($"PLAYER character={Entry(character)} hp={ReadInt(creature, "_currentHp")}/{ReadInt(creature, "_maxHp")} block={ReadInt(creature, "_block")} gold={ReadInt(player, "_gold")} deck={Count(deck)}");
        foreach (ClrObject power in ReadList(ReadObj(creature, "_powers")))
        {
            Console.WriteLine($"  PLAYER_POWER {power.Type?.Name.Split('.').Last()} amount={ReadInt(power, "_amount")}");
        }

        List<ClrObject> relics = ReadList(ReadObj(player, "_relics"));
        Console.WriteLine("RELICS " + string.Join(",", relics.Select(Entry)));
        List<ClrObject> potions = ReadList(ReadObj(player, "_potionSlots"));
        Console.WriteLine("POTIONS " + string.Join(",", potions.Where(p => !p.IsNull).Select(Entry)));

        if (!pcs.IsNull)
        {
            Console.WriteLine($"TURN number={ReadInt(pcs, "<TurnNumber>k__BackingField")} phase={ReadInt(pcs, "_phase")} energy={ReadInt(pcs, "_energy")}/{ReadInt(player, "<MaxEnergy>k__BackingField")} stars={ReadInt(pcs, "_stars")}");

            ClrObject hand = ReadObj(pcs, "<Hand>k__BackingField");
            ClrObject draw = ReadObj(pcs, "<DrawPile>k__BackingField");
            ClrObject discard = ReadObj(pcs, "<DiscardPile>k__BackingField");
            Console.WriteLine($"PILES draw={Count(draw)} discard={Count(discard)} hand={Count(hand)}");

            foreach (ClrObject card in ReadList(ReadObj(hand, "_cards")))
            {
                (int cost, bool x) = CardCost(card);
                Console.WriteLine($"CARD {Entry(card)} type={ReadInt(card, "<Type>k__BackingField")} rarity={ReadInt(card, "<Rarity>k__BackingField")} cost={(x ? "X" : cost.ToString())} up={ReadInt(card, "_currentUpgradeLevel")}");
            }

            ClrObject combat = ReadObj(creature, "<CombatState>k__BackingField");
            if (!combat.IsNull)
            {
                Console.WriteLine($"COMBAT round={ReadInt(combat, "<RoundNumber>k__BackingField")} side={ReadInt(combat, "<CurrentSide>k__BackingField")}");
                foreach (ClrObject enemy in ReadList(ReadObj(combat, "_enemies")))
                {
                    ClrObject monster = ReadObj(enemy, "<Monster>k__BackingField");
                    ClrObject nextMove = ReadObj(monster, "<NextMove>k__BackingField");
                    List<ClrObject> intents = ReadList(ReadObj(nextMove, "<Intents>k__BackingField"));
                    string intentText = string.Join("/", intents.Select(i => i.Type?.Name.Split('.').Last() ?? "?"));
                    Console.WriteLine($"ENEMY {Entry(monster)} hp={ReadInt(enemy, "_currentHp")}/{ReadInt(enemy, "_maxHp")} block={ReadInt(enemy, "_block")} intents={intentText}");
                    foreach (ClrObject power in ReadList(ReadObj(enemy, "_powers")))
                    {
                        Console.WriteLine($"  ENEMY_POWER {power.Type?.Name.Split('.').Last()} amount={ReadInt(power, "_amount")}");
                    }

                    foreach (ClrObject intent in intents)
                    {
                        ClrObject damageCalc = ReadObj(intent, "<DamageCalc>k__BackingField");
                        if (damageCalc.IsNull)
                        {
                            continue;
                        }

                        ClrDelegate del = damageCalc.AsDelegate();
                        ClrDelegateTarget delegateTarget = del.GetDelegateTarget();
                        ClrObject targetObject = delegateTarget.TargetObject;
                        Console.WriteLine($"  INTENT {intent.Type?.Name.Split('.').Last()} repeat={ReadInt(intent, "_repeat")} targetNull={targetObject.IsNull} targetType={targetObject.Type?.Name}");
                        if (!targetObject.IsNull && targetObject.Type != null)
                        {
                            foreach (ClrInstanceField field in targetObject.Type.Fields)
                            {
                                string value;
                                try
                                {
                                    value = targetObject.ReadField<int>(field.Name).ToString();
                                }
                                catch
                                {
                                    value = "?";
                                }

                                Console.WriteLine($"    {field.Name}={value}");
                            }
                        }
                    }
                }
            }
        }
    }

    return 0;
}

Console.WriteLine("usage: clrdprobe reflect | fields <pid> <type> | run <pid>");
return 1;

static ClrRuntime CreateRuntime(DataTarget target)
{
    ClrInfo info = target.ClrVersions.OrderByDescending(v => v.Version).First();
    string dataDir = @"D:\steam\steamapps\common\Slay the Spire 2\data_sts2_windows_x86_64";
    string? dac = Directory.Exists(dataDir)
        ? Directory.EnumerateFiles(dataDir, "mscordaccore_amd64_amd64_*.dll").FirstOrDefault()
          ?? Directory.EnumerateFiles(dataDir, "mscordaccore.dll").FirstOrDefault()
        : null;

    return dac != null ? info.CreateRuntime(dac, true) : info.CreateRuntime();
}

static ClrModule? FindGameModule(ClrRuntime runtime)
{
    return runtime.EnumerateModules()
        .FirstOrDefault(m => m.Name.EndsWith("sts2.dll", StringComparison.OrdinalIgnoreCase));
}

static ClrObject ReadObj(ClrObject obj, string field)
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

static string? ReadStr(ClrObject obj, string field)
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

static int ReadInt(ClrObject obj, string field)
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

static string? Entry(ClrObject model)
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

static List<ClrObject> ReadList(ClrObject obj)
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

static int Count(ClrObject pile)
{
    return pile.IsNull ? 0 : ReadList(ReadObj(pile, "_cards")).Count;
}

static IEnumerable<(ClrObject key, ClrObject value)> ReadDict(ClrObject dict)
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
            ClrObject key = entry.ReadObjectField("key");
            ClrObject value = entry.ReadObjectField("value");
            result.Add((key, value));
        }
    }
    catch (Exception ex)
    {
        Console.WriteLine("ReadDict failed: " + ex.Message);
    }

    return result;
}

static (int cost, bool x) CardCost(ClrObject card)
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

static decimal Dec(ClrValueType v)
{
    int flags = v.ReadField<int>("_flags");
    ulong lo64 = v.ReadField<ulong>("_lo64");
    uint hi32 = v.ReadField<uint>("_hi32");
    int lo = (int)(lo64 & 0xFFFFFFFFUL);
    int mid = (int)(lo64 >> 32);
    bool neg = (flags & int.MinValue) != 0;
    byte scale = (byte)((flags >> 16) & 0xFF);
    return new decimal(lo, mid, (int)hi32, neg, scale);
}

static void DumpReward(ClrObject reward, int depth)
{
    string pad = new string(' ', depth * 2);
    string type = reward.Type?.Name.Split('.').Last() ?? "?";
    Console.WriteLine($"{pad}REWARD {type}");
    if (type == "LinkedRewardSet")
    {
        foreach (ClrObject child in ReadList(ReadObj(reward, "_rewards")))
        {
            DumpReward(child, depth + 1);
        }
        return;
    }

    if (type == "CardReward")
    {
        List<ClrObject> cards = ReadList(ReadObj(reward, "_cards"));
        Console.WriteLine($"{pad}  cards={cards.Count}");
        foreach (ClrObject result in cards)
        {
            ClrObject card = ReadObj(result, "_modifiedCard");
            if (card.IsNull)
            {
                card = ReadObj(result, "originalCard");
            }

            (int cost, bool x) = CardCost(card);
            Console.WriteLine($"{pad}  CHOICE {Entry(card)} cost={(x ? "X" : cost.ToString())} up={ReadInt(card, "_currentUpgradeLevel")}");
        }
        return;
    }

    if (type == "GoldReward")
    {
        Console.WriteLine($"{pad}  amount={ReadInt(reward, "<Amount>k__BackingField")}");
    }
}

static List<(int col, int row)> ReadCoordList(ClrObject list)
{
    var result = new List<(int, int)>();
    if (list.IsNull) return result;
    ClrObject items = ReadObj(list, "_items");
    if (items.IsNull) return result;
    ClrArray array = items.AsArray();
    int size = ReadInt(list, "_size");
    for (int i = 0; i < size && i < array.Length; i++)
    {
        ClrValueType v = array.GetStructValue(i);
        result.Add((v.ReadField<int>("col"), v.ReadField<int>("row")));
    }
    return result;
}

static List<ClrObject> ReadHashSet(ClrObject set)
{
    var result = new List<ClrObject>();
    if (set.IsNull) return result;
    ClrObject entries = ReadObj(set, "_entries");
    if (entries.IsNull) return result;
    ClrArray array = entries.AsArray();
    int count = ReadInt(set, "_count");
    for (int i = 0; i < count && i < array.Length; i++)
    {
        ClrValueType e = array.GetStructValue(i);
        ClrObject v;
        try { v = e.ReadObjectField("Value"); }
        catch { v = e.ReadObjectField("value"); }
        if (!v.IsNull) result.Add(v);
    }
    return result;
}
