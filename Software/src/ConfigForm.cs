using System;
using System.Drawing;
using System.IO;
using System.Net;
using System.Text;
using System.Threading;
using System.Windows.Forms;

namespace NexusDesktop
{
    /// <summary>
    /// Tela de configuração inicial: pede o endereço do gateway Nexus.
    ///
    /// ## Por que pedir só isto
    ///
    /// O gateway é o único endereço de que o Nexus precisa. OCS, banco e
    /// Active Directory são configuração do **servidor** — o cliente nunca
    /// fala com eles. Pedir mais seria pedir o que ninguém sabe de cabeça.
    ///
    /// ## Por que testar antes de salvar
    ///
    /// Um endereço errado só se revela na primeira navegação, com uma tela
    /// em branco. O teste confirma na hora que existe um Nexus daquele lado —
    /// e diz o que houve quando não existe.
    /// </summary>
    internal sealed class ConfigForm : Form
    {
        private readonly TextBox _endereco;
        private readonly Label _estado;
        private readonly Button _testar;
        private readonly Button _salvar;
        private readonly Configuracao _cfg;

        public ConfigForm(Configuracao cfg, bool primeiraVez)
        {
            _cfg = cfg;

            Text = primeiraVez ? "Nexus — configuração inicial" : "Nexus — trocar de servidor";
            FormBorderStyle = FormBorderStyle.FixedDialog;
            StartPosition = FormStartPosition.CenterScreen;
            MaximizeBox = false;
            MinimizeBox = false;
            ClientSize = new Size(520, 232);
            Font = new Font("Segoe UI", 9f);
            BackColor = Color.FromArgb(250, 250, 250);

            var titulo = new Label
            {
                Text = "Endereço do Nexus",
                Font = new Font("Segoe UI Semibold", 12f),
                AutoSize = true,
                Location = new Point(22, 18)
            };

            var ajuda = new Label
            {
                Text = "O mesmo endereço que você abre no navegador.\n"
                     + "Ex.: http://192.168.1.10:4545   ou   https://nexus.suaempresa.com",
                ForeColor = Color.FromArgb(95, 95, 95),
                AutoSize = true,
                Location = new Point(24, 48)
            };

            _endereco = new TextBox
            {
                Location = new Point(24, 96),
                Width = 470,
                Font = new Font("Consolas", 10f),
                Text = cfg.TemServidor ? cfg.Servidor : "http://"
            };

            _testar = new Button
            {
                Text = "Testar conexão",
                Location = new Point(24, 138),
                Size = new Size(130, 30)
            };
            _testar.Click += Testar;

            _estado = new Label
            {
                AutoSize = false,
                Location = new Point(164, 143),
                Size = new Size(330, 22),
                ForeColor = Color.FromArgb(95, 95, 95),
                Text = ""
            };

            _salvar = new Button
            {
                Text = "Salvar e abrir",
                Location = new Point(354, 186),
                Size = new Size(140, 32),
                DialogResult = DialogResult.None
            };
            _salvar.Click += Salvar;

            var cancelar = new Button
            {
                Text = "Cancelar",
                Location = new Point(262, 186),
                Size = new Size(88, 32),
                DialogResult = DialogResult.Cancel
            };

            AcceptButton = _salvar;
            CancelButton = cancelar;

            Controls.AddRange(new Control[]
            {
                titulo, ajuda, _endereco, _testar, _estado, cancelar, _salvar
            });
        }

        /// <summary>Muda a cor e o texto do retorno do teste.</summary>
        private void Dizer(string texto, bool ok)
        {
            _estado.Text = texto;
            _estado.ForeColor = ok ? Color.FromArgb(31, 107, 63) : Color.FromArgb(186, 26, 26);
        }

        private void Testar(object sender, EventArgs e)
        {
            var url = Configuracao.NormalizarUrl(_endereco.Text);
            if (url.Length == 0 || url == "http://")
            {
                Dizer("Informe o endereço.", false);
                return;
            }

            _endereco.Text = url;
            _testar.Enabled = false;
            Dizer("Testando…", true);

            // Em thread separada: uma rede que não responde congelaria a
            // janela por 15 segundos, e pareceria travamento.
            var thread = new Thread(() =>
            {
                string mensagem;
                bool ok;

                try
                {
                    var req = (HttpWebRequest)WebRequest.Create(url + "/health");
                    req.Timeout = 8000;
                    req.ReadWriteTimeout = 8000;
                    req.Method = "GET";
                    req.UserAgent = "NexusDesktop";

                    using (var resp = (HttpWebResponse)req.GetResponse())
                    using (var leitor = new StreamReader(resp.GetResponseStream(), Encoding.UTF8))
                    {
                        var corpo = leitor.ReadToEnd();
                        // O `/health` responde `{"status":"ok","database":true,...}`.
                        // Não vale a pena trazer um parser de JSON só para ler
                        // três campos: procura-se o marcador.
                        if (corpo.IndexOf("\"status\"", StringComparison.OrdinalIgnoreCase) >= 0 &&
                            corpo.IndexOf("ok", StringComparison.OrdinalIgnoreCase) >= 0)
                        {
                            ok = true;
                            mensagem = "Conectado. Servidor Nexus respondeu.";
                        }
                        else
                        {
                            ok = false;
                            mensagem = "Respondeu, mas não parece um Nexus.";
                        }
                    }
                }
                catch (WebException ex)
                {
                    ok = false;
                    var http = ex.Response as HttpWebResponse;
                    if (http != null)
                    {
                        mensagem = "O servidor respondeu " + (int)http.StatusCode + ". Confira o endereço.";
                    }
                    else if (ex.Status == WebExceptionStatus.Timeout)
                    {
                        mensagem = "Sem resposta em 8 segundos. A rede bloqueia esta porta?";
                    }
                    else
                    {
                        mensagem = "Não foi possível conectar. Confira o endereço e a rede.";
                    }
                }
                catch
                {
                    ok = false;
                    mensagem = "Endereço inválido.";
                }

                // Volta para a thread da interface antes de tocar nos controles.
                BeginInvoke(new Action(() =>
                {
                    Dizer(mensagem, ok);
                    _testar.Enabled = true;
                }));
            });

            thread.IsBackground = true;
            thread.Start();
        }

        private void Salvar(object sender, EventArgs e)
        {
            var url = Configuracao.NormalizarUrl(_endereco.Text);
            if (url.Length == 0 || url == "http://")
            {
                Dizer("Informe o endereço.", false);
                return;
            }

            _cfg.Servidor = url;
            _cfg.Salvar();

            DialogResult = DialogResult.OK;
            Close();
        }
    }
}
