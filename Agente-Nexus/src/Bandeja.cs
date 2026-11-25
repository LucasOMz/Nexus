// =====================================================================
// Janelas e bandeja do Agente Nexus
// =====================================================================
//
// ## Configuração na primeira abertura
//
// O MSI instala como SYSTEM e não tem como abrir janela para o usuário. Por
// isso a configuração fica na bandeja: ela detecta que não há servidor
// configurado e abre a tela sozinha no primeiro logon.
//
// Instalação e configuração separadas — a ordem que o usuário pediu.
//
// ## Dois estados, duas janelas
//
//   sem configuração  -> JanelaConfiguracao (servidor + código)
//   configurado       -> JanelaStatus (conexão, último envio, atualizar)
//
// =====================================================================

using System;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Windows.Forms;

namespace AgenteNexus
{
    /// <summary>Tela de configuração — primeira execução.</summary>
    public class JanelaConfiguracao : Form
    {
        private readonly Campo _servidor;
        private readonly Campo _codigo;
        private readonly Label _erro;
        private readonly Botao _conectar;

        public bool Conectou { get; private set; }

        public JanelaConfiguracao()
        {
            Text = "Configurar o Nexus Agente";
            ClientSize = new Size(460, 400);
            FormBorderStyle = FormBorderStyle.FixedDialog;
            StartPosition = FormStartPosition.CenterScreen;
            MaximizeBox = false;
            MinimizeBox = false;
            BackColor = Tema.Superficie;
            Font = Tema.Normal;

            var titulo = new Label
            {
                Text = "Conectar ao servidor",
                Font = Tema.Titulo,
                ForeColor = Tema.Texto,
                Left = 24, Top = 22, Width = 400, Height = 32,
            };

            var sub = new Label
            {
                Text = "Informe o endereço do Nexus e o código gerado em\n"
                     + "Administração → Agente Nexus. Basta uma vez.",
                Font = Tema.Pequena,
                ForeColor = Tema.TextoSuave,
                Left = 24, Top = 56, Width = 410, Height = 40,
            };

            var rotuloServidor = new Label
            {
                Text = "Servidor",
                Font = Tema.Negrito,
                ForeColor = Tema.Texto,
                Left = 24, Top = 108, Width = 200, Height = 20,
            };
            _servidor = new Campo(false) { Left = 24, Top = 130, Width = 412 };

            // Ao editar, o endereço atual vem preenchido: quem vai trocar
            // precisa ver o que está lá antes de sobrescrever.
            var atual = Configuracao.Carregar();
            _servidor.Caixa.Text = (atual != null && !string.IsNullOrEmpty(atual.Servidor))
                ? atual.Servidor
                : "http://";

            var rotuloCodigo = new Label
            {
                Text = "Código de instalação",
                Font = Tema.Negrito,
                ForeColor = Tema.Texto,
                Left = 24, Top = 186, Width = 200, Height = 20,
            };
            _codigo = new Campo(false) { Left = 24, Top = 208, Width = 412 };

            _erro = new Label
            {
                Text = "",
                Font = Tema.Pequena,
                ForeColor = Tema.Vermelho,
                Left = 24, Top = 258, Width = 412, Height = 44,
            };

            _conectar = new Botao { Text = "Conectar", Left = 236, Top = 316, Width = 200 };
            _conectar.Click += (s, e) => Conectar();

            var cancelar = new Botao
            {
                Text = "Agora não",
                Preenchido = false,
                Left = 24, Top = 316, Width = 140,
            };
            cancelar.Click += (s, e) => { DialogResult = DialogResult.Cancel; Close(); };

            Controls.AddRange(new Control[] {
                titulo, sub, rotuloServidor, _servidor, rotuloCodigo, _codigo,
                _erro, _conectar, cancelar,
            });

            CancelButton = cancelar;
        }

