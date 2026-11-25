// =====================================================================
// Configuração do agente — servidor e token
// =====================================================================
//
// ## O que fica em disco
//
// `%ProgramData%\Nexus\agente.json`
//
//   servidor   texto claro (não é segredo; é o endereço do Nexus)
//   ativo_id   texto claro
//   token      **cifrado com DPAPI de máquina** (base64)
//
// ## Por que DPAPI e não um arquivo qualquer
//
// Uma chave em texto pode ser copiada para outra máquina e funcionar. A
// protegida por DPAPI só é decifrável **naquela máquina** — copiar o arquivo
// não serve. É a diferença entre "segredo guardado" e "segredo guardado de
// verdade".
//
// O escopo é `LocalMachine`: o serviço roda como SYSTEM e a tarefa de logon
// como o usuário. Escopo de usuário faria o token sumir para um dos dois.
//
// =====================================================================

using System;
using System.Collections.Generic;
using System.IO;
using System.Security.Cryptography;
using System.Text;
using System.Web.Script.Serialization;

namespace AgenteNexus
{
    public class Configuracao
    {
        public string Servidor { get; set; }
        public int AtivoId { get; set; }
        // Token cifrado, em base64. Nunca em claro no arquivo.
        public string TokenProtegido { get; set; }

        // Código de instalação. Fica guardado **mesmo após o sucesso**, para
        // permitir recadastrar quando o ativo é excluído no painel.
        public string CodigoPendenteProtegido { get; set; }

        // De quantas em quantas horas enviar a lista de programas.
        //
        // Vem do servidor, na resposta do inventario. Guardado aqui para
        // sobreviver a reinicio e para o agente nao perder o valor quando o
        // servidor estiver fora do ar.
        public int IntervaloSoftwareHoras { get; set; }

        /// <summary>
        /// O último registro FALHOU e o serviço ainda vai tentar de novo.
        ///
        /// ## Por que separado de `TemPendencia`
        ///
        /// O código fica guardado sempre — sucesso ou falha — porque é ele que
        /// permite refazer o cadastro quando o ativo é excluído.
        ///
        /// `TemPendencia` respondia "existe código guardado". Depois dessa
        /// mudança, **toda** máquina passou a responder `true`, e a tela
        /// mostrava "aguardando vinculação" mesmo com o registro concluído.
        ///
        /// Este campo responde a pergunta certa: o registro está pendente?
        /// </summary>
        public bool RegistroPendente { get; set; }

        private static string Pasta()
        {
            // `%ProgramData%\Nexus` é criado pelo MSI como SYSTEM e pode não ser
            // gravável para o usuário comum que abre a bandeja. O
            // `Operacao.PastaDados` testa a escrita de verdade e cai para
            // `%LOCALAPPDATA%` quando não há permissão.
            return Operacao.PastaDados();
        }

        private static string Arquivo()
        {
            return Path.Combine(Pasta(), "agente.json");
        }

        /// <summary>Lê a configuração. Devolve null se ainda não registrado.</summary>
        public static Configuracao Carregar()
        {
            try
            {
                string caminho = Arquivo();
                if (!File.Exists(caminho)) return null;
                string bruto = File.ReadAllText(caminho, Encoding.UTF8);
                var ser = new JavaScriptSerializer();
                var cfg = ser.Deserialize<Configuracao>(bruto);
                if (cfg == null || string.IsNullOrEmpty(cfg.Servidor)) return null;
                return cfg;
            }
            catch (Exception) { return null; }
        }

        public void Salvar()
        {
            var ser = new JavaScriptSerializer();
            File.WriteAllText(Arquivo(), ser.Serialize(this), Encoding.UTF8);
        }


        /// <summary>Cifra um texto com DPAPI de máquina.</summary>
        public static string Cifrar(string texto)
        {
            if (string.IsNullOrEmpty(texto)) return null;
            byte[] cifrado = ProtectedData.Protect(
                Encoding.UTF8.GetBytes(texto), null, DataProtectionScope.LocalMachine);
            return Convert.ToBase64String(cifrado);
        }

