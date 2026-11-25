// =====================================================================
// Console sob demanda
// =====================================================================
//
// ## O problema
//
// O agente precisa dos dois mundos:
//
//   bandeja  -> winexe (sem janela de console piscando)
//   registrar, enviar, coletar -> console (o tecnico precisa ver a saida)
//
// Um binario so pode ter um subsystem. Se for console, a bandeja abre uma
// janela preta junto. Se for winexe, os modos de console nao imprimem nada.
//
// ## A solucao
//
// O binario e `winexe`. Quando o modo pede console, ele **anexa ao console
// do processo que o chamou** (`AttachConsole(ATTACH_PARENT_PROCESS)`) e
// reconecta stdout/stderr nele.
//
// Chamado do PowerShell ou do cmd, a saida aparece normalmente. Chamado por
// duplo clique (sem console pai), nao aparece janela nenhuma.
//
// =====================================================================

using System;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;

namespace AgenteNexus
{
    public static class ConsoleSobDemanda
    {
        private const int ATTACH_PARENT_PROCESS = -1;

        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern bool AttachConsole(int processoId);

        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern bool AllocConsole();

        private static bool _pronto;

        /// <summary>
        /// Liga a saida de console, se houver um console para se ligar.
        ///
        /// Chamar duas vezes nao faz mal. Em ambiente sem console (duplo
        /// clique, servico), simplesmente nao faz nada — e o programa segue.
        /// </summary>
        public static void Preparar()
        {
            if (_pronto) return;
            _pronto = true;

            try
            {
                // Anexa ao console de quem chamou. Falha quando nao ha pai
                // (duplo clique, servico) — e isso e normal.
                if (!AttachConsole(ATTACH_PARENT_PROCESS))
                {
                    // Sem console pai: nao aloca um. Abrir uma janela preta
                    // do nada assustaria mais que ajudar.
                    return;
                }

                var saida = new StreamWriter(Console.OpenStandardOutput(), Encoding.UTF8)
                {
                    AutoFlush = true,
                };
                Console.SetOut(saida);

                var erro = new StreamWriter(Console.OpenStandardError(), Encoding.UTF8)
                {
                    AutoFlush = true,
                };
                Console.SetError(erro);
            }
            catch (Exception) { }
        }
    }
}
