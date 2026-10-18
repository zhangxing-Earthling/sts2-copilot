using System.IO;
using System.Windows;
using System.Windows.Threading;

namespace Sts2Copilot;

public partial class App : System.Windows.Application
{
    private static readonly string LogPath = AppPaths.AppLogFile;
    private static Mutex? _singleInstance;
    private static bool _ownsMutex;

    public static RulesServiceHost RulesHost { get; } = new();

    protected override void OnStartup(StartupEventArgs e)
    {
        _singleInstance = new Mutex(true, "Sts2Copilot.SingleInstance", out bool createdNew);
        _ownsMutex = createdNew;
        if (!createdNew)
        {
            System.Windows.MessageBox.Show("StS2 Copilot 已经在运行。", "StS2 Copilot", MessageBoxButton.OK, MessageBoxImage.Information);
            Shutdown();
            return;
        }

        AppDomain.CurrentDomain.UnhandledException += (_, args) => Log("AppDomain: " + args.ExceptionObject);
        DispatcherUnhandledException += (_, args) =>
        {
            Log("Dispatcher: " + args.Exception);
            args.Handled = true;
        };

        Log("startup");
        base.OnStartup(e);
    }

    protected override void OnExit(ExitEventArgs e)
    {
        RulesHost.Dispose();
        if (_ownsMutex)
        {
            _singleInstance?.ReleaseMutex();
        }

        _singleInstance?.Dispose();
        base.OnExit(e);
    }

    public static void Log(string message)
    {
        try
        {
            File.AppendAllText(LogPath, $"{DateTime.Now:HH:mm:ss} {message}{Environment.NewLine}");
        }
        catch
        {
            // Logging must never crash the app.
        }
    }
}