        /// <summary>Decifra. Devolve null se o blob não abrir nesta máquina.</summary>
        public static string Decifrar(string base64)
        {
            if (string.IsNullOrEmpty(base64)) return null;
            try
            {
                byte[] claro = ProtectedData.Unprotect(
                    Convert.FromBase64String(base64), null, DataProtectionScope.LocalMachine);
                return Encoding.UTF8.GetString(claro);
            }
            catch (CryptographicException) { return null; }
        }

        /// <summary>Guarda o código para tentar de novo depois.</summary>
        public void DefinirCodigoPendente(string codigo)
        {
            CodigoPendenteProtegido = Cifrar(codigo);
        }

        public string CodigoPendente()
        {
            return Decifrar(CodigoPendenteProtegido);
        }

        public bool TemPendencia
        {
            get { return !string.IsNullOrEmpty(CodigoPendenteProtegido); }
        }

        public void LimparPendencia()
        {
            CodigoPendenteProtegido = null;
        }

        /// <summary>Guarda o token cifrado com DPAPI de máquina.</summary>
        public void DefinirToken(string token)
        {
            byte[] claro = Encoding.UTF8.GetBytes(token);
            byte[] cifrado = ProtectedData.Protect(
                claro, null, DataProtectionScope.LocalMachine);
            TokenProtegido = Convert.ToBase64String(cifrado);
        }

        /// <summary>Recupera o token. Devolve null se o blob não abrir aqui.</summary>
        public string Token()
        {
            if (string.IsNullOrEmpty(TokenProtegido)) return null;
            try
            {
                byte[] cifrado = Convert.FromBase64String(TokenProtegido);
                byte[] claro = ProtectedData.Unprotect(
                    cifrado, null, DataProtectionScope.LocalMachine);
                return Encoding.UTF8.GetString(claro);
            }
            catch (CryptographicException)
            {
                // Blob de outra máquina ou de outro sistema. Reformatar o PC
                // chega aqui — e aí é preciso registrar de novo.
                return null;
            }
        }

        /// <summary>URL completa de um endpoint, com barra normalizada.</summary>
        public string Url(string caminho)
        {
            string base_ = (Servidor ?? "").TrimEnd('/');
            return base_ + "/api/v1" + caminho;
        }
    }

    public static class Comandos
    {
        /// <summary>
        /// Registra a máquina: troca o código de instalação pelo token.
        ///
        /// O código **não é guardado** — ele morre aqui. O que persiste é o
        /// token que o servidor devolveu.
        /// </summary>
        public static int Registrar(string servidor, string codigo)
        {
            if (string.IsNullOrEmpty(servidor) || string.IsNullOrEmpty(codigo))
            {
                Console.Error.WriteLine(
                    "Uso: agente.exe registrar --servidor https://host:porta --codigo AAAA-BBBB-CCCC");
                return 2;
            }

            var inv = Coletor.Inventario();
            var corpo = new Dictionary<string, object> {
                { "codigo", codigo },
                { "serial", inv["serial"] },
                { "hostname", inv["hostname"] },
                { "basico", inv["basico"] },
                { "detalhes", inv["detalhes"] },
            };

            var cfg = new Configuracao { Servidor = servidor };
            string resposta;
            try
            {
                resposta = Canal.Post(cfg.Url("/agente/registrar"), Canal.Json(corpo), null);
            }
            catch (Exception ex)
            {
                // ## Não falha: guarda o código e tenta de novo sozinho
                //
                // Antes o instalador abortava com "Falha no registro", fechava
                // a janela, e o técnico ficava sem nada — sem saber quando
                // tentar de novo.
                //
                // Agora o código fica guardado (com DPAPI) e o serviço tenta
                // a cada ciclo. Quando o servidor passar a conhecer a máquina,
                // ela se conecta sozinha, sem reinstalar nada.
                //
                // O código de saída 3 é distinto de 1 (erro real): o
                // instalador sabe que isto é "pendente", não "falhou".
                cfg.DefinirCodigoPendente(codigo);
                cfg.RegistroPendente = true;
                try
                {
                    cfg.Salvar();
                }
                catch (Exception erroGravacao)
                {
                    // %ProgramData% exige elevacao. Em producao o instalador ja
                    // roda como administrador; sem ele, avisar e melhor que um
                    // stack trace na cara do tecnico.
                    Console.Error.WriteLine(
                        "Nao foi possivel gravar a configuracao: " + erroGravacao.Message);
                    Console.Error.WriteLine(
                        "Execute o instalador como Administrador.");
                    return 1;
                }
                Console.WriteLine("Registro pendente: " + ex.Message);
                Console.WriteLine(
                    "O agente vai tentar de novo automaticamente. Nada mais a fazer.");
                return 3;
            }

            var ser = new JavaScriptSerializer();
            var dados = ser.Deserialize<Dictionary<string, object>>(resposta);
            object token;
            if (dados == null || !dados.TryGetValue("token", out token) || token == null)
            {
                Console.Error.WriteLine("Resposta sem token: " + resposta);
                return 1;
            }

            cfg.AtivoId = Convert.ToInt32(dados["ativo_id"]);
            cfg.DefinirToken(Convert.ToString(token));

            // O código fica guardado MESMO no sucesso: é o que permite
            // recadastrar se o ativo for excluído depois. O token sozinho
            // não serve para isso — ele aponta para o ativo que sumiu.
            cfg.DefinirCodigoPendente(codigo);
            cfg.RegistroPendente = false;
            cfg.Salvar();

            Console.WriteLine("Registrado. ativo_id=" + cfg.AtivoId);
            Console.WriteLine("Servidor: " + cfg.Servidor);
            return 0;
        }

