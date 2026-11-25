// =====================================================================
// Serviço Windows — o coração do agente
// =====================================================================
//
// ## Por que serviço, e não tarefa agendada
//
// Tarefa agendada depende de: política de grupo que não desabilite, tarefa que
// não seja apagada por política de segurança, antivírus que não bloqueie, e
// ninguém precisa saber quando ela falha.
//
// Serviço tem o que a tarefa não tem:
//
//   * `restart on failure` nativo do SCM — o Windows reinicia sozinho
//   * aparece em `services.msc`, status visível
//   * sobe no boot sem depender de sessão
//   * log de erro no Event Viewer
//
// ## Quem está logado, visto de dentro de um serviço
//
// `Win32_ComputerSystem.UserName` vem **vazio** quando consultado como
// SYSTEM — ele lê a sessão do processo, e o serviço não tem uma.
//
// A solução é `WTSEnumerateSessions`, que pergunta ao Terminal Services quais
// sessões existem e quem está em cada uma. Funciona de dentro do serviço,
// porque não depende da sessão do chamador.
//
// Isso torna a tarefa de logon **opcional** — o serviço já responde sozinho.
// Ela fica como refinamento para máquina compartilhada.
//
// =====================================================================

using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.ServiceProcess;
using System.Threading;

namespace AgenteNexus
{
    /// <summary>Quem usa esta máquina.</summary>
    public static class Sessoes
    {
        /// <summary>
        /// Último usuário que fez logon interativo, como `DOMINIO\usuario`.
        ///
        /// ## Por que registro, e não WTS
        ///
        /// A versão anterior usava `WTSEnumerateSessions` + P/Invoke. Ela
        /// devolveu `界慣s` — lixo de memória lido como UTF-16. Ponteiro,
        /// buffer e liberação manual: três lugares para errar, e nenhum
        /// deles testável sem a máquina na frente.
        ///
        /// O registro entrega o mesmo dado como **texto simples**. Não há o
        /// que decodificar errado.
        ///
        /// Limitação: é o **último logon**, não "quem está na tela agora".
        /// Em máquina compartilhada pode ficar desatualizado até o próximo
        /// logon — preço honesto por confiabilidade.
        /// </summary>
        public static List<string> UsuariosAtivos()
        {
            var saida = new List<string>();
            try
            {
                using (var chave = Microsoft.Win32.Registry.LocalMachine.OpenSubKey(
                    @"SOFTWARE\Microsoft\Windows\CurrentVersion\Authentication\LogonUI"))
                {
                    if (chave != null)
                    {
                        object valor = chave.GetValue("LastLoggedOnUser");
                        if (valor != null)
                        {
                            string usuario = valor.ToString().Trim();
                            // O registro às vezes vem como `DOMINIO\usuario`,
                            // às vezes só o nome. Ambos servem.
                            // `.\Lucas` significa "usuário local". O prefixo
                            // nao ajuda ninguem na tela.
                            if (usuario.StartsWith(".\\")) usuario = usuario.Substring(2);
                            if (usuario.Length > 0) saida.Add(usuario);
                        }
                    }
                }
            }
            catch (Exception) { }
            return saida;
        }
    }

    /// <summary>O serviço propriamente dito.</summary>
    public class ServicoAgente : ServiceBase
    {
        private Thread _thread;
        private volatile bool _rodando;
        // 1 hora. A coleta e barata quando o hardware nao muda: o servidor
        // compara o hash e faz um UPDATE em vez de criar historico.
        private int _intervaloMinutos = 60;

        public ServicoAgente()
        {
            ServiceName = "NexusAgente";
            CanStop = true;
            CanShutdown = true;
            AutoLog = true;
        }

        protected override void OnStart(string[] args)
        {
            _rodando = true;
            _thread = new Thread(Laco);
            _thread.IsBackground = true;
            _thread.Start();
        }

