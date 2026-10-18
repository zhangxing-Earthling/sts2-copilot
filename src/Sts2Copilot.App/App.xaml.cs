using System.IO;
using System.Windows;
using System.Windows.Threading;

namespace Sts2Copilot;

public partial class App : System.Windows.Application
{
    private static readonly string LogPath = Path.Combine(AppContext.BaseDirectory, "app.log");

    protected override void OnStartup(StartupEventArgs e)
    {
        AppDomain.CurrentDomain.UnhandledException += (_, args) => Log("AppDomain: " + args.ExceptionObject);
        DispatcherUnhandledException += (_, args) =>
        {
            Log("Dispatcher: " + args.Exception);
            args.Handled = true;
        };

        Log("startup");
        base.OnStartup(e);
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