        /// <summary>Envia o inventário usando o token guardado.</summary>
        public static int Enviar()
        {
            var cfg = Configuracao.Carregar();
            if (cfg == null)
            {
                Console.Error.WriteLine("Agente não registrado. Rode 'registrar' primeiro.");
                return 2;
            }
            string token = cfg.Token();
            if (token == null)
            {
                Console.Error.WriteLine(
                    "Token não pôde ser aberto nesta máquina. Registre novamente.");
                return 2;
            }

            string corpo = Canal.Json(Coletor.Inventario());
            try
            {
                string r = Canal.Post(cfg.Url("/agente/inventario"), corpo, token);
                EstadoLocal.Gravar(true, r);
                Console.WriteLine("Enviado. " + r);

                // O envio manual tambem manda a lista de programas. Sem isto,
                // "Atualizar agora" deixaria o software esperando o ciclo
                // diario — justamente o que o usuario quis evitar ao clicar.
                EnviarSoftwareComAviso(cfg, token);

                return 0;
            }
            catch (Exception ex)
            {
                EstadoLocal.Gravar(false, ex.Message);
                Console.Error.WriteLine("Falha no envio: " + ex.Message);

                // O ativo foi excluído. O token continua válido, mas aponta
                // para algo que não existe mais — é preciso cadastrar do zero.
                if (ex.Message.IndexOf("ativo_removido", StringComparison.OrdinalIgnoreCase) >= 0)
                {
                    Console.WriteLine("Ativo removido. Cadastrando novamente...");
                    cfg.TokenProtegido = null;
                    cfg.AtivoId = 0;
                    cfg.Salvar();

                    if (TentarRegistroPendente())
                        return Enviar();
                }
                return 1;
            }
        }


        /// <summary>
        /// Se existe código pendente, tenta o registro antes de enviar.
        ///
        /// ## Por que isto existe
        ///
        /// Quando a instalação não consegue registrar — servidor fora do ar,
        /// ou a máquina ainda não conhecida — o código fica guardado com
        /// DPAPI. Aqui ele é usado em cada ciclo do serviço.
        ///
        /// Quando dá certo, o próprio `Registrar` grava o token e limpa a
        /// pendência. A máquina passa a enviar sem ninguém tocar em nada.
        /// </summary>
        public static bool TentarRegistroPendente()
        {
            var cfg = Configuracao.Carregar();
            if (cfg == null || !cfg.TemPendencia) return false;

            string codigo = cfg.CodigoPendente();
            if (string.IsNullOrEmpty(codigo)) return false;

            return Registrar(cfg.Servidor, codigo) == 0;
        }

