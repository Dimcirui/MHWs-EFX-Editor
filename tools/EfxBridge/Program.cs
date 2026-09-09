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
using ReeLib.Efx;
using ReeLib.Efx.Structs.Basic;
using ReeLib.Efx.Structs.Common;

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

if (args.Length < 2 || args[0] != "roundtrip")
{
    Console.WriteLine("用法:");
    Console.WriteLine("  dotnet <dll> roundtrip <目录或文件路径> [--verbose] [--dump <输出目录>]");
    Console.WriteLine("  dotnet <dll> dump <efx 文件路径> <json 输出路径>");
    Console.WriteLine("  dotnet <dll> load <json 文件路径> <efx 输出路径>");
    Console.WriteLine("  dotnet <dll> exprcheck <公式文本>");
    Console.WriteLine("  dotnet <dll> types <json 输出路径> [游戏版本，默认 MHWilds]");
    Console.WriteLine("  dotnet <dll> new attribute <类型名> <json 输出路径> [游戏版本，默认 MHWilds]");
    Console.WriteLine("  dotnet <dll> new entry|action <json 输出路径> [游戏版本，默认 MHWilds]");
    Console.WriteLine("  dotnet <dll> fieldstats <语料目录> <attribute 类型名> <json 输出路径> [每字段保留的不同取值数，默认 40]");
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

        efx.WriteTo(efxOutPath);
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
