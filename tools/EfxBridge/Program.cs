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

static JsonSerializerOptions CreateBridgeJsonOptions() => new(EfxJsonTypeResolver.jsonOptions)
{
    // EFX 里的 float 字段会出现 Infinity/NaN（例如"无上限"语义），默认 JSON 数字语法
    // 不支持这两个字面量，需要显式放开（写成 "Infinity"/"NaN" 字符串形式的具名浮点值）。
    NumberHandling = System.Text.Json.Serialization.JsonNumberHandling.AllowNamedFloatingPointLiterals,
};

if (args.Length >= 1 && args[0] == "dump")
{
    return RunDump(args);
}
if (args.Length >= 1 && args[0] == "load")
{
    return RunLoad(args);
}

if (args.Length < 2 || args[0] != "roundtrip")
{
    Console.WriteLine("用法:");
    Console.WriteLine("  dotnet <dll> roundtrip <目录或文件路径> [--verbose] [--dump <输出目录>]");
    Console.WriteLine("  dotnet <dll> dump <efx 文件路径> <json 输出路径>");
    Console.WriteLine("  dotnet <dll> load <json 文件路径> <efx 输出路径>");
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