        /// <summary>
        /// Confere a senha de fechamento no servidor.
        ///
        /// ## Por que falha de rede fecha o caminho
        ///
        /// Esta é uma trava: se o servidor não responde, o certo é **não
        /// fechar**. Liberar por falta de resposta transformaria uma queda de
        /// rede em "qualquer um encerra o agente".
        ///
        /// O servidor devolve `ok` também quando ninguém definiu senha —
        /// instalação nova precisa poder ser encerrada.
        /// </summary>
        public static bool ValidarSenhaFechamento(string senha)
        {
            var cfg = Configuracao.Carregar();

            // Sem servidor configurado, não há senha a pedir: não existe
            // sistema para consultar. Desinstalar e fechar funcionam normal.
            if (cfg == null) return true;

            // Configurado mas ainda sem token (registro pendente): também
            // libera. A máquina não está vinculada a ativo nenhum, então não
            // há inventário a proteger — e travar aqui deixaria o técnico
            // sem saída, porque sem token o servidor não valida nada.
            string token = cfg.Token();
            if (token == null) return true;

            try
            {
                var corpo = new Dictionary<string, object> { { "senha", senha ?? "" } };
                Canal.Post(cfg.Url("/agente/validar-senha"), Canal.Json(corpo), token);
                return true;
            }
            catch (Exception)
            {
                return false;
            }
        }

        /// <summary>
        /// Envio feito pelo serviço — sem console, sem estourar exceção.
        ///
        /// O serviço roda sem ninguém olhando: uma exceção aqui mataria a
        /// thread do laço e o agente pararia em silêncio. Quem chama trata, e
        /// o erro vai para o log do serviço.
        /// </summary>
        public static void EnviarSilencioso()
        {
            var cfg = Configuracao.Carregar();
            if (cfg == null) throw new InvalidOperationException("nao registrado");
            string token = cfg.Token();
            if (token == null) throw new InvalidOperationException("token ilegivel");

            // Sem token: só faz sentido tentar se houver código guardado.
            if (cfg.AtivoId == 0) { TentarRegistroPendente(); return; }

            // Os usuários vêm das sessões do Windows, não da sessão do
            // processo — o serviço não tem uma.
            string corpo = Canal.Json(Coletor.Inventario(Sessoes.UsuariosAtivos()));
            string resposta = Canal.Post(cfg.Url("/agente/inventario"), corpo, token);
            EstadoLocal.Gravar(true, "ok");

            // O servidor manda de quanto em quanto tempo enviar o software.
            // Guardar aqui permite mudar o intervalo pelo painel, sem
            // reinstalar o agente.
            int horas = ExtrairIntervalo(resposta);
            if (horas > 0 && horas != cfg.IntervaloSoftwareHoras)
            {
                cfg.IntervaloSoftwareHoras = horas;
                cfg.Salvar();
            }
        }



        /// <summary>
        /// Le `intervalo_software_horas` de uma resposta JSON do servidor.
        ///
        /// Implementado à mão porque o alvo é .NET Framework 4.0 com C# 5:
        /// não há `System.Text.Json`, e o `JavaScriptSerializer` traria uma
        /// dependência de assembly só para ler um inteiro.
        ///
        /// Devolve 0 quando não encontra — o chamador decide o padrão.
        /// </summary>
        private static int ExtrairIntervalo(string json)
        {
            if (string.IsNullOrEmpty(json)) return 0;

            const string chave = "\"intervalo_software_horas\"";
            int pos = json.IndexOf(chave, StringComparison.Ordinal);
            if (pos < 0) return 0;

            int doisPontos = json.IndexOf(':', pos + chave.Length);
            if (doisPontos < 0) return 0;

            int inicio = doisPontos + 1;
            while (inicio < json.Length && char.IsWhiteSpace(json[inicio])) inicio++;

            int fim = inicio;
            while (fim < json.Length && char.IsDigit(json[fim])) fim++;
            if (fim == inicio) return 0;

            int valor;
            if (!int.TryParse(json.Substring(inicio, fim - inicio), out valor))
                return 0;

            // Faixa sã: 1 hora a 168 (uma semana). Valor absurdo é resposta
            // corrompida, e vale mais o padrão que um intervalo de 10 anos.
            return valor < 1 || valor > 168 ? 0 : valor;
        }

