// =====================================================================
// Agente Nexus — coletor de inventário
// =====================================================================
//
// Compilado com o csc.exe do .NET Framework 4.0 (C# 5): sem interpolação
// de string, sem membros de expressão. É o compilador que já existe em
// qualquer Windows 10, sem SDK instalado.
//
// ## Modos
//
//   coletar    lê o hardware e imprime o JSON (não precisa de servidor)
//   registrar  troca o código de instalação pelo token da máquina
//   enviar     envia o inventário com o token guardado
//
// ## O que ele NÃO faz
//
// - Não abre porta de escuta.
// - Não aceita comando do servidor: só envia. Um impostor na rede não tem o
//   que mandar esta máquina fazer.
// - Não acessa documentos, navegador ou qualquer dado do usuário.
//
// =====================================================================

using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Management;
using System.Net;
using System.Security.Cryptography;
using System.Text;
using System.Web.Script.Serialization;

namespace AgenteNexus
{
    /// <summary>Coleta de hardware via WMI.</summary>
    public static class Coletor
    {
        private const string NS = "root\\cimv2";
        private const string NS_WMI = "root\\wmi";

        /// <summary>Primeiro valor de uma consulta WMI, ou null.</summary>
        private static string Valor(string ns, string consulta, string campo)
        {
            try
            {
                using (var busca = new ManagementObjectSearcher(ns, consulta))
                    foreach (ManagementObject obj in busca.Get())
                    {
                        object v = obj[campo];
                        if (v == null) continue;
                        string s = Convert.ToString(v, CultureInfo.InvariantCulture).Trim();
                        if (s.Length > 0) return s;
                    }
            }
            catch (ManagementException) { }
            catch (UnauthorizedAccessException) { }
            return null;
        }

        private static string V(string consulta, string campo)
        {
            return Valor(NS, consulta, campo);
        }

        /// <summary>
        /// Serial da BIOS — o identificador do ativo.
        ///
        /// Máquina virtual e placa genérica devolvem lixo aqui
        /// ("To be filled by O.E.M.", "00000000", "Default string"). O
        /// servidor recusa esses valores e a máquina vai para a fila de
        /// cadastro, onde alguém escolhe outro identificador.
        /// </summary>
        public static string Serial()
        {
            string s = V("SELECT SerialNumber FROM Win32_BIOS", "SerialNumber");
            if (s == null) return null;
            string t = s.Trim();
            string[] lixo = {
                "", "0", "00000000", "To be filled by O.E.M.",
                "To Be Filled By O.E.M.", "Default string", "None",
                "System Serial Number", "Not Specified", "N/A",
            };
            foreach (string l in lixo)
                if (string.Equals(t, l, StringComparison.OrdinalIgnoreCase)) return null;
            if (t.StartsWith("VMware-", StringComparison.OrdinalIgnoreCase)) return null;
            if (t.StartsWith("0000-0000", StringComparison.Ordinal)) return null;
            return t;
        }

        /// <summary>
        /// Identificador derivado, quando a BIOS não tem serial de fábrica.
        ///
        /// ## Por que o MachineGuid
        ///
        /// Placa de montagem própria devolve `To be filled by O.E.M.` — igual
        /// em milhares de máquinas. Usar isso como identificador faria todas
        /// virarem um registro só.
        ///
        /// O Windows gera um GUID único por instalação, em
        /// `HKLM\SOFTWARE\Microsoft\Cryptography\MachineGuid`. Ele existe em
        /// qualquer máquina, **inclusive branca**, e não muda entre reinícios.
        ///
        /// O prefixo `OEM-` deixa óbvio, na tela, que aquele identificador não
        /// veio do fabricante.
        ///
        /// **Limitação**: formatar o PC gera outro GUID, e a máquina vira um
        /// ativo novo. Para máquina branca é o preço de não ter serial.
        /// </summary>
        public static string IdentificadorDerivado()
        {
            try
            {
                using (var chave = Microsoft.Win32.Registry.LocalMachine.OpenSubKey(
                    @"SOFTWARE\Microsoft\Cryptography"))
                {
                    if (chave != null)
                    {
                        object g = chave.GetValue("MachineGuid");
                        if (g != null)
                        {
                            string guia = g.ToString().Replace("-", "").Trim();
                            if (guia.Length >= 12)
                                return "OEM-" + guia.Substring(0, 12).ToUpperInvariant();
                        }
                    }
                }
            }
            catch (Exception) { }

            // Último recurso: hostname. Menos estável (renomear muda), mas
            // melhor que ficar sem identificador nenhum.
            return "HOST-" + Environment.MachineName.ToUpperInvariant();
        }

