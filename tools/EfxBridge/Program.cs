// EfxBridge — Phase 0 验证工具 + Phase 1 Python↔C# JSON 桥接 CLI
//
// ===== roundtrip 子命令（Phase 0）=====
//
// 验证标准（已从"与原文件逐字节相同"改为"二次往返稳定"，见 PLAN.md 第 0 阶段讨论）：
// RE-Engine-Lib 不是"保留原字节"哲学，是"解码成干净对象模型后总是重新生成字节"——
// 即使是它完全理解的字段，重建顺序也可能和原始文件不同（例：CollisionEffect 的
// efxEntryIndex[] 原文件是任意顺序，重建后按 entry 下标排序——语义等价，字节不同）。
// 因为有 REFramework/TDB 反射作支撑，这套解码是成体系的、可信的，不是瞎猜字节布局；
// 所以我们不再要求"和原文件一样"，转而验证一个更贴合编辑器场景的属性：
//
//   原文件 --Read--> A --Write--> bytes1 --Read--> B --Write--> bytes2
//   PASS ⟺ bytes1 == bytes2
//
// 也就是"读它刚写出来的东西，再写一遍，得到完全一样的结果"（二次往返不动点）。
// 这才是编辑器真正需要的安全性：用户打开、不管编不编辑、每次保存都应该是当前内存状态的
// 确定性函数，不会无编辑却一存再存越漂越远。bytes1 是否等于原始字节仅作为参考信息统计，
// 不再是 PASS/FAIL 判据。
//
// 用法：
//   dotnet <dll> roundtrip <目录或单个文件路径> [--verbose] [--dump <输出目录>]
//
// --dump <dir>：不稳定（bytes1 != bytes2）时，把 original / bytes1 / bytes2 三份都写到
// <dir>/<文件名>.{orig,pass1,pass2}，供 hexdump/010 Editor 对比（诊断用）。
//
// ===== dump / load 子命令（Phase 1，Python↔C# 交换协议）=====
//
// RE-Engine-Lib 自带 EfxJsonTypeResolver（见 REE-Lib/OtherFiles/EfxFile.cs），用
// System.Text.Json 的多态序列化（$type 判别字段 + GetTypeInfo 反射注册全部 ~150 个
// EFXAttribute 子类）实现了通用 JSON 往返，不需要在这一层手工枚举每个 attribute 类型。
// dump/load 只是薄封装：
//
//   dump <efx 文件路径> <json 输出路径>   —— 读 .efx，序列化整个 EfxFile 对象图为 JSON
//   load <json 文件路径> <efx 输出路径>   —— 反序列化 JSON 为 EfxFile，写回 .efx
//
// 中间表示是"整个 EfxFile 对象图"的直译 JSON（字段名、结构均来自 C# 类本身），
// 不是为 Blender UI 设计过的精简 schema——Python 侧后续按需再从这份 JSON 里挑字段
// 映射到 PropertyGroup。这一层只负责"批处理、文件进文件出"的桥接，不做语义裁剪。
//
// 曾经发现并绕过过三个坑（EFXExpressionParameter.{Float2,Color,Range} 三个"标签联合视图"
// 属性互相 throw、EFXEntryBase.TypeAttribute 只读计算属性配 Populate 创建模式时处理不了
// null、EfxFile.parentFile 内嵌 efxrData 反向指针形成序列化环），2026-07-04 vendor 升级
// （`ebb1bc7`，"Fix efx json serialization for expressions, embedded efx"）后全部由 vendor
// 自己解决（前两个分别用自定义 JsonConverter 和 [JsonIgnore] 处理，parentFile 也直接标了
// [JsonIgnore]），这层 TypeInfoResolver 包装不再需要，直接用 vendor 自带的
// `EfxJsonTypeResolver.jsonOptions` 即可（历史包袱记录见 git blame，不在这里堆讲解）。
//
// 编译需要 -p:LangVersion=preview（vendor 用了 C# 13 的 field 关键字）：
//   dotnet build tools/EfxBridge -p:LangVersion=preview

using System.Reflection;
using System.Text.Json;
using ReeLib;
using ReeLib.Common;
using ReeLib.Efx;
using ReeLib.Efx.Structs.Basic;
using ReeLib.Efx.Structs.Common;
using ReeLib.Efx.Structs.Pt;
using ReeLib.Efx.Structs.Transforms;
using ReeLib.Uvs;

// bridge.py 用 `subprocess.run(..., encoding="utf-8")` 读这个进程的 stdout/stderr，严格按
// UTF-8 解码。但 .NET 在 stdout 被重定向成管道（而不是真终端）时，Console 的默认输出编码是
// 当前系统的 ANSI/OEM 代码页（中文 Windows 上是 GBK/936），不是 UTF-8——`Console.WriteLine`
// 里的中文字符会按 GBK 编码写出字节，Python 那边按 UTF-8 strict 解码，踩到不合法的
// UTF-8 首字节（比如某个 GBK 汉字的高位字节 0xB9）就在 subprocess 内部的 reader 线程里直接
// 抛 UnicodeDecodeError——这个线程的异常不会传播回主线程（CPython 的
// `Popen._readerthread` 没有 try/except），只是把 traceback 打印到控制台，看着像插件崩了，
// 实际上 JSON 交换走的是文件而不是 stdout，数据本身没坏，但这坨吓人的 traceback 应该消掉。
// 显式钉死 UTF-8，不依赖系统代码页，从根上避免这个编码错配。
try
{
    Console.OutputEncoding = System.Text.Encoding.UTF8;
}
catch
{
    // 极少数非交互式重定向场景可能不支持设置输出编码，不能因为这个附带功能就让整个 CLI 崩掉。
}

static JsonSerializerOptions CreateBridgeJsonOptions()
{
    var options = new JsonSerializerOptions(EfxJsonTypeResolver.jsonOptions)
    {
        // EFX 里的 float 字段会出现 Infinity/NaN（例如"无上限"语义），默认 JSON 数字语法
        // 不支持这两个字面量，需要显式放开（写成 "Infinity"/"NaN" 字符串形式的具名浮点值）。
        NumberHandling = System.Text.Json.Serialization.JsonNumberHandling.AllowNamedFloatingPointLiterals,
    };
    // 插到最前面：System.Text.Json 按 Converters 列表顺序找第一个 CanConvert 命中的，插在最前
    // 保证盖过 vendor 自带的（有 bug 的）EFXExpressionTreeJsonConverter，见
    // FixedExpressionTreeJsonConverter 的说明。
    options.Converters.Insert(0, new FixedExpressionTreeJsonConverter());
    options.Converters.Insert(0, new FloatKeepsDecimalPointConverter());
    // vendor 的 EfxJsonTypeResolver 只给 EFXAttribute / EFXExpressionDataBase /
    // PtBehaviorVariableDataBase 配了多态判别（GetTypeInfo 里按 type == 判断），没覆盖
    // EfxMaterialStructBase（V1/V2 两个子类）——实测过 dump 出来的 material 字段只剩
    // `{"Version": ...}`，V1/V2 各自的 mdfPath/properties/texPaths 等字段全部被基类声明
    // 悄悄截断丢掉（不是 load 才炸的那 3.6%，是所有带 material 字段的文件从 dump 那一步就已经
    // 丢数据，见 KNOWN_UPSTREAM_ISSUES.md #7 的补充记录）。不改 vendor 源码，改用同一个套路：
    // 包一层 IJsonTypeInfoResolver，委托给 EfxJsonTypeResolver.Instance 拿到基础 JsonTypeInfo，
    // 只在 EfxMaterialStructBase 这一个类型上补多态配置。
    options.TypeInfoResolver = new MaterialPolymorphismResolver();
    return options;
}

if (args.Length >= 1 && args[0] == "dump")
{
    return RunDump(args);
}
if (args.Length >= 1 && args[0] == "load")
{
    return RunLoad(args);
}
if (args.Length >= 1 && args[0] == "uvsdump")
{
    return RunUvsDump(args);
}
if (args.Length >= 1 && args[0] == "uvsload")
{
    return RunUvsLoad(args);
}
if (args.Length >= 1 && args[0] == "tex2dds")
{
    return RunTex2Dds(args);
}
if (args.Length >= 1 && args[0] == "mdfdump")
{
    return RunMdfDump(args);
}
if (args.Length >= 1 && args[0] == "pakextract")
{
    return RunPakExtract(args);
}
if (args.Length >= 1 && args[0] == "exprcheck")
{
    return RunExprCheck(args);
}
if (args.Length >= 1 && args[0] == "types")
{
    return RunTypes(args);
}
if (args.Length >= 1 && args[0] == "new")
{
    return RunNew(args);
}
if (args.Length >= 1 && args[0] == "fieldstats")
{
    return RunFieldStats(args);
}
if (args.Length >= 1 && args[0] == "relstats")
{
    return RunRelStats(args);
}
if (args.Length >= 1 && args[0] == "typefreq")
{
    return RunTypeFreq(args);
}
if (args.Length >= 1 && args[0] == "fieldstatsbatch")
{
    return RunFieldStatsBatch(args);
}
if (args.Length >= 1 && args[0] == "attrindex")
{
    return RunAttrIndex(args);
}
if (args.Length >= 1 && args[0] == "condstats")
{
    return RunCondStats(args);
}
if (args.Length >= 1 && args[0] == "flagsurvey")
{
    return RunFlagsSurvey(args);
}
if (args.Length >= 1 && args[0] == "ptbehaviorcatalog")
{
    return RunPtBehaviorCatalog(args);
}
if (args.Length >= 1 && args[0] == "bonealign")
{
    return RunBoneAlign(args);
}
if (args.Length >= 1 && args[0] == "pairstats")
{
    return RunPairStats(args);
}
if (args.Length >= 1 && args[0] == "exprvarstats")
{
    return RunExprVarStats(args);
}
if (args.Length >= 1 && args[0] == "bitnames")
{
    return RunBitNames(args);
}
if (args.Length >= 1 && args[0] == "exprassignstats")
{
    return RunExprAssignStats(args);
}
if (args.Length >= 1 && args[0] == "exprrotationstats")
{
    return RunExprRotationStats(args);
}
if (args.Length >= 1 && args[0] == "exprhostcorr")
{
    return RunExprHostCorr(args);
}
if (args.Length >= 1 && args[0] == "instancedefaults")
{
    return RunInstanceDefaults(args);
}
if (args.Length >= 1 && args[0] == "clipinterpstats")
{
    return RunClipInterpStats(args);
}
if (args.Length >= 1 && args[0] == "clipeventstats")
{
    return RunClipEventStats(args);
}
if (args.Length >= 1 && args[0] == "spawnringbuffer")
{
    return RunSpawnRingBuffer(args);
}
if (args.Length >= 1 && args[0] == "rootstats")
{
    return RunRootStats(args);
}

if (args.Length < 2 || args[0] != "roundtrip")
{
    Console.WriteLine("用法:");
    Console.WriteLine("  dotnet <dll> roundtrip <目录或文件路径> [--verbose] [--dump <输出目录>]");
    Console.WriteLine("  dotnet <dll> dump <efx 文件路径> <json 输出路径>");
    Console.WriteLine("  dotnet <dll> load <json 文件路径> <efx 输出路径>");
    Console.WriteLine("  dotnet <dll> uvsdump <uvs 文件路径> <json 输出路径>");
    Console.WriteLine("  dotnet <dll> uvsload <json 文件路径> <uvs 输出路径>");
    Console.WriteLine("  dotnet <dll> tex2dds <tex 文件路径> <dds 输出路径>");
    Console.WriteLine("  dotnet <dll> exprcheck <公式文本>");
    Console.WriteLine("  dotnet <dll> types <json 输出路径> [游戏版本，默认 MHWilds]");
    Console.WriteLine("  dotnet <dll> new attribute <类型名> <json 输出路径> [游戏版本，默认 MHWilds]");
    Console.WriteLine("  dotnet <dll> new entry|action <json 输出路径> [游戏版本，默认 MHWilds]");
    Console.WriteLine("  dotnet <dll> fieldstats <语料目录> <attribute 类型名> <json 输出路径> [每字段保留的不同取值数，默认 40]");
    Console.WriteLine("  dotnet <dll> relstats <语料目录> <json 输出路径>");
    Console.WriteLine("  dotnet <dll> typefreq <语料目录> <json 输出路径>");
    Console.WriteLine("  dotnet <dll> fieldstatsbatch <语料目录> <逗号分隔的类型名列表> <json 输出路径> [每字段保留的不同取值数，默认 40]");
    Console.WriteLine("  dotnet <dll> condstats <语料目录> <attribute 类型名> <条件字段名> <json 输出路径> [每字段保留的不同取值数，默认 40]");
    Console.WriteLine("  dotnet <dll> flagsurvey <语料目录> <json 输出路径> [每字段保留的不同取值数，默认 40]");
    Console.WriteLine("  dotnet <dll> ptbehaviorcatalog <语料目录> <json 输出路径>");
    Console.WriteLine("  dotnet <dll> bonealign <语料目录> <json 输出路径> [--extra 类型名,类型名]");
    Console.WriteLine("  dotnet <dll> pairstats <语料目录> <json 输出路径> [每字段保留的高频组合数，默认 20]");
    Console.WriteLine("  dotnet <dll> exprvarstats <语料目录> <json 输出路径> [每个哈希保留的示例条数，默认 5]");
    Console.WriteLine("  dotnet <dll> bitnames <json 输出路径> [游戏版本，默认 MHWilds]");
    Console.WriteLine("  dotnet <dll> exprassignstats <语料目录> <json 输出路径>");
    Console.WriteLine("  dotnet <dll> exprrotationstats <语料目录> <json 输出路径>");
    Console.WriteLine("  dotnet <dll> exprhostcorr <语料目录> <json 输出路径> [每桶保留的不同取值数，默认 10]");
    Console.WriteLine("  dotnet <dll> instancedefaults <语料目录> <逗号分隔的类型名列表|all> <json 输出路径>");
    Console.WriteLine("  dotnet <dll> spawnringbuffer <语料目录> <json 输出路径> [每桶保留的不同取值数，默认 30]");
    return 1;
}

var target = args[1];
var verbose = args.Contains("--verbose");
var dumpIdx = Array.IndexOf(args, "--dump");
var dumpDir = dumpIdx >= 0 && dumpIdx + 1 < args.Length ? args[dumpIdx + 1] : null;
if (dumpDir != null) Directory.CreateDirectory(dumpDir);

List<string> files;
if (Directory.Exists(target))
{
    // MHWs 的 .efx 文件扩展名带版本号后缀，如 xxx.efx.5571972
    files = Directory.EnumerateFiles(target, "*.efx.*", SearchOption.AllDirectories).ToList();
}
else if (File.Exists(target))
{
    files = new List<string> { target };
}
else
{
    Console.WriteLine($"路径不存在: {target}");
    return 1;
}

Console.WriteLine($"共 {files.Count} 个文件待测。\n");

int stable = 0, unstable = 0, errored = 0;
int exactOriginalMatch = 0; // stable 里同时还与原文件逐字节相同的数量，仅供参考
var unstableFiles = new List<string>();
var erroredFiles = new List<(string file, string error)>();

foreach (var path in files)
{
    byte[] original;
    try
    {
        original = File.ReadAllBytes(path);
    }
    catch (Exception ex)
    {
        errored++;
        erroredFiles.Add((path, $"读取原文件失败: {ex.Message}"));
        continue;
    }

    try
    {
        var bytes1 = ReadThenWrite(original, path);
        var bytes2 = ReadThenWrite(bytes1, path);

        if (bytes1.AsSpan().SequenceEqual(bytes2))
        {
            stable++;
            if (original.AsSpan().SequenceEqual(bytes1)) exactOriginalMatch++;
            if (verbose) Console.WriteLine($"[STABLE] {path}");
        }
        else
        {
            unstable++;
            unstableFiles.Add(path);
            var (offset, lenA, lenB) = FirstDiff(bytes1, bytes2);
            Console.WriteLine($"[UNSTABLE] {path}");
            Console.WriteLine($"       第一次写出长度={lenA} 第二次写出长度={lenB} 首个差异偏移={offset}");
            if (dumpDir != null)
            {
                var baseName = Path.GetFileName(path);
                File.WriteAllBytes(Path.Combine(dumpDir, baseName + ".orig"), original);
                File.WriteAllBytes(Path.Combine(dumpDir, baseName + ".pass1"), bytes1);
                File.WriteAllBytes(Path.Combine(dumpDir, baseName + ".pass2"), bytes2);
            }
        }
    }
    catch (Exception ex)
    {
        errored++;
        erroredFiles.Add((path, ex.ToString()));
        Console.WriteLine($"[ERROR] {path}");
        if (verbose) Console.WriteLine($"        {ex}");
    }
}

Console.WriteLine();
Console.WriteLine($"===== 汇总 =====");
Console.WriteLine($"稳定（bytes1==bytes2） : {stable}");
Console.WriteLine($"  其中与原文件逐字节相同 : {exactOriginalMatch}（仅供参考，不是判据）");
Console.WriteLine($"不稳定                 : {unstable}");
Console.WriteLine($"异常                   : {errored}");
Console.WriteLine($"总计                   : {files.Count}");

if (unstable > 0)
{
    Console.WriteLine("\n不稳定文件列表:");
    foreach (var f in unstableFiles) Console.WriteLine($"  {f}");
}
if (errored > 0)
{
    Console.WriteLine("\n异常类型分布（按异常信息首行归类，数字归一化）:");
    var grouped = erroredFiles
        .Select(x => System.Text.RegularExpressions.Regex.Replace(x.error.Split('\n')[0], @"\d+", "#"))
        .GroupBy(x => x)
        .OrderByDescending(g => g.Count());
    foreach (var g in grouped)
        Console.WriteLine($"  {g.Count(),5}  {g.Key}");

    Console.WriteLine("\n异常文件列表（全部）:");
    foreach (var (f, e) in erroredFiles)
        Console.WriteLine($"  {f}\n    -> {e.Split('\n')[0]}");
}

return unstable == 0 && errored == 0 ? 0 : 1;

static byte[] ReadThenWrite(byte[] input, string originalPathForContext)
{
    using var readStream = new MemoryStream(input, writable: false);
    var readHandler = new FileHandler(readStream, originalPathForContext);
    var efx = new EfxFile(readHandler);
    efx.Read();

    using var writeStream = new MemoryStream();
    using var writeHandler = new FileHandler(writeStream);
    efx.WriteTo(writeHandler);
    return writeStream.ToArray();
}

static (int offset, int lenA, int lenB) FirstDiff(byte[] a, byte[] b)
{
    int n = Math.Min(a.Length, b.Length);
    for (int i = 0; i < n; i++)
    {
        if (a[i] != b[i]) return (i, a.Length, b.Length);
    }
    return (n, a.Length, b.Length); // 长度不同但公共前缀完全一致
}

static int RunDump(string[] args)
{
    if (args.Length < 3)
    {
        Console.WriteLine("用法: dotnet <dll> dump <efx 文件路径> <json 输出路径>");
        return 1;
    }
    var efxPath = args[1];
    var jsonOutPath = args[2];

    try
    {
        var handler = new FileHandler(efxPath);
        var efx = new EfxFile(handler);
        efx.Read();
        // Expression/MaterialExpressions 的 parsedExpressions 默认是 null（vendor 只在显式调用
        // ParseExpressions() 时才反向重建成人类可读的公式字符串+参数列表），不主动调用的话
        // dump 出来的 JSON 里公式内容永远拿不到，Blender 侧没法展示/编辑。
        efx.ParseExpressions();

        var json = JsonSerializer.Serialize(efx, CreateBridgeJsonOptions());
        File.WriteAllText(jsonOutPath, json);
        Console.WriteLine($"OK: {efxPath} -> {jsonOutPath}");
        return 0;
    }
    catch (Exception ex)
    {
        Console.WriteLine($"[ERROR] {efxPath}");
        Console.WriteLine(ex.ToString());
        return 1;
    }
}

static int RunLoad(string[] args)
{
    if (args.Length < 3)
    {
        Console.WriteLine("用法: dotnet <dll> load <json 文件路径> <efx 输出路径>");
        return 1;
    }
    var jsonPath = args[1];
    var efxOutPath = args[2];

    try
    {
        var json = File.ReadAllText(jsonPath);
        var efx = JsonSerializer.Deserialize<EfxFile>(json, CreateBridgeJsonOptions())
            ?? throw new Exception("反序列化结果为 null");

        FixJsonRoundtripGaps(efx);

        // Python 侧只写 Expression.parsedExpressions（人类可读的公式字符串——反序列化时已经
        // 由 vendor 的 EFXExpressionTreeJsonConverter 调用 EfxExpressionStringParser.Parse()
        // 编译成树了），不写 expressions（真正参与二进制写出的扁平后缀栈）。这里补一步把树
        // 摊平回 expressions，镜像 EfxFile.ParseExpressions() 自己的遍历方式（Entries + 递归
        // Actions/efxrData）。IExpressionAttribute 和 IMaterialExpressionAttribute 都处理
        // （后者只有 Python 端 model.MATERIAL_EXPRESSION_VERIFIED_TYPES 里那两个类型才会有
        // 非空的 parsedExpressions，其余实现类维持原样透传，这里的分支对它们是空操作）。
        CompileExpressions(efx);

        // Subselect（EffectGroups）组内成员：`UpdateEffectGroups()`（EfxFile.cs:1312，vendor
        // 代码，不改）写出时无条件按 Entry 扫描顺序（ascending）重新生成每个组的 efxEntryIndexes，
        // 不管传进来的原始顺序是什么——见 PLAN.md E2；同名组还会被合并成一个、其余清空
        // （KNOWN_UPSTREAM_ISSUES.md #13）。数组级顺序（EffectGroups 本身谁在前谁在后）已经靠
        // "不传空数组"绕开了，组内内容只能 Write() 之前按位置算好，写完之后整段改回去（见
        // PlanEffectGroups() / ApplyEffectGroupPlan()）。
        var groupPlan = PlanEffectGroups(efx);

        efx.WriteTo(efxOutPath);
        ApplyEffectGroupPlan(efxOutPath, efx, groupPlan);

        Console.WriteLine($"OK: {jsonPath} -> {efxOutPath}");
        return 0;
    }
    catch (Exception ex)
    {
        Console.WriteLine($"[ERROR] {jsonPath}");
        Console.WriteLine(ex.ToString());
        return 1;
    }
}

// Write() 之前算出每个**原有**组（按位置，不按名字——同名组在语料里真实存在，见
// KNOWN_UPSTREAM_ISSUES.md #13）写出后该有的成员列表：
//   - 原列表里、当前仍打着这个组标签的 entry，保持原相对顺序（包括原有的重复下标）；
//   - 当前打了标签、但同名的哪一份原列表里都没有的 entry（新加入的），按升序追加到同名的
//     第一份末尾——对应"新增在尾部追加"；
//   - 标签全被去掉的组留空（跟 vendor 一致，保留位置）。
// 同时把每个 entry 的 Groups 规整成"这个名字在各份目标列表里一共出现几次，就重复几次"
// （原本没有对应组的新名字去重成 1 次）。Groups 只被 UpdateEffectGroups() 拿来建表、不单独
// 写进文件，这样规整之后 vendor 写出的 EffectGroups 段总长度恰好等于目标布局的总长度，
// ApplyEffectGroupPlan() 才能原地整段改写而不挪动后面的任何字节。
static List<int[]> PlanEffectGroups(EfxFile efx)
{
    var members = new Dictionary<string, HashSet<int>>();
    for (int i = 0; i < efx.Entries.Count; i++)
    {
        foreach (var name in efx.Entries[i].Groups)
        {
            if (!members.TryGetValue(name, out var set)) members[name] = set = new HashSet<int>();
            set.Add(i);
        }
    }

    var plan = efx.EffectGroups.Select(g =>
    {
        var current = members.TryGetValue(g.groupName, out var set) ? set : new HashSet<int>();
        return (g.efxEntryIndexes ?? Array.Empty<int>()).Where(current.Contains).ToArray();
    }).ToList();

    foreach (var byName in efx.EffectGroups.Select((g, k) => (g.groupName, k)).GroupBy(x => x.groupName))
    {
        if (!members.TryGetValue(byName.Key, out var current)) continue;
        var covered = new HashSet<int>(byName.SelectMany(x => plan[x.k]));
        var first = byName.First().k;
        plan[first] = plan[first].Concat(current.Where(i => !covered.Contains(i)).OrderBy(i => i)).ToArray();
    }

    var occurrences = new Dictionary<(string, int), int>();
    for (int k = 0; k < plan.Count; k++)
    {
        foreach (var i in plan[k])
        {
            var key = (efx.EffectGroups[k].groupName, i);
            occurrences[key] = occurrences.GetValueOrDefault(key) + 1;
        }
    }
    var knownNames = new HashSet<string>(efx.EffectGroups.Select(g => g.groupName));
    for (int i = 0; i < efx.Entries.Count; i++)
    {
        var groups = efx.Entries[i].Groups;
        var normalized = groups.Distinct()
            .SelectMany(name => Enumerable.Repeat(name, knownNames.Contains(name) ? occurrences[(name, i)] : 1))
            .ToList();
        groups.Clear();
        groups.AddRange(normalized);
    }
    return plan;
}

// 按 PlanEffectGroups() 的结果整段改写原有组的二进制。定位靠 `EffectGroup.Start`（BaseModel
// 公开属性，Write() 时记的这个对象在流里的起始位置，见 Models.cs），不是靠猜整个文件的偏移
// 布局：一个 EffectGroup 的二进制布局固定是 hash16(4B) + hash8(4B) + valueCount(4B) +
// efxEntryIndexes(valueCount * 4B)，见 EfxFile.cs 的字段声明顺序，各组首尾相接
// （EffectGroups.Write() 连续写出）。UpdateEffectGroups() 新造的组排在原有组后面，本来就是
// vendor 刚生成的内容，不动。
static void ApplyEffectGroupPlan(string path, EfxFile efx, List<int[]> plan)
{
    if (plan.Count == 0) return;
    var bytes = File.ReadAllBytes(path);
    var start = (int)efx.EffectGroups[0].Start;
    var end = plan.Count < efx.EffectGroups.Count
        ? (int)efx.EffectGroups[plan.Count].Start
        : start + efx.Header.effectGroupsLength;

    using var rebuilt = new MemoryStream();
    using (var writer = new BinaryWriter(rebuilt, System.Text.Encoding.UTF8, leaveOpen: true))
    {
        for (int k = 0; k < plan.Count; k++)
        {
            writer.Write(bytes, (int)efx.EffectGroups[k].Start, 8); // 两个名字哈希原样照抄
            writer.Write(plan[k].Length);
            foreach (var index in plan[k]) writer.Write(index);
        }
    }
    // 长度对不上说明 Groups 规整没生效（vendor 改了 UpdateEffectGroups 的算法之类），原地改写
    // 会把后面的字节覆盖掉——宁可报错拒绝导出，也不写一个错位的文件（铁律 #1）。
    if (rebuilt.Length != end - start)
    {
        throw new Exception(
            $"EffectGroups 段长度对不上（vendor 写出 {end - start} 字节，按原组重建 {rebuilt.Length} 字节），" +
            "拒绝写出，免得覆盖后面的数据。");
    }
    rebuilt.ToArray().CopyTo(bytes, start);
    File.WriteAllBytes(path, bytes);
}

