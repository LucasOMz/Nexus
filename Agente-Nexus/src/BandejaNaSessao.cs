// =====================================================================
// O serviço abre a bandeja na sessão do usuário
// =====================================================================
//
// ## O problema
//
// Três caminhos foram tentados, e nenhum dá o que se quer:
//
//   chave Run              inicia no logon, mas SEM elevação — ou pede UAC
//                          toda vez, se o manifesto exige administrador
//
//   tarefa agendada        criada por SYSTEM, roda como SYSTEM na sessão 0.
//                          O ícone existe, mas ninguém vê
//
//   tarefa com /rl highest criada por SYSTEM, o principal é SYSTEM. Mesmo
//                          defeito: sessão 0
//
// ## A solução
//
// O serviço já roda como SYSTEM. Ele pega o **token do usuário logado** na
// sessão interativa (`WTSQueryUserToken`), duplica, e cria o processo da
// bandeja **naquela sessão** (`CreateProcessAsUser`).
//
// O processo herda a elevação do serviço — **admin, sem UAC**.
//
// ## Quando abre
//
//   * no start do serviço, se já houver alguém logado
//   * a cada ciclo, se a bandeja tiver sido fechada
//
// Isso substitui a chave Run e a tarefa agendada no instalador.
//
// =====================================================================

using System;
using System.Diagnostics;
using System.Runtime.InteropServices;

namespace AgenteNexus
{
    public static class BandejaNaSessao
    {
        private const uint TOKEN_DUPLICATE = 0x0002;
        private const uint TOKEN_QUERY = 0x0008;
        private const uint TOKEN_ASSIGN_PRIMARY = 0x0001;
        private const uint TOKEN_ADJUST_DEFAULT = 0x0080;
        private const uint TOKEN_ADJUST_SESSIONID = 0x0100;

        private const int SecurityImpersonation = 2;
        private const int TokenPrimary = 1;

        private const uint CREATE_UNICODE_ENVIRONMENT = 0x00000400;
        private const uint CREATE_NEW_CONSOLE = 0x00000010;

        [StructLayout(LayoutKind.Sequential)]
        private struct STARTUPINFO
        {
            public int cb;
            public string lpReserved;
            public string lpDesktop;
            public string lpTitle;
            public int dwX, dwY, dwXSize, dwYSize, dwXCountChars, dwYCountChars;
            public int dwFillAttribute, dwFlags;
            public short wShowWindow, cbReserved2;
            public IntPtr lpReserved2, hStdInput, hStdOutput, hStdError;
        }

        [StructLayout(LayoutKind.Sequential)]
        private struct PROCESS_INFORMATION
        {
            public IntPtr hProcess, hThread;
            public int dwProcessId, dwThreadId;
        }

        [DllImport("kernel32.dll")]
        private static extern int WTSGetActiveConsoleSessionId();

        [DllImport("wtsapi32.dll", SetLastError = true)]
        private static extern bool WTSQueryUserToken(int sessionId, out IntPtr phToken);

        [DllImport("advapi32.dll", SetLastError = true)]
        private static extern bool DuplicateTokenEx(
            IntPtr hExistingToken, uint dwDesiredAccess, IntPtr lpTokenAttributes,
            int ImpersonationLevel, int TokenType, out IntPtr phNewToken);

