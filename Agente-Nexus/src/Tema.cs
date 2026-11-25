// =====================================================================
// Interface do Agente Nexus — configuração, status e bandeja
// =====================================================================
//
// ## Paleta
//
// As mesmas cores do painel web (Material You / MD3): roxo #6750A4 como
// primário, superfícies claras, texto quase preto. Quem usa o sistema
// reconhece o agente como parte dele.
//
// ## Por que cantos arredondados desenhados à mão
//
// WinForms não tem borda arredondada. Um `FormBorderStyle.None` daria o
// visual mais bonito, mas teria que reimplementar arrastar, fechar,
// minimizar e redimensionar — e cada um desses é um ponto de falha que eu
// não consigo testar sem a máquina na frente.
//
// A escolha: **moldura padrão do Windows** (confiável) e **arredondamento
// nos controles internos** (cartões, campos, botões). O resultado é o visual
// do sistema sem apostar a janela inteira em código não testado.
//
// ## Estados da bandeja
//
//   verde    conectado, enviou há pouco
//   âmbar    registro pendente ou servidor fora
//   vermelho token inválido
//
// O ícone é desenhado em código: sem arquivo .ico para faltar depois de uma
// instalação.
//
// =====================================================================

using System;
using System.Collections.Generic;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.IO;
using System.Text;
using System.Web.Script.Serialization;
using System.Windows.Forms;

namespace AgenteNexus
{
    /// <summary>Cores do Material You, iguais às do painel web.</summary>
    public static class Tema
    {
        // Verde do logo Nexus (logo-nexus.svg): #08BC48 e o ponto medio do
        // gradiente da letra, e e a cor que o painel web usa nas acoes.
        public static readonly Color Primario = Color.FromArgb(8, 188, 72);
        public static readonly Color PrimarioClaro = Color.FromArgb(200, 245, 214);
        public static readonly Color Superficie = Color.FromArgb(247, 252, 249);
        public static readonly Color Cartao = Color.White;
        public static readonly Color Texto = Color.FromArgb(24, 32, 27);
        public static readonly Color TextoSuave = Color.FromArgb(68, 82, 73);
        public static readonly Color Borda = Color.FromArgb(116, 130, 121);
        public static readonly Color Verde = Color.FromArgb(46, 125, 50);
        public static readonly Color Ambar = Color.FromArgb(180, 120, 0);
        public static readonly Color Vermelho = Color.FromArgb(179, 38, 30);

        public static Font Titulo = new Font("Segoe UI Semibold", 15f);
        public static Font Normal = new Font("Segoe UI", 9.75f);
        public static Font Pequena = new Font("Segoe UI", 8.75f);

        /// <summary>Fonte em negrito, derivada da normal.</summary>
        public static Font Negrito = new Font("Segoe UI Semibold", 9.75f);
    }

    /// <summary>Painel com cantos arredondados e cor de fundo própria.</summary>
    public class Cartao : Panel
    {
        public int Raio { get; set; }
        public Color Cor { get; set; }

        public Cartao()
        {
            Raio = 14;
            Cor = Tema.Cartao;
            SetStyle(ControlStyles.AllPaintingInWmPaint | ControlStyles.OptimizedDoubleBuffer
                     | ControlStyles.UserPaint | ControlStyles.ResizeRedraw, true);
            BackColor = Tema.Superficie;
        }

        protected override void OnPaint(PaintEventArgs e)
        {
            // Limpar antes de desenhar. Sem isto, o quadro anterior fica na
            // tela e aparece um "fantasma" do conteúdo antigo — foi o que
            // duplicou o botão na janela de status.
            e.Graphics.Clear(BackColor);
            e.Graphics.SmoothingMode = SmoothingMode.AntiAlias;

            var area = new Rectangle(0, 0, Width - 1, Height - 1);
            using (var caminho = Arredondado(area, Raio))
            using (var pincel = new SolidBrush(Cor))
            using (var caneta = new Pen(Color.FromArgb(30, Tema.Borda)))
            {
                e.Graphics.FillPath(pincel, caminho);
                e.Graphics.DrawPath(caneta, caminho);
            }

            base.OnPaint(e);
        }