        /// <summary>Soma dos pentes de memória, em GB.</summary>
        private static int RamGb()
        {
            try
            {
                long total = 0;
                using (var busca = new ManagementObjectSearcher(
                    NS, "SELECT Capacity FROM Win32_PhysicalMemory"))
                    foreach (ManagementObject m in busca.Get())
                    {
                        object c = m["Capacity"];
                        if (c != null) total += Convert.ToInt64(c, CultureInfo.InvariantCulture);
                    }
                return (int)Math.Round(total / 1073741824.0);
            }
            catch (Exception) { return 0; }
        }

        /// <summary>Capacidade somada dos discos físicos, em GB.</summary>
        private static int DiscoGb()
        {
            try
            {
                long total = 0;
                using (var busca = new ManagementObjectSearcher(
                    NS, "SELECT Size FROM Win32_DiskDrive"))
                    foreach (ManagementObject m in busca.Get())
                    {
                        object s = m["Size"];
                        if (s != null) total += Convert.ToInt64(s, CultureInfo.InvariantCulture);
                    }
                return (int)Math.Round(total / 1073741824.0);
            }
            catch (Exception) { return 0; }
        }

        private static List<Dictionary<string, object>> Discos()
        {
            var saida = new List<Dictionary<string, object>>();
            try
            {
                using (var busca = new ManagementObjectSearcher(
                    NS, "SELECT Model, SerialNumber, Size, MediaType FROM Win32_DiskDrive"))
                    foreach (ManagementObject m in busca.Get())
                    {
                        long bytes = m["Size"] == null ? 0
                            : Convert.ToInt64(m["Size"], CultureInfo.InvariantCulture);
                        saida.Add(new Dictionary<string, object> {
                            { "modelo", Texto(m["Model"]) },
                            { "serial", Texto(m["SerialNumber"]) },
                            { "gb", (int)Math.Round(bytes / 1073741824.0) },
                            { "tipo", Texto(m["MediaType"]) },
                        });
                    }
            }
            catch (Exception) { }
            return saida;
        }

        private static List<Dictionary<string, object>> Rede()
        {
            var saida = new List<Dictionary<string, object>>();
            try
            {
                using (var busca = new ManagementObjectSearcher(NS,
                    "SELECT Description, MACAddress, IPAddress FROM Win32_NetworkAdapterConfiguration " +
                    "WHERE IPEnabled = True"))
                    foreach (ManagementObject m in busca.Get())
                    {
                        var ips = new List<string>();
                        string[] arr = m["IPAddress"] as string[];
                        if (arr != null)
                            foreach (string ip in arr)
                                if (ip != null && ip.IndexOf(':') < 0) ips.Add(ip);

                        saida.Add(new Dictionary<string, object> {
                            { "adaptador", Texto(m["Description"]) },
                            { "mac", Texto(m["MACAddress"]) },
                            { "ips", ips },
                        });
                    }
            }
            catch (Exception) { }
            return saida;
        }

