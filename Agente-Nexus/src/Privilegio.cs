// =====================================================================
// Privilegio SeTcbPrivilege
// =====================================================================
//
// ## Por que isto existe
//
// `WTSQueryUserToken` **falha com ERROR_PRIVILEGE_NOT_HELD (1314)** se o
// processo nao tiver `SeTcbPrivilege` habilitado.
//
// Ser LocalSystem **nao basta**: o token do LocalSystem contem a privilegio,
// mas ela vem **desabilitada**. Um administrador interativo a tem ativa
// porque o UAC a concede; um servico nao.
//
// Sem este passo, `WTSQueryUserToken` sempre retorna false e a bandeja nunca
// abre — foi exatamente o sintoma.
//
// ## Como se habilita
//
// `AdjustTokenPrivileges` com o LUID de `SeTcbPrivilege`. O LUID e estavel
// em qualquer Windows, entao pode ser declarado direto em vez de procurado
// por nome.

using System;
using System.Runtime.InteropServices;

namespace AgenteNexus
{
    internal static class Privilegio
    {
        private const uint TOKEN_ADJUST_PRIVILEGES = 0x0020;
        private const uint TOKEN_QUERY = 0x0008;
        private const uint SE_PRIVILEGE_ENABLED = 0x00000002;

        /// <summary>LUID de SeTcbPrivilege. Igual em qualquer Windows.</summary>
        private static readonly long SE_TCB = 0x0000000000000007;

        [StructLayout(LayoutKind.Sequential)]
        private struct LUID
        {
            public uint LowPart;
            public int HighPart;
        }

        [StructLayout(LayoutKind.Sequential)]
        private struct LUID_AND_ATTRIBUTES
        {
            public LUID Luid;
            public uint Attributes;
        }

        [StructLayout(LayoutKind.Sequential)]
        private struct TOKEN_PRIVILEGES
        {
            public uint PrivilegeCount;
            public LUID_AND_ATTRIBUTES Privilege;
        }

        [DllImport("advapi32.dll", SetLastError = true)]
        private static extern bool OpenProcessToken(
            IntPtr ProcessHandle, uint DesiredAccess, out IntPtr TokenHandle);

        [DllImport("advapi32.dll", SetLastError = true)]
        private static extern bool AdjustTokenPrivileges(
            IntPtr TokenHandle, bool DisableAllPrivileges,
            ref TOKEN_PRIVILEGES NewState, uint BufferLength,
            IntPtr PreviousState, IntPtr ReturnLength);

        [DllImport("kernel32.dll")]
        private static extern IntPtr GetCurrentProcess();

        [DllImport("kernel32.dll")]
        private static extern bool CloseHandle(IntPtr hObject);

        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern uint GetLastError();

        /// <summary>
        /// Habilita `SeTcbPrivilege` no token do processo atual.
        ///
        /// Devolve string vazia em caso de sucesso, ou a descricao do erro —
        /// que vai para o log do servico, porque falha silenciosa aqui custou
        /// horas de investigacao.
        /// </summary>
        public static string HabilitarSeTcb()
        {
            IntPtr token = IntPtr.Zero;

            try
            {
                if (!OpenProcessToken(
                        GetCurrentProcess(),
                        TOKEN_ADJUST_PRIVILEGES | TOKEN_QUERY,
                        out token))
                {
                    return "OpenProcessToken falhou (erro " + GetLastError() + ")";
                }

                var estado = new TOKEN_PRIVILEGES();
                estado.PrivilegeCount = 1;
                estado.Privilege.Luid = new LUID
                {
                    LowPart = (uint)(SE_TCB & 0xFFFFFFFF),
                    HighPart = (int)(SE_TCB >> 32),
                };
                estado.Privilege.Attributes = SE_PRIVILEGE_ENABLED;

                if (!AdjustTokenPrivileges(
                        token, false, ref estado,
                        (uint)Marshal.SizeOf(typeof(TOKEN_PRIVILEGES)),
                        IntPtr.Zero, IntPtr.Zero))
                {
                    return "AdjustTokenPrivileges falhou (erro " + GetLastError() + ")";
                }

                // `AdjustTokenPrivileges` devolve TRUE mesmo quando nao alterou
                // nada: o erro fica em GetLastError. Conferir e obrigatorio.
                uint erro = GetLastError();
                if (erro != 0)
                {
                    return "SeTcbPrivilege nao concedida (erro " + erro + ")";
                }

                return "";
            }
            catch (Exception ex)
            {
                return "Excecao ao habilitar SeTcbPrivilege: " + ex.Message;
            }
            finally
            {
                if (token != IntPtr.Zero) CloseHandle(token);
            }
        }
    }
}
