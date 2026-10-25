using System;
using System.Diagnostics;
using System.Drawing;
using System.Threading.Tasks;
using System.Windows.Forms;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;

namespace NexusDesktop
{
    /// <summary>
    /// Janela principal: o Nexus dentro do WebView2.
    ///
    /// ## Por que hospedar a aplicação web, em vez de reescrever a interface
    ///
    /// O Nexus é uma PWA: 19 módulos, 34 telas, e a mesma API. Reescrever isso
    /// numa interface nativa significaria **duas interfaces para manter** — e
    /// cada correção feita na web precisaria ser refeita aqui.
    ///
    /// Hospedando a mesma aplicação, a paridade é **por construção**: não
    /// existe tela "que ficou para trás", porque é a mesma tela. O que o
    /// programa acrescenta é o que o navegador não dá: janela própria sem
    /// barra de endereço, atalho na área de trabalho, e lembrar o servidor.
    ///
    /// ## O que o WebView2 entrega de graça
    ///
    /// É o mesmo motor do Edge, então tudo o que a PWA usa funciona:
    /// service worker (offline), `localStorage` (sessão), download de CSV,
    /// seletor de arquivo da importação, e a câmera do leitor de QR — esta
    /// última mediante permissão explícita, tratada abaixo.
    /// </summary>
    internal sealed class MainForm : Form
    {
        private readonly Configuracao _cfg;
        private WebView2 _web;
        private Label _aviso;

        public MainForm(Configuracao cfg)
        {
            _cfg = cfg;

            Text = "Nexus";
            StartPosition = FormStartPosition.CenterScreen;
            ClientSize = new Size(cfg.Largura, cfg.Altura);
            MinimumSize = new Size(900, 600);
            if (cfg.Maximizado) WindowState = FormWindowState.Maximized;
            Icon = SystemIcons.Application;

            ConstruirMenu();
            ConstruirAviso();

            // `Shown`, e não `Load`: o WebView2 exige uma janela **já
            // visível** para criar o controlador. Em `Load` a criação falha
            // com `0x800700AA (Recurso solicitado em uso)` — uma mensagem
            // que não sugere nada sobre a causa real.
            Shown += async (s, e) => await Iniciar();
            FormClosing += AoFechar;        }

        // ------------------------------------------------------------------
        // Menu
        // ------------------------------------------------------------------
        private void ConstruirMenu()
        {
            var menu = new MenuStrip();

            var arquivo = new ToolStripMenuItem("&Arquivo");
            arquivo.DropDownItems.Add(Item("Trocar de servidor…", (s, e) => TrocarServidor()));
            arquivo.DropDownItems.Add(new ToolStripSeparator());
            arquivo.DropDownItems.Add(Item("Sair", (s, e) => Close()));

            var ver = new ToolStripMenuItem("&Exibir");
            ver.DropDownItems.Add(Item("Recarregar        F5", (s, e) => Recarregar()));
            ver.DropDownItems.Add(Item("Ferramentas do desenvolvedor   F12", (s, e) => AbrirDevTools()));

            var ajuda = new ToolStripMenuItem("A&juda");
            ajuda.DropDownItems.Add(Item("Sobre", (s, e) => Sobre()));

            menu.Items.Add(arquivo);
            menu.Items.Add(ver);
            menu.Items.Add(ajuda);
            MainMenuStrip = menu;
            Controls.Add(menu);

            // F5 e F12 ficam na janela, e não só no menu: são as teclas que
            // alguém aperta por reflexo.
            KeyPreview = true;
            KeyDown += (s, e) =>
            {
                if (e.KeyCode == Keys.F5) { e.Handled = true; Recarregar(); }
                else if (e.KeyCode == Keys.F12) { e.Handled = true; AbrirDevTools(); }
            };
        }

        private static ToolStripMenuItem Item(string texto, EventHandler aoClicar)
        {
            var item = new ToolStripMenuItem(texto);
            item.Click += aoClicar;
            return item;
        }

