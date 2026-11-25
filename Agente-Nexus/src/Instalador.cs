// =====================================================================
// Instalador autoextraível do Agente Nexus
// =====================================================================
//
// ## Por que não MSI
//
// MSI de verdade exige WiX, que exige SDK. O alvo é distribuir por GPO ou
// SCCM para 3.000 máquinas — e um `.exe` único resolve isso: o GPO executa o
// arquivo, ele se eleva, extrai e instala.
//
// ## O que ele faz
//
//   1. Recebe `SERVER=` e `CODIGO=` como argumento (ou pela interface)
//   2. Extrai o agente e os scripts de instalação e remoção para %TEMP%
//   3. Executa o instalador com `-ExecutionPolicy Bypass`
//
// ## Por que autoextraível e não só o .ps1
//
// Script por GPO esbarra em política de execução — e cada máquina pode ter a
// sua. O `.exe` não: ele executa o PowerShell **com a política contornada
// para aquela chamada**, sem alterar a configuração da máquina.
//
// ## Assinatura de código
//
// Sem certificado de assinatura, o SmartScreen mostra "aplicativo não
// reconhecido" e antivírus corporativo pode bloquear. Isso não se resolve em
// código — é compra de certificado e assinatura com `signtool`.
//
// =====================================================================

using System;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Threading.Tasks;
using System.Windows.Forms;

namespace AgenteNexus
{
    public static class Instalador
    {
        private const string Titulo = "Nexus Agente";

        /// <summary>Extrai um recurso embutido para um arquivo temporário.</summary>
        private static string Extrair(string recurso, string nomeArquivo, string destino)
        {
            var asm = Assembly.GetExecutingAssembly();
            using (Stream s = asm.GetManifestResourceStream(recurso))
            {
                if (s == null)
                    throw new InvalidOperationException("Recurso ausente: " + recurso);
                string caminho = Path.Combine(destino, nomeArquivo);
                using (var f = File.Create(caminho))
                    s.CopyTo(f);
                return caminho;
            }
        }

        /// <summary>Lê `CHAVE=valor` dos argumentos.</summary>
        private static string Argumento(string[] args, string chave)
        {
            foreach (string a in args)
            {
                if (a.StartsWith(chave + "=", StringComparison.OrdinalIgnoreCase))
                    return a.Substring(chave.Length + 1).Trim();
            }
            return null;
        }

        private static bool TemFlag(string[] args, params string[] nomes)
        {
            foreach (string a in args)
            {
                foreach (string nome in nomes)
                    if (string.Equals(a.TrimStart('-', '/'), nome, StringComparison.OrdinalIgnoreCase))
                        return true;
            }
            return false;
        }

        /// <summary>
        /// Traduz o motivo do servidor numa orientacao pratica.
        ///
        /// Sem isto o tecnico ve "serial_nao_cadastrado" e nao sabe se o
        /// problema e a maquina, a rede ou o codigo.
        /// </summary>
        private static string Dica(string detalhe)
        {
            if (detalhe.IndexOf("sem_serial", StringComparison.OrdinalIgnoreCase) >= 0
                || detalhe.IndexOf("serial_nao_cadastrado", StringComparison.OrdinalIgnoreCase) >= 0)
            {
                return "\n\nEsta maquina NAO esta no inventario.\n\n"
                     + "Ela foi para a fila de cadastro. Peca ao TI para cadastra-la\n"
                     + "em Administracao > Agente Nexus, e depois rode o instalador\n"
                     + "novamente com um codigo novo.";
            }
            if (detalhe.IndexOf("codigo_invalido", StringComparison.OrdinalIgnoreCase) >= 0
                || detalhe.IndexOf("codigo_expirado", StringComparison.OrdinalIgnoreCase) >= 0)
            {
                return "\n\nO codigo de instalacao nao vale mais.\n\n"
                     + "Gere outro em Administracao > Agente Nexus.";
            }
            if (detalhe.IndexOf("Administrador", StringComparison.OrdinalIgnoreCase) >= 0)
            {
                return "\n\nA instalacao precisa de privilegio de administrador.";
            }
            return "";
        }