        /// <summary>
        /// Envia a lista de programas instalados.
        ///
        /// ## Frequência: uma vez por hora
        ///
        /// Software muda mais que hardware — instalação e desinstalação
        /// acontecem no meio do dia, e uma lista de 24h atrás esconde a
        /// mudança que o técnico acabou de fazer.
        ///
        /// O controle fica em `software.json`: se a última coleta tem menos
        /// de uma hora, não envia. O envio manual ("Atualizar agora") também
        /// marca, para não haver dois envios seguidos.
        /// </summary>
        public static int EnviarSoftware()
        {
            var cfg = Configuracao.Carregar();
            if (cfg == null || cfg.AtivoId == 0)
            {
                Console.Error.WriteLine("Agente nao registrado.");
                return 2;
            }

            string token = cfg.Token();
            if (token == null)
            {
                Console.Error.WriteLine("Token ilegivel.");
                return 2;
            }

            var lista = ColetorSoftware.Coletar();
            var corpo = new Dictionary<string, object> { { "software", lista } };

            string resposta = Canal.Post(
                cfg.Url("/agente/software"), Canal.Json(corpo), token);

            Console.WriteLine("Enviados " + lista.Count + " programas.");
            if (!string.IsNullOrEmpty(resposta))
                Console.WriteLine(resposta);

            EstadoLocal.Gravar(true, "software");
            return 0;
        }

        /// <summary>
        /// Envia a lista de programas mostrando o resultado, sem derrubar o
        /// envio principal.
        ///
        /// Usado pelo envio manual, onde a pessoa está olhando a tela e quer
        /// saber o que aconteceu — diferente do ciclo do serviço, que só
        /// registra em log.
        /// </summary>
        public static void EnviarSoftwareComAviso(Configuracao cfg, string token)
        {
            try
            {
                var lista = ColetorSoftware.Coletar();
                var corpo = new Dictionary<string, object> { { "software", lista } };

                string resposta = Canal.Post(
                    cfg.Url("/agente/software"), Canal.Json(corpo), token);

                MarcarSoftware(cfg);
                Console.WriteLine(
                    "Softwares: " + lista.Count + " enviados. " + resposta);
            }
            catch (Exception ex)
            {
                // Não propaga: o inventário já foi aceito. Avisar é o bastante.
                Console.WriteLine("Softwares: falhou (" + ex.Message + ")");
            }
        }

        /// <summary>
        /// Versao silenciosa, chamada pelo servico a cada ciclo.
        ///
        /// **Nao lanca**: o servico nao pode morrer porque a coleta de
        /// software falhou. Devolve `true` quando enviou.
        /// </summary>
        public static bool EnviarSoftwareSeVencido(int horas)
        {
            try
            {
                var cfg = Configuracao.Carregar();
                if (cfg == null || cfg.AtivoId == 0) return false;

                string token = cfg.Token();
                if (token == null) return false;

                if (!SoftwareVencido(cfg, horas)) return false;

                var lista = ColetorSoftware.Coletar();
                var corpo = new Dictionary<string, object> { { "software", lista } };

                Canal.Post(cfg.Url("/agente/software"), Canal.Json(corpo), token);
                MarcarSoftware(cfg);
                return true;
            }
            catch (Exception ex)
            {
                ServicoAgente.Registrar("software nao enviado: " + ex.Message);
                return false;
            }
        }

        /// <summary>Ja passou tempo suficiente desde o ultimo envio?</summary>
        private static bool SoftwareVencido(Configuracao cfg, int horas)
        {
            try
            {
                string caminho = System.IO.Path.Combine(
                    Operacao.PastaDados(), "software.json");

                if (!System.IO.File.Exists(caminho)) return true;

                string texto = System.IO.File.ReadAllText(caminho);
                DateTime quando;
                if (!DateTime.TryParse(texto, out quando)) return true;

                return (DateTime.UtcNow - quando).TotalHours >= horas;
            }
            catch (Exception) { return true; }
        }

        private static void MarcarSoftware(Configuracao cfg)
        {
            try
            {
                System.IO.File.WriteAllText(
                    System.IO.Path.Combine(Operacao.PastaDados(), "software.json"),
                    DateTime.UtcNow.ToString("o"));
            }
            catch (Exception) { }
        }

        /// <summary>Mostra o inventário sem enviar — para diagnóstico.</summary>
        public static int Coletar()
        {
            // winexe sem console lanca IOException aqui. O
            // ConsoleSobDemanda ja ajustou a saida quando havia console;
            // esta linha e so um reforco, e nao pode derrubar o comando.
            try { Console.OutputEncoding = Encoding.UTF8; } catch (Exception) { }
            Console.WriteLine(Canal.Json(Coletor.Inventario()));
            return 0;
        }
    }
}