        [DllImport("advapi32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
        private static extern bool CreateProcessAsUser(
            IntPtr hToken, string lpApplicationName, string lpCommandLine,
            IntPtr lpProcessAttributes, IntPtr lpThreadAttributes,
            bool bInheritHandles, uint dwCreationFlags, IntPtr lpEnvironment,
            string lpCurrentDirectory, ref STARTUPINFO lpStartupInfo,
            out PROCESS_INFORMATION lpProcessInformation);

        [DllImport("userenv.dll", SetLastError = true)]
        private static extern bool CreateEnvironmentBlock(out IntPtr lpEnvironment, IntPtr hToken, bool bInherit);

        [DllImport("userenv.dll")]
        private static extern bool DestroyEnvironmentBlock(IntPtr lpEnvironment);

        [DllImport("kernel32.dll")]
        private static extern bool CloseHandle(IntPtr hObject);

        /// <summary>
        /// Já existe uma bandeja aberta em alguma sessão interativa?
        ///
        /// ## O bug que isto corrige
        ///
        /// Serviço e bandeja são o **mesmo executável** (gente.exe). A
        /// checagem antiga perguntava "existe processo agente?" — e o próprio
        /// serviço respondia que sim. Resultado: a condição nunca era falsa e
        /// a bandeja nunca abria.
        ///
        /// O que distingue os dois é a sessão: serviço roda na **0**, bandeja
        /// roda na sessão do usuário (1, 2, ...).
        /// </summary>
        public static bool JaRodando()
        {
            try
            {
                foreach (var p in Process.GetProcessesByName("agente"))
                {
                    if (p.SessionId != 0) return true;
                }
                return false;
            }
            catch (Exception) { return false; }
        }

        /// <summary>
        /// Abre a bandeja na sessão interativa, com a elevação do serviço.
        ///
        /// Devolve `true` se conseguiu. Falha quando não há ninguém logado —
        /// e aí não há sessão para onde abrir.
        /// </summary>
        public static string Abrir(string caminhoExe)
        {
            if (JaRodando()) return "";

            int sessao = WTSGetActiveConsoleSessionId();
            // 0xFFFFFFFF = nenhuma sessão de console ativa (ninguém logado).
            if (sessao == -1 || sessao == 0)
                return "sem sessao interativa ativa (usuario nao logado?)";

            IntPtr token = IntPtr.Zero;
            IntPtr tokenDuplicado = IntPtr.Zero;
            IntPtr ambiente = IntPtr.Zero;

            try
            {
                if (!WTSQueryUserToken(sessao, out token))
                    return "WTSQueryUserToken falhou (erro "
                        + Marshal.GetLastWin32Error()
                        + ") — SeTcbPrivilege habilitada?";

                if (!DuplicateTokenEx(
                        token, TOKEN_ASSIGN_PRIMARY | TOKEN_DUPLICATE | TOKEN_QUERY
                               | TOKEN_ADJUST_DEFAULT | TOKEN_ADJUST_SESSIONID,
                        IntPtr.Zero, SecurityImpersonation, TokenPrimary,
                        out tokenDuplicado))
                    return "DuplicateTokenEx falhou (erro "
                        + Marshal.GetLastWin32Error() + ")";

                CreateEnvironmentBlock(out ambiente, tokenDuplicado, false);

                var inicio = new STARTUPINFO();
                inicio.cb = Marshal.SizeOf(typeof(STARTUPINFO));
                // "winsta0\default" = a área de trabalho do usuário.
                inicio.lpDesktop = "winsta0\\default";

                PROCESS_INFORMATION info;
                bool ok = CreateProcessAsUser(
                    tokenDuplicado, caminhoExe, "\"" + caminhoExe + "\"",
                    IntPtr.Zero, IntPtr.Zero, false,
                    CREATE_UNICODE_ENVIRONMENT | CREATE_NEW_CONSOLE,
                    ambiente, null, ref inicio, out info);

                if (ok)
                {
                    CloseHandle(info.hProcess);
                    CloseHandle(info.hThread);
                    return "";
                }

                return "CreateProcessAsUser falhou (erro "
                    + Marshal.GetLastWin32Error() + ")";
            }
            catch (Exception) { return ""; }
            finally
            {
                if (ambiente != IntPtr.Zero) DestroyEnvironmentBlock(ambiente);
                if (tokenDuplicado != IntPtr.Zero) CloseHandle(tokenDuplicado);
                if (token != IntPtr.Zero) CloseHandle(token);
            }
        }
    }
}