// `EfxMaterialClipData.Version`（`[RszIgnore] public EfxVersion Version;`）在 System.Text.Json
// 往返中永远丢失、恒定停在默认值 0——这个字段只在二进制 Read() 的对象图构造顺序里由
// `RszConstructorParams(nameof(Version))` 正确赋值（外层 attr.Version 早于 clipData 字段初始化
// 前已经就位），JSON 反序列化走的是无参默认构造函数 + Populate 就地填充，没有任何一步会把
// 外层 attr.Version 传给这个已经造好的 clipData 实例，也没有 JSON 键能覆盖它——它是
// `[RszIgnore]`，压根不参与 JSON 序列化（实测：手工在 JSON 里塞一个正确的 "Version" 值，
// 反序列化结果的字节长度分毫不变，证明这个键从未被读取）。`EfxMaterialClipData.DoWrite()`
// 用这个字段判断走新格式（Version>=RE4 时多写 mdfPropertyCount/mdfProperties，
// >=RE3 时多写 indicesCount/indices）还是旧格式，字段停在 0 就会漏写这四个字段，产物比
// `expectedSize` 短一截，下次读回直接错位（"Expected: 44 Actual: 100" 这类症状）。
//
// KNOWN_UPSTREAM_ISSUES.md #8 把这 9 个 `IMaterialClipAttribute` 实现类的这个症状归因于
// "MaterialClip => clipData 只读别名 + Populate 重复填充"——这个归因是没有反例复现验证过的
// 猜测（铁律 #7 提醒过的那种），实测证伪：一个全新创建、除 clipData.Version 外别无二致的
// 空 attribute（列表全空，没有任何"重复填充"能填的内容）单独往返就已经必现同一症状，
// 猜测的机制作废，真正根因是这个版本号丢失。9 个实现类全部受影响（不止已确认的 5 个），
// `new_attribute`（走 InitBlankClipData）和 `load`（走这里）两条路径都要补。
//
// 同一批症状里另外 5 个 `IMaterialExpressionAttribute` 实现类是完全不同的根因，别用上面这套
// 解释类比过去：源生成器给可空 `[RszClassInstance]` 字段生成的 Read/Write 本身就不对称
// （`ReeLibGenerator.cs`，实测导出 `--EmitCompilerGeneratedFiles` 拿到的
// `*_EFXAttributeTypeBillboard3DMaterialExpression.rsz.cs` 逐字确认）——
// `materialExpressions ??= new(Version); materialExpressions.Read(handler);` 无条件读，
// 但 `materialExpressions?.Write(handler);` 是空条件写：字段为 null 时 Write 完全不写
// 任何字节，Read 却始终认为这里有数据要读，直接把后面属于别的字段/下一个 attribute 的字节
// 当成这个容器的内容消费掉。`materialExpressions` 恰好没有任何一条路径会主动构造它
// （Python 只给 IExpressionAttribute 专属的 `expressions`/`expressionBits` 建了真实对象，
// `materialExpressions` 原样透传 raw dump 里的 null），所以每一个新建/透传的
// `IMaterialExpressionAttribute` 实例都会踩上。跟 #2 版本号丢失那个 bug 判据一致
// （空 attribute 单独往返即可稳定复现），但机制、受影响字段、影响范围都不同，分开记。
// 这是源生成器级别的缺陷，理论上任何"可空 RszClassInstance 字段"都可能中招，但目前
// 只在这一个字段上验证过，不铺开断言（铁律 #7）；绕不开生成器本身，就地在这两条入口把
// null 的 MaterialExpressions 换成一个空容器，效果等价于"一条公式都没有"，构造参数走
// 正确的 Version，同时避免 #2 那个版本号丢失坑。
//
// 用反射按属性名+类型找，不按 IMaterialExpressionAttribute 接口找：
// `EFXAttributeTypeRibbonParticleMaterialExpression` 结构上和其它 5 个一模一样（同名
// `MaterialExpressions` 属性、同一个只读别名写法），但类声明上只写了 `IExpressionAttribute`，
// 没有声明 `IMaterialExpressionAttribute`——接口列表本身在 vendor 里就是不完整的（漏声明，
// 不是没有这个字段），按接口找会漏掉它，已用真实复现确认（同样的 [bytes==sizeof(T)]
// 崩溃）。这是 vendor 自己遗漏了接口声明，不是我们瞎猜的模式扩大化。
static void FixNullMaterialExpressions(EFXAttribute attr)
{
    var prop = attr.GetType().GetProperty("MaterialExpressions");
    if (prop == null || prop.PropertyType != typeof(EFXMaterialExpressionList) || !prop.CanRead || !prop.CanWrite)
    {
        return;
    }
    if (prop.GetValue(attr) == null)
    {
        prop.SetValue(attr, new EFXMaterialExpressionList(attr.Version));
    }
}

static void FixJsonRoundtripGaps(EfxFile file)
{
    void Visit(EFXEntryBase entry)
    {
        foreach (var attr in entry.Attributes)
        {
            if (attr is IMaterialClipAttribute matClip)
            {
                matClip.MaterialClip.Version = attr.Version;
            }
            FixNullMaterialExpressions(attr);
            if (attr is EFXAttributePlayEmitter { efxrData: not null } pe)
            {
                FixJsonRoundtripGaps(pe.efxrData);
            }
        }
    }
    foreach (var entry in file.Entries) Visit(entry);
    foreach (var action in file.Actions) Visit(action);
}

static void CompileExpressions(EfxFile file)
{
    foreach (var entry in file.Entries)
    {
        foreach (var attr in entry.Attributes)
        {
            if (attr is IExpressionAttribute expr && expr.Expression != null)
            {
                expr.Expression.expressions.Clear();
                // 不直接调用 EfxFile.FlattenExpressionTrees()——它内部用 `new
                // EFXExpressionObject()`（无参构造函数）造新对象，Version 留在默认值，而
                // EFXExpressionObject 是 [RszVersionedObject]（`struct3Count` 字段只在
                // Version > DD2 时才写/读），Version 不对会导致写出的字节和这个文件真实版本号
                // 要求的字段布局对不上，读回来直接在别处崩溃（EFXExpressionData 的多态判别
                // 字段错位，报 NotImplementedException）。改成自己逐个 tree 摊平，手动补上
                // 正确的 Version（照抄 EfxFile.cs 里 `param.Version = Header.Version` 那种
                // 现成写法）。
                foreach (var tree in expr.Expression.ParsedExpressions ?? new())
                {
                    // EfxExpressionStringParser.Parse() 解析裸标识符（不带 p:/ext:/const: 前缀）
                    // 时，StoreNewParameters() 一律先打上 source=External，只有调用方传进来的
                    // parameters 参数里有同 hash 的条目才会在 Parse() 末尾被换回正确 source——
                    // 我们的 parsedExpressions 只存公式文本，不预先提供这份 parameters
                    // 上下文（同一个 hash 具体是 Parameter 引用还是真的 External，只有查
                    // ExpressionParameters 表才知道，没必要在 Python 端重新实现一遍标识符
                    // 提取）。而 FlattenExpression() 的 ParameterHash 分支只在 tree.parameters
                    // 里"还没有这个 hash"时才会去查 FindParameterByHash 补 source——Parse()
                    // 已经把每个 hash 都加进去了（哪怕 source 是错的 External），所以这个补救
                    // 分支永远不会触发。这里在摊平之前先手动跑一遍同样的查表校正，效果等价于
                    // 一开始就传对 parameters，但不用在 Python 端重复解析公式文本。
                    for (int i = 0; i < tree.parameters.Count; i++)
                    {
                        var p = tree.parameters[i];
                        if (p.source != ExpressionParameterSource.Parameter && file.FindParameterByHash(p.parameterNameHash) != null)
                        {
                            p.source = ExpressionParameterSource.Parameter;
                            tree.parameters[i] = p;
                        }
                    }
                    var flat = file.FlattenExpressionTree(tree);
                    flat.Version = file.Header!.Version;
                    expr.Expression.AddExpression(flat);
                }
            }

            // IMaterialExpressionAttribute：同一套 EFXExpressionObject 树，但每条
            // EFXMaterialExpression 额外带 4 个结构字段（mdfPropertyHash/propertyComponentIndex/
            // unkn1/unkn2，Python 侧 _export_material_expression_attribute() 已经原样写出）。
            // 只有语料验证过的两个类型（model.MATERIAL_EXPRESSION_VERIFIED_TYPES）会走到这里，
            // Python 端只对它们生成 parsedExpressions/expressions；其余实现类的 expressions
            // 数量本来就是 0（Python 从不碰它们），下面的循环体自然是空操作。
            //
            // 不 Clear()+AddExpression()（那样会丢 Python 已经写回的 4 个结构字段，
            // FlattenExpressionTree() 只产出裸 EFXExpressionObject，没有那些字段可填）——
            // 改成就地覆盖每条已有条目的 components/parameters/Version，其余字段保持
            // Python 写的值不动。两个数组长度不一致说明 Python 那边没能一一对应写出
            // （不该发生，v1 不支持增删条目），直接报错而不是静默错位覆盖（铁律 #1）。
            if (attr is IMaterialExpressionAttribute matExpr && matExpr.MaterialExpressions != null)
            {
                var list = matExpr.MaterialExpressions;
                var parsedList = list.ParsedExpressions ?? new();
                if (list.expressions.Count != parsedList.Count)
                {
                    throw new Exception(
                        $"MaterialExpressions 条目数不匹配（$type={attr.type}）：" +
                        $"expressions={list.expressions.Count}, parsedExpressions={parsedList.Count}");
                }
                for (int i = 0; i < parsedList.Count; i++)
                {
                    var tree = parsedList[i];
                    for (int j = 0; j < tree.parameters.Count; j++)
                    {
                        var p = tree.parameters[j];
                        if (p.source != ExpressionParameterSource.Parameter && file.FindParameterByHash(p.parameterNameHash) != null)
                        {
                            p.source = ExpressionParameterSource.Parameter;
                            tree.parameters[j] = p;
                        }
                    }
                    var flat = file.FlattenExpressionTree(tree);
                    var target = list.expressions[i];
                    target.components.Clear();
                    target.components.AddRange(flat.components);
                    target.parameters = flat.parameters;
                    target.Version = file.Header!.Version;
                }
            }
        }
    }
    foreach (var action in file.Actions)
    {
        foreach (var a in action.Attributes.OfType<EFXAttributePlayEmitter>())
        {
            if (a.efxrData == null) continue;
            // 必须先补上 parentFile 再递归：具名 Expression 参数表（ExpressionParameters）只存在
            // 于最外层文件里，内嵌的 efxrData 自己那张表是空的，`EfxFile.FindParameterByHash()`
            // 靠 `(parentFile ?? this).ExpressionParameters` 往上找（EfxFile.cs:1432）。二进制
            // 读取路径会在 DoRead()/ReadActions() 里做这件事（`a.efxrData.parentFile = this`，
            // EfxFile.cs:1190/1255），但 parentFile 是 [JsonIgnore]，走 JSON 反序列化进来时是
            // null——不补的话内嵌子树里每个 hash 都查不到，下面的 source 校正一个都不触发，
            // 公式里的具名参数引用全部退化成 source=External 写出去（bit 位翻掉、dump 回来
            // 只剩 `ext:<hash>`，具名信息丢失）。照抄读取路径的做法，指向直接父文件。
            a.efxrData.parentFile = file;
            CompileExpressions(a.efxrData);
        }
    }
}

// ===== uvsdump / uvsload 子命令（Phase 2，PLAN.md "UVS 编辑"）=====
//
// .uvs（UV 序列图集）比 .efx 简单得多——不是多态 attribute 树，是一棵固定形状的结构
// （Header/TextureBlock/SequenceBlock/UvsPattern，见 vendor OtherFiles/UvsFile.cs），
// 不需要 EfxJsonTypeResolver 那套多态注册，一个普通的 IncludeFields=true 选项就够。
//
// 版本号处理和 .efx 是同一个坑，但成因不同：.efx 的版本号存在 Header.Version 字段里（JSON
// 里看得到），RszConditional 门控查的是这个字段；.uvs 的 Header **没有**持久化 Version 字段，
// `[RszConditional("handler.FileVersion >= 7")]`（Header.attributes）直接查 handler.FileVersion
// 本身——而 FileHandler.FileVersion 是"文件名推导 + 可显式覆盖"的（见 FileHandler.cs:24-31，
// setter 是公开的）。所以 dump 时把读取用的 handler.FileVersion 另外存一个 fileVersion 字段
// 带出去，load 时显式赋回写入用的 handler.FileVersion，而不是依赖输出路径的文件名——这样
// Blender 侧不管导出对话框里填了什么文件名，字节都是确定的（同 EFX 那边"写出侧不看输出路径"
// 的效果，只是这里要靠我们主动赋值而不是内容字段驱动）。
//
// Header 的其余字段（textureCount/sequenceCount/patternCount/各种 *Offset）以及
// SequenceBlock.patternCount/patternTableOffset 全部由 `UvsFile.DoWrite()` 在写出时按当前
// Textures/Sequences/patterns 的实际内容重新计算（UvsFile.cs:145-182），JSON 里这些字段的
// 值不影响写出结果，dump 只是如实带出方便查看，load 时完全不读它们。
//
// `UvsPattern.cutoutUVCount` 是唯一的例外——DoWrite() 同样会无条件按 `cutoutUVs.Count`
// 重算它（空列表写 -1），但这个重算结果不总是我们想要的：Blender 侧（uvs_io.export_uvs_
// root()）在"这一帧显式选择不裁剪"时需要字面 `0`，DoWrite() 只会给出 -1（见 UvsFile.cs:172，
// 空列表没有产出字面 0 的路径）。所以 `RunUvsLoad()` 在 JSON 里显式带了 `cutoutUVCount` 字段
// 的 pattern 上，会在 `uvs.Write()` 完成之后再做一次二次字节 patch（`PatchZeroCutoutCounts()`），
// 把 DoWrite() 算出来的 -1 改回 0——跟 EffectGroups 顺序的 `ApplyEffectGroupPlan()`
// 是同一个套路。

static JsonSerializerOptions CreateUvsJsonOptions()
{
    var options = new JsonSerializerOptions
    {
        IncludeFields = true,
        NumberHandling = System.Text.Json.Serialization.JsonNumberHandling.AllowNamedFloatingPointLiterals,
        // UvsPattern.cutoutUVs 是一个没有 setter 的 readonly 字段（`public readonly
        // List<Vector2> cutoutUVs = new(0);`）——默认反序列化行为下 System.Text.Json 直接跳过
        // 它（既不能 Replace，也不会自动 Populate），实测会静默丢光全部 cutout 点。这个开关让
        // 反序列化改成"往已存在的实例里塞元素"（Populate），而不是"换一个新实例"（Replace），
        // 对只读集合字段是唯一能生效的策略。
        PreferredObjectCreationHandling = System.Text.Json.Serialization.JsonObjectCreationHandling.Populate,
    };
    // 同 CreateBridgeJsonOptions()：UV 矩形坐标全是 0/1 这种整数值浮点，不带小数点写出去的话
    // Blender 侧会画成整数框。
    options.Converters.Insert(0, new FloatKeepsDecimalPointConverter());
    return options;
}

static int RunUvsDump(string[] args)
{
    if (args.Length < 3)
    {
        Console.WriteLine("用法: dotnet <dll> uvsdump <uvs 文件路径> <json 输出路径>");
        return 1;
    }
    var uvsPath = args[1];
    var jsonOutPath = args[2];

    try
    {
        var handler = new FileHandler(uvsPath);
        var uvs = new UvsFile(handler);
        uvs.Read();

        var payload = new
        {
            fileVersion = handler.FileVersion,
            header = new { attributes = uvs.Header.attributes },
            textures = uvs.Textures,
            sequences = uvs.Sequences,
        };
        var json = JsonSerializer.Serialize(payload, CreateUvsJsonOptions());
        File.WriteAllText(jsonOutPath, json);
        Console.WriteLine($"OK: {uvsPath} -> {jsonOutPath}");
        return 0;
    }
    catch (Exception ex)
    {
        Console.WriteLine($"[ERROR] {uvsPath}");
        Console.WriteLine(ex.ToString());
        return 1;
    }
}

static int RunUvsLoad(string[] args)
{
    if (args.Length < 3)
    {
        Console.WriteLine("用法: dotnet <dll> uvsload <json 文件路径> <uvs 输出路径>");
        return 1;
    }
    var jsonPath = args[1];
    var uvsOutPath = args[2];

    try
    {
        var json = File.ReadAllText(jsonPath);
        var payload = JsonSerializer.Deserialize<UvsBridgePayload>(json, CreateUvsJsonOptions())
            ?? throw new Exception("反序列化结果为 null");

        // 不用 `using var outStream`——PatchZeroCutoutCounts() 需要在这个函数结束前就重新
        // 用 File.ReadAllBytes()/WriteAllBytes() 打开同一个路径，`using` 拖到函数末尾才释放
        // 的话，文件还被这里的 FileStream 独占着，会报"进程正在使用中"。改成写完/Save()
        // 之后显式 Dispose，再做二次 patch。
        var outStream = File.Create(uvsOutPath);
        // 显式赋值 FileVersion（见本节头部说明），不依赖 uvsOutPath 这个参数本身的文件名——
        // Blender 侧的版本号后缀校验是独立的一层保险（同 .efx 的 _ensure_version_suffix()），
        // 这里只保证字节内容本身永远正确。
        var writeHandler = new FileHandler(outStream, uvsOutPath) { FileVersion = payload.fileVersion };
        var uvs = new UvsFile(writeHandler);
        uvs.Header.attributes = payload.header?.attributes ?? 0;
        uvs.Textures = payload.textures ?? new List<TextureBlock>();
        uvs.Sequences = payload.sequences ?? new List<SequenceBlock>();

        // Python 侧（uvs_io.export_uvs_root()）只在"文件级 cutout_related 开着、但这一帧
        // 选择不裁剪"时才显式带上 `"cutoutUVCount": 0` 这个字段（其它情况一律不带，让 vendor
        // 的 DoWrite() 按 cutoutUVs 的实际内容重新计算）。这里不能直接读反序列化后的
        // `pattern.cutoutUVCount` 来判断"JSON 是不是显式带了这个字段"——JSON 缺省时 int
        // 字段的 C# 默认值同样是 0，两者从数值上分不出来。所以额外拿 JsonDocument 摊平检查
        // 原始 JSON 里每个 pattern 是不是真的带了这个 key（而不是看值），按数组下标对应到
        // 反序列化出来的 UvsPattern 对象——找出所有需要在写出后二次 patch 回字面 0 的 pattern。
        var zeroCutoutPatterns = new List<UvsPattern>();
        using (var doc = JsonDocument.Parse(json))
        {
            if (doc.RootElement.TryGetProperty("sequences", out var seqArrayEl))
            {
                var sequences = uvs.Sequences;
                var seqCount = Math.Min(seqArrayEl.GetArrayLength(), sequences.Count);
                for (int i = 0; i < seqCount; i++)
                {
                    if (!seqArrayEl[i].TryGetProperty("patterns", out var patArrayEl)) continue;
                    var patterns = sequences[i].patterns;
                    var patCount = Math.Min(patArrayEl.GetArrayLength(), patterns.Count);
                    for (int j = 0; j < patCount; j++)
                    {
                        // 光看这个 key 存不存在不够——uvsdump 的原始输出对每个 pattern 都会
                        // 带上 cutoutUVCount（不管值是 -1/0/8），如果有调用方把 dump 出来的
                        // JSON 原样喂回 uvsload（比如 roundtrip 测试脚本的"纯 CLI 基准对照"
                        // 那条路径，不经过 Blender/uvs_io.export_uvs_root()），每个 pattern
                        // 都会命中"key 存在"，把本该是 8 的也强行 patch 成 0——2026-09-10 加这个
                        // patch 时马上被 verify_blender_uvs_roundtrip.py 测出来过。必须连值一起
                        // 判断：只有字面量精确是 0 才需要二次 patch，8/-1 让 vendor 按
                        // cutoutUVs.Count 正常重算就好。
                        if (patArrayEl[j].TryGetProperty("cutoutUVCount", out var countEl)
                            && countEl.ValueKind == JsonValueKind.Number
                            && countEl.GetInt32() == 0)
                        {
                            zeroCutoutPatterns.Add(patterns[j]);
                        }
                    }
                }
            }
        }

        uvs.Write();
        writeHandler.Save();
        outStream.Dispose();

        if (zeroCutoutPatterns.Count > 0)
            PatchZeroCutoutCounts(uvsOutPath, zeroCutoutPatterns);

        Console.WriteLine($"OK: {jsonPath} -> {uvsOutPath}");
        return 0;
    }
    catch (Exception ex)
    {
        Console.WriteLine($"[ERROR] {jsonPath}");
        Console.WriteLine(ex.ToString());
        return 1;
    }
}

// 把 vendor DoWrite() 算出来的 cutoutUVCount（空列表一律写 -1，见 UvsFile.cs:172）改回字面
// 0——这些 pattern 是真实、活跃使用的游戏特效数据（2026-09-10 交叉核对过引用它们的 EFX
// 语料，见 PLAN.md "Phase 2" 一节），不是可以丢弃的编辑器残留。定位靠 `UvsPattern.Start`
// （BaseModel 公开属性，Write() 时记的这个对象在流里的起始位置，同 EFX 侧
// ApplyEffectGroupPlan() 的思路）——一个 UvsPattern 的二进制布局固定是
// flags(8B) + left/top/right/bottom(4B×4=16B) + textureIndex(4B) + cutoutUVCount(4B)
// （见 UvsFile.cs 的字段声明顺序），所以这个字段总是从 `Start + 28` 开始。
static void PatchZeroCutoutCounts(string path, List<UvsPattern> patterns)
{
    var bytes = File.ReadAllBytes(path);
    foreach (var pat in patterns)
    {
        var offset = (int)pat.Start + 28;
        BitConverter.GetBytes(0).CopyTo(bytes, offset);
    }
    File.WriteAllBytes(path, bytes);
}

// tex2dds 子命令：PLAN.md Phase 2 Step 4"贴图预览"——把游戏的 .tex 转成 Blender 原生能读的
// .dds，供 UVS 图形编辑界面把 pattern 矩形画在真实贴图上（而不是让用户对着空白方框editing）。
// vendor 自带现成转换器（`TexFile.SaveAsDDS()`），不需要我们自己解 GPU 压缩格式。
static int RunTex2Dds(string[] args)
{
    if (args.Length < 3)
    {
        Console.WriteLine("用法: dotnet <dll> tex2dds <tex 文件路径> <dds 输出路径>");
        return 1;
    }
    var texPath = args[1];
    var ddsOutPath = args[2];

    try
    {
        var handler = new FileHandler(texPath);
        var tex = new TexFile(handler);
        tex.Read();
        tex.SaveAsDDS(ddsOutPath);
        Console.WriteLine($"OK: {texPath} -> {ddsOutPath}");
        return 0;
    }
    catch (Exception ex)
    {
        Console.WriteLine($"[ERROR] {texPath}");
        Console.WriteLine(ex.ToString());
        return 1;
    }
}

// mdfdump 子命令：读一个 .mdf2 材质文件，把它声明的参数表/贴图槽吐成 JSON。
//
//   mdfdump <mdf2 文件路径> <json 输出路径>
//   mdfdump --pak <游戏安装目录> <mdf2 内部路径（natives/STM/... 带版本号后缀）> <json 输出路径>
//
// TypeMeshV2 的 `properties`（MdfProperty 数组）语义是"这个 attribute 覆盖了所引用材质的哪几个
// 参数"：能覆盖哪些、每个几个分量、`mdfPropertyIndex` 该填几，全部由 `MaterialPath` 指向的那个
// .mdf2 决定。所以"新增一条 property"必须先读到材质本身，否则只能照语料里见过的组合猜，而
// `mdfPropertyIndex` 猜错等于静默改到另一个参数上（铁律 #1、用户文案规则）。
//
// 哈希：EFX 侧的 `PropertyNameUTF8Hash` 和 mdf2 自己存的 `hash`/`asciiHash` 是同一个名字的三种
// 不同哈希（mdf2 存 UTF-16 和 ASCII 两种，EFX 用 UTF-8），互相对不上。这里按参数名现算一遍
// UTF-8 的一并输出，Python 侧才能直接和 EFX 里的哈希比对。
//
// pak 模式只把要找的那一个路径加进 `searchedPaths` 再 `FindFiles()`，走的是"扫各 pak 的条目表
// 找这个哈希"，不是 `CacheEntries()` 那种把全部条目读进内存的路子。
static int RunMdfDump(string[] args)
{
    var usePak = args.Length >= 2 && args[1] == "--pak";
    if (usePak ? args.Length < 5 : args.Length < 3)
    {
        Console.WriteLine("用法: dotnet <dll> mdfdump <mdf2 文件路径> <json 输出路径>");
        Console.WriteLine("      dotnet <dll> mdfdump --pak <游戏安装目录> <mdf2 内部路径> <json 输出路径>");
        return 1;
    }

    var sourcePath = usePak ? args[3] : args[1];
    var jsonOutPath = usePak ? args[4] : args[2];

    try
    {
        MdfFile mdf;
        if (usePak)
        {
            var gameDir = args[2];
            var reader = new PakReader { EnableConsoleLogging = false };
            reader.PakFilePriority = PakUtils.ScanPakFiles(gameDir);
            if (reader.PakFilePriority.Count == 0)
            {
                Console.WriteLine($"[ERROR] 目录里没有找到任何 .pak：{gameDir}");
                return 1;
            }
            reader.AddFiles(sourcePath);
            var hit = reader.FindFiles().FirstOrDefault();
            if (hit.stream == null)
            {
                Console.WriteLine($"[ERROR] pak 里找不到这个路径：{sourcePath}");
                return 1;
            }
            // 从内存流读时 FilePath 只是给版本号解析用的（`FileHandler.FileVersion` 从路径算，
            // 见 CLAUDE.md 已知机关 #13），流本身和磁盘无关。
            var memory = new MemoryStream();
            hit.stream.CopyTo(memory);
            memory.Seek(0, SeekOrigin.Begin);
            mdf = new MdfFile(new FileHandler(memory, sourcePath));
        }
        else
        {
            mdf = new MdfFile(new FileHandler(sourcePath));
        }
        mdf.Read();

        var materials = mdf.Materials.Select(mat => new
        {
            name = mat.Name,
            masterMaterial = mat.MasterMaterial,
            // index 就是 EFX `MdfProperty.mdfPropertyIndex` 要填的值（参数在这张表里的位置）。
            parameters = mat.Parameters.Select((p, i) => new
            {
                index = i,
                name = p.paramName,
                utf8Hash = MurMur3HashUtils.GetUTF8Hash(p.paramName),
                componentCount = p.componentCount,
                value = p.parameter,
            }).ToArray(),
            // 贴图槽：EFX 侧对应 parameterType=Texture 的 property（那种 mdfPropertyIndex 恒为 -1，
            // 由 vendor 写出时强制，见 MdfProperty.DoWrite）。path 可以当新建时的基础值。
            textures = mat.Textures.Select((t, i) => new
            {
                index = i,
                name = t.texType,
                utf8Hash = MurMur3HashUtils.GetUTF8Hash(t.texType),
                path = t.texPath,
            }).ToArray(),
        }).ToArray();

        var payload = new
        {
            sourcePath,
            fileVersion = mdf.FileHandler.FileVersion,
            materials,
        };
        var json = JsonSerializer.Serialize(payload, CreateUvsJsonOptions());
        File.WriteAllText(jsonOutPath, json);
        Console.WriteLine($"OK: {sourcePath} -> {jsonOutPath}");
        return 0;
    }
    catch (Exception ex)
    {
        Console.WriteLine($"[ERROR] {sourcePath}");
        Console.WriteLine(ex.ToString());
        return 1;
    }
}