        // ------------------------------------------------------------------
        // Aviso (usado enquanto carrega e quando algo falha)
        // ------------------------------------------------------------------
        private void ConstruirAviso()
        {
            _aviso = new Label
            {
                Dock = DockStyle.Fill,
                TextAlign = ContentAlignment.MiddleCenter,
                Font = new Font("Segoe UI", 11f),
                ForeColor = Color.FromArgb(90, 90, 90),
                BackColor = Color.FromArgb(250, 250, 250),
                Text = "Conectando a " + _cfg.Servidor + "…"
            };
            Controls.Add(_aviso);
            _aviso.BringToFront();
        }

        // ------------------------------------------------------------------
        // Inicialização
        // ------------------------------------------------------------------
        private async Task Iniciar()
        {
            try
            {
                // A pasta de dados guarda `localStorage` e o service worker.
                // Sem ela, o login se perderia a cada abertura do programa.
                // `EscolherPasta` já tenta criá-la e cai para um caminho
                // alternativo quando não consegue.
                var pastaDados = Configuracao.PastaDeDados;

                var ambiente = await CoreWebView2Environment.CreateAsync(
                    null, pastaDados, null);

                _web = new WebView2 { Dock = DockStyle.Fill, DefaultBackgroundColor = Color.White };
                Controls.Add(_web);
                _web.BringToFront();

                // `EnsureCoreWebView2Async` exige que a janela já tenha
                // handle criado e esteja visível: antes disso, a criação do
                // controlador devolve `0x800700AA`.
                if (!IsHandleCreated) CreateHandle();

                await _web.EnsureCoreWebView2Async(ambiente);

                ConfigurarNavegador();
                _web.CoreWebView2.Navigate(_cfg.Servidor);
            }
            catch (WebView2RuntimeNotFoundException)
            {
                Falhar(
                    "O WebView2 Runtime não está instalado.\n\n"
                    + "Ele vem com o Microsoft Edge, e está disponível em:\n"
                    + "https://developer.microsoft.com/microsoft-edge/webview2/",
                    null);
            }
            catch (Exception ex)
            {
                // Mostrar a exceção na tela: um `winexe` não tem console, e
                // "não foi possível abrir" sem o motivo não permite nem
                // relatar o problema nem corrigi-lo.
                Falhar(
                    "Não foi possível abrir a aplicação.\n\n"
                    + ex.GetType().Name + ": " + ex.Message,
                    ex);
            }
        }

        private void ConfigurarNavegador()
        {
            var nucleo = _web.CoreWebView2;

            // --- links externos vão para o navegador ---------------------
            //
            // Um link para o site do fabricante não deve abrir dentro da
            // janela do sistema: trocaria a aplicação por uma página qualquer,
            // sem barra de endereço para voltar.
            nucleo.NewWindowRequested += (s, e) =>
            {
                e.Handled = true;
                AbrirNoNavegador(e.Uri);
            };

            // --- câmera do leitor de QR ----------------------------------
            //
            // O `getUserMedia` do leitor de código de barras pede permissão.
            // No navegador aparece um diálogo; aqui, sem tratamento, a
            // requisição é negada em silêncio e a câmera nunca abre.
            nucleo.PermissionRequested += (s, e) =>
            {
                if (e.PermissionKind == CoreWebView2PermissionKind.Camera)
                {
                    e.State = CoreWebView2PermissionState.Allow;
                }
                else
                {
                    // Microfone, localização e notificações não são usados
                    // pelo sistema; negar é mais seguro que permitir tudo.
                    e.State = CoreWebView2PermissionState.Deny;
                }
            };

            // --- downloads (CSV, PDF de etiqueta, anexos) ----------------
            //
            // O comportamento padrão do WebView2 já pergunta onde salvar.
            // Só registramos no log de eventos para diagnóstico.
            nucleo.DownloadStarting += (s, e) =>
            {
                // Sem ação: mantém a caixa de diálogo do próprio WebView2.
            };

            // --- aviso de carregamento -----------------------------------
            nucleo.NavigationCompleted += (s, e) =>
            {
                if (_aviso != null && _aviso.Visible) _aviso.Visible = false;

                if (!e.IsSuccess && e.WebErrorStatus != CoreWebView2WebErrorStatus.OperationCanceled)
                {
                    Falhar(
                        "Não foi possível carregar o Nexus em\n"
                        + _cfg.Servidor + "\n\n"
                        + "Verifique se o servidor está no ar e se esta máquina alcança a porta.\n"
                        + "Erro: " + e.WebErrorStatus,
                        null);
                }
            };
        }