        private static int Main(string[] args)
        {
            bool silencioso = TemFlag(args, "s", "silent", "silencioso", "qn");
            bool atualizar = TemFlag(args, "atualizar");
            try
            {
                string servidor = Argumento(args, "SERVER");
                string codigo = Argumento(args, "CODIGO");

                // Sem argumentos, pergunta. Com argumentos, instala direto —
                // é o modo GPO/SCCM.
                if (!atualizar && (string.IsNullOrEmpty(servidor) || string.IsNullOrEmpty(codigo)))
                {
                    if (silencioso)
                    {
                        Console.Error.WriteLine("Modo silencioso exige SERVER= e CODIGO=.");
                        return 2;
                    }
                    using (var form = new JanelaInstalacao())
                    {
                        if (form.ShowDialog() != DialogResult.OK) return 1;
                        servidor = form.Servidor;
                        codigo = form.Codigo;
                    }
                }

                string temp = Path.Combine(Path.GetTempPath(),
                    "nexus-agente-" + Guid.NewGuid().ToString("N").Substring(0, 8));
                Directory.CreateDirectory(temp);

                try
                {
                    Extrair("agente.exe", "agente.exe", temp);
                    Extrair("instalar.ps1", "instalar.ps1", temp);
                    Extrair("desinstalar.ps1", "desinstalar.ps1", temp);

                    var psi = new ProcessStartInfo
                    {
                        FileName = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.System),
                            @"WindowsPowerShell\v1.0\powershell.exe"),
                        Arguments =
                            "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File \"" +
                            Path.Combine(temp, "instalar.ps1") + "\"" +
                            (silencioso ? " -Silencioso" : "") +
                            (atualizar ? " -Atualizar" : ""),
                        UseShellExecute = false,
                        CreateNoWindow = true,
                        // Capturar a saída é o que transforma "codigo 1" numa
                        // mensagem que diz o que fazer. Sem isto, o instalador
                        // esconde a única informação útil.
                        RedirectStandardOutput = true,
                        RedirectStandardError = true,
                    };
                    psi.EnvironmentVariables["NEXUS_SETUP_SERVIDOR"] = servidor ?? "";
                    psi.EnvironmentVariables["NEXUS_SETUP_CODIGO"] = codigo ?? "";

                    using (var p = Process.Start(psi))
                    {
                        Task<string> saida = p.StandardOutput.ReadToEndAsync();
                        Task<string> erro = p.StandardError.ReadToEndAsync();
                        p.WaitForExit();

                        if (p.ExitCode != 0)
                        {
                            string detalhe = (erro.Result + "\n" + saida.Result).Trim();
                            if (detalhe.Length == 0) detalhe = "(sem saida)";
                            string dica = Dica(detalhe);

                            if (!silencioso)
                                MessageBox.Show(
                                    "A instalacao falhou.\n\n" + detalhe + dica,
                                    Titulo, MessageBoxButtons.OK, MessageBoxIcon.Error);
                            Console.Error.WriteLine(detalhe);
                            return p.ExitCode;
                        }
                        if (!silencioso)
                        {
                            string detalhe = saida.Result.Trim();
                            MessageBox.Show(detalhe.Length > 0 ? detalhe : "Agente Nexus instalado.",
                                Titulo, MessageBoxButtons.OK, MessageBoxIcon.Information);
                        }
                    }
                    return 0;
                }
                finally
                {
                    try { Directory.Delete(temp, true); } catch (Exception) { }
                }
            }
            catch (Exception ex)
            {
                Console.Error.WriteLine("Falha: " + ex.Message);
                try
                {
                    if (!silencioso)
                        MessageBox.Show("Falha na instalacao:\n\n" + ex.Message,
                            Titulo, MessageBoxButtons.OK, MessageBoxIcon.Error);
                }
                catch (Exception) { }
                return 1;
            }
        }
    }

    /// <summary>Janela mínima — só os dois campos que a instalação precisa.</summary>
    internal class JanelaInstalacao : Form
    {
        private readonly TextBox _servidor;
        private readonly TextBox _codigo;

        public string Servidor { get { return _servidor.Text.Trim(); } }
        public string Codigo { get { return _codigo.Text.Trim(); } }

        public JanelaInstalacao()
        {
            Text = "Instalar " + "Nexus Agente";
            Width = 460;
            Height = 260;
            FormBorderStyle = FormBorderStyle.FixedDialog;
            StartPosition = FormStartPosition.CenterScreen;
            MaximizeBox = false;
            MinimizeBox = false;

            var rotuloServidor = new Label
            {
                Text = "Servidor Nexus (ex.: http://10.0.0.5:4545)",
                Left = 16, Top = 16, Width = 420,
            };
            _servidor = new TextBox { Left = 16, Top = 38, Width = 420 };

            var rotuloCodigo = new Label
            {
                Text = "Codigo de instalacao (gerado em Administracao > Agente Nexus)",
                Left = 16, Top = 76, Width = 420,
            };
            _codigo = new TextBox { Left = 16, Top = 98, Width = 420 };

            var ok = new Button { Text = "Instalar", Left = 250, Top = 140, Width = 90 };
            ok.Click += (s, e) =>
            {
                if (Servidor.Length == 0 || Codigo.Length == 0)
                {
                    MessageBox.Show("Preencha os dois campos.", "Nexus Agente",
                        MessageBoxButtons.OK, MessageBoxIcon.Warning);
                    return;
                }
                DialogResult = DialogResult.OK;
                Close();
            };

            var cancelar = new Button
            {
                Text = "Cancelar", Left = 346, Top = 140, Width = 90,
                DialogResult = DialogResult.Cancel,
            };

            Controls.Add(rotuloServidor);
            Controls.Add(_servidor);
            Controls.Add(rotuloCodigo);
            Controls.Add(_codigo);
            Controls.Add(ok);
            Controls.Add(cancelar);
            AcceptButton = ok;
            CancelButton = cancelar;
        }
    }
}