        private void Conectar()
        {
            string servidor = _servidor.Text.Trim().TrimEnd('/');
            string codigo = _codigo.Text.Trim();

            if (servidor.Length <= 7)
            {
                _erro.Text = "Informe o endereço completo, ex.: http://10.0.0.5:4545";
                return;
            }
            if (codigo.Length < 4)
            {
                _erro.Text = "Informe o código de instalação gerado no painel.";
                return;
            }

            _conectar.Enabled = false;
            _conectar.Text = "Conectando...";
            _erro.Text = "";

            try
            {
                int r = Comandos.Registrar(servidor, codigo);

                // 0 = registrado; 3 = pendente (o serviço tenta de novo).
                if (r == 0 || r == 3)
                {
                    Conectou = true;
                    DialogResult = DialogResult.OK;
                    Close();
                    return;
                }

                _erro.Text = "Não foi possível conectar. Confira o endereço, "
                           + "se o servidor está no ar, e se o código ainda vale.";
            }
            catch (Exception ex)
            {
                _erro.Text = "Falha: " + ex.Message;
            }
            finally
            {
                _conectar.Enabled = true;
                _conectar.Text = "Conectar";
            }
        }
    }

    /// <summary>Tela de status — depois de configurado.</summary>
    public class JanelaStatus : Form
    {
        private readonly Label _situacao;
        private readonly Label _explicacao;
        private readonly Label _servidor;
        private readonly Label _ativo;
        private readonly Label _ultima;
        private readonly Label _erro;

        public JanelaStatus()
        {
            Text = "Nexus Agente";
            ClientSize = new Size(460, 430);
            FormBorderStyle = FormBorderStyle.FixedDialog;
            StartPosition = FormStartPosition.CenterScreen;
            MaximizeBox = false;
            MinimizeBox = false;
            BackColor = Tema.Superficie;
            Font = Tema.Normal;

            var cartao = new Cartao { Left = 20, Top = 20, Width = 420, Height = 130 };

            _situacao = new Label
            {
                Left = 22, Top = 18, Width = 380, Height = 30,
                Font = Tema.Titulo, ForeColor = Tema.Verde, BackColor = Color.Transparent,
            };
            _explicacao = new Label
            {
                Left = 22, Top = 52, Width = 380, Height = 60,
                Font = Tema.Pequena, ForeColor = Tema.TextoSuave, BackColor = Color.Transparent,
            };
            cartao.Controls.Add(_situacao);
            cartao.Controls.Add(_explicacao);

            _servidor = Rotulo(170);
            _ativo = Rotulo(196);
            _ultima = Rotulo(222);

            _erro = new Label
            {
                Left = 24, Top = 252, Width = 412, Height = 70,
                Font = Tema.Pequena, ForeColor = Tema.Vermelho,
            };

            var atualizar = new Botao
            {
                Text = "Atualizar agora", Left = 24, Top = 340, Width = 412,
            };
            atualizar.Click += (s, e) =>
            {
                atualizar.Enabled = false;
                atualizar.Text = "Enviando...";
                try
                {
                    Comandos.TentarRegistroPendente();
                    Comandos.Enviar();
                }
                catch (Exception) { }
                finally
                {
                    atualizar.Enabled = true;
                    atualizar.Text = "Atualizar agora";
                    Recarregar();
                }
            };

            // Sem botao Fechar: a janela ja tem o X do Windows, e dois caminhos
            // para a mesma acao so ocupam espaco.
            Controls.AddRange(new Control[] {
                cartao, _servidor, _ativo, _ultima, _erro, atualizar,
            });

            Recarregar();
        }

        private Label Rotulo(int topo)
        {
            return new Label
            {
                Left = 24, Top = topo, Width = 412, Height = 22,
                Font = Tema.Normal, ForeColor = Tema.Texto,
            };
        }