// pakextract 子命令：按内部路径从游戏 .pak 里捞一个文件写到磁盘上。
//
//   pakextract <游戏安装目录> <内部路径（natives/STM/... 带版本号后缀）> <输出路径>
//
// 材质参数覆盖表那套要求用户手上有一个真的 .mdf2 文件（见 blender_efx_re/mdf_catalog.py），
// 而 VFX 用的材质通常没人会专门去解包。有这条命令就不用为了拿一个参考材质去装第三方解包工具。
// 按内部路径的哈希直接定位条目，不建全量条目缓存，实测单次 <1 秒。
static int RunPakExtract(string[] args)
{
    if (args.Length < 4)
    {
        Console.WriteLine("用法: dotnet <dll> pakextract <游戏安装目录> <内部路径> <输出路径>");
        return 1;
    }
    var gameDir = args[1];
    var internalPath = args[2];
    var outPath = args[3];

    try
    {
        var reader = new PakReader { EnableConsoleLogging = false };
        reader.PakFilePriority = PakUtils.ScanPakFiles(gameDir);
        if (reader.PakFilePriority.Count == 0)
        {
            Console.WriteLine($"[ERROR] 目录里没有找到任何 .pak：{gameDir}");
            return 1;
        }
        reader.AddFiles(internalPath);
        var hit = reader.FindFiles().FirstOrDefault();
        if (hit.stream == null)
        {
            Console.WriteLine($"[ERROR] pak 里找不到这个路径：{internalPath}");
            return 1;
        }

        var directory = Path.GetDirectoryName(Path.GetFullPath(outPath));
        if (!string.IsNullOrEmpty(directory)) Directory.CreateDirectory(directory);
        using (var file = File.Create(outPath))
        {
            hit.stream.CopyTo(file);
        }
        Console.WriteLine($"OK: {internalPath} -> {outPath}");
        return 0;
    }
    catch (Exception ex)
    {
        Console.WriteLine($"[ERROR] {internalPath}");
        Console.WriteLine(ex.ToString());
        return 1;
    }
}

// types 子命令：把某个游戏版本下**全部** attribute 类型的清单吐成 JSON，每项包含
//   itemTypeId —— 文件里那个整数（决定 entry 内的排序，见 EfxFile.cs 的 typeId 升序断言）
//   name       —— EfxAttributeType 枚举名（= 010 模板 ItemType 里的 MHWS_* 名字）
//   type       —— 完整 C# 类名，和 dump 出来的 JSON 里那个 "$type" 一模一样
//   fields     —— dump/load 走的那些 JSON 键名（照 CreateBridgeJsonOptions 的解析器算，
//                 所以和真实 dump 出来的键完全一致，不是从源码猜的）
//   readable   —— false 表示 vendor 只登记了 id→枚举名、没有读写实现类（KNOWN_UPSTREAM_ISSUES
//                 #4/#5 那几个就是这种），这类既解析不了也新建不了
//
// 两个用处：给字段知识表当"JSON 键名的权威来源"（对齐 010 模板的字段名时要用），
// 以及将来 C 层"新增 Attribute"的类型选择器直接读这份清单。
static int RunTypes(string[] args)
{
    if (args.Length < 2)
    {
        Console.WriteLine("用法: dotnet <dll> types <json 输出路径> [游戏版本，默认 MHWilds]");
        return 1;
    }
    var jsonOutPath = args[1];
    var version = EfxVersion.MHWilds;
    if (args.Length >= 3 && !Enum.TryParse(args[2], true, out version))
    {
        Console.WriteLine($"[ERROR] 未知的 EfxVersion: {args[2]}");
        return 1;
    }

    var options = CreateBridgeJsonOptions();
    var items = new List<object>();
    var enumDefs = new Dictionary<string, List<object>>();
    // `type`（EfxAttributeType）和 `Version`（EfxVersion）虽然也是枚举，但属于记账字段，
    // 面板上不画（见 model.ATTRIBUTE_BOOKKEEPING_KEYS），成员表也没必要塞进清单。
    var bookkeepingEnums = new HashSet<string> { "EfxAttributeType", "EfxVersion" };
    foreach (var (typeId, attrType) in EfxAttributeTypeRemapper.GetAllTypes(version).OrderBy(kv => kv.Key))
    {
        EFXAttribute? instance = null;
        string? error = null;
        try
        {
            instance = EfxAttributeTypeRemapper.Create(attrType, version);
        }
        catch (Exception ex)
        {
            error = ex.Message;
        }

        var fields = new List<string>();
        var fieldEnums = new Dictionary<string, string>();
        if (instance != null)
        {
            // 从序列化器自己的 JsonTypeInfo 拿属性名，**不实际序列化**：键名一样是权威的
            // （dump 走的就是这份元数据），但不会去调 getter——空实例上有些计算属性会炸，
            // 比如 EfxClipData.ParsedClip 在 clipData 还没解析时直接 NullReferenceException。
            foreach (var prop in options.GetTypeInfo(instance.GetType()).Properties)
            {
                if (prop.Get == null) continue;
                fields.Add(prop.Name);

                // 枚举字段：记下枚举类型名，成员表单独去重存一份（见 payload.enums）。
                // 这些字段在 JSON 里就是个裸数字，Blender 面板不知道 `2` 是 `XYZ` 还是别的，
                // 有了这份元数据才能画成下拉。
                var pt = Nullable.GetUnderlyingType(prop.PropertyType) ?? prop.PropertyType;
                if (!pt.IsEnum || bookkeepingEnums.Contains(pt.Name)) continue;
                fieldEnums[prop.Name] = pt.Name;
                if (!enumDefs.ContainsKey(pt.Name))
                {
                    enumDefs[pt.Name] = Enum.GetValues(pt).Cast<object>()
                        .Select(v => new { value = Convert.ToInt64(v), name = Enum.GetName(pt, v) })
                        .GroupBy(x => x.value).Select(g => g.First())   // [Flags] 别名去重
                        .OrderBy(x => x.value).Cast<object>().ToList();
                }
            }
        }

        items.Add(new
        {
            itemTypeId = typeId,
            name = attrType.ToString(),
            type = instance?.GetType().FullName,
            readable = instance != null,
            error,
            fields,
            fieldEnums,
        });
    }

    var payload = new
    {
        game = version.ToString(),
        count = items.Count,
        // 枚举成员表按枚举类型名去重存一份，字段那边只记类型名——1373 个枚举字段只涉及
        // 二十来个枚举类型，逐字段展开会把清单撑大一个数量级。
        enums = enumDefs.OrderBy(kv => kv.Key).ToDictionary(kv => kv.Key, kv => kv.Value),
        types = items,
    };
    File.WriteAllText(jsonOutPath, JsonSerializer.Serialize(payload, new JsonSerializerOptions { WriteIndented = true }));
    var readable = items.Count(i => (bool)i.GetType().GetProperty("readable")!.GetValue(i)!);
    Console.WriteLine($"OK: {version} 共 {items.Count} 个类型（可读写 {readable} 个）-> {jsonOutPath}");
    return 0;
}

// bitnames 子命令：给每个 IExpressionAttribute/IClipAttribute 类型算一份"bit_index -> 字段名"
// 静态表，喂给 Blender 面板把裸整数 bit_index 换成按名字选的下拉（见仓库 CLAUDE.md 铁律 #19
// 附近关于 Expression bit 语义的讨论）。
//
// Expression 侧：每个类只声明了 bit 位数（`expressionBits = new BitSet(N)`），bit 的身份靠
// **这个类里紧挨着的一串 `ExpressionAssignType` 字段**——vendor 只给其中一部分起了别名塞进
// `BitNameDict`（如 `nameof(translationX)`），剩下那些没别名的字段（`ukn1_7` 这种）依然是
// 真实声明的字段，只是没人给它注册进字典。这里用反射把同一个类里全部 `ExpressionAssignType`
// 字段按**声明顺序**（`MetadataToken` 单调递增，C# 编译器保证）取出来，位置直接对应 bit 下标，
// 用来补全 `BitNameDict` 没登记的那部分——已经用 Transform3DExpression（9 位全部具名）、
// RotateAnimExpression（前 6 位具名、后 6 位是 `ukn1_7..12`）交叉核对过，取出来的顺序和源码
// 里手写的 `[1]=nameof(xxx)` 对得上。
//
// Clip 侧完全是另一回事：`IClipAttribute` 的曲线数据都存进同一个共享的 `clipData`，**没有
// per-bit 的具名字段可反射**，唯一的名字来源是 vendor 自己愿不愿意给 `clipBits` 挂
// `BitNames`/`BitNameDict`——绝大多数类型什么都没挂（比如 Transform3DClip 的 9 位无一具名），
// 只有极少数（RGBA 四件套、TypeMesh 的材质槽）挂了。挂了就如实抄，没挂的就是没挂，不编名字
// （用户文案规则）——Python 侧对这些 null 条目只能显示裸 "bit{N}"。
static int RunBitNames(string[] args)
{
    if (args.Length < 2)
    {
        Console.WriteLine("用法: dotnet <dll> bitnames <json 输出路径> [游戏版本，默认 MHWilds]");
        return 1;
    }
    var jsonOutPath = args[1];
    var version = EfxVersion.MHWilds;
    if (args.Length >= 3 && !Enum.TryParse(args[2], true, out version))
    {
        Console.WriteLine($"[ERROR] 未知的 EfxVersion: {args[2]}");
        return 1;
    }

    static string?[] ResolveExpressionBitNames(Type type, BitSet bits)
    {
        var names = new string?[bits.BitCount];
        for (int i = 0; i < bits.BitCount; i++) names[i] = bits.GetBitName(i);

        var assignFields = type
            .GetFields(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.DeclaredOnly)
            .Where(f => f.FieldType == typeof(ExpressionAssignType))
            .OrderBy(f => f.MetadataToken)
            .ToList();

        for (int i = 0; i < assignFields.Count && i < names.Length; i++)
        {
            names[i] ??= assignFields[i].Name;
        }
        return names;
    }

    var expressionItems = new List<object>();
    var clipItems = new List<object>();

    foreach (var (typeId, attrType) in EfxAttributeTypeRemapper.GetAllTypes(version).OrderBy(kv => kv.Key))
    {
        EFXAttribute? instance;
        try
        {
            instance = EfxAttributeTypeRemapper.Create(attrType, version);
        }
        catch
        {
            continue;
        }
        if (instance == null) continue;

        if (instance is IExpressionAttribute exprAttr)
        {
            var bits = exprAttr.ExpressionBits;
            expressionItems.Add(new
            {
                type = instance.GetType().FullName,
                name = attrType.ToString(),
                bitCount = bits.BitCount,
                bitNames = ResolveExpressionBitNames(instance.GetType(), bits),
            });
        }
        if (instance is IClipAttribute clipAttr)
        {
            var bits = clipAttr.ClipBits;
            var names = new string?[bits.BitCount];
            for (int i = 0; i < bits.BitCount; i++) names[i] = bits.GetBitName(i);
            clipItems.Add(new
            {
                type = instance.GetType().FullName,
                name = attrType.ToString(),
                bitCount = bits.BitCount,
                bitNames = names,
            });
        }
    }

    var payload = new
    {
        game = version.ToString(),
        expressionAttributes = expressionItems,
        clipAttributes = clipItems,
    };
    File.WriteAllText(jsonOutPath, JsonSerializer.Serialize(payload, new JsonSerializerOptions { WriteIndented = true }));
    Console.WriteLine($"OK: {version} 共 {expressionItems.Count} 个 Expression 类型 / {clipItems.Count} 个 Clip 类型 -> {jsonOutPath}");
    return 0;
}

// new 子命令：凭空造一个空白的 attribute / entry / action，序列化成和 dump 里同一形状的 JSON。
//
// C 层"新增"功能的地基。**不需要我们自己写模板/预设文件**——vendor 的每个 attribute 类型都是
// 真实的 C# 类，`new` 出来就是一份带正确默认值的实例，序列化器再按 dump 的同一套规则写出去，
// Python 侧直接喂给 io_tree.build_attribute_object() 就行。姊妹项目 EFX-Editor 那边要靠人工
// 攒预设字节，是因为它没有这层类型化对象模型。
//
//   new attribute <类型名> <json 输出> [版本]   类型名 = EfxAttributeType 枚举名，见 types 子命令
//   new entry <json 输出> [版本]
//   new action <json 输出> [版本]
// fieldstats 子命令：在整个语料上普查某个 attribute 类型每个字段的取值分布。
//
// 一个进程扫完全部文件（9221 个约一分钟），比 Python 侧对每个文件起一次 `dump` 快两个数量级。
// 用途：
//   - 逆向字段语义时看"这个字段实际只出现过哪几个值"（比如判断一个 uint 是枚举还是位域）
//   - 将来给"新建 attribute"挑合理默认值（取语料众数，而不是 C# 的零值）
//
//   fieldstats <语料目录> <类型名> <json 输出>
//
// 类型名 = EfxAttributeType 枚举名，见 types 子命令。输出里每个字段一个取值直方图（按出现
// 次数降序，最多留 MaxDistinct 项，超出的合并成 "__other__"）。解析失败的文件直接跳过并计数
// ——语料里本来就有 14% 读不了（见 KNOWN_UPSTREAM_ISSUES）。
static int RunFieldStats(string[] args)
{
    if (args.Length < 4)
    {
        Console.WriteLine("用法: dotnet <dll> fieldstats <语料目录> <attribute 类型名> <json 输出路径> [每字段保留的不同取值数，默认 40]");
        return 1;
    }
    var dir = args[1];
    var typeName = args[2];
    var jsonOutPath = args[3];
    // 直方图每个字段最多保留多少个不同取值（按出现次数降序）。默认 40 够看清主流分布；
    // 判断"某个字段是不是位域、有没有非法组合"这种要看全集的场景传大一点。
    var maxDistinct = args.Length >= 5 && int.TryParse(args[4], out var md) ? md : 40;

    if (!Directory.Exists(dir))
    {
        Console.WriteLine($"目录不存在: {dir}");
        return 1;
    }
    if (!Enum.TryParse<EfxAttributeType>(typeName, true, out var wanted))
    {
        Console.WriteLine($"[ERROR] 未知的 attribute 类型名: {typeName}");
        return 1;
    }

    var options = CreateBridgeJsonOptions();
    var files = Directory.EnumerateFiles(dir, "*.efx.*", SearchOption.AllDirectories).ToList();
    var histograms = new Dictionary<string, Dictionary<string, int>>();
    int scanned = 0, failed = 0, instances = 0;

    void Tally(System.Text.Json.Nodes.JsonNode? node, string path)
    {
        switch (node)
        {
            case System.Text.Json.Nodes.JsonObject obj:
                foreach (var (key, child) in obj)
                {
                    if (key == "$type") continue;
                    Tally(child, path.Length == 0 ? key : path + "." + key);
                }
                break;
            case System.Text.Json.Nodes.JsonArray arr:
                // 数组不按下标展开（长度不定会把直方图撑爆），只记长度
                Bump(path + "[].length", arr.Count.ToString());
                break;
            case null:
                Bump(path, "null");
                break;
            default:
                Bump(path, node.ToJsonString());
                break;
        }
    }

    void Bump(string path, string value)
    {
        if (!histograms.TryGetValue(path, out var hist))
            histograms[path] = hist = new Dictionary<string, int>();
        hist[value] = hist.GetValueOrDefault(value) + 1;
    }

    void Visit(EFXEntryBase container)
    {
        foreach (var attr in container.Attributes)
        {
            if (attr.type == wanted)
            {
                instances++;
                var json = JsonSerializer.Serialize(attr, typeof(EFXAttribute), options);
                Tally(System.Text.Json.Nodes.JsonNode.Parse(json), "");
            }
            if (attr is EFXAttributePlayEmitter { efxrData: not null } pe)
            {
                foreach (var e in pe.efxrData.Entries) Visit(e);
                foreach (var a in pe.efxrData.Actions) Visit(a);
            }
        }
    }

    foreach (var path in files)
    {
        try
        {
            var efx = new EfxFile(new FileHandler(path));
            efx.Read();
            scanned++;
            foreach (var e in efx.Entries) Visit(e);
            foreach (var a in efx.Actions) Visit(a);
        }
        catch (Exception)
        {
            failed++;  // 语料里本来就有一批读不了的，见 KNOWN_UPSTREAM_ISSUES
        }
    }

    var payload = new
    {
        type = wanted.ToString(),
        filesTotal = files.Count,
        filesScanned = scanned,
        filesFailed = failed,
        instances,
        fields = histograms.ToDictionary(
            kv => kv.Key,
            kv => new
            {
                distinct = kv.Value.Count,
                top = kv.Value.OrderByDescending(x => x.Value).Take(maxDistinct)
                        .ToDictionary(x => x.Key, x => x.Value),
            }),
    };
    File.WriteAllText(jsonOutPath, JsonSerializer.Serialize(payload, new JsonSerializerOptions { WriteIndented = true }));
    Console.WriteLine($"OK: {wanted} 共 {instances} 个实例（扫描 {scanned} 个文件，失败 {failed}）-> {jsonOutPath}");
    return 0;
}

// pairstats 子命令：**一次扫描**把全部 attribute 类型里所有二元字段（`via.Range`/`via.RangeI`
// 的 `{s,r}`、`via.Int2` 的 `{x,y}`）的**联合分布**统计出来，用来排查"哪个字段是 (min,max)、
// 哪个是 (静态值,随机量)、min/max 里哪些是左闭右开"。
//
//   pairstats <语料目录> <json 输出路径> [每字段保留的高频组合数，默认 20]
//
// 为什么要专门做一个子命令：`fieldstats` 只出**边缘分布**（`X.r` 和 `X.s` 各自的直方图），
// 而这三类语义的判据全在**联合分布**上——"副值小于主值出现过没有"、"两者相等占多少"。
// `condstats` 能出联合分布，但一次只能盯一个字段，全语料几百个二元字段要重扫几百遍。
//
// 输出的每个数都是**原始计数**，C# 侧不下结论——判据留在 tools/audit_range_fields.py，
// 改判据不用重新编译，也方便把"依据"和"结论"分开看。
//
// 主值/副值：`{s,r}` 的主值是**二进制首字段**（`via.RangeI` 声明成 `{r,s}`、`via.Range` 是
// `{s,r}`，见 CLAUDE.md），JSON 键序就是字段声明序，所以直接取第一个键。键序和"两个值是不是
// 都是整数"都带出来，供分析脚本交叉核对这条规律本身有没有例外。
static int RunPairStats(string[] args)
{
    if (args.Length < 3)
    {
        Console.WriteLine("用法: dotnet <dll> pairstats <语料目录> <json 输出路径> [每字段保留的高频组合数，默认 20]");
        return 1;
    }
    var dir = args[1];
    var jsonOutPath = args[2];
    var maxPairs = args.Length >= 4 && int.TryParse(args[3], out var mp) ? mp : 20;

    if (!Directory.Exists(dir))
    {
        Console.WriteLine($"目录不存在: {dir}");
        return 1;
    }

    var stats = new Dictionary<string, Dictionary<string, PairTally>>();
    var instanceCounts = new Dictionary<string, int>();
    var options = CreateBridgeJsonOptions();
    var files = Directory.EnumerateFiles(dir, "*.efx.*", SearchOption.AllDirectories).ToList();
    int scanned = 0, failed = 0;

    static bool IsIntegral(System.Text.Json.Nodes.JsonNode? n)
    {
        if (n is not System.Text.Json.Nodes.JsonValue v) return false;
        if (!v.TryGetValue<System.Text.Json.JsonElement>(out var el)) return false;
        if (el.ValueKind != System.Text.Json.JsonValueKind.Number) return false;
        var raw = el.GetRawText();
        return raw.IndexOf('.') < 0 && raw.IndexOf('e') < 0 && raw.IndexOf('E') < 0;
    }

    static double AsDouble(System.Text.Json.Nodes.JsonNode? n)
    {
        try { return n is null ? 0.0 : n.GetValue<double>(); }
        catch { return 0.0; }
    }

    void Walk(System.Text.Json.Nodes.JsonNode? node, string path, Dictionary<string, PairTally> bucket)
    {
        if (node is System.Text.Json.Nodes.JsonObject obj)
        {
            var keys = obj.Select(kv => kv.Key).Where(k => k != "$type").ToList();
            var isSR = keys.Count == 2 && keys.Contains("s") && keys.Contains("r");
            var isXY = keys.Count == 2 && keys.Contains("x") && keys.Contains("y");
            if ((isSR || isXY) && path.Length > 0)
            {
                var firstKey = keys[0];
                var secondKey = keys[1];
                var a = obj[firstKey];
                var b = obj[secondKey];
                if (a is System.Text.Json.Nodes.JsonValue && b is System.Text.Json.Nodes.JsonValue)
                {
                    if (!bucket.TryGetValue(path, out var t))
                        bucket[path] = t = new PairTally { KeyOrder = firstKey + "," + secondKey };
                    t.Observe(AsDouble(a), AsDouble(b), IsIntegral(a) && IsIntegral(b), maxPairs);
                    return;
                }
            }
            foreach (var kv in obj)
            {
                if (kv.Key == "$type") continue;
                // 不钻进嵌套的 efxrData：PlayEmitter 把一整个 EfxFile 嵌在自己里，
                // 而 Visit() 已经会沿着它递归地把里面每个 attribute 按**它自己的类型**
                // 再统计一遍。这里再钻一次就是双重计数，而且会把它们全记到
                // PlayEmitter 名下，类型归属也是错的。
                if (kv.Key == "efxrData") continue;
                Walk(kv.Value, path.Length == 0 ? kv.Key : path + "." + kv.Key, bucket);
            }
        }
        else if (node is System.Text.Json.Nodes.JsonArray arr)
        {
            // 数组不按下标展开（`properties[3].value` 这种下标进路径会把表撑爆），
            // 统一折成 `[]`，同一个位置的不同下标累加到一起
            foreach (var child in arr) Walk(child, path + "[]", bucket);
        }
    }

    void Visit(EFXEntryBase container)
    {
        foreach (var attr in container.Attributes)
        {
            var name = attr.type.ToString();
            if (!stats.TryGetValue(name, out var bucket))
                stats[name] = bucket = new Dictionary<string, PairTally>();
            instanceCounts[name] = instanceCounts.GetValueOrDefault(name) + 1;
            var json = JsonSerializer.Serialize(attr, typeof(EFXAttribute), options);
            Walk(System.Text.Json.Nodes.JsonNode.Parse(json), "", bucket);

            if (attr is EFXAttributePlayEmitter { efxrData: not null } pe)
            {
                foreach (var e in pe.efxrData.Entries) Visit(e);
                foreach (var a in pe.efxrData.Actions) Visit(a);
            }
        }
    }

    foreach (var path in files)
    {
        try
        {
            var efx = new EfxFile(new FileHandler(path));
            efx.Read();
            scanned++;
            foreach (var e in efx.Entries) Visit(e);
            foreach (var a in efx.Actions) Visit(a);
        }
        catch (Exception)
        {
            failed++;  // 语料里本来就有一批读不了的，见 KNOWN_UPSTREAM_ISSUES
        }
    }

    var payload = new
    {
        filesTotal = files.Count,
        filesScanned = scanned,
        filesFailed = failed,
        types = stats.Where(kv => kv.Value.Count > 0).OrderBy(kv => kv.Key).ToDictionary(
            kv => kv.Key,
            kv => new
            {
                instances = instanceCounts.GetValueOrDefault(kv.Key),
                fields = kv.Value.OrderBy(f => f.Key).ToDictionary(f => f.Key, f => f.Value.ToPayload(maxPairs)),
            }),
    };
    File.WriteAllText(jsonOutPath, JsonSerializer.Serialize(payload, new JsonSerializerOptions { WriteIndented = true }));
    Console.WriteLine($"OK: {stats.Count(kv => kv.Value.Count > 0)} 种类型带二元字段"
                      + $"（扫描 {scanned}/{files.Count} 个文件，失败 {failed}）-> {jsonOutPath}");
    return 0;
}


