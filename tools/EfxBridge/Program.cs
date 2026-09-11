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

using System.Text.Json;
using ReeLib;
using ReeLib.Common;
using ReeLib.Efx;
using ReeLib.Efx.Structs.Basic;
using ReeLib.Efx.Structs.Common;
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
if (args.Length >= 1 && args[0] == "ptbehaviorcatalog")
{
    return RunPtBehaviorCatalog(args);
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
    Console.WriteLine("  dotnet <dll> ptbehaviorcatalog <语料目录> <json 输出路径>");
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

        // Python 侧只写 Expression.parsedExpressions（人类可读的公式字符串——反序列化时已经
        // 由 vendor 的 EFXExpressionTreeJsonConverter 调用 EfxExpressionStringParser.Parse()
        // 编译成树了），不写 expressions（真正参与二进制写出的扁平后缀栈）。这里补一步把树
        // 摊平回 expressions，镜像 EfxFile.ParseExpressions() 自己的遍历方式（Entries + 递归
        // Actions/efxrData），但只处理 IExpressionAttribute——IMaterialExpressionAttribute
        // 本轮不碰，维持原样透传。
        CompileExpressions(efx);

        // Subselect（EffectGroups）组内成员顺序（efxEntryIndexes）快照：`UpdateEffectGroups()`
        // （EfxFile.cs:1302，vendor 代码，不改）写出时无条件把每个已匹配组的 efxEntryIndexes
        // 按 Entry 扫描顺序（ascending）重新生成，不管传进来的原始顺序是什么——见 PLAN.md E2。
        // 数组级顺序（EffectGroups 本身谁在前谁在后）已经靠"不传空数组"绕开了，但组内成员的
        // 相对顺序这条绕不过去，只能记下 Write() 之前的原始顺序，写完之后原地把这几个 int
        // 换回去（见 PatchEffectGroupMemberOrder()）。
        var originalGroupOrder = efx.EffectGroups.ToDictionary(
            g => g.groupName, g => (int[])(g.efxEntryIndexes ?? Array.Empty<int>()).Clone());

        efx.WriteTo(efxOutPath);
        PatchEffectGroupMemberOrder(efxOutPath, efx, originalGroupOrder);

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

// 把 UpdateEffectGroups() 重新排过的组内成员顺序（efxEntryIndexes）改回"原始相对顺序 +
// 新成员追加到末尾"——不改变集合内容（还是同一组 entry 下标），只调整这几个 int 在文件里的
// 排列顺序。定位靠 `EffectGroup.Start`（BaseModel 公开属性，Write() 时记的这个对象在流里的
// 起始位置，见 Models.cs），不是靠猜整个文件的偏移布局：一个 EffectGroup 的二进制布局固定是
// hash16(4B) + hash8(4B) + valueCount(4B) + efxEntryIndexes(valueCount * 4B)，见 EfxFile.cs
// 的字段声明顺序，所以下标数组总是从 `Start + 12` 开始。
static void PatchEffectGroupMemberOrder(string path, EfxFile efx, Dictionary<string, int[]> originalOrder)
{
    byte[]? bytes = null;
    foreach (var grp in efx.EffectGroups)
    {
        // 新增的组（UpdateEffectGroups() 里"unaccounted"分支现造的）在 Write() 之前的快照里
        // 没有对应项，本来就是 vendor 刚生成的顺序，不需要改。
        if (!originalOrder.TryGetValue(grp.groupName, out var original)) continue;

        var current = grp.efxEntryIndexes ?? Array.Empty<int>();
        var finalSet = new HashSet<int>(current);
        // 原顺序里还在的，保持相对顺序；原顺序里没有的（这次新加入这个组的成员），按升序
        // 追加到末尾——对应"新增在尾部追加"的要求。
        var originalSet = new HashSet<int>(original);
        var desired = original.Where(finalSet.Contains)
            .Concat(current.Where(v => !originalSet.Contains(v)).OrderBy(v => v))
            .ToArray();

        if (desired.Length != current.Length || desired.SequenceEqual(current)) continue;

        bytes ??= File.ReadAllBytes(path);
        var indicesOffset = (int)grp.Start + 12;
        for (int k = 0; k < desired.Length; k++)
        {
            BitConverter.GetBytes(desired[k]).CopyTo(bytes, indicesOffset + k * 4);
        }
    }
    if (bytes != null) File.WriteAllBytes(path, bytes);
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
// 把 DoWrite() 算出来的 -1 改回 0——跟 EffectGroups 顺序的 `PatchEffectGroupMemberOrder()`
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
// PatchEffectGroupMemberOrder() 的思路）——一个 UvsPattern 的二进制布局固定是
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
// `mdfPropertyIndex` 猜错等于静默改到另一个参数上（铁律 #2/#7）。
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

// attrindex 子命令：在整个语料上建一份 "attribute 类型 -> 出现过它的文件列表" 反查索引，
// 给 Blender 那边的资产库面板用（"设定语料路径 -> 挑一个 attr 类型 -> 列出命中文件 -> 直接
// 导入"）。只做文件级命中，不记录具体是哪个 entry/第几个实例——用途是"找一个带这个 attr 的
// 参考文件"，不是"精确定位"。
//
// 和 fieldstats/fieldstatsbatch 的关键区别：那两个只统计跨语料的聚合值（取值分布、实例数），
// 从不记录"这个实例来自哪个文件"；这里反过来，每种类型只需要知道"文件命中过没有"，不需要
// 字段级直方图，所以不走 Tally/Bump 那一套，只用 HashSet 去重。
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

    void Visit(EFXEntryBase container, HashSet<string> touched)
    {
        foreach (var attr in container.Attributes)
        {
            touched.Add(attr.type.ToString());
            if (attr is EFXAttributePlayEmitter { efxrData: not null } pe)
            {
                foreach (var e in pe.efxrData.Entries) Visit(e, touched);
                foreach (var a in pe.efxrData.Actions) Visit(a, touched);
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

            // 一个文件里同一类型可能出现好几次，只需要记一次"这个文件命中过"——先收集到
            // 一个临时集合里，再统一写回 hits，避免同一文件在 hits[type] 里被 Add 好几遍
            // （HashSet.Add 本身就去重，这里只是省一次重复的字典查找，不影响正确性）。
            var touched = new HashSet<string>();
            foreach (var e in efx.Entries) Visit(e, touched);
            foreach (var a in efx.Actions) Visit(a, touched);

            if (touched.Count > 0)
            {
                var relPath = Path.GetRelativePath(dir, path).Replace('\\', '/');
                foreach (var typeName in touched)
                {
                    if (!hits.TryGetValue(typeName, out var set))
                        hits[typeName] = set = new HashSet<string>();
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
    };
    File.WriteAllText(jsonOutPath, JsonSerializer.Serialize(payload, new JsonSerializerOptions { WriteIndented = true }));
    Console.WriteLine($"OK: {hits.Count} 种类型（扫描 {scanned}/{files.Count} 个文件，失败 {failed}）-> {jsonOutPath}");
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
        Console.WriteLine("用法: dotnet <dll> condstats <语料目录> <attribute 类型名> <条件字段名> <json 输出路径> [每字段保留的不同取值数，默认 40]");
        return 1;
    }
    var dir = args[1];
    var typeName = args[2];
    var condField = args[3];
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
                string condValue = "MISSING";
                if (node != null && node.TryGetPropertyValue(condField, out var condNode) && condNode != null)
                    condValue = condNode.ToJsonString();
                else
                    missingCond++;

                if (!buckets.TryGetValue(condValue, out var bucket))
                    bucket = (0, new Dictionary<string, Dictionary<string, int>>());
                bucket.count++;
                if (node != null)
                {
                    foreach (var (key, child) in node)
                    {
                        if (key == "$type" || key == condField) continue;
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

    var byBehavior = new Dictionary<string, PtBehaviorBucket>();

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
                }
                var seqKey = string.Join("|", names);
                bucket.Sequences[seqKey] = bucket.Sequences.GetValueOrDefault(seqKey) + 1;
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
        behaviors = byBehavior.Count,
        byBehavior = byBehavior.OrderByDescending(kv => kv.Value.InstanceCount).ToDictionary(
            kv => kv.Key,
            kv => new
            {
                instanceCount = kv.Value.InstanceCount,
                properties = kv.Value.Properties.OrderBy(p => p.Key).ToDictionary(
                    p => p.Key,
                    p => new
                    {
                        freq = p.Value.Freq,
                        dataTypes = p.Value.DataTypes,
                        varHashes = p.Value.VarHashes,
                    }),
                sequences = kv.Value.Sequences.OrderByDescending(s => s.Value)
                        .ToDictionary(s => s.Key, s => s.Value),
            }),
    };
    File.WriteAllText(jsonOutPath, JsonSerializer.Serialize(payload, new JsonSerializerOptions { WriteIndented = true }));
    Console.WriteLine(
        $"OK: PtBehavior 共 {instances} 个实例，{byBehavior.Count} 个 behaviorString"
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
    if (attr is not IClipAttribute clipAttr) return;
    var clip = clipAttr.Clip;
    clip.clips ??= Array.Empty<EfxClipHeader>();
    clip.frames ??= Array.Empty<EfxClipFrame>();
    clip.interpolationData ??= Array.Empty<EfxClipInterpolationTangents>();
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
}

class PtBehaviorPropertyBucket
{
    public int Freq;
    public Dictionary<string, int> DataTypes = new();
    public Dictionary<string, int> VarHashes = new();
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

        return EfxExpressionStringParser.Parse(expr, parameters);
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
