using System;
using System.IO;
using System.Linq;
using System.Text;
using ICSharpCode.Decompiler;
using ICSharpCode.Decompiler.CSharp;
using ICSharpCode.Decompiler.Metadata;

class Program
{
    static int Main(string[] args)
    {
        if (args.Length < 2)
        {
            Console.WriteLine("usage: decomp <assembly.dll> <outdir>");
            return 1;
        }
        string asmPath = args[0];
        string outDir = args[1];
        Directory.CreateDirectory(outDir);

        var settings = new DecompilerSettings
        {
            ThrowOnAssemblyResolveErrors = false,
            ShowXmlDocumentation = true,
            UseSdkStyleProjectFormat = false,
        };

        var decompiler = new CSharpDecompiler(asmPath, settings);

        int count = 0;
        foreach (var type in decompiler.TypeSystem.MainModule.TopLevelTypeDefinitions)
        {
            try
            {
                string ns = type.Namespace ?? "";
                string dir = Path.Combine(outDir, ns.Replace('.', Path.DirectorySeparatorChar));
                Directory.CreateDirectory(dir);
                string code = decompiler.DecompileTypeAsString(new ICSharpCode.Decompiler.TypeSystem.FullTypeName(type.FullName));
                string file = Path.Combine(dir, Sanitize(type.Name) + ".cs");
                File.WriteAllText(file, code, new UTF8Encoding(false));
                count++;
                if (count % 200 == 0) Console.WriteLine($"  {count} types...");
            }
            catch (Exception ex)
            {
                Console.WriteLine("FAIL " + type.FullName + " : " + ex.Message);
            }
        }
        Console.WriteLine($"done: {count} types -> {outDir}");
        return 0;
    }

    static string Sanitize(string name)
    {
        foreach (char c in Path.GetInvalidFileNameChars()) name = name.Replace(c, '_');
        return name;
    }
}
