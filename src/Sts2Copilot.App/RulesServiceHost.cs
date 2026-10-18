using System.Diagnostics;
using System.IO;
using System.Net.Http;

namespace Sts2Copilot;

/// <summary>
/// Starts the local Python rules service on demand and owns it for this app run.
/// If a service is already healthy (for example started manually), it is reused
/// and never killed by this process.
/// </summary>
public sealed class RulesServiceHost : IDisposable
{
    private const string HealthUrl = "http://127.0.0.1:8765/health";
    private static readonly HttpClient Health = new()
    {
        Timeout = TimeSpan.FromMilliseconds(350)
    };

    private Process? _process;
    private bool _owned;

    public string? Error { get; private set; }

    public async Task<bool> EnsureRunningAsync()
    {
        Error = null;
        if (await IsHealthyAsync())
        {
            return true;
        }

        string? rulesDir = FindRulesDirectory();
        if (rulesDir == null)
        {
            Error = "找不到 rules/server.py（发布目录缺少 rules/）";
            return false;
        }

        string? python = FindPython(out bool useLauncher);
        if (python == null)
        {
            Error = "找不到 Python（可设置 STS2_COPILOT_PYTHON 指向 python.exe）";
            return false;
        }

        try
        {
            var startInfo = new ProcessStartInfo
            {
                FileName = python,
                WorkingDirectory = rulesDir,
                UseShellExecute = false,
                CreateNoWindow = true,
                WindowStyle = ProcessWindowStyle.Hidden
            };
            if (useLauncher)
            {
                startInfo.ArgumentList.Add("-3");
            }

            startInfo.ArgumentList.Add(Path.Combine(rulesDir, "server.py"));
            startInfo.Environment["PYTHONUNBUFFERED"] = "1";

            _process = Process.Start(startInfo);
            _owned = _process != null;
            if (_process == null)
            {
                Error = "无法启动 Python 规则服务";
                return false;
            }

            // Python + imports usually take <1s; allow a slow cold start.
            for (int i = 0; i < 40; i++)
            {
                await Task.Delay(100);
                if (await IsHealthyAsync())
                {
                    App.Log($"rules service started pid={_process.Id} python={python}");
                    return true;
                }

                if (_process.HasExited)
                {
                    Error = $"Python 规则服务退出（exit {_process.ExitCode}）";
                    return false;
                }
            }

            Error = "Python 规则服务启动超时";
            return false;
        }
        catch (Exception ex)
        {
            Error = "启动规则服务失败：" + ex.Message;
            return false;
        }
    }

    public void Dispose()
    {
        if (!_owned || _process == null)
        {
            return;
        }

        try
        {
            if (!_process.HasExited)
            {
                _process.Kill(entireProcessTree: true);
            }
        }
        catch
        {
            // Shutdown must never throw.
        }
        finally
        {
            _process.Dispose();
            _process = null;
        }
    }

    private static async Task<bool> IsHealthyAsync()
    {
        try
        {
            using HttpResponseMessage response = await Health.GetAsync(HealthUrl);
            return response.IsSuccessStatusCode;
        }
        catch
        {
            return false;
        }
    }

    private static string? FindRulesDirectory()
    {
        string? configured = Environment.GetEnvironmentVariable("STS2_COPILOT_RULES_DIR");
        if (!string.IsNullOrWhiteSpace(configured))
        {
            string path = Path.GetFullPath(configured);
            if (File.Exists(Path.Combine(path, "server.py")))
            {
                return path;
            }
        }

        string bundled = Path.Combine(AppContext.BaseDirectory, "rules");
        if (File.Exists(Path.Combine(bundled, "server.py")))
        {
            return bundled;
        }

        DirectoryInfo? dir = new DirectoryInfo(AppContext.BaseDirectory);
        for (int i = 0; i < 6 && dir != null; i++, dir = dir.Parent)
        {
            string candidate = Path.Combine(dir.FullName, "py", "rules");
            if (File.Exists(Path.Combine(candidate, "server.py")))
            {
                return candidate;
            }
        }

        return null;
    }

    private static string? FindPython(out bool useLauncher)
    {
        useLauncher = false;

        string? configured = Environment.GetEnvironmentVariable("STS2_COPILOT_PYTHON");
        if (!string.IsNullOrWhiteSpace(configured) && File.Exists(configured))
        {
            useLauncher = Path.GetFileName(configured).Equals("py.exe", StringComparison.OrdinalIgnoreCase);
            return configured;
        }

        string? path = Environment.GetEnvironmentVariable("PATH");
        if (string.IsNullOrWhiteSpace(path))
        {
            return null;
        }

        foreach (string rawDir in path.Split(Path.PathSeparator, StringSplitOptions.RemoveEmptyEntries))
        {
            string directory = rawDir.Trim().Trim('"');
            if (directory.Length == 0)
            {
                continue;
            }

            string python = Path.Combine(directory, "python.exe");
            if (File.Exists(python))
            {
                return python;
            }
        }

        foreach (string rawDir in path.Split(Path.PathSeparator, StringSplitOptions.RemoveEmptyEntries))
        {
            string directory = rawDir.Trim().Trim('"');
            if (directory.Length == 0)
            {
                continue;
            }

            string launcher = Path.Combine(directory, "py.exe");
            if (File.Exists(launcher))
            {
                useLauncher = true;
                return launcher;
            }
        }

        return null;
    }
}