        public void Recarregar()
        {
            var cfg = Configuracao.Carregar();
            var est = EstadoLocal.Ler();

            if (cfg == null)
            {
                _situacao.Text = "Não configurado";
                _situacao.ForeColor = Tema.Vermelho;
                _explicacao.Text = "Abra a configuração para informar o servidor e o código.";
                _servidor.Text = "";
                _ativo.Text = "";
                _ultima.Text = "";
                _erro.Text = "";
                return;
            }

            _servidor.Text = "Servidor:  " + cfg.Servidor;
            _ativo.Text = cfg.RegistroPendente
                ? "Ativo:  aguardando vinculação"
                : "Ativo vinculado:  #" + cfg.AtivoId;
            _ultima.Text = "Último envio:  " + Quando(est.UltimoSucesso);

            if (cfg.RegistroPendente)
            {
                _situacao.Text = "Registro pendente";
                _situacao.ForeColor = Tema.Ambar;
                _explicacao.Text = "O servidor ainda não reconheceu esta máquina. "
                    + "O agente tenta sozinho a cada ciclo — nada a fazer.";
                _erro.Text = est.Mensagem ?? "";
            }
            else if (est.Ok)
            {
                _situacao.Text = "Conectado";
                _situacao.ForeColor = Tema.Verde;
                _explicacao.Text = "Esta máquina está reportando ao inventário.";
                _erro.Text = "";
            }
            else
            {
                _situacao.Text = "Sem conexão";
                _situacao.ForeColor = Tema.Ambar;
                _explicacao.Text = "O último envio falhou. O agente tenta de novo a cada ciclo.";
                _erro.Text = est.Mensagem ?? "";
            }
        }

        private static string Quando(string iso)
        {
            if (string.IsNullOrEmpty(iso)) return "nenhum ainda";

            DateTime quando;
            if (!DateTime.TryParse(iso, out quando)) return iso;

            var diff = DateTime.Now - quando;
            if (diff.TotalMinutes < 1) return "agora";
            if (diff.TotalMinutes < 60) return "há " + (int)diff.TotalMinutes + " min";
            if (diff.TotalHours < 24) return "há " + (int)diff.TotalHours + " h";
            return "há " + (int)diff.TotalDays + " dias";
        }
    }


    /// <summary>Pedido de senha para encerrar o agente.</summary>
    public class JanelaSenha : Form
    {
        private readonly Campo _senha;
        private readonly Label _erro;

        public JanelaSenha() : this("Senha para fechar")
        {
        }

        public JanelaSenha(string tituloJanela)
        {
            Text = "Nexus Agente";
            ClientSize = new Size(420, 240);
            FormBorderStyle = FormBorderStyle.FixedDialog;
            StartPosition = FormStartPosition.CenterScreen;
            MaximizeBox = false;
            MinimizeBox = false;
            BackColor = Tema.Superficie;
            Font = Tema.Normal;

            var titulo = new Label
            {
                Text = tituloJanela,
                Font = Tema.Titulo,
                ForeColor = Tema.Texto,
                Left = 22, Top = 18, Width = 380, Height = 30,
            };
            var sub = new Label
            {
                Text = "Definida em Administração → Agente Nexus.",
                Font = Tema.Pequena,
                ForeColor = Tema.TextoSuave,
                Left = 22, Top = 50, Width = 380, Height = 20,
            };

            _senha = new Campo(true) { Left = 22, Top = 82, Width = 376 };

            _erro = new Label
            {
                Text = "",
                Font = Tema.Pequena,
                ForeColor = Tema.Vermelho,
                Left = 22, Top = 132, Width = 376, Height = 40,
            };

            var sair = new Botao { Text = "Encerrar", Left = 22, Top = 178, Width = 180 };
            sair.Click += (s, e) => Confirmar();

            var cancelar = new Botao
            {
                Text = "Cancelar", Preenchido = false,
                Left = 218, Top = 178, Width = 180,
                DialogResult = DialogResult.Cancel,
            };

            Controls.AddRange(new Control[] { titulo, sub, _senha, _erro, sair, cancelar });
            AcceptButton = sair;
            CancelButton = cancelar;

            Shown += (s, e) => _senha.Caixa.Focus();
        }

