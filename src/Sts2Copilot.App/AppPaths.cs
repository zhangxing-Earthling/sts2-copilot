using System.IO;

namespace Sts2Copilot;

/// <summary>
/// Single source of truth for on-disk paths. Logs live under the project's
/// logs/ folder, not %APPDATA%, so they stay next to the code and are easy to
/// hand to DSH. STS2_COPILOT_LOG_DIR can override the root.
/// </summary>
public static class AppPaths
{
    public static string ProjectRoot { get; } = ResolveProjectRoot();

    public static string LogRoot { get; } = ResolveLogRoot();

    public static string RunsDir { get; } = Path.Combine(LogRoot, "runs");

    public static string AppLogDir { get; } = Path.Combine(LogRoot, "app");

    public static string AppLogFile { get; } = Path.Combine(AppLogDir, "app.log");

    static AppPaths()
    {
        foreach (string directory in new[] { RunsDir, AppLogDir })
        {
            try
            {
                Directory.CreateDirectory(directory);
            }
            catch
            {
                // Logging directories must never prevent the app from starting.
            }
        }
    }

    private static string ResolveProjectRoot()
    {
        string? current = TryProjectRoot(Directory.GetCurrentDirectory());
        if (current != null)
        {
            return current;
        }

        DirectoryInfo? dir = new DirectoryInfo(AppContext.BaseDirectory);
        for (int i = 0; i < 6 && dir != null; i++, dir = dir.Parent)
        {
            if (File.Exists(Path.Combine(dir.FullName, ".agent.md")))
            {
                return dir.FullName;
            }
        }

        return AppContext.BaseDirectory;
    }

    private static string? TryProjectRoot(string path)
    {
        try
        {
            return File.Exists(Path.Combine(path, ".agent.md")) ? Path.GetFullPath(path) : null;
        }
        catch
        {
            return null;
        }
    }

    private static string ResolveLogRoot()
    {
        string? configured = Environment.GetEnvironmentVariable("STS2_COPILOT_LOG_DIR");
        if (!string.IsNullOrWhiteSpace(configured))
        {
            return Path.GetFullPath(configured);
        }

        return Path.Combine(ProjectRoot, "logs");
    }
}