        private static List<Dictionary<string, object>> Monitores()
        {
            var saida = new List<Dictionary<string, object>>();
            try
            {
                using (var busca = new ManagementObjectSearcher(NS_WMI,
                    "SELECT ManufacturerName, UserFriendlyName, SerialNumberID FROM WmiMonitorID"))
                    foreach (ManagementObject m in busca.Get())
                    {
                        saida.Add(new Dictionary<string, object> {
                            { "fabricante", TextoUInt16(m["ManufacturerName"]) },
                            { "modelo", TextoUInt16(m["UserFriendlyName"]) },
                            { "serial", TextoUInt16(m["SerialNumberID"]) },
                        });
                    }
            }
            catch (Exception) { }
            return saida;
        }

        /// <summary>WmiMonitorID devolve arrays de ushort — é texto em UTF-16.</summary>
        private static string TextoUInt16(object valor)
        {
            ushort[] arr = valor as ushort[];
            if (arr == null) return null;
            var sb = new StringBuilder();
            foreach (ushort u in arr)
            {
                if (u == 0) break;
                sb.Append((char)u);
            }
            string s = sb.ToString().Trim();
            return s.Length == 0 ? null : s;
        }

        private static string Texto(object v)
        {
            if (v == null) return null;
            string s = Convert.ToString(v, CultureInfo.InvariantCulture).Trim();
            return s.Length == 0 ? null : s;
        }

        private static Dictionary<string, object> Dicionario()
        {
            return new Dictionary<string, object>();
        }

        /// <summary>Quem está logado na sessão interativa.</summary>
        private static string UsuarioLogado()
        {
            string u = V("SELECT UserName FROM Win32_ComputerSystem", "UserName");
            if (u != null) return u;
            try
            {
                object v = Environment.GetEnvironmentVariable("USERNAME");
                object d = Environment.GetEnvironmentVariable("USERDOMAIN");
                if (v != null && d != null) return d + "\\" + v;
            }
            catch (Exception) { }
            return null;
        }

        /// <summary>Monta o objeto que será enviado ao servidor.</summary>
        public static Dictionary<string, object> Inventario()
        {
            return Inventario(null);
        }

        /// <summary>
        /// Inventário com usuários informados de fora.
        ///
        /// O serviço roda como SYSTEM e não tem sessão: `Win32_ComputerSystem.UserName`
        /// vem vazio. A lista vem de `WTSEnumerateSessions`, que enxerga as
        /// sessões da máquina sem precisar de uma.
        /// </summary>
        public static Dictionary<string, object> Inventario(List<string> usuariosForcados)
        {
            var basico = Dicionario();
            basico["fabricante"] = V("SELECT Manufacturer FROM Win32_ComputerSystem", "Manufacturer");
            basico["modelo"] = V("SELECT Model FROM Win32_ComputerSystem", "Model");
            basico["cpu"] = V("SELECT Name FROM Win32_Processor", "Name");
            basico["ram_gb"] = RamGb();
            basico["armazenamento_gb"] = DiscoGb();
            basico["so"] = V("SELECT Caption FROM Win32_OperatingSystem", "Caption");
            basico["dominio"] = V("SELECT Domain FROM Win32_ComputerSystem", "Domain");

            var detalhes = Dicionario();
            detalhes["bios_versao"] = V("SELECT SMBIOSBIOSVersion FROM Win32_BIOS", "SMBIOSBIOSVersion");
            detalhes["placa_mae"] = V("SELECT Product FROM Win32_BaseBoard", "Product");
            detalhes["placa_mae_fabricante"] = V("SELECT Manufacturer FROM Win32_BaseBoard", "Manufacturer");
            detalhes["discos"] = Discos();
            detalhes["rede"] = Rede();
            detalhes["monitores"] = Monitores();
            detalhes["gpu"] = V("SELECT Name FROM Win32_VideoController", "Name");
            string usuario = usuariosForcados != null && usuariosForcados.Count > 0
                ? string.Join(", ", usuariosForcados)
                : UsuarioLogado();
            detalhes["usuario_logado"] = usuario;

            string boot = V("SELECT LastBootUpTime FROM Win32_OperatingSystem", "LastBootUpTime");
            detalhes["ultimo_boot"] = boot;
            detalhes["uptime_horas"] = UptimeHoras(boot);

            var raiz = Dicionario();
            // Serial da BIOS quando existe; senao, o derivado do MachineGuid.
            // Sem isso a maquina branca nunca se registra.
            string serialFinal = Serial();
            if (string.IsNullOrEmpty(serialFinal)) serialFinal = IdentificadorDerivado();
            raiz["serial"] = serialFinal;
            raiz["hostname"] = Environment.MachineName;
            raiz["usuario"] = usuario;
            raiz["coletado_em"] = DateTime.Now.ToString("yyyy-MM-ddTHH:mm:sszzz", CultureInfo.InvariantCulture);
            raiz["basico"] = basico;
            raiz["detalhes"] = detalhes;
            return raiz;
        }

