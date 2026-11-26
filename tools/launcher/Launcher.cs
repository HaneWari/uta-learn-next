// Native entry point for the portable build.
//
// The `.vbs` and `.cmd` it replaces had three problems a compiled launcher
// fixes outright:
//   * a `.vbs` has no icon in Explorer, so the app looked like a script folder;
//   * SmartScreen treats an unsigned script and an unsigned exe the same, but an
//     exe can *be* signed — a script can never carry an Authenticode signature;
//   * the windowed entry point inherited no console streams, which crashed
//     uvicorn's logger before this launcher existed.
//
// It does one thing: locate `<app>\python\pythonw.exe`, start `desktop.py` with
// the app folder as the working directory, and exit. Everything else — port
// choice, readiness wait, the window — stays in desktop.py where it can be
// tested without rebuilding an exe.
using System;
using System.Diagnostics;
using System.IO;
using System.Windows.Forms;

namespace UtaLearnNext
{
    internal static class Launcher
    {
        [STAThread]
        private static int Main(string[] args)
        {
            string root = AppDomain.CurrentDomain.BaseDirectory.TrimEnd('\\');
            string python = Path.Combine(root, "python", "pythonw.exe");
            string desktop = Path.Combine(root, "desktop.py");

            // A launcher started from a shortcut or the shell inherits that
            // folder as the CWD. desktop.py resolves localdata/ against its own
            // location, but a stray CWD still breaks relative paths in user
            // config, so pin it to the app folder.
            Directory.SetCurrentDirectory(root);

            if (!File.Exists(python))
            {
                Fail("找不到内置的 Python 运行时:\n\n" + python +
                     "\n\n请确认压缩包已完整解压(不要直接在压缩包里运行)。");
                return 2;
            }
            if (!File.Exists(desktop))
            {
                Fail("找不到 desktop.py:\n\n" + desktop);
                return 3;
            }

            var start = new ProcessStartInfo
            {
                FileName = python,
                Arguments = Quote(desktop),
                WorkingDirectory = root,
                // pythonw has no console, so `UseShellExecute = false` would
                // hand it a null stdout and uvicorn's formatter dies. Let the
                // shell create the process; desktop.py also installs a sink.
                UseShellExecute = true,
            };
            foreach (string a in args)
            {
                start.Arguments += " " + Quote(a);
            }

            try
            {
                Process.Start(start);
                return 0;
            }
            catch (Exception e)
            {
                Fail("启动失败:\n\n" + e.Message);
                return 1;
            }
        }

        private static string Quote(string value)
        {
            return "\"" + value.Replace("\"", "\\\"") + "\"";
        }

        private static void Fail(string message)
        {
            MessageBox.Show(message, "Uta Learn Next",
                            MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
    }
}