        /// <summary>Caminho com cantos arredondados.</summary>
        public static GraphicsPath Arredondado(Rectangle r, int raio)
        {
            var caminho = new GraphicsPath();
            int d = raio * 2;

            caminho.AddArc(r.X, r.Y, d, d, 180, 90);
            caminho.AddArc(r.Right - d, r.Y, d, d, 270, 90);
            caminho.AddArc(r.Right - d, r.Bottom - d, d, d, 0, 90);
            caminho.AddArc(r.X, r.Bottom - d, d, d, 90, 90);
            caminho.CloseFigure();
            return caminho;
        }
    }

    /// <summary>Botão preenchido, com cantos arredondados.</summary>
    public class Botao : Button
    {
        public bool Preenchido { get; set; }
        public Color CorFundo { get; set; }

        public Botao()
        {
            Preenchido = true;
            CorFundo = Tema.Primario;
            FlatStyle = FlatStyle.Flat;
            FlatAppearance.BorderSize = 0;
            Font = Tema.Negrito;
            Height = 40;
            Cursor = Cursors.Hand;
            SetStyle(ControlStyles.AllPaintingInWmPaint | ControlStyles.OptimizedDoubleBuffer
                     | ControlStyles.UserPaint | ControlStyles.ResizeRedraw, true);
            BackColor = Tema.Superficie;
        }

        protected override void OnPaint(PaintEventArgs e)
        {
            e.Graphics.Clear(BackColor);
            e.Graphics.SmoothingMode = SmoothingMode.AntiAlias;

            var area = new Rectangle(0, 0, Width - 1, Height - 1);
            using (var caminho = Cartao.Arredondado(area, 20))
            {
                if (Preenchido)
                {
                    using (var pincel = new SolidBrush(Enabled ? CorFundo : Color.FromArgb(80, CorFundo)))
                        e.Graphics.FillPath(pincel, caminho);
                }
                else
                {
                    using (var caneta = new Pen(Tema.Primario, 1.4f))
                        e.Graphics.DrawPath(caneta, caminho);
                }
            }

            TextRenderer.DrawText(
                e.Graphics, Text, Font, area,
                Preenchido ? Color.White : Tema.Primario,
                TextFormatFlags.HorizontalCenter | TextFormatFlags.VerticalCenter);
        }
    }

    /// <summary>Campo de texto com moldura arredondada.</summary>
    public class Campo : Panel
    {
        public readonly TextBox Caixa;

        public Campo(bool senha)
        {
            Height = 42;
            BackColor = Tema.Superficie;

            Caixa = new TextBox
            {
                BorderStyle = BorderStyle.None,
                Font = Tema.Normal,
                ForeColor = Tema.Texto,
                BackColor = Tema.Cartao,
                Left = 14,
                Top = 12,
                Width = Width - 28,
                Anchor = AnchorStyles.Left | AnchorStyles.Right | AnchorStyles.Top,
            };
            if (senha) Caixa.UseSystemPasswordChar = true;

            Controls.Add(Caixa);
            SetStyle(ControlStyles.AllPaintingInWmPaint | ControlStyles.OptimizedDoubleBuffer
                     | ControlStyles.UserPaint | ControlStyles.ResizeRedraw, true);
        }

        public override string Text
        {
            get { return Caixa.Text; }
            set { Caixa.Text = value; }
        }

        protected override void OnPaint(PaintEventArgs e)
        {
            e.Graphics.Clear(BackColor);
            e.Graphics.SmoothingMode = SmoothingMode.AntiAlias;
            var area = new Rectangle(0, 0, Width - 1, Height - 1);
            using (var caminho = Cartao.Arredondado(area, 12))
            using (var pincel = new SolidBrush(Tema.Cartao))
            using (var caneta = new Pen(Caixa.Focused ? Tema.Primario : Color.FromArgb(60, Tema.Borda),
                                        Caixa.Focused ? 1.8f : 1f))
            {
                e.Graphics.FillPath(pincel, caminho);
                e.Graphics.DrawPath(caneta, caminho);
            }
        }
    }