        private void Confirmar()
        {
            _erro.Text = "";
            Application.DoEvents();

            if (Comandos.ValidarSenhaFechamento(_senha.Text))
            {
                DialogResult = DialogResult.OK;
                Close();
                return;
            }
            _erro.Text = "Senha incorreta, ou o servidor não está acessível. "
                       + "O agente continua funcionando.";
            _senha.Caixa.Clear();
            _senha.Caixa.Focus();
        }
    }


    /// <summary>Status da conexão, com acesso à edição.</summary>
    public class JanelaConexao : Form
    {
        public bool PediuEdicao { get; private set; }

        public JanelaConexao()
        {
            Text = "Conexão — Nexus Agente";
            ClientSize = new Size(460, 340);
            FormBorderStyle = FormBorderStyle.FixedDialog;
            StartPosition = FormStartPosition.CenterScreen;
            MaximizeBox = false;
            MinimizeBox = false;
            BackColor = Tema.Superficie;
            Font = Tema.Normal;

            var cfg = Configuracao.Carregar();
            var est = EstadoLocal.Ler();

            var cartao = new Cartao { Left = 20, Top = 20, Width = 420, Height = 120 };

            var situacao = new Label
            {
                Left = 22, Top = 16, Width = 380, Height = 30,
                Font = Tema.Titulo, BackColor = Color.Transparent,
            };
            var explicacao = new Label
            {
                Left = 22, Top = 50, Width = 380, Height = 58,
                Font = Tema.Pequena, ForeColor = Tema.TextoSuave,
                BackColor = Color.Transparent,
            };

            if (cfg == null)
            {
                situacao.Text = "Não configurado";
                situacao.ForeColor = Tema.Ambar;
                explicacao.Text = "Esta máquina ainda não tem servidor definido. "
                                + "Clique em editar para informar o endereço e o código.";
            }
            else if (cfg.RegistroPendente)
            {
                situacao.Text = "Registro pendente";
                situacao.ForeColor = Tema.Ambar;
                explicacao.Text = "Servidor definido, mas o registro não concluiu. "
                                + "O agente tenta sozinho a cada ciclo.";
            }
            else if (est.Ok)
            {
                situacao.Text = "Conectado";
                situacao.ForeColor = Tema.Verde;
                explicacao.Text = "Reportando ao inventário normalmente.";
            }
            else
            {
                situacao.Text = "Sem conexão";
                situacao.ForeColor = Tema.Vermelho;
                explicacao.Text = "O último envio falhou. O agente tenta de novo a cada ciclo.";
            }

            cartao.Controls.Add(situacao);
            cartao.Controls.Add(explicacao);

            var servidor = new Label
            {
                Left = 24, Top = 156, Width = 412, Height = 22,
                Font = Tema.Normal, ForeColor = Tema.Texto,
                Text = cfg == null ? "Servidor:  não definido" : "Servidor:  " + cfg.Servidor,
            };
            var ativo = new Label
            {
                Left = 24, Top = 182, Width = 412, Height = 22,
                Font = Tema.Normal, ForeColor = Tema.Texto,
                Text = cfg == null
                    ? "Ativo:  não vinculado"
                    : (cfg.RegistroPendente ? "Ativo:  aguardando vinculação"
                                            : "Ativo vinculado:  #" + cfg.AtivoId),
            };

            var editar = new Botao
            {
                Text = "Editar configurações", Left = 24, Top = 240, Width = 412,
            };
            editar.Click += (s, e) => { PediuEdicao = true; DialogResult = DialogResult.OK; Close(); };

            var fechar = new Botao
            {
                Text = "Fechar", Preenchido = false,
                Left = 24, Top = 288, Width = 412,
                DialogResult = DialogResult.Cancel,
            };

            Controls.AddRange(new Control[] { cartao, servidor, ativo, editar, fechar });
            CancelButton = fechar;
        }
    }

    /// <summary>Ícone ao lado do relógio.</summary>
    public class Bandeja : IDisposable
    {
        private readonly NotifyIcon _icone;
        private readonly Timer _relogio;
        private readonly Timer _primeiroUso;
        private JanelaStatus _janela;