// exprvarstats 子命令：全语料扫描 IExpressionAttribute 的公式，统计每个"未被 KnownExternalHashes
// 解出名字"的外部/常量变量哈希出现了多少次、都出现在哪些 attribute 类型里，并留几条完整公式当例子。
//
// 原理：EfxFile.ParseExpressions() 把二进制后缀栈还原成 EFXExpressionTree，
// ExpressionParameter.ToString()（ExpressionTree.cs）对 External/Constant 来源、
// 又查不到名字的参数会退化成 "ext:<hash>" / "const:<hash>" 这种带哈希的占位文本
// （Parameter 来源查不到时会退化成 "p:<hash>"，是 vendor 那边遗留的一个小状态位 bug——
// 没重新赋 source，默认落回 Parameter，不是这里的问题，一并扫出来存档即可）。
// 直接对公式的 ToString() 正则找这几种占位前缀，比手动重新遍历树省一遍代码。
//
//   exprvarstats <语料目录> <json 输出路径> [每个哈希保留的示例条数，默认 5]
//
// 输出结构：{ filesTotal, filesScanned, filesFailed, treesSeen, markers: { "<marker>:<hash>":
// { count, attrTypes: {类型名: 次数}, examples: [{file, attrType, formula}] } } }，
// 按 count 降序排列，方便优先看最值得继续猜名字的那几个。
static int RunExprVarStats(string[] args)
{
    if (args.Length < 3)
    {
        Console.WriteLine("用法: dotnet <dll> exprvarstats <语料目录> <json 输出路径> [每个哈希保留的示例条数，默认 5]");
        return 1;
    }
    var dir = args[1];
    var jsonOutPath = args[2];
    var maxExamples = args.Length >= 4 && int.TryParse(args[3], out var me) ? me : 5;

    if (!Directory.Exists(dir))
    {
        Console.WriteLine($"目录不存在: {dir}");
        return 1;
    }

    var files = Directory.EnumerateFiles(dir, "*.efx.*", SearchOption.AllDirectories).ToList();
    var markerRegex = new System.Text.RegularExpressions.Regex(@"\b(ext|const|p|ukn):(\d+)\b");
    // 函数/算子调用名——覆盖 Lerp/InvLerp/Clamp/Min/Max 这些已知语义的，
    // 也覆盖 Unary0-12/Func18-21 这些数字命名、语义未确认的（ExpressionTree.cs 的注释
    // 自己都说是"potential candidates"，不是定论），用来摸底真实语料里数字函数占比多少，
    // 决定要不要为了不到 1% 的用例专门去猜语义。
    var funcRegex = new System.Text.RegularExpressions.Regex(@"\b([A-Za-z_][A-Za-z0-9_]*)\(");
    var stats = new Dictionary<string, ExprVarStat>();
    var funcCounts = new Dictionary<string, int>();
    // 语义未确认的函数名（见 efx_sim/expr.py 的 _UNKNOWN_FUNC_ARGC）——只给这批留完整公式
    // 例子，方便照抄真实语料里的用法（参数量级/外层怎么包）去校准探测公式，而不是瞎猜。
    var unknownFuncNames = new HashSet<string> {
        "Unary0", "Unary1", "Unary2", "Unary4", "Unary5", "Unary6",
        "Unary7", "Unary8", "Unary9", "Unary10", "Unary11", "Unary12",
        "Func18", "Func19", "Func20", "Func21",
    };
    var funcExamples = new Dictionary<string, List<ExprVarExample>>();
    // "两根值"（`ExpressionRootValueOption`）的完整样本：vendor 在
    // `ReconstructExpressionTree()` 里发现"组件没用完"时会造这个节点，它自己的注释说
    // "maybe it's a feature where you can specify two values, and they get used as a
    // min-max random range?"。但同样的"组件没用完"也可能是**某个函数的 arity 读错**造成
    // 的假象（MHWilds 这边已经撞见过两次栈残留），所以这里把**原始组件流**一起记下来，
    // 好判断到底是引擎特性还是解析 bug。
    var rootOptionExamples = new List<Dictionary<string, object?>>();
    int scanned = 0, failed = 0, treesSeen = 0, rootOptionCount = 0;
    string currentPath = "";

    void Visit(EFXEntryBase container)
    {
        foreach (var attr in container.Attributes)
        {
            if (attr is IExpressionAttribute exprAttr && exprAttr.Expression?.ParsedExpressions is { } trees)
            {
                var attrTypeName = attr.type.ToString();
                var rawList = exprAttr.Expression.Expressions.ToList();
                for (var treeIndex = 0; treeIndex < trees.Count; treeIndex++)
                {
                    var tree = trees[treeIndex];
                    treesSeen++;
                    var formula = tree.ToString();
                    if (tree.root is ExpressionRootValueOption)
                    {
                        rootOptionCount++;
                        if (rootOptionExamples.Count < 40)
                        {
                            var comps = new List<string>();
                            if (treeIndex < rawList.Count)
                            {
                                foreach (var c in rawList[treeIndex].Components)
                                {
                                    comps.Add(c.data switch {
                                        EFXExpressionDataFloat f => $"CONST {f.value}",
                                        EFXExpressionDataFunction fn => $"FUNC {(int)fn.value}",
                                        EFXExpressionDataBinaryOperator b => $"BINOP {(int)b.value}",
                                        EFXExpressionDataUnaryOperator u => $"UNOP {u.value}",
                                        EFXExpressionDataParameterHash ph => $"PARAM {ph.parameterHash}",
                                        _ => c.data?.GetType().Name ?? "null",
                                    });
                                }
                            }
                            rootOptionExamples.Add(new Dictionary<string, object?> {
                                ["file"] = currentPath,
                                ["attrType"] = attrTypeName,
                                ["formula"] = formula,
                                ["components"] = comps,
                            });
                        }
                    }
                    var seenInThisFormula = new HashSet<string>();
                    foreach (System.Text.RegularExpressions.Match fm in funcRegex.Matches(formula))
                    {
                        var fname = fm.Groups[1].Value;
                        funcCounts[fname] = funcCounts.GetValueOrDefault(fname) + 1;
                        if (unknownFuncNames.Contains(fname) && seenInThisFormula.Add(fname))
                        {
                            if (!funcExamples.TryGetValue(fname, out var exList))
                                funcExamples[fname] = exList = new List<ExprVarExample>();
                            if (exList.Count < maxExamples)
                                exList.Add(new ExprVarExample(currentPath, attrTypeName, formula));
                        }
                    }
                    foreach (System.Text.RegularExpressions.Match m in markerRegex.Matches(formula))
                    {
                        var key = $"{m.Groups[1].Value}:{m.Groups[2].Value}";
                        if (!stats.TryGetValue(key, out var stat))
                            stats[key] = stat = new ExprVarStat();
                        stat.count++;
                        stat.attrTypes[attrTypeName] = stat.attrTypes.GetValueOrDefault(attrTypeName) + 1;
                        if (stat.examples.Count < maxExamples)
                            stat.examples.Add(new ExprVarExample(currentPath, attrTypeName, formula));
                    }
                }
            }
            if (attr is EFXAttributePlayEmitter { efxrData: not null } pe)
            {
                foreach (var e in pe.efxrData.Entries) Visit(e);
                foreach (var a in pe.efxrData.Actions) Visit(a);
            }
        }
    }

    foreach (var path in files)
    {
        currentPath = path;
        try
        {
            var efx = new EfxFile(new FileHandler(path));
            efx.Read();
            efx.ParseExpressions();
            scanned++;
            foreach (var e in efx.Entries) Visit(e);
            foreach (var a in efx.Actions) Visit(a);
        }
        catch (Exception)
        {
            failed++;  // 语料里本来就有一批读不了的，见 KNOWN_UPSTREAM_ISSUES
        }
    }

    var payload = new
    {
        filesTotal = files.Count,
        filesScanned = scanned,
        filesFailed = failed,
        treesSeen,
        functions = funcCounts.OrderByDescending(kv => kv.Value).ToDictionary(kv => kv.Key, kv => kv.Value),
        rootOptionCount,
        rootOptionExamples,
        functionExamples = funcExamples.ToDictionary(kv => kv.Key, kv => kv.Value),
        markers = stats.OrderByDescending(kv => kv.Value.count).ToDictionary(
            kv => kv.Key,
            kv => new
            {
                count = kv.Value.count,
                attrTypes = kv.Value.attrTypes.OrderByDescending(t => t.Value).ToDictionary(t => t.Key, t => t.Value),
                examples = kv.Value.examples,
            }),
    };
    File.WriteAllText(jsonOutPath, JsonSerializer.Serialize(payload, new JsonSerializerOptions { WriteIndented = true }));
    Console.WriteLine($"OK: {stats.Count} 个不同的 marker:hash 组合"
                      + $"（扫描 {scanned}/{files.Count} 个文件，失败 {failed}，共见到 {treesSeen} 棵表达式树）-> {jsonOutPath}");
    return 0;
}

// exprrotationstats 子命令：抓全语料里 Transform3DExpression 驱动 rotationX/Y/Z 的公式原文，
// 给 Python 侧判断"公式字面量到底是角度还是弧度"当真实证据用——不是猜。背景：`LocalRotation`
// 的**静态**存储值已经字节级确认是弧度制（取值精确落在 π 的有理数倍上），但用户实测一条
// `Lerp(Clamp(TIMER,120,0),190,-30)` 转出了每帧 105° 的"疯狂转圈"，怀疑 Expression 公式
// 里的字面量走的是完全不同的单位（度数）——EFX 里"同一个概念、不同子系统各用一套约定"不是
// 孤例（static/random vs min/max、闭区间/半开区间都各玩各的），不能想当然套用静态字段那一套。
// 只扫 `Transform3DExpression`：bit 3/4/5 = rotationX/Y/Z（`EfxTransform.cs:118`，
// Python 侧 `efx_sim/simulator.py::_EXPR_FIELD_OVERRIDES` 同一份映射），bit 序号对应
// `ExpressionBits.GetExpressionInts()` 的枚举顺序，和 `ParsedExpressions` 列表下标一一对应
// （`BitSet` 只存"哪些位置位"，`ParsedExpressions` 只存"置位的那些"，顺序天然对齐）。
//
//   exprrotationstats <语料目录> <json 输出路径>
static int RunExprRotationStats(string[] args)
{
    if (args.Length < 3)
    {
        Console.WriteLine("用法: dotnet <dll> exprrotationstats <语料目录> <json 输出路径>");
        return 1;
    }
    var dir = args[1];
    var jsonOutPath = args[2];
    if (!Directory.Exists(dir))
    {
        Console.WriteLine($"目录不存在: {dir}");
        return 1;
    }

    var files = Directory.EnumerateFiles(dir, "*.efx.*", SearchOption.AllDirectories).ToList();
    var rotationBitNames = new Dictionary<int, string> { [3] = "rotationX", [4] = "rotationY", [5] = "rotationZ" };
    var examples = new List<object>();
    int scanned = 0, failed = 0, rotationFormulasSeen = 0;
    string currentPath = "";

    void Visit(EFXEntryBase container)
    {
        foreach (var attr in container.Attributes)
        {
            if (attr is EFXAttributeTransform3DExpression texpr
                && texpr.Expression?.ParsedExpressions is { } trees)
            {
                var bitIndices = texpr.ExpressionBits.GetExpressionInts().ToList();
                for (int k = 0; k < trees.Count && k < bitIndices.Count; k++)
                {
                    if (!rotationBitNames.TryGetValue(bitIndices[k], out var bitName)) continue;
                    rotationFormulasSeen++;
                    var assignType = bitName switch
                    {
                        "rotationX" => (int)texpr.rotationX,
                        "rotationY" => (int)texpr.rotationY,
                        "rotationZ" => (int)texpr.rotationZ,
                        _ => -1,
                    };
                    examples.Add(new
                    {
                        file = currentPath,
                        bitName,
                        assignType,
                        formula = trees[k].ToString(),
                    });
                }
            }
            if (attr is EFXAttributePlayEmitter { efxrData: not null } pe)
            {
                foreach (var e in pe.efxrData.Entries) Visit(e);
                foreach (var a in pe.efxrData.Actions) Visit(a);
            }
        }
    }

    foreach (var path in files)
    {
        currentPath = path;
        try
        {
            var efx = new EfxFile(new FileHandler(path));
            efx.Read();
            efx.ParseExpressions();
            scanned++;
            foreach (var e in efx.Entries) Visit(e);
            foreach (var a in efx.Actions) Visit(a);
        }
        catch (Exception)
        {
            failed++;
        }
    }

    var payload = new
    {
        filesTotal = files.Count,
        filesScanned = scanned,
        filesFailed = failed,
        rotationFormulasSeen,
        examples,
    };
    File.WriteAllText(jsonOutPath, JsonSerializer.Serialize(payload, new JsonSerializerOptions { WriteIndented = true }));
    Console.WriteLine($"OK: 扫到 {rotationFormulasSeen} 条 Transform3DExpression 的 rotationX/Y/Z 公式"
                      + $"（扫描 {scanned}/{files.Count} 个文件，失败 {failed}）-> {jsonOutPath}");
    return 0;
}

// exprassignstats 子命令：给全语料里每个 IExpressionAttribute 实例的每一位 bit，交叉统计
// "这一位在 ExpressionBits 里到底有没有置位（即有没有一条真正绑定的公式）" x "同一个字段
// 自己存的 ExpressionAssignType 静态值（Add/Subtract/Multiply/Divide/Assign）"，
// 用来验证"是不是只有 Assign 才会真的吃公式结果、其余取值和公式互不相干"这个假说——
// 光看单个文件猜不出来，语料级的联合分布才是证据（不把猜测当事实）。
//
//   exprassignstats <语料目录> <json 输出路径>
//
// 字段顺序复用 bitnames 命令同一套反射（`ExpressionAssignType` 字段按 MetadataToken 排序），
// 不需要额外查 bitNames——这里只要下标对得上，不需要名字。
static int RunExprAssignStats(string[] args)
{
    if (args.Length < 3)
    {
        Console.WriteLine("用法: dotnet <dll> exprassignstats <语料目录> <json 输出路径>");
        return 1;
    }
    var dir = args[1];
    var jsonOutPath = args[2];

    if (!Directory.Exists(dir))
    {
        Console.WriteLine($"目录不存在: {dir}");
        return 1;
    }

    var files = Directory.EnumerateFiles(dir, "*.efx.*", SearchOption.AllDirectories).ToList();
    var fieldCache = new Dictionary<Type, List<FieldInfo>>();

    List<FieldInfo> GetAssignFields(Type type)
    {
        if (fieldCache.TryGetValue(type, out var cached)) return cached;
        var fields = type
            .GetFields(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.DeclaredOnly)
            .Where(f => f.FieldType == typeof(ExpressionAssignType))
            .OrderBy(f => f.MetadataToken)
            .ToList();
        fieldCache[type] = fields;
        return fields;
    }

    // attrType -> bitIndex -> "set"/"unset" -> assignTypeValue(string) -> count
    var stats = new Dictionary<string, Dictionary<int, Dictionary<string, Dictionary<string, int>>>>();
    int scanned = 0, failed = 0, instances = 0;
    // 结构性校验："一个字段最多只挂一条公式"这个假说的证据——BitSet 每一位只是个布尔位，
    // 数据结构上没有"同一位挂两条公式"的表达方式，这里核实置位数和实际公式对象数是否总是相等
    // （zip 消费时如果不等，_populate_expression_attribute() 会静默按短的那边截断）。
    int countMismatches = 0;
    var countMismatchExamples = new List<object>();
    string currentPath = "";

    void Bump(string attrType, int bitIndex, bool isSet, ExpressionAssignType value)
    {
        var byBit = stats.TryGetValue(attrType, out var bb) ? bb : (stats[attrType] = new());
        var byState = byBit.TryGetValue(bitIndex, out var bs) ? bs : (byBit[bitIndex] = new());
        var stateKey = isSet ? "set" : "unset";
        var byValue = byState.TryGetValue(stateKey, out var bv) ? bv : (byState[stateKey] = new());
        var valueKey = value.ToString();
        byValue[valueKey] = byValue.GetValueOrDefault(valueKey) + 1;
    }

    void Visit(EFXEntryBase container)
    {
        foreach (var attr in container.Attributes)
        {
            if (attr is IExpressionAttribute exprAttr)
            {
                instances++;
                var bits = exprAttr.ExpressionBits;
                var attrTypeName = attr.type.ToString();
                var fields = GetAssignFields(attr.GetType());
                for (int i = 0; i < fields.Count; i++)
                {
                    var value = (ExpressionAssignType)fields[i].GetValue(attr)!;
                    Bump(attrTypeName, i, bits.HasBit(i), value);
                }

                var setBitCount = bits.Count;
                var componentCount = exprAttr.Expression?.expressions.Count ?? 0;
                if (setBitCount != componentCount)
                {
                    countMismatches++;
                    if (countMismatchExamples.Count < 10)
                        countMismatchExamples.Add(new { file = currentPath, attrTypeName, setBitCount, componentCount });
                }
            }
            if (attr is EFXAttributePlayEmitter { efxrData: not null } pe)
            {
                foreach (var e in pe.efxrData.Entries) Visit(e);
                foreach (var a in pe.efxrData.Actions) Visit(a);
            }
        }
    }

    foreach (var path in files)
    {
        currentPath = path;
        try
        {
            var efx = new EfxFile(new FileHandler(path));
            efx.Read();
            scanned++;
            foreach (var e in efx.Entries) Visit(e);
            foreach (var a in efx.Actions) Visit(a);
        }
        catch (Exception)
        {
            failed++;  // 语料里本来就有一批读不了的，见 KNOWN_UPSTREAM_ISSUES
        }
    }

    var payload = new
    {
        filesTotal = files.Count,
        filesScanned = scanned,
        filesFailed = failed,
        instances,
        setBitCountVsComponentCountMismatches = countMismatches,
        mismatchExamples = countMismatchExamples,
        byAttrType = stats.OrderBy(kv => kv.Key).ToDictionary(
            kv => kv.Key,
            kv => kv.Value.OrderBy(b => b.Key).ToDictionary(b => b.Key.ToString(), b => b.Value)),
    };
    File.WriteAllText(jsonOutPath, JsonSerializer.Serialize(payload, new JsonSerializerOptions { WriteIndented = true }));
    Console.WriteLine($"OK: {instances} 个 IExpressionAttribute 实例（扫描 {scanned}/{files.Count} 个文件，失败 {failed}）-> {jsonOutPath}");
    return 0;
}

// exprhostcorr 子命令：给每个 `IExpressionAttribute` 的每一位 bit，统计它置位时**本体属性**
// （sibling，去掉类名里的 "Expression" 得到，和 vendor `EFXEntryBase.AddAttribute()` 同一套
// 判据）各字段的取值分布，外加公式原文 / entry 名 / efx 文件名的高频样本。
//
//   exprhostcorr <语料目录> <json 输出路径> [每桶保留的不同取值数，默认 10]
//
// 用来回答"这一位到底驱动本体的哪个字段"。vendor 的 `BitNameDict` 只给一部分 bit 起了名，
// 其余是 `unkn<N>` 占位；但**有名字的那些是现成的正对照**——同一套判据必须先把
// `speed -> Speed`、`velocityY -> DirectionVectorY` 这类已知答案重新推出来，才有资格拿去
// 推未知的。判据本身全部写在 `tools/infer_expression_bit_fields.py`（依据和结论分开，
// 同 `tools/audit_range_fields.py` 的先例），这里只吐原始计数、不做任何判断。
//
// 最硬的一条线索是 **Multiply 的退化性**：`Multiply` 把公式结果乘在字段**导入时的原值**上，
// 原值为 0 时结果恒为 0 —— 作者不会写恒为 0 的曲线。所以"这一位用 Multiply 驱动时，
// 候选字段出现过 0"就能把这个候选**排除**掉（`zeroUnderMultiply`）。这条对"中性值是 1"的
// 字段（`SpeedCoef` 那种）同样成立，因为 0 乘任何数还是 0。
static int RunExprHostCorr(string[] args)
{
    if (args.Length < 3)
    {
        Console.WriteLine("用法: dotnet <dll> exprhostcorr <语料目录> <json 输出路径> [每桶保留的不同取值数，默认 10]");
        return 1;
    }
    var dir = args[1];
    var jsonOutPath = args[2];
    var topN = args.Length >= 4 && int.TryParse(args[3], out var n) ? n : 10;

    if (!Directory.Exists(dir))
    {
        Console.WriteLine($"目录不存在: {dir}");
        return 1;
    }

    var files = Directory.EnumerateFiles(dir, "*.efx.*", SearchOption.AllDirectories).ToList();
    var assignFieldCache = new Dictionary<Type, List<FieldInfo>>();
    var hostFieldCache = new Dictionary<Type, List<FieldInfo>>();

    List<FieldInfo> AssignFields(Type type)
    {
        if (assignFieldCache.TryGetValue(type, out var cached)) return cached;
        var fields = type
            .GetFields(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.DeclaredOnly)
            .Where(f => f.FieldType == typeof(ExpressionAssignType))
            .OrderBy(f => f.MetadataToken)
            .ToList();
        assignFieldCache[type] = fields;
        return fields;
    }

    // 本体的"可比字段"：只收自己声明的、值类型/字符串的公开字段。基类那几个
    // （type/UniqueID/Version）和 BitSet / 列表 / 嵌套对象一律不收——它们不可能是公式目标，
    // 收进来只会把每个桶撑大一圈。
    List<FieldInfo> HostFields(Type type)
    {
        if (hostFieldCache.TryGetValue(type, out var cached)) return cached;
        var fields = type
            .GetFields(BindingFlags.Public | BindingFlags.Instance | BindingFlags.DeclaredOnly)
            .Where(f => (f.FieldType.IsValueType || f.FieldType == typeof(string))
                        && f.FieldType != typeof(EfxVersion))
            .OrderBy(f => f.MetadataToken)
            .ToList();
        hostFieldCache[type] = fields;
        return fields;
    }

    var perType = new Dictionary<string, TypeCorr>();
    int scanned = 0, failed = 0, instances = 0, hostMissing = 0;
    string currentFile = "";

    void Visit(EFXEntryBase container)
    {
        foreach (var attr in container.Attributes)
        {
            if (attr is IExpressionAttribute exprAttr)
            {
                instances++;
                var attrTypeName = attr.type.ToString();
                // vendor `AddAttribute()` 用的就是这个换算，不另发明一套
                var hostTypeName = attrTypeName.Replace("Expression", "");
                var host = container.Attributes.FirstOrDefault(a => a.type.ToString() == hostTypeName);
                if (host == null) hostMissing++;

                if (!perType.TryGetValue(attrTypeName, out var tc))
                    tc = perType[attrTypeName] = new TypeCorr { hostType = hostTypeName };
                tc.instances++;
                if (host == null) tc.hostMissing++;

                var hostFields = host == null ? new List<FieldInfo>() : HostFields(host.GetType());
                foreach (var hf in hostFields)
                    Tally(tc.hostBaseline, hf.Name, ValueKey(hf.GetValue(host)));

                var bits = exprAttr.ExpressionBits;
                var assignFields = AssignFields(attr.GetType());
                var formulas = exprAttr.Expression?.ParsedExpressions;
                int setSoFar = 0;
                for (int i = 0; i < assignFields.Count; i++)
                {
                    if (!bits.HasBit(i)) continue;
                    var assign = (ExpressionAssignType)assignFields[i].GetValue(attr)!;
                    var bc = tc.Bit(i, assignFields[i].Name);
                    bc.setCount++;
                    Tally(bc.assign, "", assign.ToString());
                    if (assign == ExpressionAssignType.Multiply) bc.multiplyCount++;

                    foreach (var hf in hostFields)
                    {
                        var value = hf.GetValue(host);
                        Tally(bc.hostFields, hf.Name, ValueKey(value));
                        var allZero = NumericComponents(value).All(c => c == 0.0);
                        if (allZero)
                        {
                            bc.ZeroCount(hf.Name);
                            if (assign == ExpressionAssignType.Multiply) bc.ZeroUnderMultiply(hf.Name);
                        }
                    }

                    // 置位顺序 <-> 公式顺序是既有约定（zip 消费），这里照同一个顺序取
                    if (formulas != null && setSoFar < formulas.Count)
                    {
                        var text = formulas[setSoFar]?.root?.ToString();
                        // 按 assign 分桶：`Assign` 那一桶的公式输出**就是字段的新值**，
                        // 是唯一能拿来和字段自己的取值分布对量级的样本；`Multiply` 桶里
                        // 的输出是无量纲倍率，混在一起量级就没法比了
                        if (!string.IsNullOrEmpty(text)) Tally(bc.formulas, assign.ToString(), text);
                    }
                    if (!string.IsNullOrEmpty(container.name)) Tally(bc.entryNames, "", container.name!);
                    Tally(bc.efxNames, "", Path.GetFileName(currentFile));
                    setSoFar++;
                }
            }
            if (attr is EFXAttributePlayEmitter { efxrData: not null } pe)
            {
                foreach (var e in pe.efxrData.Entries) Visit(e);
                foreach (var a in pe.efxrData.Actions) Visit(a);
            }
        }
    }

    foreach (var path in files)
    {
        currentFile = path;
        try
        {
            var efx = new EfxFile(new FileHandler(path));
            efx.Read();
            // 公式文本不在文件里，要 ParseExpressions() 把后缀栈还原成树才拿得到
            efx.ParseExpressions();
            scanned++;
            foreach (var e in efx.Entries) Visit(e);
            foreach (var a in efx.Actions) Visit(a);
        }
        catch (Exception)
        {
            failed++;   // 语料里本来就有一批读不了的，见 KNOWN_UPSTREAM_ISSUES
        }
    }

    var payload = new
    {
        filesTotal = files.Count,
        filesScanned = scanned,
        filesFailed = failed,
        instances,
        hostMissing,
        topN,
        types = perType.OrderBy(kv => kv.Key).ToDictionary(kv => kv.Key, kv => kv.Value.Render(topN)),
    };
    File.WriteAllText(jsonOutPath, JsonSerializer.Serialize(payload, new JsonSerializerOptions { WriteIndented = true }));
    Console.WriteLine($"OK: {instances} 个 IExpressionAttribute 实例、{perType.Count} 个类型"
                      + $"（本体缺失 {hostMissing}；扫描 {scanned}/{files.Count} 个文件，失败 {failed}）-> {jsonOutPath}");
    return 0;
}

// spawnringbuffer：一次性研究命令，回答"Spawn.RingBufferMode==true 的实例，所在 Entry
// 有什么特征"。按 RingBufferMode 的取值分两桶，桶内统计：
//   - 所在 Entry 的具名字符串（container.name）
//   - 同一个 Entry 上还挂了哪些其它 attribute 类型（兄弟 attribute，看画法/行为组合）
//   - 文件所在目录名（语料目录一般按"一个效果一个文件夹"组织，目录名常带风格提示）
//   - Spawn 自己其余字段的取值分布（对照两桶能不能看出 RingBufferMode 和某个字段联动）
// 用法跟 condstats 类似，但 condstats 只能看同一个 attribute 内部的字段，看不到"同一个
// Entry 上还有什么"，所以单独写一个命令。
static int RunSpawnRingBuffer(string[] args)
{
    if (args.Length < 3)
    {
        Console.WriteLine("用法: dotnet <dll> spawnringbuffer <语料目录> <json 输出路径> [每桶保留的不同取值数，默认 30]");
        return 1;
    }
    var dir = args[1];
    var jsonOutPath = args[2];
    var topN = args.Length >= 4 && int.TryParse(args[3], out var n) ? n : 30;

    if (!Directory.Exists(dir))
    {
        Console.WriteLine($"目录不存在: {dir}");
        return 1;
    }

    var files = Directory.EnumerateFiles(dir, "*.efx.*", SearchOption.AllDirectories).ToList();
    var spawnFields = typeof(EFXAttributeSpawn)
        .GetFields(BindingFlags.Public | BindingFlags.Instance | BindingFlags.DeclaredOnly)
        .Where(f => f.Name != "RingBufferMode" && (f.FieldType.IsValueType || f.FieldType == typeof(string)))
        .OrderBy(f => f.MetadataToken)
        .ToList();

    var buckets = new Dictionary<string, SpawnRingBucket>
    {
        ["True"] = new SpawnRingBucket(),
        ["False"] = new SpawnRingBucket(),
    };
    int scanned = 0, failed = 0, instances = 0;
    string currentFile = "";
    string currentDirName = "";

    void Visit(EFXEntryBase container)
    {
        foreach (var attr in container.Attributes)
        {
            if (attr is EFXAttributeSpawn spawn)
            {
                instances++;
                var key = spawn.RingBufferMode ? "True" : "False";
                var b = buckets[key];
                b.count++;
                if (!string.IsNullOrEmpty(container.name)) Tally(b.entryNames, "", container.name!);
                Tally(b.dirNames, "", currentDirName);
                Tally(b.fileNames, "", Path.GetFileName(currentFile));
                foreach (var sibling in container.Attributes)
                {
                    if (ReferenceEquals(sibling, attr)) continue;
                    Tally(b.siblingTypes, "", sibling.type.ToString());
                }
                foreach (var f in spawnFields)
                    Tally(b.fields, f.Name, ValueKey(f.GetValue(spawn)));
            }
            if (attr is EFXAttributePlayEmitter { efxrData: not null } pe)
            {
                foreach (var e in pe.efxrData.Entries) Visit(e);
                foreach (var a in pe.efxrData.Actions) Visit(a);
            }
        }
    }

    foreach (var path in files)
    {
        currentFile = path;
        currentDirName = Path.GetFileName(Path.GetDirectoryName(path)) ?? "";
        try
        {
            var efx = new EfxFile(new FileHandler(path));
            efx.Read();
            scanned++;
            foreach (var e in efx.Entries) Visit(e);
            foreach (var a in efx.Actions) Visit(a);
        }
        catch (Exception)
        {
            failed++;
        }
    }

    Dictionary<string, object> RenderBucket(SpawnRingBucket b) => new()
    {
        ["count"] = b.count,
        ["entryNames"] = TopN(b.entryNames.GetValueOrDefault(""), topN),
        ["siblingAttrTypes"] = TopN(b.siblingTypes.GetValueOrDefault(""), topN),
        ["dirNames"] = TopN(b.dirNames.GetValueOrDefault(""), topN),
        ["fileNames"] = TopN(b.fileNames.GetValueOrDefault(""), topN),
        ["fields"] = b.fields.OrderBy(kv => kv.Key)
            .ToDictionary(kv => kv.Key, kv => TopN(kv.Value, topN)),
    };

    var payload = new
    {
        filesTotal = files.Count,
        filesScanned = scanned,
        filesFailed = failed,
        spawnInstances = instances,
        topN,
        ringBufferTrue = RenderBucket(buckets["True"]),
        ringBufferFalse = RenderBucket(buckets["False"]),
    };
    File.WriteAllText(jsonOutPath, JsonSerializer.Serialize(payload, new JsonSerializerOptions { WriteIndented = true }));
    Console.WriteLine($"OK: {instances} 个 Spawn 实例（RingBufferMode=true 的 {buckets["True"].count} 个，"
                      + $"false 的 {buckets["False"].count} 个；扫描 {scanned}/{files.Count} 个文件，失败 {failed}）-> {jsonOutPath}");
    return 0;
}