    /// <summary>Icones da bandeja — o N do logo, na cor do estado.</summary>
    public static class Icones
    {
        /// <summary>
        /// Desenha o N do logo Nexus com o anel orbital, na cor pedida.
        ///
        /// ## Por que em codigo
        ///
        /// Um arquivo .ico ao lado do executavel pode faltar depois de uma
        /// instalacao parcial, e a bandeja ficaria sem icone. Desenhar
        /// elimina essa dependencia.
        ///
        /// ## A cor e o estado
        ///
        /// Verde  = conectado
        /// Ambar  = pendente ou sem conexao
        /// Vermelho = token invalido
        ///
        /// Mantem o desenho do logo em todos os casos: quem olha reconhece o
        /// produto antes de interpretar a cor.
        /// </summary>
        public static Icon Criar(Color cor)
        {
            int tam = 32;
            var bmp = new Bitmap(tam, tam);
            using (var g = Graphics.FromImage(bmp))
            {
                g.SmoothingMode = SmoothingMode.AntiAlias;
                g.Clear(Color.Transparent);

                // anel orbital, inclinado
                var estado = g.Save();
                g.TranslateTransform(tam / 2f, tam / 2f);
                g.RotateTransform(-24f);
                using (var caneta = new Pen(cor, 2.4f))
                {
                    g.DrawEllipse(caneta, -14f, -4.6f, 28f, 9.2f);
                }
                g.Restore(estado);

                // a letra N
                using (var pincel = new SolidBrush(cor))
                {
                    float larg = 5.4f;
                    float x0 = 8f, x1 = tam - 8f;
                    float y0 = 7f, y1 = tam - 7f;

                    g.FillRectangle(pincel, x0, y0, larg, y1 - y0);
                    g.FillRectangle(pincel, x1 - larg, y0, larg, y1 - y0);

                    var pontos = new[]
                    {
                        new PointF(x0 + larg / 2, y0 + 1),
                        new PointF(x1 - larg / 2, y1 - 1),
                    };
                    using (var canetaN = new Pen(cor, larg))
                    {
                        canetaN.StartCap = LineCap.Round;
                        canetaN.EndCap = LineCap.Round;
                        g.DrawLine(canetaN, pontos[0], pontos[1]);
                    }
                }
            }

            return Icon.FromHandle(bmp.GetHicon());
        }
    }

    /// <summary>Último resultado de envio, gravado pelo agente.</summary>
    public class EstadoLocal
    {
        public string UltimoEnvio { get; set; }
        public string UltimoSucesso { get; set; }
        public bool Ok { get; set; }
        public string Mensagem { get; set; }

        private static string Arquivo()
        {
            string pasta = Operacao.PastaDados();
            return Path.Combine(pasta, "estado.json");
        }

        public static EstadoLocal Ler()
        {
            try
            {
                string caminho = Arquivo();
                if (!File.Exists(caminho)) return new EstadoLocal();
                return new JavaScriptSerializer()
                    .Deserialize<EstadoLocal>(File.ReadAllText(caminho, Encoding.UTF8))
                    ?? new EstadoLocal();
            }
            catch (Exception) { return new EstadoLocal(); }
        }

        public static void Gravar(bool ok, string mensagem)
        {
            try
            {
                string pasta = Operacao.PastaDados();
                if (!Directory.Exists(pasta)) return;

                var anterior = Ler();
                var agora = DateTime.Now.ToString("o");
                var novo = new EstadoLocal
                {
                    UltimoEnvio = agora,
                    UltimoSucesso = ok ? agora : anterior.UltimoSucesso,
                    Ok = ok,
                    Mensagem = mensagem,
                };
                File.WriteAllText(Arquivo(),
                    new JavaScriptSerializer().Serialize(novo), Encoding.UTF8);
            }
            catch (Exception) { }
        }
    }

    /// <summary>Onde ficam os dados, com fallback quando falta permissão.</summary>
    public static class Operacao
    {
        private static string _pasta;

        /// <summary>
        /// `%ProgramData%\Nexus`, ou `%LOCALAPPDATA%\Nexus\Agente` quando o
        /// primeiro não é gravável.
        ///
        /// O serviço roda como SYSTEM e grava no ProgramData. A bandeja roda
        /// como usuário comum e pode não ter permissão lá — daí o fallback.
        /// </summary>
        public static string PastaDados()
        {
            if (_pasta != null) return _pasta;

            string comum = Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.CommonApplicationData), "Nexus");
            try
            {
                if (!Directory.Exists(comum)) Directory.CreateDirectory(comum);
                // Testa escrita real: existir não garante poder gravar.
                string teste = Path.Combine(comum, ".teste");
                File.WriteAllText(teste, "x");
                File.Delete(teste);
                _pasta = comum;
                return _pasta;
            }
            catch (Exception) { }

            _pasta = Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                "Nexus", "Agente");
            try { Directory.CreateDirectory(_pasta); } catch (Exception) { }
            return _pasta;
        }
    }
}