        private static int UptimeHoras(string bootWmi)
        {
            if (bootWmi == null) return 0;
            try
            {
                DateTime quando = ManagementDateTimeConverter.ToDateTime(bootWmi);
                double h = (DateTime.Now - quando).TotalHours;
                return h < 0 ? 0 : (int)Math.Round(h);
            }
            catch (Exception) { return 0; }
        }
    }

    /// <summary>Comunicação com o servidor Nexus.</summary>
    public static class Canal
    {
        /// <summary>JSON sem escapar acentos — o servidor espera UTF-8.</summary>
        public static string Json(object obj)
        {
            var ser = new JavaScriptSerializer { MaxJsonLength = int.MaxValue };
            return ser.Serialize(obj);
        }

        /// <summary>
        /// POST simples com HttpWebRequest.
        ///
        /// `HttpClient` não existe no .NET 4.0 sem referência extra, e o
        /// `csc.exe` do Framework não traz. `HttpWebRequest` está em toda
        /// instalação.
        /// </summary>
        public static string Post(string url, string corpo, string token)
        {
            var req = (HttpWebRequest)WebRequest.Create(url);
            req.Method = "POST";
            req.ContentType = "application/json; charset=utf-8";
            req.Timeout = 30000;
            req.ReadWriteTimeout = 30000;
            req.UserAgent = "NexusAgente/1.0";
            if (token != null) req.Headers["Authorization"] = "Bearer " + token;

            byte[] bytes = Encoding.UTF8.GetBytes(corpo);
            req.ContentLength = bytes.Length;
            using (var s = req.GetRequestStream()) s.Write(bytes, 0, bytes.Length);

            try
            {
                using (var resp = (HttpWebResponse)req.GetResponse())
                using (var leitor = new StreamReader(resp.GetResponseStream(), Encoding.UTF8))
                    return leitor.ReadToEnd();
            }
            catch (WebException ex)
            {
                // O corpo do erro traz a razão ("ativo_nao_cadastrado"), e é
                // isso que precisa ser mostrado — não "erro 404".
                if (ex.Response != null)
                    using (var leitor = new StreamReader(ex.Response.GetResponseStream(), Encoding.UTF8))
                        throw new Exception(leitor.ReadToEnd());
                throw;
            }
        }
    }

    public static class Programa
    {
        /// <summary>Lê `--chave valor` da linha de comando.</summary>
        private static string Opcao(string[] args, string nome)
        {
            for (int i = 0; i < args.Length - 1; i++)
                if (string.Equals(args[i], "--" + nome, StringComparison.OrdinalIgnoreCase))
                    return args[i + 1];
            return null;
        }