static List<KeyValuePair<string, int>> TopN(Dictionary<string, int>? hist, int n)
    => hist == null ? new() : hist.OrderByDescending(kv => kv.Value).Take(n).ToList();

static void Tally(Dictionary<string, Dictionary<string, int>> buckets, string bucket, string key)
{
    if (!buckets.TryGetValue(bucket, out var hist)) hist = buckets[bucket] = new();
    hist[key] = hist.GetValueOrDefault(key) + 1;
}

// 值 -> 数值分量序列。用来判"这个字段是不是整个为 0"（Multiply 退化判据）。
// 值类型按公开字段递归展开（`via.Range` 的 s/r、`Vector3` 的 X/Y/Z 都走这条），
// 引用类型不展开（返回空序列 = 不参与零值判断）。
static IEnumerable<double> NumericComponents(object? v)
{
    if (v == null) yield break;
    var t = v.GetType();
    if (t == typeof(string)) { yield return ((string)v).Length; yield break; }
    if (t.IsEnum || t.IsPrimitive) { yield return Convert.ToDouble(v); yield break; }
    if (t.IsValueType)
    {
        foreach (var f in t.GetFields(BindingFlags.Public | BindingFlags.Instance))
            foreach (var c in NumericComponents(f.GetValue(v)))
                yield return c;
    }
}

// 值 -> 稳定的字符串键（直方图用）。`float` 固定 G6，避免 `0.30000001` 和 `0.3` 分成两桶。
static string ValueKey(object? v)
{
    if (v == null) return "null";
    var t = v.GetType();
    if (t.IsEnum) return v.ToString()!;
    if (v is float f) return f.ToString("G6", System.Globalization.CultureInfo.InvariantCulture);
    if (v is double d) return d.ToString("G6", System.Globalization.CultureInfo.InvariantCulture);
    if (v is string s) return s.Length == 0 ? "\"\"" : "\"" + s + "\"";
    if (t.IsPrimitive) return Convert.ToString(v, System.Globalization.CultureInfo.InvariantCulture)!;
    if (t.IsValueType)
        return "(" + string.Join(",", t.GetFields(BindingFlags.Public | BindingFlags.Instance)
                                       .Select(x => ValueKey(x.GetValue(v)))) + ")";
    return t.Name;
}

// fieldstatsbatch 子命令：一次扫描里同时给一批 attribute 类型做 fieldstats。
//
// 单独调 fieldstats N 次会把语料重新解析 N 遍（解析耗时跟"要不要过滤这个类型"无关，
// 过滤只影响要不要 Tally，不影响读文件本身），N=40 就是 40 倍的 IO/反序列化开销。
// 这里把 fieldstats 的 Tally/Bump 逻辑原样搬过来，只是按类型分桶，一遍扫描出全部结果。
//
//   fieldstatsbatch <语料目录> <逗号分隔的类型名列表> <json 输出路径> [每字段保留的不同取值数，默认 40]
//
// 输出结构：{ "<类型名>": { instances, fields: {...} }, ... }，跟单个 fieldstats 的
// "fields" 部分同构，方便复用现有的众数提取代码。
static int RunFieldStatsBatch(string[] args)
{
    if (args.Length < 4)
    {
        Console.WriteLine("用法: dotnet <dll> fieldstatsbatch <语料目录> <逗号分隔的类型名列表> <json 输出路径> [每字段保留的不同取值数，默认 40]");
        return 1;
    }
    var dir = args[1];
    var typeNames = args[2].Split(',', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries);
    var jsonOutPath = args[3];
    var maxDistinct = args.Length >= 5 && int.TryParse(args[4], out var md) ? md : 40;

    if (!Directory.Exists(dir))
    {
        Console.WriteLine($"目录不存在: {dir}");
        return 1;
    }

    var wanted = new Dictionary<EfxAttributeType, string>();
    foreach (var typeName in typeNames)
    {
        if (!Enum.TryParse<EfxAttributeType>(typeName, true, out var t))
        {
            Console.WriteLine($"[ERROR] 未知的 attribute 类型名: {typeName}");
            return 1;
        }
        wanted[t] = typeName;
    }

    var options = CreateBridgeJsonOptions();
    var files = Directory.EnumerateFiles(dir, "*.efx.*", SearchOption.AllDirectories).ToList();
    // 每个类型独立一份直方图集合，key 是字段路径
    var histograms = new Dictionary<EfxAttributeType, Dictionary<string, Dictionary<string, int>>>();
    var instances = new Dictionary<EfxAttributeType, int>();
    foreach (var t in wanted.Keys)
    {
        histograms[t] = new Dictionary<string, Dictionary<string, int>>();
        instances[t] = 0;
    }
    int scanned = 0, failed = 0, totalAttrInstances = 0;

    void Tally(Dictionary<string, Dictionary<string, int>> hist, System.Text.Json.Nodes.JsonNode? node, string path)
    {
        switch (node)
        {
            case System.Text.Json.Nodes.JsonObject obj:
                foreach (var (key, child) in obj)
                {
                    if (key == "$type") continue;
                    Tally(hist, child, path.Length == 0 ? key : path + "." + key);
                }
                break;
            case System.Text.Json.Nodes.JsonArray arr:
                Bump(hist, path + "[].length", arr.Count.ToString());
                break;
            case null:
                Bump(hist, path, "null");
                break;
            default:
                Bump(hist, path, node.ToJsonString());
                break;
        }
    }

    void Bump(Dictionary<string, Dictionary<string, int>> hist, string path, string value)
    {
        if (!hist.TryGetValue(path, out var h))
            hist[path] = h = new Dictionary<string, int>();
        h[value] = h.GetValueOrDefault(value) + 1;
    }

    void Visit(EFXEntryBase container)
    {
        foreach (var attr in container.Attributes)
        {
            totalAttrInstances++;  // 全部类型都计数，用来算下面的 instancePercent
            if (wanted.ContainsKey(attr.type))
            {
                instances[attr.type]++;
                var json = JsonSerializer.Serialize(attr, typeof(EFXAttribute), options);
                Tally(histograms[attr.type], System.Text.Json.Nodes.JsonNode.Parse(json), "");
            }
            if (attr is EFXAttributePlayEmitter { efxrData: not null } pe)
            {
                foreach (var e in pe.efxrData.Entries) Visit(e);
                foreach (var a in pe.efxrData.Actions) Visit(a);
            }
        }
    }

    foreach (var path in files)
    {
        try
        {
            var efx = new EfxFile(new FileHandler(path));
            efx.Read();
            scanned++;
            foreach (var e in efx.Entries) Visit(e);
            foreach (var a in efx.Actions) Visit(a);
        }
        catch (Exception)
        {
            failed++;  // 语料里本来就有一批读不了的，见 KNOWN_UPSTREAM_ISSUES
        }
    }

    // 频率排名按本次批次内部（这批 instances 降序）来算——如果传的就是 typefreq 的
    // 前 N 名，这个 rank 天然就是全语料排名；传别的子集时它只是"这批里的相对排名"。
    var rankOf = wanted.Keys
        .OrderByDescending(t => instances[t])
        .Select((t, i) => (t, rank: i + 1))
        .ToDictionary(x => x.t, x => x.rank);

    var payload = wanted.ToDictionary(
        kv => kv.Value,
        kv => new
        {
            instances = instances[kv.Key],
            // 出现频率：占本次扫描到的全部 attribute 实例（不限于这批类型）的百分比，
            // 跟 typefreq 输出的 counts 是同一套分母，可以直接对照。
            instancePercent = totalAttrInstances > 0
                ? Math.Round(instances[kv.Key] * 100.0 / totalAttrInstances, 4)
                : 0.0,
            rank = rankOf[kv.Key],
            fields = histograms[kv.Key].ToDictionary(
                h => h.Key,
                h => new
                {
                    distinct = h.Value.Count,
                    top = h.Value.OrderByDescending(x => x.Value).Take(maxDistinct)
                            .ToDictionary(x => x.Key, x => x.Value),
                }),
        });
    var envelope = new
    {
        filesTotal = files.Count,
        filesScanned = scanned,
        filesFailed = failed,
        totalAttrInstances,
        types = payload,
    };
    File.WriteAllText(jsonOutPath, JsonSerializer.Serialize(envelope, new JsonSerializerOptions { WriteIndented = true }));
    Console.WriteLine($"OK: {wanted.Count} 种类型（扫描 {scanned}/{files.Count} 个文件，失败 {failed}）-> {jsonOutPath}");
    return 0;
}

// instancedefaults 子命令：给"新建 attribute 用什么默认值"换一条不同的生成策略——不是逐字段
// 独立取众数再拼回零值结构（那样会拆散字段耦合：某个开关字段本身是 0 时，另一组字段可能
// 从来不是全 0——逐字段各自取众数完全可能拼出语料里从没出现过的假组合，见用户原话
// "分块默认值可能恰好让一些非0值字段没法作用"），而是先算出逐字段众数向量，再从语料里挑一份
// "跟众数向量最贴近的真实实例"整份抄下来——保证落地的默认值是游戏文件里真实存在过的字段
// 组合，不是统计拼出来的。分两遍扫描：第一遍复用 fieldstatsbatch 的直方图逻辑算众数向量，
// 第二遍按众数向量给每份实例打分（匹配上的叶子字段数），只留分数最高的那份（整份 JSON，不
// 是众数向量本身）。判断"这个字段是否等于全语料最常见取值"不需要知道字段含义，所以这条流程
// 可以覆盖全部 282 个类型（包括语义完全未标注的字段）——我们限制的是语义结论，不是这种
// 纯字节层面的"复制一份真实存在过的实例"。
//
// clipeventstats — raw=3（Event，共享枚举里叫 Event）严格来说不是真正的曲线形状（vendor 自己
// 注释 "found at end"），但语料里用得很频繁（clipinterpstats 已经看到几千次），需要单独看它在
// 每条曲线内部"长在哪个位置、和邻居帧的值什么关系"，才能判断它该归进"能用原生 fcurve 编辑的
// 标准曲线"（如果表现纯粹是"保持值不变+在这一帧触发点什么"，可以用 CONSTANT + 一个额外标记
// 代表）还是该归"非标准，暂不做"。2026-09-19 用户明确要求先看分布再分类。
//
//   clipeventstats <语料目录> <json 输出路径>
static int RunClipEventStats(string[] args)
{
    if (args.Length < 3)
    {
        Console.WriteLine("用法: dotnet <dll> clipeventstats <语料目录> <json 输出路径>");
        return 1;
    }
    var dir = args[1];
    var jsonOutPath = args[2];
    if (!Directory.Exists(dir))
    {
        Console.WriteLine($"目录不存在: {dir}");
        return 1;
    }

    const int EventType = 3;
    var files = Directory.EnumerateFiles(dir, "*.efx.*", SearchOption.AllDirectories).ToList();
    int scanned = 0, failed = 0, curvesWithEvent = 0, eventFrames = 0;
    var positionHist = new Dictionary<string, int>();      // "first"/"middle"/"last"/"only"
    var valueVsPrevHist = new Dictionary<string, int>();   // "no_prev"/"equal_prev"/"different_prev"
    var valueVsNextHist = new Dictionary<string, int>();   // "no_next"/"equal_next"/"different_next"
    var valueTypeHist = new Dictionary<string, int>();     // Int / Float
    var attrTypeHist = new Dictionary<string, int>();
    var sampleValues = new List<double>();                 // 只存前 200 个，看看数值本身长什么样

    static void Bump(Dictionary<string, int> hist, string key) => hist[key] = hist.GetValueOrDefault(key) + 1;

    void VisitAttr(EFXAttribute attr)
    {
        if (attr is not IClipAttribute clipAttr) return;
        var clipData = clipAttr.Clip;
        var headers = clipData.clips ?? Array.Empty<EfxClipHeader>();
        var frames = clipData.frames ?? Array.Empty<EfxClipFrame>();
        var typeName = attr.type.ToString();
        int frameIndex = 0;
        foreach (var header in headers)
        {
            int start = frameIndex;
            int count = header.frameCount;
            bool sawEvent = false;
            for (int f = 0; f < count && frameIndex < frames.Length; ++f)
            {
                int i = frameIndex++;
                if (frames[i].type != (FrameInterpolationType)EventType) continue;
                sawEvent = true;
                eventFrames++;
                Bump(valueTypeHist, header.valueType.ToString());
                Bump(attrTypeHist, typeName);

                string pos = count == 1 ? "only" : i == start ? "first" : i == start + count - 1 ? "last" : "middle";
                Bump(positionHist, pos);

                double v = frames[i].AsFloat(header.valueType);
                if (sampleValues.Count < 200) sampleValues.Add(v);

                if (i == start)
                {
                    Bump(valueVsPrevHist, "no_prev");
                }
                else
                {
                    double prev = frames[i - 1].AsFloat(header.valueType);
                    Bump(valueVsPrevHist, Math.Abs(prev - v) < 1e-6 ? "equal_prev" : "different_prev");
                }
                if (i == start + count - 1)
                {
                    Bump(valueVsNextHist, "no_next");
                }
                else
                {
                    double next = frames[i + 1].AsFloat(header.valueType);
                    Bump(valueVsNextHist, Math.Abs(next - v) < 1e-6 ? "equal_next" : "different_next");
                }
            }
            if (sawEvent) curvesWithEvent++;
        }
    }

    void Visit(EFXEntryBase container)
    {
        foreach (var attr in container.Attributes)
        {
            VisitAttr(attr);
            if (attr is EFXAttributePlayEmitter { efxrData: not null } pe)
            {
                foreach (var e in pe.efxrData.Entries) Visit(e);
                foreach (var a in pe.efxrData.Actions) Visit(a);
            }
        }
    }

    foreach (var path in files)
    {
        try
        {
            var efx = new EfxFile(new FileHandler(path));
            efx.Read();
            scanned++;
            foreach (var e in efx.Entries) Visit(e);
            foreach (var a in efx.Actions) Visit(a);
        }
        catch (Exception)
        {
            failed++;
        }
    }

    var payload = new
    {
        filesTotal = files.Count,
        filesScanned = scanned,
        filesFailed = failed,
        curvesWithEvent,
        eventFrames,
        positionHist,
        valueVsPrevHist,
        valueVsNextHist,
        valueTypeHist,
        attrTypeHist,
        sampleValues,
    };

    File.WriteAllText(jsonOutPath, JsonSerializer.Serialize(payload, new JsonSerializerOptions { WriteIndented = true }));
    Console.WriteLine($"scanned={scanned} failed={failed} curvesWithEvent={curvesWithEvent} eventFrames={eventFrames} -> {jsonOutPath}");
    return 0;
}

// clipinterpstats — 按 bit_index 统计**全部** IClipAttribute 类型（不只 Transform3DClip/
// PtTransform3DClip，是全部 12 个实现了 IClipAttribute 的 attribute 类型）的
// FrameInterpolationType 实际取值分布，用来交叉验证"FrameInterpolationType 和独立 .clip/.tml
// 共用同一套枚举"这个假设——第一版只扫了 Transform3D 那两个类型，会漏看其它 Clip 类型（比如
// PtColorClip/PtVelocity3DClip/AttractorClip）有没有用过 Transform3D 系列从没出现过的原始值
// （2026-09-19 用户指出这个盲区）。role（position/rotation/scale/other）的分类只对 bit 顺序已经
// 实机确认过的 Transform3D 系列有意义（见 `blender_efx_re/clip_fcurve.py` 的
// `_TRANSFORM3D_CLIP_XFORM` 和 `PtTransform3DExpression` 的 `BitNameDict`），其它类型的 bit
// 落进 "other"，靠 byAttributeType 那份按类型名分开的统计单独看。
//
//   clipinterpstats <语料目录> <json 输出路径>
static int RunClipInterpStats(string[] args)
{
    if (args.Length < 3)
    {
        Console.WriteLine("用法: dotnet <dll> clipinterpstats <语料目录> <json 输出路径>");
        return 1;
    }
    var dir = args[1];
    var jsonOutPath = args[2];
    if (!Directory.Exists(dir))
    {
        Console.WriteLine($"目录不存在: {dir}");
        return 1;
    }

    var files = Directory.EnumerateFiles(dir, "*.efx.*", SearchOption.AllDirectories).ToList();
    int scanned = 0, failed = 0, instances = 0;
    // role ("position"/"rotation"/"scale") -> bitIndex -> rawInterpType -> count
    var byRole = new Dictionary<string, Dictionary<int, Dictionary<int, int>>>();
    // attribute 类型名 -> bitIndex -> rawInterpType -> count（避免把 Transform3DClip 和
    // PtTransform3DClip 的 9 位混在一起，万一两者 bit 顺序其实不一样也能看出来）
    var byAttrType = new Dictionary<string, Dictionary<int, Dictionary<int, int>>>();

    static void Bump(Dictionary<int, int> hist, int key) => hist[key] = hist.GetValueOrDefault(key) + 1;

    static string RoleOf(EfxAttributeType type, int bitIndex)
    {
        // 只有这两个类型的 bit 顺序被实机确认过是"3 位移+3 旋转+3 缩放"；其它类型的 BitSet
        // 是各自独立定义的字段布局，同一个数字 bitIndex 在别的类型上完全是另一件事，不能套用
        // 这张表——分类不到就统一归 "other"，靠 byAttributeType 单独看。
        if (type != EfxAttributeType.Transform3DClip && type != EfxAttributeType.PtTransform3DClip)
            return "other";
        return bitIndex switch
        {
            0 or 1 or 2 => "position",
            3 or 4 or 5 => "rotation",
            6 or 7 or 8 => "scale",
            _ => "other",
        };
    }

    void VisitAttr(EFXAttribute attr)
    {
        if (attr is not IClipAttribute clipAttr) return;

        instances++;
        var activeBits = clipAttr.ClipBits.GetExpressionInts().OrderBy(i => i).ToList();
        var clipData = clipAttr.Clip;
        var headers = clipData.clips ?? Array.Empty<EfxClipHeader>();
        var frames = clipData.frames ?? Array.Empty<EfxClipFrame>();
        var typeName = attr.type.ToString();
        int frameIndex = 0;
        for (int i = 0; i < headers.Length && i < activeBits.Count; ++i)
        {
            var header = headers[i];
            var bitIndex = activeBits[i];
            var role = RoleOf(attr.type, bitIndex);
            for (int f = 0; f < header.frameCount && frameIndex < frames.Length; ++f)
            {
                var rawType = (int)frames[frameIndex++].type;

                if (!byRole.TryGetValue(role, out var roleBits))
                    byRole[role] = roleBits = new Dictionary<int, Dictionary<int, int>>();
                if (!roleBits.TryGetValue(bitIndex, out var hist))
                    roleBits[bitIndex] = hist = new Dictionary<int, int>();
                Bump(hist, rawType);

                if (!byAttrType.TryGetValue(typeName, out var typeBits))
                    byAttrType[typeName] = typeBits = new Dictionary<int, Dictionary<int, int>>();
                if (!typeBits.TryGetValue(bitIndex, out var thist))
                    typeBits[bitIndex] = thist = new Dictionary<int, int>();
                Bump(thist, rawType);
            }
        }
    }

    void Visit(EFXEntryBase container)
    {
        foreach (var attr in container.Attributes)
        {
            VisitAttr(attr);
            if (attr is EFXAttributePlayEmitter { efxrData: not null } pe)
            {
                foreach (var e in pe.efxrData.Entries) Visit(e);
                foreach (var a in pe.efxrData.Actions) Visit(a);
            }
        }
    }

    foreach (var path in files)
    {
        try
        {
            var efx = new EfxFile(new FileHandler(path));
            efx.Read();
            scanned++;
            foreach (var e in efx.Entries) Visit(e);
            foreach (var a in efx.Actions) Visit(a);
        }
        catch (Exception)
        {
            failed++;  // 语料里本来就有一批读不了的，见 KNOWN_UPSTREAM_ISSUES
        }
    }

    static Dictionary<string, Dictionary<string, int>> Flatten(Dictionary<int, Dictionary<int, int>> bits) =>
        bits.OrderBy(b => b.Key).ToDictionary(
            b => b.Key.ToString(),
            b => b.Value.OrderBy(t => t.Key).ToDictionary(t => t.Key.ToString(), t => t.Value));

    var payload = new
    {
        filesTotal = files.Count,
        filesScanned = scanned,
        filesFailed = failed,
        instances,
        byRole = byRole.OrderBy(r => r.Key).ToDictionary(r => r.Key, r => Flatten(r.Value)),
        byAttributeType = byAttrType.OrderBy(r => r.Key).ToDictionary(r => r.Key, r => Flatten(r.Value)),
    };

    File.WriteAllText(jsonOutPath, JsonSerializer.Serialize(payload, new JsonSerializerOptions { WriteIndented = true }));
    Console.WriteLine($"scanned={scanned} failed={failed} instances={instances} -> {jsonOutPath}");
    return 0;
}

//   instancedefaults <语料目录> <逗号分隔的类型名列表|all> <json 输出路径>
static int RunInstanceDefaults(string[] args)
{
    if (args.Length < 4)
    {
        Console.WriteLine("用法: dotnet <dll> instancedefaults <语料目录> <逗号分隔的类型名列表|all> <json 输出路径>");
        return 1;
    }
    var dir = args[1];
    var typeArg = args[2];
    var jsonOutPath = args[3];

    if (!Directory.Exists(dir))
    {
        Console.WriteLine($"目录不存在: {dir}");
        return 1;
    }

    var wanted = new Dictionary<EfxAttributeType, string>();
    if (typeArg == "all")
    {
        foreach (EfxAttributeType t in Enum.GetValues(typeof(EfxAttributeType)))
            wanted[t] = t.ToString();
    }
    else
    {
        foreach (var typeName in typeArg.Split(',', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries))
        {
            if (!Enum.TryParse<EfxAttributeType>(typeName, true, out var t))
            {
                Console.WriteLine($"[ERROR] 未知的 attribute 类型名: {typeName}");
                return 1;
            }
            wanted[t] = typeName;
        }
    }

    // 记账字段：type/Version/UniqueID/IsTypeAttribute。不参与众数/打分，也不进最终输出——
    // 它们该由创建逻辑自己填（尤其 UniqueID，抄某一份实例当时的值等于让两份文件共享同一个 ID）。
    var bookkeeping = new HashSet<string> { "type", "Version", "UniqueID", "IsTypeAttribute" };

    var options = CreateBridgeJsonOptions();
    // 排序保证跨次运行文件遍历顺序一致——打分打平时"先出现的赢"才是确定性的，不依赖文件系统
    // 底层的目录遍历顺序（不同操作系统/文件系统不保证一致）。
    var files = Directory.EnumerateFiles(dir, "*.efx.*", SearchOption.AllDirectories)
        .OrderBy(p => p, StringComparer.Ordinal).ToList();

    // ---------- 第一遍：逐字段众数直方图（逻辑照抄 fieldstatsbatch）----------
    var histograms = new Dictionary<EfxAttributeType, Dictionary<string, Dictionary<string, int>>>();
    var instanceCounts = new Dictionary<EfxAttributeType, int>();
    foreach (var t in wanted.Keys)
    {
        histograms[t] = new Dictionary<string, Dictionary<string, int>>();
        instanceCounts[t] = 0;
    }

    void Bump(Dictionary<string, Dictionary<string, int>> hist, string path, string value)
    {
        if (!hist.TryGetValue(path, out var h))
            hist[path] = h = new Dictionary<string, int>();
        h[value] = h.GetValueOrDefault(value) + 1;
    }

    void Tally(Dictionary<string, Dictionary<string, int>> hist, System.Text.Json.Nodes.JsonNode? node, string path)
    {
        switch (node)
        {
            case System.Text.Json.Nodes.JsonObject obj:
                foreach (var (key, child) in obj)
                {
                    if (key == "$type" || (path.Length == 0 && bookkeeping.Contains(key))) continue;
                    Tally(hist, child, path.Length == 0 ? key : path + "." + key);
                }
                break;
            case System.Text.Json.Nodes.JsonArray arr:
                Bump(hist, path + "[].length", arr.Count.ToString());
                break;
            case null:
                Bump(hist, path, "null");
                break;
            default:
                Bump(hist, path, node.ToJsonString());
                break;
        }
    }

    void VisitPass1(EFXEntryBase container)
    {
        foreach (var attr in container.Attributes)
        {
            if (wanted.ContainsKey(attr.type))
            {
                instanceCounts[attr.type]++;
                var json = JsonSerializer.Serialize(attr, typeof(EFXAttribute), options);
                Tally(histograms[attr.type], System.Text.Json.Nodes.JsonNode.Parse(json), "");
            }
            if (attr is EFXAttributePlayEmitter { efxrData: not null } pe)
            {
                foreach (var e in pe.efxrData.Entries) VisitPass1(e);
                foreach (var a in pe.efxrData.Actions) VisitPass1(a);
            }
        }
    }

    int scanned1 = 0, failed1 = 0;
    foreach (var path in files)
    {
        try
        {
            var efx = new EfxFile(new FileHandler(path));
            efx.Read();
            scanned1++;
            foreach (var e in efx.Entries) VisitPass1(e);
            foreach (var a in efx.Actions) VisitPass1(a);
        }
        catch (Exception) { failed1++; }
    }

    // 每个类型一份众数向量：字段路径 -> 出现次数最多的取值（原始 JSON 字面量字符串）。
    var modeVectors = new Dictionary<EfxAttributeType, Dictionary<string, string>>();
    foreach (var (t, hist) in histograms)
    {
        var mode = new Dictionary<string, string>();
        foreach (var (fieldPath, counts) in hist)
        {
            if (counts.Count == 0) continue;
            var (modeVal, _) = counts.OrderByDescending(kv => kv.Value).First();
            mode[fieldPath] = modeVal;
        }
        modeVectors[t] = mode;
    }

    // ---------- 第二遍：找一份跟众数向量最贴近的真实实例，整份留下来 ----------
    var best = new Dictionary<EfxAttributeType, (int score, int totalFields, string sourceFile, System.Text.Json.Nodes.JsonObject instance)>();

    void ScoreAndRecord(EfxAttributeType t, EFXAttribute attr, string sourceFile)
    {
        var json = JsonSerializer.Serialize(attr, typeof(EFXAttribute), options);
        if (System.Text.Json.Nodes.JsonNode.Parse(json) is not System.Text.Json.Nodes.JsonObject obj) return;

        var flat = new Dictionary<string, string>();
        void Flatten(System.Text.Json.Nodes.JsonNode? n, string path)
        {
            switch (n)
            {
                case System.Text.Json.Nodes.JsonObject o:
                    foreach (var (key, child) in o)
                    {
                        if (key == "$type" || (path.Length == 0 && bookkeeping.Contains(key))) continue;
                        Flatten(child, path.Length == 0 ? key : path + "." + key);
                    }
                    break;
                case System.Text.Json.Nodes.JsonArray arr:
                    flat[path + "[].length"] = arr.Count.ToString();
                    break;
                case null:
                    flat[path] = "null";
                    break;
                default:
                    flat[path] = n.ToJsonString();
                    break;
            }
        }
        Flatten(obj, "");

        var mode = modeVectors[t];
        int score = 0;
        foreach (var (path, val) in flat)
        {
            if (mode.TryGetValue(path, out var modeVal) && modeVal == val) score++;
        }

        if (!best.TryGetValue(t, out var current) || score > current.score)
        {
            var trimmed = new System.Text.Json.Nodes.JsonObject();
            foreach (var (key, child) in obj)
            {
                if (key == "$type" || bookkeeping.Contains(key)) continue;
                trimmed[key] = child?.DeepClone();
            }
            best[t] = (score, flat.Count, sourceFile, trimmed);
        }
    }

    void VisitPass2(EFXEntryBase container, string sourceFile)
    {
        foreach (var attr in container.Attributes)
        {
            if (wanted.ContainsKey(attr.type))
            {
                ScoreAndRecord(attr.type, attr, sourceFile);
            }
            if (attr is EFXAttributePlayEmitter { efxrData: not null } pe)
            {
                foreach (var e in pe.efxrData.Entries) VisitPass2(e, sourceFile);
                foreach (var a in pe.efxrData.Actions) VisitPass2(a, sourceFile);
            }
        }
    }

    int scanned2 = 0, failed2 = 0;
    foreach (var path in files)
    {
        try
        {
            var efx = new EfxFile(new FileHandler(path));
            efx.Read();
            scanned2++;
            foreach (var e in efx.Entries) VisitPass2(e, path);
            foreach (var a in efx.Actions) VisitPass2(a, path);
        }
        catch (Exception) { failed2++; }
    }

    var payload = new Dictionary<string, object?>();
    foreach (var (t, name) in wanted)
    {
        if (!best.TryGetValue(t, out var b))
        {
            payload[name] = null; // 语料里一次都没出现过这个类型
            continue;
        }
        payload[name] = new
        {
            instances = instanceCounts[t],
            matchScore = b.score,
            totalFields = b.totalFields,
            sourceFile = b.sourceFile,
            instance = b.instance,
        };
    }

    var envelope = new
    {
        filesTotal = files.Count,
        filesScanned = scanned2,
        filesFailed = failed2,
        types = payload,
    };
    File.WriteAllText(jsonOutPath, JsonSerializer.Serialize(envelope, new JsonSerializerOptions { WriteIndented = true }));
    var covered = best.Count;
    Console.WriteLine($"OK: {wanted.Count} 种类型请求，{covered} 种在语料里有命中（扫描 {scanned2}/{files.Count} 个文件，失败 {failed2}）-> {jsonOutPath}");
    return 0;
}