        public Bandeja()
        {
            _icone = new NotifyIcon
            {
                Icon = Icones.Criar(Tema.Ambar),
                Text = "Nexus Agente",
                Visible = true,
            };

            var menu = new ContextMenuStrip();
            menu.Items.Add("Abrir status", null, (s, e) => AbrirStatus());
            menu.Items.Add("Configurar", null, (s, e) => AbrirConfiguracao());
            menu.Items.Add(new ToolStripSeparator());
            menu.Items.Add("Sair", null, (s, e) =>
            {
                // Confirmacao: o agente deixa de reportar enquanto estiver
                // fechado, e um clique acidental e silencioso demais.
                // Senha definida no painel. Sem senha configurada, o servidor
                // libera e a janela ainda pede confirmacao.
                //
                // Encerrar agora PARA TAMBEM o servico: a maquina deixa de
                // reportar ate alguem abrir o agente de novo.
                using (var pedido = new JanelaSenha("Senha para encerrar o agente"))
                {
                    if (pedido.ShowDialog() == DialogResult.OK) Encerrar();
                }
            });
            _icone.ContextMenuStrip = menu;
            _icone.DoubleClick += (s, e) => AbrirStatus();

            _relogio = new Timer { Interval = 30000 };
            _relogio.Tick += (s, e) => AtualizarIcone();
            _relogio.Start();

            // Primeiro uso: sem configuração, abre a tela sozinho. Sem isso o
            // técnico instala, vê um ícone mudo, e não sabe o que fazer.
            _primeiroUso = new Timer { Interval = 1200 };
            _primeiroUso.Tick += (s, e) =>
            {
                _primeiroUso.Stop();
                if (Configuracao.Carregar() == null) AbrirConfiguracao();
            };
            _primeiroUso.Start();

            // Abrir o agente liga a coleta. Sem isto, um "Sair" anterior
            // deixaria a bandeja aberta e o serviço parado — o pior dos dois
            // mundos: o técnico vê o ícone e acha que está reportando.
            GarantirServicoRodando();

            AtualizarIcone();
        }

        /// <summary>
        /// Sobe o serviço se ele estiver parado.
        ///
        /// "Sair" para o serviço. Abrir o agente significa "quero ele
        /// funcionando", então precisa subir de volta.
        ///
        /// Falha silenciosa: se não der para subir (sem elevação, política),
        /// a bandeja continua abrindo e o status mostra o estado real.
        /// </summary>
        private static void GarantirServicoRodando()
        {
            try
            {
                using (var svc = new System.ServiceProcess.ServiceController("NexusAgente"))
                {
                    if (svc.Status == System.ServiceProcess.ServiceControllerStatus.Running) return;
                    svc.Start();
                    svc.WaitForStatus(
                        System.ServiceProcess.ServiceControllerStatus.Running,
                        TimeSpan.FromSeconds(15));
                }
            }
            catch (Exception) { }
        }

        private void AtualizarIcone()
        {
            var cfg = Configuracao.Carregar();
            var est = EstadoLocal.Ler();

            // O icone e SEMPRE o verde do logo. A cor do estado mudava a
            // marca, e o usuario pediu o mesmo icone — o estado aparece no
            // texto do tooltip e na janela, nao na cor.
            Color cor = Tema.Primario;
            string texto = "Nexus Agente";

            if (cfg == null)
            {
                
                texto += " — não configurado";
            }
            else if (cfg.RegistroPendente)
            {
                
                texto += " — registro pendente";
            }
            else if (est.Ok)
            {
                
                texto += " — conectado";
            }
            else
            {
                
                texto += " — sem conexão";
            }

            _icone.Icon = Icones.Criar(cor);
            _icone.Text = texto.Length > 63 ? texto.Substring(0, 63) : texto;

            if (_janela != null && _janela.Visible) _janela.Recarregar();
        }