        public static int Main(string[] args)
        {
            string modo = args.Length > 0 ? args[0].ToLowerInvariant() : "coletar";

            // `--servico` é como o Windows inicia este executável. Sem a flag,
            // ele se comporta como console — necessário para os modos
            // `coletar`, `registrar` e `enviar` durante a instalação.

            if (modo == "--servico" || modo == "-servico")
            {
                EntradaServico.Rodar();
                return 0;
            }

            // Sem argumento = bandeja. E o que roda no logon do usuario.
            if (args.Length == 0)
            {
                // Antes de abrir: garante a tarefa que faz o agente subir
                // elevado no proximo logon. Aqui a bandeja ja tem
                // administrador — o unico contexto em que isso funciona.
                GarantirTarefaLogon();
                return EntradaBandeja.Iniciar();
            }

            if (modo == "bandeja" || modo == "tray") return EntradaBandeja.Iniciar();

            // Os modos abaixo precisam de console. `Preparar` anexa ao console
            // do processo pai — funciona chamado do PowerShell, e nao abre
            // janela nenhuma se o binario for iniciado por duplo clique.
            if (modo == "coletar")
            {
                ConsoleSobDemanda.Preparar();
                return Comandos.Coletar();
            }

            if (modo == "registrar")
            {
                ConsoleSobDemanda.Preparar();
                return Comandos.Registrar(Opcao(args, "servidor"), Opcao(args, "codigo"));
            }


            if (modo == "software")
            {
                ConsoleSobDemanda.Preparar();
                var lista = ColetorSoftware.Coletar();
                Console.WriteLine(Canal.Json(
                    new Dictionary<string, object> { { "software", lista } }));
                return 0;
            }

            if (modo == "enviar-software")
            {
                ConsoleSobDemanda.Preparar();
                return Comandos.EnviarSoftware();
            }

            if (modo == "enviar")
            {
                ConsoleSobDemanda.Preparar();
                return Comandos.Enviar();
            }

            ConsoleSobDemanda.Preparar();
            Console.Error.WriteLine("Modo desconhecido: " + modo);
            Console.Error.WriteLine("Uso:");
            Console.Error.WriteLine("  agente.exe coletar");
            Console.Error.WriteLine("  agente.exe registrar --servidor URL --codigo CODIGO");
            Console.Error.WriteLine("  agente.exe enviar");
            Console.Error.WriteLine("  agente.exe bandeja          (ou sem argumento)");
            Console.Error.WriteLine("  agente.exe --servico        (uso do Windows)");
            return 2;
        }

        /// <summary>
        /// Garante a tarefa agendada que abre a bandeja elevada no logon.
        ///
        /// Chamada pela bandeja, que ja roda com administrador — e o unico
        /// contexto em que schtasks /rl highest funciona sem pedir senha.
        /// Falha silenciosa: sem a tarefa o agente ainda abre pelo atalho.
        /// </summary>
        internal static void GarantirTarefaLogon()
        {
            try
            {
                string exe = System.Reflection.Assembly.GetExecutingAssembly().Location;

                var inicio = new System.Diagnostics.ProcessStartInfo
                {
                    // ## Por que `cmd /c` e aspas escapadas
                    //
                    // `schtasks /tr` quebra o caminho no primeiro espaço, mesmo
                    // entre aspas simples: `/tr "C:\Program Files\...\agente.exe"`
                    // vira programa `C:\Program` e argumento `Files\...`.
                    //
                    // A forma aceita é com aspas **escapadas** dentro do valor:
                    //     /tr "\"C:\Program Files\...\agente.exe\""
                    //
                    // Passar por `cmd /c` preserva os escapes; deixando o .NET
                    // montar a linha, ele os normaliza e o problema volta.
                    FileName = "cmd.exe",
                    Arguments = "/c schtasks /create /f /tn \"Nexus Agente\" /tr \"\\\""
                        + exe + "\\\"\" /sc onlogon /rl highest",
                    CreateNoWindow = true,
                    UseShellExecute = false,
                    RedirectStandardOutput = true,
                    RedirectStandardError = true,
                };

                using (var p = System.Diagnostics.Process.Start(inicio))
                {
                    p.StandardOutput.ReadToEnd();
                    p.StandardError.ReadToEnd();
                    p.WaitForExit(8000);
                }
            }
            catch (Exception) { }
        }
    }
}