// attrindex 子命令：在整个语料上建一份 "attribute 类型 -> 出现过它的文件列表" 反查索引，
// 给 Blender 那边的资产库面板用（"设定语料路径 -> 挑一个 attr 类型 -> 列出命中文件 -> 直接
// 导入"）。只做文件级命中，不记录具体是哪个 entry/第几个实例——用途是"找一个带这个 attr 的
// 参考文件"，不是"精确定位"。
//
// 同一趟遍历顺带建第二张反查表：`behaviors`，key 是 PtBehavior.behaviorString（游戏原生类名，
// 如 `via.effect.script.EffectLight5000lm`），value 同样是命中文件列表。"PtBehavior" 这个
// attribute 类型太粗——语料里成百上千个文件都挂着某个 PtBehavior，但具体是哪个游戏类完全
// 不同，只靠类型反查找不到"这个具体行为类的参考文件"；behaviorString 是直接内联在结构体里的
// `RszInlineString`（不是偏移间接引用，见 EfxPtBehavior.cs:192-195），扫描时不用额外解析
// 成本就能读到，值得单独建一张表。
//
// 和 fieldstats/fieldstatsbatch 的关键区别：那两个只统计跨语料的聚合值（取值分布、实例数），
// 从不记录"这个实例来自哪个文件"；这里反过来，每种类型/behaviorString 只需要知道"文件命中过
// 没有"，不需要字段级直方图，所以不走 Tally/Bump 那一套，只用 HashSet 去重。
//
//   attrindex <语料目录> <json 输出路径>
static int RunAttrIndex(string[] args)
{
    if (args.Length < 3)
    {
        Console.WriteLine("用法: dotnet <dll> attrindex <语料目录> <json 输出路径>");
        return 1;
    }
    var dir = args[1];
    var jsonOutPath = args[2];

    if (!Directory.Exists(dir))
    {
        Console.WriteLine($"目录不存在: {dir}");
        return 1;
    }

    var files = Directory.EnumerateFiles(dir, "*.efx.*", SearchOption.AllDirectories).ToList();
    // key 用 attr.type.ToString()（EfxAttributeType 枚举名），和 `types` 子命令输出的
    // `name` 字段、`attribute_types.py` 里 readable_types() 的 "name" 是同一个字符串——
    // Blender 侧用这个反查回类目/可读性目录才对得上号。
    var hits = new Dictionary<string, HashSet<string>>();
    // 第二张反查表：PtBehavior.behaviorString -> 出现过它的文件。跟 `types` 表同一趟遍历一起
    // 收集，不另开一遍全语料扫描——behaviorString 是 `RszInlineString`，就在 attribute 结构体
    // 里，不是偏移间接引用，扫描到 EFXAttributePtBehavior 时直接能读到，不用额外解析成本。
    var behaviorHits = new Dictionary<string, HashSet<string>>();

    void Visit(EFXEntryBase container, HashSet<string> touchedTypes, HashSet<string> touchedBehaviors)
    {
        foreach (var attr in container.Attributes)
        {
            touchedTypes.Add(attr.type.ToString());
            if (attr is EFXAttributePtBehavior { behaviorString: { Length: > 0 } bs })
            {
                touchedBehaviors.Add(bs);
            }
            if (attr is EFXAttributePlayEmitter { efxrData: not null } pe)
            {
                foreach (var e in pe.efxrData.Entries) Visit(e, touchedTypes, touchedBehaviors);
                foreach (var a in pe.efxrData.Actions) Visit(a, touchedTypes, touchedBehaviors);
            }
        }
    }

    int scanned = 0, failed = 0;
    foreach (var path in files)
    {
        try
        {
            var efx = new EfxFile(new FileHandler(path));
            efx.Read();
            scanned++;

            // 一个文件里同一类型/同一 behaviorString 可能出现好几次，只需要记一次"这个文件
            // 命中过"——先收集到临时集合里，再统一写回 hits/behaviorHits，避免同一文件在
            // 命中列表里被 Add 好几遍（HashSet.Add 本身就去重，这里只是省一次重复的字典
            // 查找，不影响正确性）。
            var touchedTypes = new HashSet<string>();
            var touchedBehaviors = new HashSet<string>();
            foreach (var e in efx.Entries) Visit(e, touchedTypes, touchedBehaviors);
            foreach (var a in efx.Actions) Visit(a, touchedTypes, touchedBehaviors);

            if (touchedTypes.Count > 0 || touchedBehaviors.Count > 0)
            {
                var relPath = Path.GetRelativePath(dir, path).Replace('\\', '/');
                foreach (var typeName in touchedTypes)
                {
                    if (!hits.TryGetValue(typeName, out var set))
                        hits[typeName] = set = new HashSet<string>();
                    set.Add(relPath);
                }
                foreach (var behaviorString in touchedBehaviors)
                {
                    if (!behaviorHits.TryGetValue(behaviorString, out var set))
                        behaviorHits[behaviorString] = set = new HashSet<string>();
                    set.Add(relPath);
                }
            }
        }
        catch (Exception)
        {
            failed++;  // 语料里本来就有一批读不了的，见 KNOWN_UPSTREAM_ISSUES，跳过不中断整批
        }
    }

    var payload = new
    {
        corpusRoot = dir,
        filesTotal = files.Count,
        filesScanned = scanned,
        filesFailed = failed,
        types = hits.OrderBy(kv => kv.Key)
            .ToDictionary(kv => kv.Key, kv => kv.Value.OrderBy(p => p, StringComparer.Ordinal).ToList()),
        behaviors = behaviorHits.OrderBy(kv => kv.Key)
            .ToDictionary(kv => kv.Key, kv => kv.Value.OrderBy(p => p, StringComparer.Ordinal).ToList()),
    };
    File.WriteAllText(jsonOutPath, JsonSerializer.Serialize(payload, new JsonSerializerOptions { WriteIndented = true }));
    Console.WriteLine($"OK: {hits.Count} 种类型、{behaviorHits.Count} 种 PtBehavior（扫描 {scanned}/{files.Count} 个文件，失败 {failed}）-> {jsonOutPath}");
    return 0;
}

// relstats 子命令：在整个语料上普查"两个数凑一对"的字段（`via.Int2` 的 x/y、`via.Range{I}`
// 的 s/r），按 (attribute 类型.字段路径) 分组，统计每一对数值之间的关系——不是看单个字段的
// 取值分布（fieldstats 已经干这个），是看**同一个实例里两个字段互相之间**的大小关系：
//   x/y 那一对：x 是不是恒 <= y（min/max 假说）
//   s/r 那一对：r 是不是经常 < 0、s 是不是恒 <= r（如果恒 <= r，s/r 也可能其实是 min/max，
//   不是"静态值+随机抖动"）
//
//   relstats <语料目录> <json 输出路径>
//
// 复用 fieldstats 同一套单进程扫全部文件的遍历（含 PlayEmitter.efxrData 递归），不按
// attribute 类型过滤——这两种"双值字段"横跨了几十种 attribute 类型。
// ===== bonealign 子命令 =====
//
// 校核 BoneRelations 索引流的对齐：Bones/BoneRelations 是"按遇到顺序消费"的位置制下标数组
// （EfxFile.SetupBoneReferences()），只要 vendor 认得的"消费者" attribute 类型集合和游戏侧
// 实际写入时用的那一套对不上，整条流就从第一个差异处起整体错位——表现是 ParentBone 被解析成
// 别的骨骼，而且导出时 BoneRelations 会按错误的（更短的）消费者数量重新生成，**静默丢槽位**。
//
//   bonealign <语料目录> <json 输出路径> [--extra 类型名,类型名]
//
// 判据有两条，都不依赖"我们猜它该是什么"：
//   1. 数量：消费者个数必须 == BoneRelations 长度（后者来自 Header.boneAttributeEntryCount，
//      是游戏自己的导出器写进文件的数字）。
//   2. 取值：按下标查出来的骨骼名，必须 == 该 attribute 自己内联存的骨骼名字段
//      （ParentOptions.BoneName / Attractor.boneName / VanishArea3D.JointName /
//      TypeLightning3D.boneName）。这两处是同一个值的两种编码，对齐正确时必然一致。
//
// 同时按 vendor 当前集合（IBoneRelationAttribute）和 --extra 补充后的集合各算一遍，便于对比。
// 对"补充后仍然对不上"的作用域输出完整类型直方图，外加"从未出现在任何已对齐作用域里的类型"
// 清单——这两样就是继续找漏网消费者类型的原料。
//
// 作用域 = 一个 EfxFile（顶层文件，或 PlayEmitter.efxrData 内嵌文件），各有自己的
// BoneRelations；嵌套作用域的骨骼名要用外层文件的 Bones 表解析（同 SetupBoneReferences）。
static int RunBoneAlign(string[] args)
{
    if (args.Length < 3)
    {
        Console.WriteLine("用法: dotnet <dll> bonealign <语料目录> <json 输出路径> [--extra 类型名,类型名]");
        return 1;
    }
    var dir = args[1];
    var jsonOutPath = args[2];
    var extraIdx = Array.IndexOf(args, "--extra");
    var extraNames = extraIdx >= 0 && extraIdx + 1 < args.Length
        ? args[extraIdx + 1].Split(',', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries).ToHashSet()
        : new HashSet<string> { "EFXAttributeTypeStrainRibbonV3", "EFXAttributeFluidParticle2DSimulator" };

    if (!Directory.Exists(dir))
    {
        Console.WriteLine($"目录不存在: {dir}");
        return 1;
    }

    // 内联骨骼名字段的反射缓存：四个已知实现类各自叫 BoneName / boneName / JointName，
    // 按名字找，不维护硬编码的"类型 -> 字段名"表（新增实现类自动覆盖）。
    var inlineCache = new Dictionary<Type, System.Reflection.MemberInfo?>();
    string? InlineBoneName(EFXAttribute attr)
    {
        var t = attr.GetType();
        if (!inlineCache.TryGetValue(t, out var member))
        {
            member = null;
            foreach (var name in new[] { "BoneName", "boneName", "JointName" })
            {
                var f = t.GetField(name);
                if (f != null && f.FieldType == typeof(string)) { member = f; break; }
                var pr = t.GetProperty(name);
                if (pr != null && pr.PropertyType == typeof(string)) { member = pr; break; }
            }
            inlineCache[t] = member;
        }
        return inlineCache[t] switch
        {
            System.Reflection.FieldInfo f => f.GetValue(attr) as string,
            System.Reflection.PropertyInfo pr => pr.GetValue(attr) as string,
            _ => null,
        };
    }

    var files = Directory.EnumerateFiles(dir, "*.efx.*", SearchOption.AllDirectories).ToList();
    int scanned = 0, failed = 0, scopes = 0;
    int curCountBad = 0, newCountBad = 0;
    int curAgree = 0, curDisagree = 0, newAgree = 0, newDisagree = 0;
    var stillBad = new List<object>();
    var allTypes = new HashSet<string>();
    var typesInAlignedScope = new HashSet<string>();

    (int consumers, int agree, int disagree) Walk(
        List<EFXEntry> entries, List<short> relations, List<EFXBone> bones, HashSet<string> consumerExtra)
    {
        int i = 0, agree = 0, disagree = 0;
        foreach (var entry in entries)
        {
            foreach (var attr in entry.Attributes)
            {
                var typeName = attr.GetType().Name;
                var isConsumer = attr is IBoneRelationAttribute || consumerExtra.Contains(typeName);
                if (!isConsumer) continue;
                short idx = i < relations.Count ? relations[i] : (short)-1;
                i++;
                if (attr is not IBoneRelationAttribute) continue;   // 补充类型没有内联名可比
                var resolved = idx >= 0 && idx < bones.Count ? bones[idx].name : null;
                var inline = InlineBoneName(attr);
                var a = string.IsNullOrEmpty(resolved) ? null : resolved;
                var b = string.IsNullOrEmpty(inline) ? null : inline;
                if (a == b) agree++; else disagree++;
            }
        }
        return (i, agree, disagree);
    }

    void VisitScope(string path, string scopeName, EfxFile efx, List<EFXBone> outerBones)
    {
        var bones = efx.Bones.Count > 0 ? efx.Bones : outerBones;
        scopes++;
        foreach (var entry in efx.Entries)
            foreach (var attr in entry.Attributes)
                allTypes.Add(attr.GetType().Name);

        var cur = Walk(efx.Entries, efx.BoneRelations, bones, new HashSet<string>());
        var neu = Walk(efx.Entries, efx.BoneRelations, bones, extraNames);
        curAgree += cur.agree; curDisagree += cur.disagree;
        newAgree += neu.agree; newDisagree += neu.disagree;
        if (cur.consumers != efx.BoneRelations.Count) curCountBad++;

        var newOk = neu.consumers == efx.BoneRelations.Count && neu.disagree == 0;
        if (newOk)
        {
            foreach (var entry in efx.Entries)
                foreach (var attr in entry.Attributes)
                    typesInAlignedScope.Add(attr.GetType().Name);
        }
        else
        {
            newCountBad++;
            var hist = new Dictionary<string, int>();
            foreach (var entry in efx.Entries)
                foreach (var attr in entry.Attributes)
                    hist[attr.GetType().Name] = hist.GetValueOrDefault(attr.GetType().Name) + 1;
            if (stillBad.Count < 400)
            {
                stillBad.Add(new
                {
                    file = path,
                    scope = scopeName,
                    declared = efx.BoneRelations.Count,
                    consumers = neu.consumers,
                    deficit = efx.BoneRelations.Count - neu.consumers,
                    nameDisagree = neu.disagree,
                    types = hist,
                });
            }
        }

        int ai = 0;
        foreach (var action in efx.Actions)
        {
            foreach (var attr in action.Attributes)
            {
                if (attr is EFXAttributePlayEmitter { efxrData: not null } pe)
                    VisitScope(path, $"{scopeName}/Actions[{ai}].PlayEmitter", pe.efxrData, bones);
            }
            ai++;
        }
    }

    foreach (var path in files)
    {
        try
        {
            var efx = new EfxFile(new FileHandler(path));
            efx.Read();
            scanned++;
            VisitScope(path, path, efx, efx.Bones);
        }
        catch (Exception)
        {
            failed++;
        }
        if (scanned > 0 && scanned % 1000 == 0)
            Console.WriteLine($"  ... 已扫 {scanned}/{files.Count}");
    }

    var neverAligned = allTypes.Except(typesInAlignedScope).OrderBy(x => x).ToList();
    var result = new
    {
        directory = dir,
        extraConsumerTypes = extraNames.OrderBy(x => x).ToList(),
        filesTotal = files.Count,
        filesScanned = scanned,
        filesFailed = failed,
        scopes,
        vendorCurrent = new { countMismatchScopes = curCountBad, nameAgree = curAgree, nameDisagree = curDisagree },
        withExtra = new { countMismatchScopes = newCountBad, nameAgree = newAgree, nameDisagree = newDisagree },
        typesNeverInAlignedScope = neverAligned,
        stillMismatched = stillBad,
    };
    File.WriteAllText(jsonOutPath, JsonSerializer.Serialize(result,
        new JsonSerializerOptions { WriteIndented = true, Encoder = System.Text.Encodings.Web.JavaScriptEncoder.UnsafeRelaxedJsonEscaping }));

    Console.WriteLine($"扫描 {scanned} 个文件（失败 {failed}），{scopes} 个作用域");
    Console.WriteLine($"  vendor 当前:  数量对不上的作用域 {curCountBad}，名字一致 {curAgree} / 不一致 {curDisagree}");
    Console.WriteLine($"  补充 [{string.Join(", ", extraNames)}] 后:");
    Console.WriteLine($"                数量对不上的作用域 {newCountBad}，名字一致 {newAgree} / 不一致 {newDisagree}");
    Console.WriteLine($"  从未出现在任何已对齐作用域里的类型: {neverAligned.Count} 个");
    Console.WriteLine($"结果写入 {jsonOutPath}");
    return newCountBad == 0 && newDisagree == 0 ? 0 : 1;
}

static int RunRelStats(string[] args)
{
    if (args.Length < 3)
    {
        Console.WriteLine("用法: dotnet <dll> relstats <语料目录> <json 输出路径>");
        return 1;
    }
    var dir = args[1];
    var jsonOutPath = args[2];

    if (!Directory.Exists(dir))
    {
        Console.WriteLine($"目录不存在: {dir}");
        return 1;
    }

    var options = CreateBridgeJsonOptions();
    var files = Directory.EnumerateFiles(dir, "*.efx.*", SearchOption.AllDirectories).ToList();

    var xyStats = new Dictionary<string, (int total, int violations, List<double[]> examples)>();
    var srStats = new Dictionary<string, (int total, int rNegative, int sGreaterR, List<double[]> examples, Dictionary<string, int> diffHist)>();

    static bool TryNumber(System.Text.Json.Nodes.JsonNode? node, out double value)
    {
        value = 0;
        return node is System.Text.Json.Nodes.JsonValue v
            && double.TryParse(v.ToJsonString(), System.Globalization.NumberStyles.Float,
                System.Globalization.CultureInfo.InvariantCulture, out value);
    }

    void VisitNode(System.Text.Json.Nodes.JsonNode? node, string path)
    {
        if (node is System.Text.Json.Nodes.JsonObject obj)
        {
            var keys = new HashSet<string>(obj.Select(kv => kv.Key).Where(k => k != "$type"));

            // 小写 x/y 是 via.Int2 的字段名；大写 X/Y 是 via.Vector2（System.Numerics.Vector2
            // 的公有字段）——两种大小写都可能是"看着像普通二维量、实际是 min/max"的候选，
            // 用户明确问了"其它 attr 有没有 X/Y 组合也这样"，所以两种大小写都查，不只查 Int2
            // 那三个已确认的字段。
            string? xKey = keys.Contains("x") && keys.Contains("y") ? "x"
                : keys.Contains("X") && keys.Contains("Y") ? "X" : null;
            if (keys.Count == 2 && xKey != null)
            {
                var yKey = xKey == "x" ? "y" : "Y";
                if (TryNumber(obj[xKey], out var xd) && TryNumber(obj[yKey], out var yd))
                {
                    if (!xyStats.TryGetValue(path, out var st)) st = (0, 0, new List<double[]>());
                    st.total++;
                    if (xd > yd)
                    {
                        st.violations++;
                        if (st.examples.Count < 5) st.examples.Add(new[] { xd, yd });
                    }
                    xyStats[path] = st;
                    return;
                }
            }
            if (keys.Count == 2 && keys.Contains("s") && keys.Contains("r")
                && TryNumber(obj["s"], out var sd) && TryNumber(obj["r"], out var rd))
            {
                if (!srStats.TryGetValue(path, out var st)) st = (0, 0, 0, new List<double[]>(), new Dictionary<string, int>());
                st.total++;
                if (rd < 0) st.rNegative++;
                if (sd > rd) st.sGreaterR++;
                if (st.examples.Count < 5) st.examples.Add(new[] { sd, rd });
                var diffKey = Math.Round(sd - rd, 6).ToString(System.Globalization.CultureInfo.InvariantCulture);
                st.diffHist[diffKey] = st.diffHist.GetValueOrDefault(diffKey) + 1;
                srStats[path] = st;
                return;
            }

            foreach (var (key, child) in obj)
            {
                if (key == "$type") continue;
                VisitNode(child, path.Length == 0 ? key : path + "." + key);
            }
        }
        else if (node is System.Text.Json.Nodes.JsonArray arr)
        {
            foreach (var item in arr) VisitNode(item, path + "[]");
        }
    }

    int scanned = 0, failed = 0, attrInstances = 0;

    void Visit(EFXEntryBase container)
    {
        foreach (var attr in container.Attributes)
        {
            attrInstances++;
            var json = JsonSerializer.Serialize(attr, typeof(EFXAttribute), options);
            VisitNode(System.Text.Json.Nodes.JsonNode.Parse(json), attr.type.ToString());
            if (attr is EFXAttributePlayEmitter { efxrData: not null } pe)
            {
                foreach (var e in pe.efxrData.Entries) Visit(e);
                foreach (var a in pe.efxrData.Actions) Visit(a);
            }
        }
    }

    foreach (var path in files)
    {
        try
        {
            var efx = new EfxFile(new FileHandler(path));
            efx.Read();
            scanned++;
            foreach (var e in efx.Entries) Visit(e);
            foreach (var a in efx.Actions) Visit(a);
        }
        catch (Exception)
        {
            failed++;
        }
    }

    var payload = new
    {
        filesTotal = files.Count,
        filesScanned = scanned,
        filesFailed = failed,
        attrInstances,
        xyFields = xyStats.ToDictionary(
            kv => kv.Key,
            kv => new { total = kv.Value.total, violations = kv.Value.violations, examples = kv.Value.examples }),
        srFields = srStats.ToDictionary(
            kv => kv.Key,
            kv => new {
                total = kv.Value.total, rNegative = kv.Value.rNegative, sGreaterR = kv.Value.sGreaterR,
                examples = kv.Value.examples,
                diffTop = kv.Value.diffHist.OrderByDescending(x => x.Value).Take(15)
                    .ToDictionary(x => x.Key, x => x.Value),
            }),
    };
    File.WriteAllText(jsonOutPath, JsonSerializer.Serialize(payload, new JsonSerializerOptions { WriteIndented = true }));
    Console.WriteLine(
        $"OK: 扫描 {scanned}/{files.Count} 个文件（失败 {failed}），{attrInstances} 个 attribute 实例，"
        + $"{xyStats.Count} 种 x/y 字段，{srStats.Count} 种 s/r 字段 -> {jsonOutPath}");
    return 0;
}

// typefreq 子命令：在整个语料上数每种 attribute 类型（EfxAttributeType）出现了多少次，
// 按次数降序输出。用途：给"新建 attribute 默认值"这件事排优先级——先弄语料里最常见的
// 那些类型，长尾类型（可能全语料就出现几次）往后放。
//
//   typefreq <语料目录> <json 输出路径>
//
// 复用 fieldstats/relstats 同一套遍历（含 PlayEmitter.efxrData 递归）。
static int RunTypeFreq(string[] args)
{
    if (args.Length < 3)
    {
        Console.WriteLine("用法: dotnet <dll> typefreq <语料目录> <json 输出路径>");
        return 1;
    }
    var dir = args[1];
    var jsonOutPath = args[2];

    if (!Directory.Exists(dir))
    {
        Console.WriteLine($"目录不存在: {dir}");
        return 1;
    }

    var files = Directory.EnumerateFiles(dir, "*.efx.*", SearchOption.AllDirectories).ToList();
    var counts = new Dictionary<string, int>();
    int scanned = 0, failed = 0, attrInstances = 0;

    void Visit(EFXEntryBase container)
    {
        foreach (var attr in container.Attributes)
        {
            attrInstances++;
            var key = attr.type.ToString();
            counts[key] = counts.GetValueOrDefault(key) + 1;
            if (attr is EFXAttributePlayEmitter { efxrData: not null } pe)
            {
                foreach (var e in pe.efxrData.Entries) Visit(e);
                foreach (var a in pe.efxrData.Actions) Visit(a);
            }
        }
    }

    foreach (var path in files)
    {
        try
        {
            var efx = new EfxFile(new FileHandler(path));
            efx.Read();
            scanned++;
            foreach (var e in efx.Entries) Visit(e);
            foreach (var a in efx.Actions) Visit(a);
        }
        catch (Exception)
        {
            failed++;  // 语料里本来就有一批读不了的，见 KNOWN_UPSTREAM_ISSUES
        }
    }

    var payload = new
    {
        filesTotal = files.Count,
        filesScanned = scanned,
        filesFailed = failed,
        attrInstances,
        typesSeen = counts.Count,
        counts = counts.OrderByDescending(x => x.Value)
            .ToDictionary(x => x.Key, x => x.Value),
    };
    File.WriteAllText(jsonOutPath, JsonSerializer.Serialize(payload, new JsonSerializerOptions { WriteIndented = true }));
    Console.WriteLine(
        $"OK: 扫描 {scanned}/{files.Count} 个文件（失败 {failed}），{attrInstances} 个 attribute 实例，"
        + $"{counts.Count} 种类型 -> {jsonOutPath}");
    return 0;
}

