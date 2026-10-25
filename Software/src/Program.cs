using System;
using System.IO;
using System.Text;
using System.Threading;
using System.Windows.Forms;

namespace NexusDesktop
{
    /// <summary>
    /// Ponto de entrada do aplicativo.
    ///
    /// ## Instância única
    ///
    /// Abrir o programa duas vezes criaria duas janelas apontando para o mesmo
    /// servidor e disputando a mesma pasta de dados do WebView2 — o que pode
    /// corromper o cache. O `Mutex` impede a segunda execução.
    ///
    /// ## Registro de falhas
    ///
    /// Um programa `winexe` não tem console: uma exceção não tratada
    /// simplesmente fecha a janela, sem dizer nada. Quem usa não tem o que
    /// relatar, e quem dá suporte não tem o que ler.
    ///
    /// Por isso três capturas, todas escrevendo em `%APPDATA%\Nexus\erro.log`:
    /// a da thread de interface, a de qualquer thread, e a do próprio `Main`.
    /// </summary>
    internal static class Program
    {
        [STAThread]
        private static void Main()
        {
            // Marca de vida: distingue "não chegou a iniciar" de "iniciou e
            // saiu por algum motivo". Sem isto, um programa `winexe` que
            // fecha sem exceção não deixa rastro nenhum.
            Registrar("Inicio", null);

            AppDomain.CurrentDomain.UnhandledException += (s, e) =>
                Registrar("AppDomain", e.ExceptionObject as Exception);

            Application.ThreadException += (s, e) =>
                Registrar("Interface", e.Exception);

            Application.SetUnhandledExceptionMode(UnhandledExceptionMode.CatchException);

            bool criou;
            using (var trava = new Mutex(true, @"Local\NexusDesktop.App", out criou))
            {
                if (!criou)
                {
                    MessageBox.Show(
                        "O Nexus já está aberto.\n\nProcure a janela na barra de tarefas.",
                        "Nexus",
                        MessageBoxButtons.OK,
                        MessageBoxIcon.Information);
                    return;
                }

                try
                {
                    Application.EnableVisualStyles();
                    Application.SetCompatibleTextRenderingDefault(false);

                    var cfg = Configuracao.Carregar();

                    // Sem endereço salvo (primeira execução, ou configuração
                    // apagada), a primeira coisa é perguntar onde está o servidor.
                    if (!cfg.TemServidor)
                    {
                        using (var dlg = new ConfigForm(cfg, true))
                        {
                            if (dlg.ShowDialog() != DialogResult.OK) return;
                        }
                    }

                    Application.Run(new MainForm(cfg));
                }
                catch (Exception ex)
                {
                    Registrar("Main", ex);
                    MessageBox.Show(
                        "O Nexus encontrou um erro e precisou fechar.\n\n"
                        + ex.Message
                        + "\n\nDetalhes em:\n" + CaminhoLog,
                        "Nexus",
                        MessageBoxButtons.OK,
                        MessageBoxIcon.Error);
                }

                GC.KeepAlive(trava);
            }
        }

        internal static string CaminhoLog
        {
            get
            {
                return Path.Combine(
                    Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData),
                    "Nexus", "erro.log");
            }
        }

        /// <summary>
        /// Grava uma ocorrência no log. Público dentro do assembly porque a
        /// janela também precisa registrar o que deu errado ao abrir — e um
        /// `MessageBox` só não basta para diagnosticar.
        /// </summary>
        internal static void Registrar(string origem, Exception ex)
        {
            try
            {
                var pasta = Path.GetDirectoryName(CaminhoLog);
                if (!Directory.Exists(pasta)) Directory.CreateDirectory(pasta);

                var sb = new StringBuilder();
                sb.AppendLine("=========================================================");
                sb.AppendLine(DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss") + "  [" + origem + "]");
                sb.AppendLine(ex == null ? "(sem exceção)" : ex.ToString());
                File.AppendAllText(CaminhoLog, sb.ToString(), Encoding.UTF8);
            }
            catch
            {
                // Se nem o log pode ser escrito, não há o que fazer.
            }
        }
    }
}