        private void AbrirStatus()
        {
            if (Configuracao.Carregar() == null)
            {
                AbrirConfiguracao();
                return;
            }
            if (_janela == null || _janela.IsDisposed) _janela = new JanelaStatus();
            _janela.Show();
            _janela.BringToFront();
            _janela.Recarregar();
        }

        /// <summary>
        /// Abre a configuracao, pedindo senha quando a maquina ja esta
        /// configurada.
        ///
        /// ## Por que a diferenca
        ///
        /// Na primeira instalacao nao ha nada a proteger, e exigir senha
        /// travaria o tecnico sem motivo.
        ///
        /// Depois de configurada, trocar o servidor e o suficiente para a
        /// maquina sair do inventario sem chamar atencao — isso precisa de
        /// senha.
        /// </summary>
        /// <summary>Status da conexão e acesso à edição.</summary>
        ///
        /// <remarks>
        /// A tela intermediária existe para responder "como está" antes de
        /// pedir "o que muda". Abrir um formulário só para conferir se está
        /// tudo certo seria pior.
        /// </remarks>
        private void AbrirConfiguracao()
        {
            bool jaConfigurado = Configuracao.Carregar() != null;

            using (var status = new JanelaConexao())
            {
                if (status.ShowDialog() != DialogResult.OK || !status.PediuEdicao)
                    return;
            }

            // Só pede senha ao EDITAR. Conferir o status é livre — mostrar
            // "conectado" não muda nada.
            if (jaConfigurado)
            {
                using (var pedido = new JanelaSenha("Senha para alterar a configuração"))
                {
                    if (pedido.ShowDialog() != DialogResult.OK) return;
                }
            }

            using (var janela = new JanelaConfiguracao())
                janela.ShowDialog();
            AtualizarIcone();
        }

        /// <summary>
        /// Encerra a bandeja **e** o servico.
        ///
        /// ## Por que parar o servico
        ///
        /// Sem isto, fechar o icone nao para a coleta — e o tecnico acredita
        /// que parou. A parada exige elevacao; o manifesto ja garante isso.
        ///
        /// Se a parada falhar (servico ja parado, politica), a bandeja sai
        /// mesmo assim: nao poder fechar a janela por causa disso seria pior.
        /// </summary>
        private void Encerrar()
        {
            try
            {
                using (var svc = new System.ServiceProcess.ServiceController("NexusAgente"))
                {
                    if (svc.Status == System.ServiceProcess.ServiceControllerStatus.Running)
                    {
                        svc.Stop();
                        svc.WaitForStatus(
                            System.ServiceProcess.ServiceControllerStatus.Stopped,
                            TimeSpan.FromSeconds(20));
                    }
                }
            }
            catch (Exception ex)
            {
                // Sem elevacao o agente nao para o servico. Avisar e melhor
                // que fechar em silencio e deixar a coleta rodando.
                MessageBox.Show(
                    "O servico nao pode ser parado sem privilegio de administrador." +
                    Environment.NewLine + Environment.NewLine +
                    "A coleta continua. A bandeja sera encerrada." +
                    Environment.NewLine + Environment.NewLine +
                    "Detalhe: " + ex.Message,
                    "Nexus Agente", MessageBoxButtons.OK, MessageBoxIcon.Warning);
            }

            _relogio.Stop();
            _icone.Visible = false;
            _icone.Dispose();
            Application.Exit();
        }

        public void Dispose()
        {
            if (_icone != null) { _icone.Visible = false; _icone.Dispose(); }
        }
    }

    public static class EntradaBandeja
    {
        /// <summary>Abre a bandeja. Devolve o código de saída do processo.</summary>
        [STAThread]
        public static int Iniciar()
        {
            try
            {
                Application.EnableVisualStyles();
                Application.SetCompatibleTextRenderingDefault(false);

                using (var bandeja = new Bandeja())
                {
                    Application.Run();
                }
                return 0;
            }
            catch (Exception) { return 1; }
        }
    }
}