// condstats 子命令：跟 fieldstats 一样在整个语料上给某个 attribute 类型的字段做取值直方图，
// 但先按某个"条件字段"（一般是枚举，如 VelocityType）的取值分桶，桶内再统计其余字段——
// 用来验证"某个模式字段是否门控其余字段"这类假说：如果假说成立，某些字段的分布应该在
// 不同桶之间明显偏移（比如某字段在条件=0 的桶里五花八门，在条件=1 的桶里几乎全是同一个值）。
// 不满足假说时两个桶分布看不出差异，这时不能门控，反而是有力的反证。
//
//   condstats <语料目录> <attribute 类型名> <条件字段名> <json 输出路径> [每字段保留的不同取值数，默认 40]
//
// 复用 fieldstats 的 Tally/Bump 逻辑，只是外面多包一层按条件字段值分桶。
static int RunCondStats(string[] args)
{
    if (args.Length < 5)
    {
        Console.WriteLine("用法: dotnet <dll> condstats <语料目录> <attribute 类型名> <条件字段名[,条件字段名2,...]> <json 输出路径> [每字段保留的不同取值数，默认 40]");
        Console.WriteLine("      条件字段名可以逗号分隔传多个（联合分桶，如 ShapeType,UseExtension），桶键用 | 拼接各字段取值");
        return 1;
    }
    var dir = args[1];
    var typeName = args[2];
    var condField = args[3];
    var condFields = condField.Split(',', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries);
    var jsonOutPath = args[4];
    var maxDistinct = args.Length >= 6 && int.TryParse(args[5], out var md) ? md : 40;

    if (!Directory.Exists(dir))
    {
        Console.WriteLine($"目录不存在: {dir}");
        return 1;
    }
    if (!Enum.TryParse<EfxAttributeType>(typeName, true, out var wanted))
    {
        Console.WriteLine($"[ERROR] 未知的 attribute 类型名: {typeName}");
        return 1;
    }

    var options = CreateBridgeJsonOptions();
    var files = Directory.EnumerateFiles(dir, "*.efx.*", SearchOption.AllDirectories).ToList();
    // 条件字段取值(字符串形式) -> (该桶实例数, 字段路径 -> 取值 -> 出现次数)
    var buckets = new Dictionary<string, (int count, Dictionary<string, Dictionary<string, int>> fields)>();
    int scanned = 0, failed = 0, instances = 0, missingCond = 0;

    void Bump(Dictionary<string, Dictionary<string, int>> fields, string path, string value)
    {
        if (!fields.TryGetValue(path, out var hist))
            fields[path] = hist = new Dictionary<string, int>();
        hist[value] = hist.GetValueOrDefault(value) + 1;
    }

    void Tally(Dictionary<string, Dictionary<string, int>> fields, System.Text.Json.Nodes.JsonNode? node, string path)
    {
        switch (node)
        {
            case System.Text.Json.Nodes.JsonObject obj:
                foreach (var (key, child) in obj)
                {
                    if (key == "$type") continue;
                    Tally(fields, child, path.Length == 0 ? key : path + "." + key);
                }
                break;
            case System.Text.Json.Nodes.JsonArray arr:
                Bump(fields, path + "[].length", arr.Count.ToString());
                break;
            case null:
                Bump(fields, path, "null");
                break;
            default:
                Bump(fields, path, node.ToJsonString());
                break;
        }
    }

    void Visit(EFXEntryBase container)
    {
        foreach (var attr in container.Attributes)
        {
            if (attr.type == wanted)
            {
                instances++;
                var json = JsonSerializer.Serialize(attr, typeof(EFXAttribute), options);
                var node = System.Text.Json.Nodes.JsonNode.Parse(json) as System.Text.Json.Nodes.JsonObject;
                var condParts = new List<string>();
                bool anyMissing = false;
                foreach (var cf in condFields)
                {
                    if (node != null && node.TryGetPropertyValue(cf, out var condNode) && condNode != null)
                        condParts.Add(condNode.ToJsonString());
                    else
                    {
                        condParts.Add("MISSING");
                        anyMissing = true;
                    }
                }
                if (anyMissing) missingCond++;
                string condValue = string.Join("|", condParts);

                if (!buckets.TryGetValue(condValue, out var bucket))
                    bucket = (0, new Dictionary<string, Dictionary<string, int>>());
                bucket.count++;
                if (node != null)
                {
                    foreach (var (key, child) in node)
                    {
                        if (key == "$type" || condFields.Contains(key)) continue;
                        Tally(bucket.fields, child, key);
                    }
                }
                buckets[condValue] = bucket;
            }
            if (attr is EFXAttributePlayEmitter { efxrData: not null } pe)
            {
                foreach (var e in pe.efxrData.Entries) Visit(e);
                foreach (var a in pe.efxrData.Actions) Visit(a);
            }
        }
    }

    foreach (var path in files)
    {
        try
        {
            var efx = new EfxFile(new FileHandler(path));
            efx.Read();
            scanned++;
            foreach (var e in efx.Entries) Visit(e);
            foreach (var a in efx.Actions) Visit(a);
        }
        catch (Exception)
        {
            failed++;  // 语料里本来就有一批读不了的，见 KNOWN_UPSTREAM_ISSUES
        }
    }

    var payload = new
    {
        type = wanted.ToString(),
        conditionField = condField,
        filesTotal = files.Count,
        filesScanned = scanned,
        filesFailed = failed,
        instances,
        missingCond,
        buckets = buckets.OrderBy(kv => kv.Key).ToDictionary(
            kv => kv.Key,
            kv => new
            {
                count = kv.Value.count,
                fields = kv.Value.fields.ToDictionary(
                    f => f.Key,
                    f => new
                    {
                        distinct = f.Value.Count,
                        top = f.Value.OrderByDescending(x => x.Value).Take(maxDistinct)
                                .ToDictionary(x => x.Key, x => x.Value),
                    }),
            }),
    };
    File.WriteAllText(jsonOutPath, JsonSerializer.Serialize(payload, new JsonSerializerOptions { WriteIndented = true }));
    Console.WriteLine(
        $"OK: {wanted} 按 {condField} 分桶（{buckets.Count} 个取值，缺失 {missingCond}），"
        + $"共 {instances} 个实例（扫描 {scanned}/{files.Count} 个文件，失败 {failed}）-> {jsonOutPath}");
    return 0;
}

// flagsurvey：condstats 只能一次测一个 attribute 类型，逐个手测 50 个"开头是 uint Flags"的
// 类型太慢。这里单趟全语料扫描里，见到任意 attribute（不预先指定类型）只要其顶层 JSON 有
// 数字字段 "Flags"，就按 (类型名, Flags 取值) 联合分桶，桶内其它字段的取值分布用法和
// condstats 完全一样。产出交给 tools/scan_flag_bits.py 做逐位分解（每一位 on/off 时，
// 其它字段的"主流值"占比是否剧烈变化——变化大说明这一位是"该字段的启用开关"；哪一位都测不出
// 信号，就是姊妹项目 EFX-Editor 那种"typeFlag"式的类型选择位，不是布尔开关）。
static int RunFlagsSurvey(string[] args)
{
    if (args.Length < 3)
    {
        Console.WriteLine("用法: dotnet <dll> flagsurvey <语料目录> <json 输出路径> [每字段保留的不同取值数，默认 40]");
        return 1;
    }
    var dir = args[1];
    var jsonOutPath = args[2];
    var maxDistinct = args.Length >= 4 && int.TryParse(args[3], out var md) ? md : 40;

    if (!Directory.Exists(dir))
    {
        Console.WriteLine($"目录不存在: {dir}");
        return 1;
    }

    var options = CreateBridgeJsonOptions();
    var files = Directory.EnumerateFiles(dir, "*.efx.*", SearchOption.AllDirectories).ToList();
    // 类型名 -> Flags 取值(字符串) -> (该桶实例数, 字段路径 -> 取值 -> 出现次数)
    var typeBuckets = new Dictionary<string, Dictionary<string, (int count, Dictionary<string, Dictionary<string, int>> fields)>>();
    int scanned = 0, failed = 0, instances = 0, skipped = 0;

    void Bump(Dictionary<string, Dictionary<string, int>> fields, string path, string value)
    {
        if (!fields.TryGetValue(path, out var hist))
            fields[path] = hist = new Dictionary<string, int>();
        hist[value] = hist.GetValueOrDefault(value) + 1;
    }

    void Tally(Dictionary<string, Dictionary<string, int>> fields, System.Text.Json.Nodes.JsonNode? node, string path)
    {
        switch (node)
        {
            case System.Text.Json.Nodes.JsonObject obj:
                foreach (var (key, child) in obj)
                {
                    if (key == "$type") continue;
                    Tally(fields, child, path.Length == 0 ? key : path + "." + key);
                }
                break;
            case System.Text.Json.Nodes.JsonArray arr:
                Bump(fields, path + "[].length", arr.Count.ToString());
                break;
            case null:
                Bump(fields, path, "null");
                break;
            default:
                Bump(fields, path, node.ToJsonString());
                break;
        }
    }

    void Visit(EFXEntryBase container)
    {
        foreach (var attr in container.Attributes)
        {
            var json = JsonSerializer.Serialize(attr, typeof(EFXAttribute), options);
            var node = System.Text.Json.Nodes.JsonNode.Parse(json) as System.Text.Json.Nodes.JsonObject;
            if (node != null
                && node.TryGetPropertyValue("Flags", out var flagsNode)
                && flagsNode is System.Text.Json.Nodes.JsonValue flagsValue
                && flagsValue.TryGetValue<long>(out var flagsLong))
            {
                instances++;
                var typeName = attr.type.ToString();
                if (!typeBuckets.TryGetValue(typeName, out var buckets))
                    typeBuckets[typeName] = buckets = new();
                var key = flagsLong.ToString();
                if (!buckets.TryGetValue(key, out var bucket))
                    bucket = (0, new Dictionary<string, Dictionary<string, int>>());
                bucket.count++;
                foreach (var (fkey, child) in node)
                {
                    if (fkey == "$type" || fkey == "Flags") continue;
                    Tally(bucket.fields, child, fkey);
                }
                buckets[key] = bucket;
            }
            else
            {
                skipped++;
            }
            if (attr is EFXAttributePlayEmitter { efxrData: not null } pe)
            {
                foreach (var e in pe.efxrData.Entries) Visit(e);
                foreach (var a in pe.efxrData.Actions) Visit(a);
            }
        }
    }

    foreach (var path in files)
    {
        try
        {
            var efx = new EfxFile(new FileHandler(path));
            efx.Read();
            scanned++;
            foreach (var e in efx.Entries) Visit(e);
            foreach (var a in efx.Actions) Visit(a);
        }
        catch (Exception)
        {
            failed++;  // 语料里本来就有一批读不了的，见 KNOWN_UPSTREAM_ISSUES
        }
    }

    var payload = new
    {
        filesTotal = files.Count,
        filesScanned = scanned,
        filesFailed = failed,
        instances,
        skippedNoFlagsField = skipped,
        types = typeBuckets.OrderBy(kv => kv.Key).ToDictionary(
            tkv => tkv.Key,
            tkv => new
            {
                instances = tkv.Value.Sum(b => b.Value.count),
                buckets = tkv.Value.OrderBy(kv => kv.Key).ToDictionary(
                    kv => kv.Key,
                    kv => new
                    {
                        count = kv.Value.count,
                        fields = kv.Value.fields.ToDictionary(
                            f => f.Key,
                            f => new
                            {
                                distinct = f.Value.Count,
                                top = f.Value.OrderByDescending(x => x.Value).Take(maxDistinct)
                                        .ToDictionary(x => x.Key, x => x.Value),
                            }),
                    }),
            }),
    };
    File.WriteAllText(jsonOutPath, JsonSerializer.Serialize(payload, new JsonSerializerOptions { WriteIndented = true }));
    Console.WriteLine(
        $"OK: {typeBuckets.Count} 个 attribute 类型带顶层 Flags 数字字段，共 {instances} 个实例"
        + $"（跳过 {skipped} 个无此字段的实例；扫描 {scanned}/{files.Count} 个文件，失败 {failed}）-> {jsonOutPath}");
    return 0;
}

// ptbehaviorcatalog：为「PtBehavior 能否照 MeshV2.properties/姊妹项目 EFX-Editor 那样模块化」
// 这个问题准备语料证据。PtBehavior 没有外部资产文件可读（不像 MeshV2 引用 .mdf2），只能靠
// 全语料按 behaviorString 分组，统计每个类见过的 behaviorProperty 名/dataType，以及
// properties[] 数组的实际出现顺序（判断顺序对不对游戏有意义要看这个）。
// MHWS 的 PtBehaviorVariable 自带 behaviorProperty 字符串（不像 MHWI 只存哈希），
// 所以这里不需要姊妹项目 ptbehavior/names.py 那张哈希反查表。
static int RunPtBehaviorCatalog(string[] args)
{
    if (args.Length < 3)
    {
        Console.WriteLine("用法: dotnet <dll> ptbehaviorcatalog <语料目录> <json 输出路径>");
        return 1;
    }
    var dir = args[1];
    var jsonOutPath = args[2];

    if (!Directory.Exists(dir))
    {
        Console.WriteLine($"目录不存在: {dir}");
        return 1;
    }

    var files = Directory.EnumerateFiles(dir, "*.efx.*", SearchOption.AllDirectories).ToList();
    int scanned = 0, failed = 0, instances = 0;

    var options = CreateBridgeJsonOptions();
    var byBehavior = new Dictionary<string, PtBehaviorBucket>();
    var byRawDataType = new Dictionary<int, DataTypeBucket>();

    void Visit(EFXEntryBase container)
    {
        foreach (var attr in container.Attributes)
        {
            if (attr is ReeLib.Efx.Structs.Pt.EFXAttributePtBehavior pb)
            {
                instances++;
                var bstr = pb.behaviorString ?? "";
                if (!byBehavior.TryGetValue(bstr, out var bucket))
                    byBehavior[bstr] = bucket = new PtBehaviorBucket();
                bucket.InstanceCount++;

                var names = new List<string>();
                foreach (var v in pb.properties)
                {
                    var name = v.behaviorProperty ?? "";
                    names.Add(name);
                    if (!bucket.Properties.TryGetValue(name, out var prop))
                        bucket.Properties[name] = prop = new PtBehaviorPropertyBucket();
                    prop.Freq++;
                    var typeName = v.dataType.ToString();
                    prop.DataTypes[typeName] = prop.DataTypes.GetValueOrDefault(typeName) + 1;
                    var hashKey = "0x" + v.varHash.ToString("X8");
                    prop.VarHashes[hashKey] = prop.VarHashes.GetValueOrDefault(hashKey) + 1;

                    // 全局按原始 dataType 整数值分桶（不管 vendor 认不认识），收集字节形状证据。
                    int rawType = (int)v.dataType;
                    if (!byRawDataType.TryGetValue(rawType, out var dtBucket))
                        byRawDataType[rawType] = dtBucket = new DataTypeBucket();
                    dtBucket.Count++;
                    dtBucket.VarSizes[v.varSize] = dtBucket.VarSizes.GetValueOrDefault(v.varSize) + 1;
                    if (v.variable != null)
                    {
                        dtBucket.InnerUnkn[v.variable.unkn] = dtBucket.InnerUnkn.GetValueOrDefault(v.variable.unkn) + 1;
                        dtBucket.InnerSize[v.variable.size] = dtBucket.InnerSize.GetValueOrDefault(v.variable.size) + 1;
                        var nameKey = bstr + "::" + name;
                        string? dataHex = v.variable is ReeLib.Efx.Structs.Pt.PtBehaviorVariableDataPrefabUnknown unk
                            ? Convert.ToHexString(unk.data ?? Array.Empty<byte>())
                            : null;
                        if (dtBucket.Samples.Count < 40 && dtBucket.SeenNames.Add(nameKey))
                        {
                            dtBucket.Samples.Add(new
                            {
                                behaviorString = bstr,
                                name,
                                varHash = hashKey,
                                variableType = v.variable.GetType().Name,
                                dataHex,
                            });
                        }
                        if (dataHex != null && (dtBucket.DistinctDataHex.ContainsKey(dataHex) || dtBucket.DistinctDataHex.Count < 500))
                        {
                            dtBucket.DistinctDataHex[dataHex] = dtBucket.DistinctDataHex.GetValueOrDefault(dataHex) + 1;
                        }
                    }
                    // 第一次见到这个 (behaviorString, name) 组合时，把这条 PtBehaviorVariable
                    // 原样序列化存一份当"新增候选"的模板——varSize/内层 unkn+size 这些没有
                    // [RszByteSizeField]/[RszArraySizeField] 标注、不会被 vendor 自愈的记账
                    // 字段，靠克隆真实样本规避手工拼字节的风险（用户文案规则，见 PLAN.md 对应小节）。
                    if (prop.Template is null)
                    {
                        var varJson = JsonSerializer.Serialize(v, options);
                        prop.Template = System.Text.Json.Nodes.JsonNode.Parse(varJson);
                    }
                }
                var seqKey = string.Join("|", names);
                bucket.Sequences[seqKey] = bucket.Sequences.GetValueOrDefault(seqKey) + 1;
                // 这个字段组合第一次出现时，把当前这一个实例的完整 properties 数组整体存一份
                // ——挑众数组合当默认字段块时，要用同一份真实文件的值，不是东拼西凑。
                if (!bucket.SequenceTemplates.ContainsKey(seqKey))
                {
                    var propsJson = JsonSerializer.Serialize(pb.properties, options);
                    bucket.SequenceTemplates[seqKey] = System.Text.Json.Nodes.JsonNode.Parse(propsJson);
                }
            }
            if (attr is EFXAttributePlayEmitter { efxrData: not null } pe)
            {
                foreach (var e in pe.efxrData.Entries) Visit(e);
                foreach (var a in pe.efxrData.Actions) Visit(a);
            }
        }
    }

    foreach (var path in files)
    {
        try
        {
            var efx = new EfxFile(new FileHandler(path));
            efx.Read();
            scanned++;
            foreach (var e in efx.Entries) Visit(e);
            foreach (var a in efx.Actions) Visit(a);
        }
        catch (Exception)
        {
            failed++;  // 语料里本来就有一批读不了的，见 KNOWN_UPSTREAM_ISSUES
        }
    }

    // 众数字段组合（出现次数最多的 seqKey；并列时取字典序最小的，保证同一份语料重新生成时
    // 结果稳定）。没有任何实例时返回 null。
    static string? PickModalSequenceKey(PtBehaviorBucket bucket) =>
        bucket.Sequences.Count == 0 ? null
            : bucket.Sequences.OrderByDescending(s => s.Value).ThenBy(s => s.Key, StringComparer.Ordinal)
                .First().Key;

    var payload = new
    {
        filesTotal = files.Count,
        filesScanned = scanned,
        filesFailed = failed,
        instances,
        behaviors = byBehavior.Count,
        byBehavior = byBehavior.OrderByDescending(kv => kv.Value.InstanceCount).ToDictionary(
            kv => kv.Key,
            kv =>
            {
                var modalKey = PickModalSequenceKey(kv.Value);
                return new
                {
                    instanceCount = kv.Value.InstanceCount,
                    properties = kv.Value.Properties.OrderBy(p => p.Key).ToDictionary(
                        p => p.Key,
                        p => new
                        {
                            freq = p.Value.Freq,
                            dataTypes = p.Value.DataTypes,
                            varHashes = p.Value.VarHashes,
                            template = p.Value.Template,
                        }),
                    sequences = kv.Value.Sequences.OrderByDescending(s => s.Value)
                            .ToDictionary(s => s.Key, s => s.Value),
                    // 众数组合对应的那一个完整真实实例——挑默认字段块时，众数组合里每个字段的
                    // 值都来自同一个真实文件，不是从各字段各自的"第一次见到"东拼西凑。
                    defaultSequenceKey = modalKey,
                    defaultTemplate = modalKey is null ? null : kv.Value.SequenceTemplates.GetValueOrDefault(modalKey),
                };
            }),
        // 按 dataType 原始整数值分组的全局统计，跟 behaviorString 无关——回答"这个数值
        // 对应的字节形状是什么"，不管哪个类用了它。
        byRawDataType = byRawDataType.OrderBy(kv => kv.Key).ToDictionary(
            kv => kv.Key.ToString(),
            kv => new
            {
                count = kv.Value.Count,
                knownEnumName = Enum.IsDefined(typeof(ReeLib.Efx.Structs.Pt.PtBehaviorPropType), kv.Key)
                    ? ((ReeLib.Efx.Structs.Pt.PtBehaviorPropType)kv.Key).ToString()
                    : null,
                varSizes = kv.Value.VarSizes.OrderByDescending(s => s.Value)
                    .ToDictionary(s => s.Key.ToString(), s => s.Value),
                innerUnkn = kv.Value.InnerUnkn.OrderByDescending(s => s.Value)
                    .ToDictionary(s => s.Key.ToString(), s => s.Value),
                innerSize = kv.Value.InnerSize.OrderByDescending(s => s.Value)
                    .ToDictionary(s => s.Key.ToString(), s => s.Value),
                samples = kv.Value.Samples,
                distinctDataHex = kv.Value.DistinctDataHex.OrderByDescending(s => s.Value)
                    .Take(50).ToDictionary(s => s.Key, s => s.Value),
                distinctDataHexCount = kv.Value.DistinctDataHex.Count,
            }),
    };
    File.WriteAllText(jsonOutPath, JsonSerializer.Serialize(payload, new JsonSerializerOptions { WriteIndented = true }));
    Console.WriteLine(
        $"OK: PtBehavior 共 {instances} 个实例，{byBehavior.Count} 个 behaviorString、"
        + $"{byRawDataType.Count} 种 dataType 原始值"
        + $"（扫描 {scanned}/{files.Count} 个文件，失败 {failed}）-> {jsonOutPath}");
    return 0;
}

static int RunNew(string[] args)
{
    if (args.Length < 3)
    {
        Console.WriteLine("用法: dotnet <dll> new attribute <类型名> <json 输出路径> [版本]");
        Console.WriteLine("      dotnet <dll> new entry|action <json 输出路径> [版本]");
        return 1;
    }

    var kind = args[1];
    string jsonOutPath;
    string? typeName = null;
    int versionArgIndex;
    if (kind == "attribute")
    {
        if (args.Length < 4)
        {
            Console.WriteLine("用法: dotnet <dll> new attribute <类型名> <json 输出路径> [版本]");
            return 1;
        }
        typeName = args[2];
        jsonOutPath = args[3];
        versionArgIndex = 4;
    }
    else if (kind == "entry" || kind == "action")
    {
        jsonOutPath = args[2];
        versionArgIndex = 3;
    }
    else
    {
        Console.WriteLine($"[ERROR] 未知的 new 类型: {kind}（只支持 attribute / entry / action）");
        return 1;
    }

    var version = EfxVersion.MHWilds;
    if (args.Length > versionArgIndex && !Enum.TryParse(args[versionArgIndex], true, out version))
    {
        Console.WriteLine($"[ERROR] 未知的 EfxVersion: {args[versionArgIndex]}");
        return 1;
    }

    var options = CreateBridgeJsonOptions();
    try
    {
        object payload;
        if (kind == "attribute")
        {
            if (!Enum.TryParse<EfxAttributeType>(typeName, true, out var attrType))
            {
                Console.WriteLine($"[ERROR] 未知的 attribute 类型名: {typeName}");
                return 1;
            }
            // 必须走 EFXAttribute.Create 而不是 EfxAttributeTypeRemapper.Create：
            // `protected EFXAttribute(EfxAttributeType type) { }` 的函数体是**空的**，把参数
            // 丢掉了，所以直接 new 出来的实例 `type` 字段是 0（Unknown），连带 IsTypeAttribute
            // 也恒为 false。只有静态工厂里那句 `item.type = type;` 会补上。写出 .efx 时
            // EFXEntry.DoWrite 拿 attr.type 反查 itemTypeId，type=0 会直接写坏文件。
            EFXAttribute attr;
            try
            {
                attr = EFXAttribute.Create(version, attrType);
            }
            catch (ArgumentException)
            {
                // vendor 只登记了 id→枚举名、没有读写实现类，见 KNOWN_UPSTREAM_ISSUES #4
                Console.WriteLine($"[ERROR] {version} 的 {attrType} 没有读写实现类，无法新建");
                return 1;
            }
            attr.Version = version;
            InitBlankClipData(attr);
            payload = attr;
        }
        else if (kind == "entry")
        {
            payload = new EFXEntry { Version = version };
        }
        else
        {
            payload = new EFXAction { Version = version };
        }

        // attribute 必须按基类 EFXAttribute 序列化，多态转换器才会写出 `$type` 判别字段——
        // build_attribute_object() 就是靠它认类型的。按具体子类序列化会少这一项。
        var declaredType = kind == "attribute" ? typeof(EFXAttribute) : payload.GetType();
        File.WriteAllText(jsonOutPath, JsonSerializer.Serialize(payload, declaredType, options));
        Console.WriteLine($"OK: new {kind}{(typeName != null ? " " + typeName : "")} ({version}) -> {jsonOutPath}");
        return 0;
    }
    catch (Exception ex)
    {
        Console.WriteLine($"[ERROR] 新建失败");
        Console.WriteLine(ex.ToString());
        return 1;
    }
}

