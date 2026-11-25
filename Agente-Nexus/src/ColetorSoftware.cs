// =====================================================================
// Coleta de software instalado
// =====================================================================
//
// ## Onde os programas ficam
//
// Três lugares no registro, e os três são necessários:
//
//   HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall
//       programas 64 bits instalados para a máquina inteira
//
//   HKLM\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall
//       programas 32 bits em Windows 64 — é onde estão metade das coisas
//
//   HKCU\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall
//       o que foi instalado só para o usuário atual
//
// ## Por que NÃO `Win32_Product`
//
// É o caminho que aparece em toda busca. Ele **reconfigura cada MSI** ao ser
// consultado: o Windows revalida a instalação de todos os programas, o que
// leva **minutos** e pode disparar reparo silencioso em algumas máquinas.
//
// O registro é leitura de chave, instantânea.
//
// ## O que é descartado
//
// * entrada sem `DisplayName` — são componentes internos
// * `SystemComponent = 1` — atualizações e runtime que o Windows esconde
// * `ParentKeyName` presente — é patch de outro programa, não programa
//
// Sem esse filtro, uma máquina comum reporta 400 "programas", dos quais 200
// são atualizações do Office.

using System;
using System.Collections.Generic;
using Microsoft.Win32;

namespace AgenteNexus
{
    public static class ColetorSoftware
    {
        private const int MaxItens = 500;

        /// <summary>
        /// Lista os programas instalados.
        ///
        /// Devolve uma lista de dicionários com `nome`, `versao` e
        /// `fabricante` — o mesmo formato que o endpoint espera.
        /// </summary>
        public static List<Dictionary<string, object>> Coletar()
        {
            var vistos = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            var saida = new List<Dictionary<string, object>>();

            foreach (var raiz in Raizes())
            {
                if (raiz == null) continue;

                try
                {
                    foreach (string sub in raiz.GetSubKeyNames())
                    {
                        if (saida.Count >= MaxItens) break;

                        try
                        {
                            using (var chave = raiz.OpenSubKey(sub))
                            {
                                if (chave == null) continue;
                                var item = Ler(chave);
                                if (item == null) continue;

                                // A mesma entrada aparece nos dois hives em
                                // algumas instalações. Deduplicar aqui economiza
                                // banda; o servidor deduplica de novo.
                                string chaveDedup = item["nome"] + "|" + item["versao"];
                                if (!vistos.Add(chaveDedup)) continue;

                                saida.Add(item);
                            }
                        }
                        catch (Exception) { /* chave ilegível: segue */ }
                    }
                }
                catch (Exception) { /* hive inacessível: segue */ }
            }

            saida.Sort(delegate (Dictionary<string, object> a, Dictionary<string, object> b)
            {
                return string.Compare(
                    (string)a["nome"], (string)b["nome"], StringComparison.OrdinalIgnoreCase);
            });

            return saida;
        }

        private static IEnumerable<RegistryKey> Raizes()
        {
            yield return Abrir(Registry.LocalMachine,
                @"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall");

            yield return Abrir(Registry.LocalMachine,
                @"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall");

            yield return Abrir(Registry.CurrentUser,
                @"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall");
        }

        private static RegistryKey Abrir(RegistryKey raiz, string caminho)
        {
            try { return raiz.OpenSubKey(caminho); }
            catch (Exception) { return null; }
        }

        private static Dictionary<string, object> Ler(RegistryKey chave)
        {
            // Atualização e componente interno: o Windows esconde das listas.
            object componente = chave.GetValue("SystemComponent");
            if (componente != null && Convert.ToInt32(componente) == 1) return null;

            // Patch de outro programa — o pai é que interessa.
            if (chave.GetValue("ParentKeyName") != null) return null;

            string nome = Texto(chave, "DisplayName");
            if (string.IsNullOrEmpty(nome)) return null;

            var item = new Dictionary<string, object>();
            item["nome"] = nome;
            item["versao"] = Texto(chave, "DisplayVersion");
            item["fabricante"] = Texto(chave, "Publisher");
            return item;
        }

        private static string Texto(RegistryKey chave, string valor)
        {
            object bruto = chave.GetValue(valor);
            if (bruto == null) return "";
            string texto = bruto.ToString().Trim();
            return texto.Length > 200 ? texto.Substring(0, 200) : texto;
        }
    }
}