        protected override void OnStop()
        {
            _rodando = false;
            // Espera o ciclo atual terminar antes de morrer: um envio pela
            // metade deixa o servidor com inventário parcial.
            if (_thread != null && !_thread.Join(TimeSpan.FromSeconds(30)))
                _thread.Abort();
        }

        protected override void OnShutdown()
        {
            OnStop();
            base.OnShutdown();
        }

        /// <summary>
        /// O laço de coleta.
        ///
        /// ## O atraso inicial aleatório
        ///
        /// Sem ele, 3.000 máquinas que reiniciam juntas às 8h mandam tudo no
        /// mesmo minuto. O atraso espalha a primeira coleta.
        ///
        /// ## Por que não dorme 12 h de uma vez
        ///
        /// Dormir o intervalo inteiro impede o `OnStop` de responder. Aqui o
        /// sono é em fatias de 1 minuto, e o `_rodando` é conferido a cada
        /// fatia — parar o serviço leva no máximo 1 minuto.
        /// </summary>
        /// <summary>
        /// Garante a bandeja aberta na sessao interativa.
        ///
        /// Falha silenciosa quando nao ha ninguem logado — nao ha sessao para
        /// onde abrir, e o proximo ciclo tenta de novo.
        /// </summary>
        private const string NOME_TAREFA = "Nexus Agente";

        private static void AbrirBandeja()
        {
            try
            {
                // Ja existe bandeja na sessao do usuario? Nada a fazer.
                if (BandejaNaSessao.JaRodando()) return;

                // ## Caminho 1: tarefa agendada
                //
                // E o unico jeito de abrir elevado sem UAC. O servico roda a
                // tarefa; a elevacao fica com o Agendador, na sessao certa.
                if (DispararTarefa()) return;

                // ## Caminho 2: criacao direta (instalacao sem tarefa)
                //
                // Falha com 740 quando o manifesto exige administrador. O
                // log registra — foi o que revelou o problema.
                string exe = System.Reflection.Assembly.GetExecutingAssembly().Location;
                string motivo = BandejaNaSessao.Abrir(exe);

                if (!string.IsNullOrEmpty(motivo))
                    Registrar("bandeja nao abriu: " + motivo);
            }
            catch (Exception ex)
            {
                Registrar("bandeja nao abriu (excecao): " + ex.Message);
            }
        }

        /// <summary>
        /// Executa a tarefa agendada que abre a bandeja elevada.
        ///
        /// Devolve `true` se o comando foi aceito. **Nao** verifica se a
        /// janela apareceu: o Agendador responde na hora e a janela sobe em
        /// seguida. Quem confirma e `JaRodando`, no proximo ciclo.
        /// </summary>
        private static bool DispararTarefa()
        {
            try
            {
                var inicio = new System.Diagnostics.ProcessStartInfo
                {
                    FileName = "schtasks.exe",
                    Arguments = "/run /tn \"" + NOME_TAREFA + "\"",
                    CreateNoWindow = true,
                    UseShellExecute = false,
                    RedirectStandardOutput = true,
                    RedirectStandardError = true,
                };

                using (var p = System.Diagnostics.Process.Start(inicio))
                {
                    string saida = p.StandardOutput.ReadToEnd()
                        + p.StandardError.ReadToEnd();
                    p.WaitForExit(5000);

                    if (p.ExitCode == 0) return true;

                    // Tarefa inexistente e o caso comum de instalacao antiga.
                    Registrar("tarefa agendada nao executou: " + saida.Trim());
                    return false;
                }
            }
            catch (Exception ex)
            {
                Registrar("falha ao disparar tarefa: " + ex.Message);
                return false;
            }
        }

