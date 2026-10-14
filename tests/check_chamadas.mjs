/**
 * Chamadas a helpers POSICIONAIS feitas com objeto.
 *
 * ## O defeito que isto pega
 *
 * `emptyState` é declarado assim:
 *
 *     export function emptyState(iconName, title, text)
 *
 * E uma tela chamava assim:
 *
 *     emptyState({ icon: "relatorios", titulo: "...", desc: "..." })
 *
 * O objeto ia para `iconName`, `title` ficava `undefined`, e a tela mostrava
 * **literalmente a palavra "undefined"** no lugar da mensagem.
 *
 * ## Por que nenhum guard pegou
 *
 * - `node --check` passa: é sintaxe válida;
 * - `check_dom` passa: as classes e a estrutura estavam certas;
 * - **o console fica limpo**: `undefined` interpolado numa template string é
 *   uma string perfeitamente válida. Nenhum erro, nenhum aviso.
 *
 * O defeito era **só visual** — e é por isso que ele chegou na tela.
 *
 * ## Como funciona
 *
 * Mantém a assinatura esperada de cada helper posicional. Se alguém chamar
 * com um objeto literal, acusa. É uma lista curta de propósito: só entram
 * helpers em que o erro é silencioso e visível para o usuário.
 */
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";

// Helper → quantos argumentos posicionais ele espera.
const POSICIONAIS = {
  emptyState: 3,
  // Acrescente aqui quando aparecer outro caso.
};

function arquivosJs(dir) {
  const saida = [];
  for (const nome of readdirSync(dir)) {
    const caminho = join(dir, nome);
    if (statSync(caminho).isDirectory()) saida.push(...arquivosJs(caminho));
    else if (nome.endsWith(".js")) saida.push(caminho);
  }
  return saida;
}

let falhas = 0;
let verificadas = 0;

for (const arquivo of arquivosJs("frontend/js")) {
  const linhas = readFileSync(arquivo, "utf8").split("\n");
  linhas.forEach((linha, i) => {
    for (const [helper, esperados] of Object.entries(POSICIONAIS)) {
      // A própria declaração não conta.
      if (linha.includes(`function ${helper}(`)) continue;

      const marca = `${helper}(`;
      let pos = linha.indexOf(marca);
      while (pos !== -1) {
        verificadas++;
        const resto = linha.slice(pos + marca.length).trimStart();
        if (resto.startsWith("{")) {
          falhas++;
          console.log(
            `  FALHA ${arquivo}:${i + 1}\n` +
            `        \`${helper}\` é POSICIONAL e espera ${esperados} argumentos,\n` +
            `        mas foi chamado com um objeto — os campos chegam undefined.\n` +
            `        Linha: ${linha.trim().slice(0, 70)}`
          );
        }
        pos = linha.indexOf(marca, pos + marca.length);
      }
    }
  });
}

if (falhas) {
  console.log(`\n${falhas} chamada(s) posicional(is) com objeto.`);
  process.exit(1);
}

const nomes = Object.keys(POSICIONAIS).join(", ");
console.log(
  `TODAS AS ${verificadas} CHAMADAS OK — ${nomes} usados na forma posicional.`
);
