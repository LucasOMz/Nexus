using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Text;

namespace NexusDesktop
{
    /// <summary>
    /// Configuração do aplicativo — endereço do gateway e estado da janela.
    ///
    /// ## Por que arquivo de texto, e não JSON
    ///
    /// O compilador do .NET Framework (`csc.exe`) não traz um serializador de
    /// JSON sem dependência extra: `JavaScriptSerializer` exige
    /// `System.Web.Extensions`, e `DataContractJsonSerializer` exige
    /// `System.Runtime.Serialization`. Para cinco chaves, um formato
    /// `chave=valor` é mais simples, não tem risco de compatibilidade, e é
    /// legível por quem for dar suporte.
    ///
    /// ## Onde fica
    ///
    /// `%APPDATA%\Nexus\config.ini` — no perfil do usuário, não ao lado do
    /// executável. O programa pode estar em `Program Files`, onde a escrita
    /// é negada; e a configuração é de cada pessoa (o servidor de um técnico
    /// pode não ser o de outro).
    /// </summary>
    internal sealed class Configuracao
    {
        /// <summary>Endereço base do gateway Nexus. Sem barra no fim.</summary>
        public string Servidor { get; set; }

        public int Largura { get; set; }
        public int Altura { get; set; }
        public bool Maximizado { get; set; }

        public Configuracao()
        {
            Servidor = "";
            Largura = 1280;
            Altura = 860;
            Maximizado = false;
        }

        public bool TemServidor
        {
            get { return !string.IsNullOrWhiteSpace(Servidor); }
        }

        private static string Pasta
        {
            get
            {
                return Path.Combine(
                    Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData),
                    "Nexus");
            }
        }

        private static string Arquivo
        {
            get { return Path.Combine(Pasta, "config.ini"); }
        }

        /// <summary>
        /// Pasta de dados do WebView2 — mantém login e cache entre execuções.
        ///
        /// ## Por que o nome carrega a versão
        ///
        /// O WebView2 trava a pasta enquanto qualquer processo dele estiver
        /// vivo. Se uma execução anterior ficou pendurada, a pasta continua
        /// ocupada e a próxima abertura falha com
        /// `0x800700AA — Recurso solicitado em uso`.
        ///
        /// Incluir a versão isola cada build: uma pasta emperrada deixa de
        /// bloquear a versão nova. O custo é refazer o login ao atualizar —
        /// melhor do que não abrir.
        ///
        /// ## Por que há um caminho reserva
        ///
        /// Já houve `Acesso negado` ao criar a pasta em `%LOCALAPPDATA%`,
        /// mesmo com a ACL correta e um programa .NET comum conseguindo criar
        /// ali. Não foi possível determinar a causa raiz no ambiente de teste
        /// — então o aplicativo **tenta o segundo caminho** em vez de mostrar
        /// um erro que o usuário não pode resolver.
        /// </summary>
        public static string PastaDeDados
        {
            get { return EscolherPasta(); }
        }

        private static string _pastaEscolhida;

        private static string EscolherPasta()
        {
            if (_pastaEscolhida != null) return _pastaEscolhida;

            var versao = VersaoParaPasta;
            var candidatos = new[]
            {
                Path.Combine(
                    Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                    "Nexus", "WebView2-" + versao),
                Path.Combine(Path.GetTempPath(), "Nexus-WebView2-" + versao),
            };

            foreach (var pasta in candidatos)
            {
                try
                {
                    Directory.CreateDirectory(pasta);
                    _pastaEscolhida = pasta;
                    return pasta;
                }
                catch
                {
                    // Tenta o próximo.
                }
            }

            // Último recurso: deixa o WebView2 escolher a pasta padrão.
            _pastaEscolhida = null;
            return null;
        }