        /// <summary>
        /// Grava uma linha no log do servico.
        ///
        /// Vai para arquivo, e nao para o Event Log: escrever no Event Log
        /// como LocalSystem funciona, mas consultar exige administrador — e
        /// o log precisa ser lido justamente quando algo deu errado.
        /// </summary>
        internal static void Registrar(string texto)
        {
            try
            {
                string pasta = Operacao.PastaDados();
                System.IO.Directory.CreateDirectory(pasta);
                string arquivo = System.IO.Path.Combine(pasta, "servico.log");

                // Roda a partir de 512 KB: log de servico nao pode crescer
                // para sempre numa maquina que fica meses ligada.
                var info = new System.IO.FileInfo(arquivo);
                if (info.Exists && info.Length > 512 * 1024)
                    System.IO.File.WriteAllText(arquivo, "");

                System.IO.File.AppendAllText(
                    arquivo,
                    DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss")
                        + "  " + texto + Environment.NewLine);
            }
            catch (Exception) { /* se o log falhar, nao derruba o servico */ }
        }

        private void Laco()
        {
            // Abre a bandeja na sessao do usuario. Chamado do servico, o
            // processo nasce com a elevacao de SYSTEM — sem UAC.
            // ## SeTcbPrivilege
            //
            // Ser LocalSystem nao basta para `WTSQueryUserToken`: o token
            // contem SeTcbPrivilege, mas **desabilitada**. Sem habilita-la, a
            // chamada falha com erro 1314 e a bandeja nunca abre.
            string erroPriv = Privilegio.HabilitarSeTcb();
            if (!string.IsNullOrEmpty(erroPriv))
                Registrar("ao iniciar: " + erroPriv);
            else
                Registrar("ao iniciar: SeTcbPrivilege habilitada");

            AbrirBandeja();

            var rng = new Random();
            int atrasoInicial = rng.Next(0, 15);   // 0–14 min

            for (int i = 0; i < atrasoInicial && _rodando; i++)
                Thread.Sleep(TimeSpan.FromMinutes(1));

            while (_rodando)
            {
                try
                {
                    // Se fecharam a bandeja, ela volta no próximo ciclo. O
                    // serviço é quem mantém o ícone vivo — mas só depois que o
                    // sono passar, para não reabrir enquanto a pessoa ainda
                    // está tentando fechar.
                    Comandos.TentarRegistroPendente();
                    Comandos.EnviarSilencioso();

                    // Software tem relógio próprio, mas agora no mesmo passo
                    // do inventário: uma vez por hora. O ciclo do serviço já
                    // roda de hora em hora, e `EnviarSoftwareSeVencido`
                    // confere se passou o intervalo — então não há envio
                    // dobrado.
                    // O intervalo vem do servidor; 1 hora e o padrao quando ele nunca
                    // respondeu (primeira instalacao, servidor fora do ar).
                    var cfgAtual = Configuracao.Carregar();
                    int horas = cfgAtual != null && cfgAtual.IntervaloSoftwareHoras > 0
                        ? cfgAtual.IntervaloSoftwareHoras
                        : 1;
                    Comandos.EnviarSoftwareSeVencido(horas);
                }
                catch (Exception) { /* registrado em log pelo SCM */ }

                // Só reabre a bandeja se ela tiver sido fechada E o ciclo
                // seguinte começar. Colocar antes do envio faria a janela
                // reaparecer durante o próprio fechamento.
                AbrirBandeja();

                // ## Retry da bandeja a cada minuto
                //
                // O serviço sobe junto com o Windows, **antes** de qualquer
                // login. Naquela hora não há sessão interativa para onde
                // abrir a janela, e a tentativa falha — antes ela só seria
                // repetida no próximo ciclo, uma hora depois.
                //
                // Um minuto é o tempo que o usuário leva para chegar à área
                // de trabalho. Custa uma enumeração de processos por minuto,
                // que é desprezível.
                for (int i = 0; i < _intervaloMinutos && _rodando; i++)
                {
                    Thread.Sleep(TimeSpan.FromMinutes(1));
                    if (_rodando) AbrirBandeja();
                }
            }
        }
    }

    /// <summary>Ponto de entrada quando o SCM inicia o processo.</summary>
    public static class EntradaServico
    {
        public static void Rodar()
        {
            ServiceBase.Run(new ServicoAgente());
        }
    }
}