        // ------------------------------------------------------------------
        // Ações
        // ------------------------------------------------------------------
        private void Recarregar()
        {
            if (_web != null && _web.CoreWebView2 != null)
            {
                if (_aviso != null) _aviso.Visible = false;
                _web.CoreWebView2.Reload();
            }
        }

        private void AbrirDevTools()
        {
            if (_web != null && _web.CoreWebView2 != null) _web.CoreWebView2.OpenDevToolsWindow();
        }

        private void TrocarServidor()
        {
            using (var dlg = new ConfigForm(_cfg, false))
            {
                if (dlg.ShowDialog(this) != DialogResult.OK) return;

                if (_web != null && _web.CoreWebView2 != null)
                {
                    if (_aviso != null) _aviso.Visible = false;
                    _web.CoreWebView2.Navigate(_cfg.Servidor);
                }
            }
        }

        private void Sobre()
        {
            MessageBox.Show(
                "Nexus — aplicativo para Windows\n\n"
                + "Servidor: " + _cfg.Servidor + "\n"
                + "WebView2: " + (CoreWebView2Environment.GetAvailableBrowserVersionString() ?? "—") + "\n\n"
                + "A mesma aplicação que roda no navegador: a interface é servida\n"
                + "pelo próprio Nexus, então as duas estão sempre na mesma versão.",
                "Sobre o Nexus",
                MessageBoxButtons.OK,
                MessageBoxIcon.Information);
        }

        private static void AbrirNoNavegador(string url)
        {
            try { Process.Start(new ProcessStartInfo(url) { UseShellExecute = true }); }
            catch { /* sem navegador padrão: silêncio é melhor que um erro */ }
        }

        // ------------------------------------------------------------------
        // Falha: mostra o motivo em vez de uma janela em branco
        // ------------------------------------------------------------------
        private void Falhar(string mensagem, Exception detalhe)
        {
            if (_aviso == null) ConstruirAviso();

            _aviso.Text = mensagem;
            _aviso.ForeColor = Color.FromArgb(186, 26, 26);
            _aviso.Visible = true;
            _aviso.BringToFront();

            // Sem console num `winexe`, a exceção só existe aqui. Sem gravar,
            // a tela mostra "não foi possível abrir" e o motivo se perde.
            if (detalhe != null)
            {
                Program.Registrar("Abertura", detalhe);

                // Gravação de segurança ao lado do executável: se o caminho em
                // `%APPDATA%` falhar por qualquer motivo, esta não falha.
                try
                {
                    System.IO.File.WriteAllText(
                        System.IO.Path.Combine(
                            AppDomain.CurrentDomain.BaseDirectory, "erro.txt"),
                        detalhe.ToString());
                }
                catch { /* último recurso */ }
            }
        }

        // ------------------------------------------------------------------
        // Estado da janela
        // ------------------------------------------------------------------
        private void AoFechar(object sender, FormClosingEventArgs e)
        {
            try
            {
                _cfg.Maximizado = WindowState == FormWindowState.Maximized;
                if (WindowState == FormWindowState.Normal)
                {
                    _cfg.Largura = ClientSize.Width;
                    _cfg.Altura = ClientSize.Height;
                }
                _cfg.Salvar();
            }
            catch
            {
                // Não lembrar o tamanho da janela não impede o uso.
            }
        }
    }
}