        /// <summary>
        /// Versão curta e segura para nome de pasta.
        ///
        /// Sai da data de compilação do executável — muda a cada build, sem
        /// precisar manter um número escrito à mão em dois lugares.
        /// </summary>
        private static string VersaoParaPasta
        {
            get
            {
                try
                {
                    var arquivo = new FileInfo(
                        System.Reflection.Assembly.GetExecutingAssembly().Location);
                    return arquivo.Exists
                        ? arquivo.LastWriteTimeUtc.ToString("yyyyMMddHHmm")
                        : "dev";
                }
                catch
                {
                    return "dev";
                }
            }
        }

        public static Configuracao Carregar()
        {
            var cfg = new Configuracao();
            try
            {
                if (!File.Exists(Arquivo)) return cfg;

                foreach (var linha in File.ReadAllLines(Arquivo, Encoding.UTF8))
                {
                    var texto = linha.Trim();
                    if (texto.Length == 0 || texto.StartsWith("#")) continue;

                    var igual = texto.IndexOf('=');
                    if (igual <= 0) continue;

                    var chave = texto.Substring(0, igual).Trim().ToLowerInvariant();
                    var valor = texto.Substring(igual + 1).Trim();

                    switch (chave)
                    {
                        case "servidor":
                            cfg.Servidor = NormalizarUrl(valor);
                            break;
                        case "largura":
                            cfg.Largura = LerInteiro(valor, 1280);
                            break;
                        case "altura":
                            cfg.Altura = LerInteiro(valor, 860);
                            break;
                        case "maximizado":
                            cfg.Maximizado = valor == "1" || valor.Equals("true", StringComparison.OrdinalIgnoreCase);
                            break;
                    }
                }
            }
            catch
            {
                // Configuração ilegível não pode impedir o programa de abrir:
                // volta ao padrão e pede o endereço de novo.
            }
            return cfg;
        }

        public void Salvar()
        {
            try
            {
                Directory.CreateDirectory(Pasta);
                var sb = new StringBuilder();
                sb.AppendLine("# Nexus — configuração do aplicativo");
                sb.AppendLine("# Apague este arquivo para voltar à tela inicial de configuração.");
                sb.AppendLine("servidor=" + (Servidor ?? ""));
                sb.AppendLine("largura=" + Largura.ToString(CultureInfo.InvariantCulture));
                sb.AppendLine("altura=" + Altura.ToString(CultureInfo.InvariantCulture));
                sb.AppendLine("maximizado=" + (Maximizado ? "1" : "0"));
                File.WriteAllText(Arquivo, sb.ToString(), new UTF8Encoding(false));
            }
            catch
            {
                // Sem permissão de escrita a janela ainda funciona nesta sessão;
                // só não lembra na próxima.
            }
        }

        private static int LerInteiro(string valor, int padrao)
        {
            int n;
            return int.TryParse(valor, NumberStyles.Integer, CultureInfo.InvariantCulture, out n) && n > 200
                ? n
                : padrao;
        }

        /// <summary>
        /// Deixa o endereço no formato que o WebView2 aceita.
        ///
        /// Quem digita "192.168.1.10:4545" ou "nexus.empresa.com" está pensando
        /// no endereço, não no esquema. Sem o esquema, a navegação falha com
        /// uma mensagem que não ajuda. Aqui o `http://` é acrescentado — e o
        /// `https://` é preservado quando existe.
        /// </summary>
        public static string NormalizarUrl(string bruto)
        {
            if (string.IsNullOrWhiteSpace(bruto)) return "";

            var texto = bruto.Trim();

            if (!texto.StartsWith("http://", StringComparison.OrdinalIgnoreCase) &&
                !texto.StartsWith("https://", StringComparison.OrdinalIgnoreCase))
            {
                texto = "http://" + texto;
            }

            // Barra no fim faz `Uri` tratar como diretório; e o app monta
            // caminhos como `/api/v1/...` a partir da base.
            return texto.TrimEnd('/');
        }

        /// <summary>Endereço da verificação de saúde do servidor.</summary>
        public string UrlSaude
        {
            get { return Servidor + "/health"; }
        }
    }
}