// 空白的 *Clip attribute 直接序列化会炸：`EfxClipData.ParsedClip` 是个惰性计算属性
// （`parsedClips ??= ParseClip()`），而 `ParseClip()` 上来就解引用 `clips!` / `frames!` /
// `interpolationData!` 这三个数组——刚 new 出来的实例它们都是 null，序列化器一读这个属性就
// NullReferenceException。238 个可读写类型里有 23 个（全是 *Clip）中招。
//
// 我们自己并不需要 ParsedClip（io_tree._populate_clip_attribute 读的是 clipData/clipBits
// 原始数组），所以只要把三个数组初始化成空数组，让那个 getter 能正常走完就行——语义上就是
// "一条曲线都没有的空 clip"，正是新建时应有的状态。
static void InitBlankClipData(EFXAttribute attr)
{
    // 见 FixJsonRoundtripGaps()/FixNullMaterialExpressions() 的说明：materialExpressions
    // 为 null 时 Write 完全跳过写字节、Read 却无条件读，新建的 attribute 天生就是 null，
    // 第一次 load 就会把后面的字节读错位——跟是不是 IClipAttribute 无关，必须在下面的
    // early return 之前处理。
    FixNullMaterialExpressions(attr);

    if (attr is not IClipAttribute clipAttr) return;
    var clip = clipAttr.Clip;
    clip.clips ??= Array.Empty<EfxClipHeader>();
    clip.frames ??= Array.Empty<EfxClipFrame>();
    clip.interpolationData ??= Array.Empty<EfxClipInterpolationTangents>();
    // 见 FixJsonRoundtripGaps() 的说明：clipData.Version 不会被 RszConstructorParams
    // 自动带上（这里走的是 EFXAttribute.Create() 之后手动补 attr.Version 的顺序，比字段
    // 初始化晚），新建的 attribute 必须当场补一次，否则这个 attribute 从没导出/导入过
    // 也会在第一次 load 时就写坏。
    if (attr is IMaterialClipAttribute matClipAttr)
    {
        matClipAttr.MaterialClip.Version = attr.Version;
    }
}

static int RunExprCheck(string[] args)
{
    if (args.Length < 2)
    {
        Console.WriteLine("用法: dotnet <dll> exprcheck <公式文本>");
        return 1;
    }
    var formula = args[1];

    try
    {
        EfxExpressionStringParser.Parse(formula, new List<EFXExpressionParameterName>());
        Console.WriteLine("OK");
        return 0;
    }
    catch (Exception ex)
    {
        Console.WriteLine($"[ERROR] {ex.Message}");
        return 1;
    }
}

// vendor 自带的 EFXExpressionTreeJsonConverter.Read()（EfxFile.cs）读 "expression" 这个字符串
// 属性时有个真实 bug：读到 PropertyName token 后直接调用 reader.GetString()，没有先
// reader.Read() 前进到值 token——Utf8JsonReader.GetString() 在 PropertyName token 上合法调用
// 但返回的是属性名本身（字面量 "expression"），不是它的值。结果是任何走 load 的 Expression
// 公式，不管原文写的是什么，解析出来的都是同一个 identifier "expression"（对应
// parameterHash = MurMur3("expression")）——已用真实样本复现确认（dump→load→dump 后 6 个
// TypeBillboard3DExpression attribute 全部退化成同一个 ext:2062838256）。vendor 是 git
// submodule，不在这层直接改提交，照抄原始逻辑只补一行 reader.Read() 再挂进
// CreateBridgeJsonOptions()（System.Text.Json 按顺序找第一个匹配的 converter，插在列表最前面
// 就能盖过 vendor 自己注册的那个）。
// System.Text.Json 写 float 时用"最短可往返"表示，`1.0f` 写出来就是 `1`、`0.0f` 就是 `0`。
// 这在 C# 侧无所谓（字段声明类型摆在那儿），但 Python 侧 `json.loads` 只能看值猜类型，
// 拿到的是 `int`——Blender 面板于是给这些字段画成整数框，用户没法输入小数。
// **不是只影响 0 值**：任何整数值的 float 都中招，比如 `LocalScale = {X:1, Y:1, Z:1}` 整个
// 向量都变成整数框，而同一个 `LocalPosition` 里 `Y:-0.8` 却是正常的浮点框。
//
// 修法：给 float 挂一个转换器，有限值一律带小数点写出去。这样 Python 侧靠值就能分辨，
// 不需要我们额外传一份"每个字段声明类型"的元数据下去（那要按路径递归匹配，麻烦得多）。
//
// NaN/±Infinity 仍按 `JsonNumberHandling.AllowNamedFloatingPointLiterals` 的老样子写成
// **带引号的字符串**——自定义转换器会绕过那个开关，必须自己复现，否则 EFX 里那些
// "无上限"语义的字段一写就崩（见 model.json_float_out 记录的历史事故）。
//
// EFX 结构里没有 double 字段（`grep 'public double' OtherFiles/EFX` 只有一个转换方法），
// 所以只处理 float。
// pairstats 的每字段累计量。只记**原始计数**，判据在 tools/audit_range_fields.py 里。

// rootstats 子命令：全语料普查"Root entry"（EFXEntry.entryAssignment == EfxEntryEnum.Root）。
// 关心的是三件事：哪些文件有 Root、Root 上挂得起哪些 attribute 类型、这些类型的字段实际取值
// 分布。字段用反射逐个读（public 实例字段 + 可读属性），这样新增 attribute 类型不用改这里。
// 同时记一份"同一类型出现在非 Root entry 上"的计数——"只在 Root 上出现"这个结论必须有反例
// 计数兜底，否则只是采样没扫到。
static int RunRootStats(string[] args)
{
    if (args.Length < 3)
    {
        Console.WriteLine("用法: dotnet <dll> rootstats <语料目录> <json 输出路径>");
        return 1;
    }
    var dir = args[1];
    var jsonOutPath = args[2];
    if (!Directory.Exists(dir))
    {
        Console.WriteLine($"目录不存在: {dir}");
        return 1;
    }

    var files = Directory.EnumerateFiles(dir, "*.efx.*", SearchOption.AllDirectories).ToList();

    var rootsPerFile = new Dictionary<int, int>();
    var rootNames = new Dictionary<string, int>();
    var rootIndexField = new Dictionary<int, int>();
    var rootArrayPos = new Dictionary<int, int>();
    var rootGroups = new Dictionary<string, int>();
    var rootAttrCount = new Dictionary<int, int>();
    var typesOnRoot = new Dictionary<string, int>();
    var typesElsewhere = new Dictionary<string, int>();
    var combos = new Dictionary<string, int>();
    // typeName -> fieldName -> 值文本 -> 次数
    var fields = new Dictionary<string, Dictionary<string, Dictionary<string, int>>>();
    var rootFiles = new List<string>();
    var multiRootFiles = new List<string>();

    static void Bump<T>(Dictionary<T, int> d, T k) where T : notnull
        => d[k] = d.TryGetValue(k, out var n) ? n + 1 : 1;

    static string Fmt(object? v) => v switch
    {
        null => "null",
        float f => f.ToString("R", System.Globalization.CultureInfo.InvariantCulture),
        System.Numerics.Vector3 v3 => $"({v3.X.ToString("R", System.Globalization.CultureInfo.InvariantCulture)}, {v3.Y.ToString("R", System.Globalization.CultureInfo.InvariantCulture)}, {v3.Z.ToString("R", System.Globalization.CultureInfo.InvariantCulture)})",
        System.Collections.IEnumerable e and not string => "[" + string.Join(", ", e.Cast<object?>().Select(x => x?.ToString() ?? "null")) + "]",
        _ => v.ToString() ?? "null",
    };

    int scanned = 0, failed = 0;
    foreach (var path in files)
    {
        EfxFile efx;
        try
        {
            efx = new EfxFile(new FileHandler(path));
            efx.Read();
            scanned++;
        }
        catch (Exception)
        {
            failed++;  // 语料里本来就有一批读不了的，见 KNOWN_UPSTREAM_ISSUES，跳过不中断整批
            continue;
        }

        var relPath = Path.GetRelativePath(dir, path).Replace('\\', '/');
        int rootCount = 0;
        for (int i = 0; i < efx.Entries.Count; i++)
        {
            var entry = efx.Entries[i];
            bool isRoot = entry.entryAssignment == EfxEntryEnum.Root;
            if (!isRoot)
            {
                foreach (var attr in entry.Attributes) Bump(typesElsewhere, attr.type.ToString());
                continue;
            }

            rootCount++;
            Bump(rootNames, entry.name ?? "<null>");
            Bump(rootIndexField, entry.index);
            Bump(rootArrayPos, i);
            Bump(rootGroups, entry.Groups.Count == 0 ? "<empty>" : string.Join("|", entry.Groups));
            Bump(rootAttrCount, entry.Attributes.Count);

            var names = new List<string>();
            foreach (var attr in entry.Attributes)
            {
                var typeName = attr.type.ToString();
                names.Add(typeName);
                Bump(typesOnRoot, typeName);

                if (!fields.TryGetValue(typeName, out var perField))
                    fields[typeName] = perField = new();
                var clrType = attr.GetType();
                foreach (var f in clrType.GetFields(System.Reflection.BindingFlags.Public | System.Reflection.BindingFlags.Instance))
                {
                    if (!perField.TryGetValue(f.Name, out var counter))
                        perField[f.Name] = counter = new();
                    Bump(counter, Fmt(f.GetValue(attr)));
                }
            }
            names.Sort(StringComparer.Ordinal);
            Bump(combos, string.Join(" + ", names));
        }

        Bump(rootsPerFile, rootCount);
        if (rootCount > 0) rootFiles.Add(relPath);
        if (rootCount > 1) multiRootFiles.Add(relPath);
    }

    // 每个字段的 distinct 值可能非常多（Center/Size 这类连续量），只留前 40 个高频值，
    // 另外记一个 distinct 总数，免得输出文件爆掉。
    static object TopValues(Dictionary<string, int> counter) => new
    {
        distinct = counter.Count,
        top = counter.OrderByDescending(kv => kv.Value).ThenBy(kv => kv.Key, StringComparer.Ordinal)
            .Take(40).ToDictionary(kv => kv.Key, kv => kv.Value),
    };

    var payload = new
    {
        corpusRoot = dir,
        filesTotal = files.Count,
        filesScanned = scanned,
        filesFailed = failed,
        rootsPerFile = rootsPerFile.OrderBy(kv => kv.Key).ToDictionary(kv => kv.Key.ToString(), kv => kv.Value),
        rootNames = rootNames.OrderByDescending(kv => kv.Value).Take(40).ToDictionary(kv => kv.Key, kv => kv.Value),
        rootNamesDistinct = rootNames.Count,
        rootIndexField = rootIndexField.OrderByDescending(kv => kv.Value).Take(20).ToDictionary(kv => kv.Key.ToString(), kv => kv.Value),
        rootArrayPos = rootArrayPos.OrderBy(kv => kv.Key).ToDictionary(kv => kv.Key.ToString(), kv => kv.Value),
        rootGroups = rootGroups.OrderByDescending(kv => kv.Value).Take(20).ToDictionary(kv => kv.Key, kv => kv.Value),
        rootAttrCount = rootAttrCount.OrderBy(kv => kv.Key).ToDictionary(kv => kv.Key.ToString(), kv => kv.Value),
        typesOnRoot = typesOnRoot.OrderByDescending(kv => kv.Value).ToDictionary(kv => kv.Key, kv => kv.Value),
        typesOnRootAlsoElsewhere = typesOnRoot.Keys.OrderBy(k => k, StringComparer.Ordinal)
            .ToDictionary(k => k, k => typesElsewhere.TryGetValue(k, out var n) ? n : 0),
        combos = combos.OrderByDescending(kv => kv.Value).Take(40).ToDictionary(kv => kv.Key, kv => kv.Value),
        multiRootFiles = multiRootFiles.Take(20).ToList(),
        fields = fields.OrderBy(kv => kv.Key, StringComparer.Ordinal).ToDictionary(
            kv => kv.Key,
            kv => kv.Value.OrderBy(f => f.Key, StringComparer.Ordinal).ToDictionary(f => f.Key, f => TopValues(f.Value))),
    };
    File.WriteAllText(jsonOutPath, JsonSerializer.Serialize(payload, new JsonSerializerOptions { WriteIndented = true }));
    Console.WriteLine($"OK: {rootFiles.Count}/{scanned} 个文件有 Root entry，Root 上出现 {typesOnRoot.Count} 种 attribute（失败 {failed}）-> {jsonOutPath}");
    return 0;
}


class ExprVarStat
{
    public int count;
    public Dictionary<string, int> attrTypes = new();
    public List<ExprVarExample> examples = new();
}
record ExprVarExample(string file, string attrType, string formula);

sealed class PairTally
{
    public string KeyOrder = "";
    public long N;
    public long AllIntegral;
    public long SecondLtFirst;      // 副值 < 主值 —— min/max 语义下不可能出现
    public long SecondEqFirstNonZero;// 副值 == 主值 且主值 != 0 —— "固定为某个非零值"，min/max 的招牌写法
    public long SecondEqFirst;      // 副值 == 主值 —— 闭区间的"固定值"写法；半开区间下是空区间
    public long SecondEqFirstPlus1; // 副值 == 主值+1 —— 半开区间的"固定值"写法
    public long SecondZero;         // 副值 == 0
    public long SecondZeroFirstNonZero;// 副值 == 0 且主值 != 0 —— "值 v、不随机"，static/random
                                    // 的招牌写法。和 SecondEqFirstNonZero 严格对称（那个是
                                    // min/max 的招牌写法 "固定为 v"），两者形式互斥。
    public long FirstZero;
    public long FirstNonZero;       // 主值 != 0 的实例数（主值恒为 0 时两种读法等价，无从区分）
    public double FirstMin = double.MaxValue, FirstMax = double.MinValue;
    public double SecondMin = double.MaxValue, SecondMax = double.MinValue;
    public readonly Dictionary<string, long> Pairs = new();

    public void Observe(double first, double second, bool integral, int maxPairs)
    {
        N++;
        if (integral) AllIntegral++;
        if (second < first) SecondLtFirst++;
        if (second == first) { SecondEqFirst++; if (first != 0) SecondEqFirstNonZero++; }
        if (second == first + 1) SecondEqFirstPlus1++;
        if (second == 0) { SecondZero++; if (first != 0) SecondZeroFirstNonZero++; }
        if (first == 0) FirstZero++; else FirstNonZero++;
        if (first < FirstMin) FirstMin = first;
        if (first > FirstMax) FirstMax = first;
        if (second < SecondMin) SecondMin = second;
        if (second > SecondMax) SecondMax = second;
        // 组合直方图会很大，超过上限 10 倍就不再收新键（高频的早就在里面了）
        var key = FormattableString.Invariant($"{first:G},{second:G}");
        if (Pairs.ContainsKey(key) || Pairs.Count < maxPairs * 10)
            Pairs[key] = Pairs.GetValueOrDefault(key) + 1;
    }

    public object ToPayload(int maxPairs) => new
    {
        keyOrder = KeyOrder,
        n = N,
        allIntegral = AllIntegral,
        secondLtFirst = SecondLtFirst,
        secondEqFirst = SecondEqFirst,
        secondEqFirstNonZero = SecondEqFirstNonZero,
        secondEqFirstPlus1 = SecondEqFirstPlus1,
        secondZero = SecondZero,
        secondZeroFirstNonZero = SecondZeroFirstNonZero,
        firstZero = FirstZero,
        firstNonZero = FirstNonZero,
        firstRange = new[] { FirstMin, FirstMax },
        secondRange = new[] { SecondMin, SecondMax },
        topPairs = Pairs.OrderByDescending(x => x.Value).Take(maxPairs)
                        .ToDictionary(x => x.Key, x => x.Value),
    };
}

sealed class UvsHeaderPayload
{
    public int attributes { get; set; }
}

sealed class UvsBridgePayload
{
    public int fileVersion { get; set; }
    public UvsHeaderPayload header { get; set; } = new();
    public List<TextureBlock> textures { get; set; } = new();
    public List<SequenceBlock> sequences { get; set; } = new();
}

class PtBehaviorBucket
{
    public int InstanceCount;
    public Dictionary<string, PtBehaviorPropertyBucket> Properties = new();
    public Dictionary<string, int> Sequences = new();
    // 每个不同的字段组合（seqKey）第一次出现时，把那一个真实实例的完整 properties 数组
    // 原样存一份——不是靠 Properties[name].Template 那种"每个字段各自第一次见到时"拼出来的
    // 拼盘，而是让"挑众数当默认字段块"时，众数组合里每个字段的值都来自同一个真实文件。
    public Dictionary<string, System.Text.Json.Nodes.JsonNode?> SequenceTemplates = new();
}

class PtBehaviorPropertyBucket
{
    public int Freq;
    public Dictionary<string, int> DataTypes = new();
    public Dictionary<string, int> VarHashes = new();
    public System.Text.Json.Nodes.JsonNode? Template;
}

// 跨 behaviorString 的全局桶，按 PtBehaviorVariable.dataType 的**原始整数值**分组（不管
// vendor 认不认识这个枚举值）——用于确认 PtBehaviorPropType 里那批"观测到但 vendor 没登记"
// 的未知取值（3/6/8/12/20/22/24/25/26 等）实际的字节形状：`InnerUnkn`/`InnerSize` 分别是
// `variable.unkn`/`variable.size` 的取值分布，已知类型里 `unkn` 看起来等于"4 字节分量个数"
// （PropInt/PropFloat=1、PropFloat2=2、PropFloat3=3），这里同时收集已知类型的分布用来交叉
// 验证这条假设是否对未知类型也成立。
class DataTypeBucket
{
    public int Count;
    public Dictionary<int, int> VarSizes = new();
    public Dictionary<int, int> InnerUnkn = new();
    public Dictionary<int, int> InnerSize = new();
    public List<object> Samples = new();
    // 每个 (behaviorString, name) 组合只存一份样本——诊断"这个 dataType 到底覆盖了哪些字段"
    // 时，40 条来自同一个高频字段的重复样本没有意义，宁可少存几条但覆盖面广。
    public HashSet<string> SeenNames = new();
    // 原始字节（hex）的取值分布，不限定字段——诊断"这个 dataType 的值到底有多少种真实变化"
    // （比如两个 int32 里第二个是不是真的会变，不是每次都是 0）。字节多、值种类爆炸的类型
    // （25/26，材质参数嵌套结构）超过上限就不再新增 key，但已有 key 的计数继续累加。
    public Dictionary<string, int> DistinctDataHex = new();
}

sealed class FloatKeepsDecimalPointConverter : System.Text.Json.Serialization.JsonConverter<float>
{
    public override float Read(ref Utf8JsonReader reader, Type typeToConvert, JsonSerializerOptions options)
    {
        if (reader.TokenType == JsonTokenType.String)
        {
            var text = reader.GetString();
            return text switch
            {
                "NaN" => float.NaN,
                "Infinity" => float.PositiveInfinity,
                "-Infinity" => float.NegativeInfinity,
                _ => float.Parse(text!, System.Globalization.CultureInfo.InvariantCulture),
            };
        }
        return reader.GetSingle();
    }

    public override void Write(Utf8JsonWriter writer, float value, JsonSerializerOptions options)
    {
        if (float.IsNaN(value)) { writer.WriteStringValue("NaN"); return; }
        if (float.IsPositiveInfinity(value)) { writer.WriteStringValue("Infinity"); return; }
        if (float.IsNegativeInfinity(value)) { writer.WriteStringValue("-Infinity"); return; }

        // "R" = 最短可往返表示（.NET Core 3.0+ 已修好老版本那个 R 不可靠的问题）
        var text = value.ToString("R", System.Globalization.CultureInfo.InvariantCulture);
        if (text.IndexOfAny(new[] { '.', 'e', 'E' }) < 0)
        {
            text += ".0";
        }
        writer.WriteRawValue(text);
    }
}

sealed class MaterialPolymorphismResolver : System.Text.Json.Serialization.Metadata.IJsonTypeInfoResolver
{
    public System.Text.Json.Serialization.Metadata.JsonTypeInfo? GetTypeInfo(Type type, JsonSerializerOptions options)
    {
        var info = EfxJsonTypeResolver.Instance.GetTypeInfo(type, options);
        if (info != null && type == typeof(EfxMaterialStructBase))
        {
            info.PolymorphismOptions = new System.Text.Json.Serialization.Metadata.JsonPolymorphismOptions
            {
                TypeDiscriminatorPropertyName = "$type",
                IgnoreUnrecognizedTypeDiscriminators = true,
                UnknownDerivedTypeHandling = System.Text.Json.Serialization.JsonUnknownDerivedTypeHandling.FailSerialization,
            };
            info.PolymorphismOptions.DerivedTypes.Add(new System.Text.Json.Serialization.Metadata.JsonDerivedType(typeof(EfxMaterialStructV1), typeof(EfxMaterialStructV1).FullName!));
            info.PolymorphismOptions.DerivedTypes.Add(new System.Text.Json.Serialization.Metadata.JsonDerivedType(typeof(EfxMaterialStructV2), typeof(EfxMaterialStructV2).FullName!));
            info.PreferredPropertyObjectCreationHandling = System.Text.Json.Serialization.JsonObjectCreationHandling.Populate;
        }
        return info;
    }
}

sealed class FixedExpressionTreeJsonConverter : System.Text.Json.Serialization.JsonConverter<EFXExpressionTree>
{
    public override EFXExpressionTree? Read(ref Utf8JsonReader reader, Type typeToConvert, JsonSerializerOptions options)
    {
        if (reader.TokenType != JsonTokenType.StartObject)
        {
            throw new JsonException($"Expression tree should be object at {reader.TokenStartIndex}");
        }

        var expr = "";
        var parameters = new List<EFXExpressionParameterName>();
        while (reader.Read() && reader.TokenType != JsonTokenType.EndObject)
        {
            if (reader.TokenType == JsonTokenType.PropertyName)
            {
                var prop = reader.GetString();
                switch (prop)
                {
                    case "expression":
                        reader.Read();
                        expr = reader.GetString()!;
                        break;
                    case "parameters":
                        parameters = JsonSerializer.Deserialize<List<EFXExpressionParameterName>>(ref reader, options) ?? [];
                        break;
                }
            }
        }

        var tree = EfxExpressionStringParser.Parse(expr, parameters);
        RestoreParameterOrder(tree, parameters);
        return tree;
    }

    /// <summary>
    /// 把公式树的参数表顺序恢复成 JSON 里带来的那个顺序（= 原文件里的顺序）。
    ///
    /// ⚠ **游戏会因为这个顺序判文件 Invalid**（实机确认）。两条读路的顺序来源不一样：
    ///
    /// - 二进制 -> 树（`EfxFile.ParseExpressions`）：`tree.parameters = expression.Parameters.ToList()`，
    ///   原样保留文件里的顺序；
    /// - 文本 -> 树（`EfxExpressionStringParser.Parse`）：顺序由 `StoreNewParameters()` 的
    ///   **前序遍历**重新生成，传进去的那张表只当哈希查找用（`EfxExpressionParser.cs:35`）。
    ///
    /// 而 Blender 走的正是 JSON 文本这条路，于是 `Lerp(IsBlue, colorR_N, color_N)` 这种三参
    /// 公式的参数表被整个**反序**写出去（实测 18 棵树里 6 棵，每条都是精确反序）。
    ///
    /// ⚠ **所有既有门禁对它免疫**：`roundtrip` 是纯内存对象图往返（两次都走同一条重排），
    /// Blender 产物和纯 CLI 产物逐字节相同（两边都经这条路），而"和原文件相同"按判据本来
    /// 就不要求。只有把文件放回游戏里才会暴露。
    ///
    /// 稳定排序：JSON 里出现过的按原位置排，没出现过的（`Parse` 新引入的）保持相对次序、
    /// 排在后面。不去改 vendor 的解析器——那是 submodule，绕在这里就够。
    /// </summary>
    private static void RestoreParameterOrder(EFXExpressionTree? tree, List<EFXExpressionParameterName> parameters)
    {
        if (tree == null || parameters.Count == 0 || tree.parameters.Count < 2) return;

        var order = new Dictionary<uint, int>();
        for (var i = 0; i < parameters.Count; i++)
        {
            order.TryAdd(parameters[i].parameterNameHash, i);
        }
        tree.parameters = tree.parameters
            .OrderBy(p => order.TryGetValue(p.parameterNameHash, out var index) ? index : int.MaxValue)
            .ToList();
    }

    public override void Write(Utf8JsonWriter writer, EFXExpressionTree value, JsonSerializerOptions options)
    {
        writer.WriteStartObject();
        writer.WriteString("expression", value.root.ToString());
        writer.WritePropertyName("parameters");
        JsonSerializer.Serialize(writer, value.parameters, options);
        writer.WriteEndObject();
    }
}

sealed class BitCorr
{
    public string bitName = "";
    public int setCount;
    public int multiplyCount;
    public Dictionary<string, Dictionary<string, int>> assign = new();
    public Dictionary<string, Dictionary<string, int>> hostFields = new();
    public Dictionary<string, Dictionary<string, int>> formulas = new();
    public Dictionary<string, Dictionary<string, int>> entryNames = new();
    public Dictionary<string, Dictionary<string, int>> efxNames = new();
    public Dictionary<string, int> zeroCount = new();
    public Dictionary<string, int> zeroUnderMultiply = new();

    public void ZeroCount(string field) => zeroCount[field] = zeroCount.GetValueOrDefault(field) + 1;
    public void ZeroUnderMultiply(string field) => zeroUnderMultiply[field] = zeroUnderMultiply.GetValueOrDefault(field) + 1;
}

sealed class TypeCorr
{
    public string hostType = "";
    public int instances;
    public int hostMissing;
    public Dictionary<string, Dictionary<string, int>> hostBaseline = new();
    public Dictionary<int, BitCorr> bits = new();

    public BitCorr Bit(int index, string name)
    {
        if (!bits.TryGetValue(index, out var bc)) bc = bits[index] = new BitCorr { bitName = name };
        return bc;
    }

    static Dictionary<string, int> Top(Dictionary<string, int> hist, int topN) =>
        hist.OrderByDescending(kv => kv.Value).Take(topN).ToDictionary(kv => kv.Key, kv => kv.Value);

    static Dictionary<string, Dictionary<string, int>> TopPerBucket(
        Dictionary<string, Dictionary<string, int>> buckets, int topN) =>
        buckets.OrderBy(kv => kv.Key).ToDictionary(kv => kv.Key, kv => Top(kv.Value, topN));

    public object Render(int topN) => new
    {
        hostType,
        instances,
        hostMissing,
        hostBaseline = TopPerBucket(hostBaseline, topN),
        bits = bits.OrderBy(kv => kv.Key).ToDictionary(kv => kv.Key.ToString(), kv => (object)new
        {
            bits[kv.Key].bitName,
            bits[kv.Key].setCount,
            bits[kv.Key].multiplyCount,
            assign = bits[kv.Key].assign.TryGetValue("", out var a) ? Top(a, 16) : new(),
            zeroCount = bits[kv.Key].zeroCount,
            zeroUnderMultiply = bits[kv.Key].zeroUnderMultiply,
            hostFields = TopPerBucket(bits[kv.Key].hostFields, topN),
            formulas = TopPerBucket(bits[kv.Key].formulas, 12),
            entryNames = bits[kv.Key].entryNames.TryGetValue("", out var e) ? Top(e, 12) : new(),
            efxNames = bits[kv.Key].efxNames.TryGetValue("", out var x) ? Top(x, 8) : new(),
        }),
    };
}

sealed class SpawnRingBucket
{
    public int count;
    public Dictionary<string, Dictionary<string, int>> entryNames = new();
    public Dictionary<string, Dictionary<string, int>> siblingTypes = new();
    public Dictionary<string, Dictionary<string, int>> dirNames = new();
    public Dictionary<string, Dictionary<string, int>> fileNames = new();
    public Dictionary<string, Dictionary<string, int>> fields = new();
}