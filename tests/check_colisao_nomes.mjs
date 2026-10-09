// Colisão entre nome de PARÂMETRO e de FUNÇÃO interna.
//
// Em JavaScript, a declaração de função no corpo sobrescreve o parâmetro de
// mesmo nome. A chamada então vira recursão e o callback NUNCA executa —
// silenciosamente, sem erro no console.
//
// Foi exatamente o que fez o arraste da barra lateral reordenar na tela sem
// nunca gravar a ordem. Este teste impede que volte.
import fs from "node:fs";
import path from "node:path";

const RAIZ = new URL("../frontend/", import.meta.url);

function arquivosJs(dir) {
  const saida = [];
  for (const item of fs.readdirSync(dir, { withFileTypes: true })) {
    const alvo = new URL(item.name + (item.isDirectory() ? "/" : ""), dir);
    if (item.isDirectory()) saida.push(...arquivosJs(alvo));
    else if (item.name.endsWith(".js")) saida.push(alvo);
  }
  return saida;
}

let colisoes = 0;
const arquivos = arquivosJs(RAIZ).sort((a, b) => a.pathname.localeCompare(b.pathname));
console.log(`  varrendo ${arquivos.length} arquivos JavaScript...\n`);

for (const arquivo of arquivos) {
  const linhas = fs.readFileSync(arquivo, "utf8").split("\n");
  const rel = arquivo.pathname.split("/frontend/")[1];

  // Pilha de funções abertas, para saber quais parâmetros estão no escopo.
  const pilha = [];
  let profundidade = 0;

  linhas.forEach((linha, i) => {
    // A colisão é entre o NOME de uma função interna e o PARÂMETRO de uma
    // função que a contém — não com os parâmetros dela mesma.
    const m = /(?:^|\s)(?:async\s+)?function\s+(\w+)\s*\(([^)]*)\)/.exec(linha);
    if (m) {
      const [, nomeFuncao, params] = m;
      const externa = pilha.find((f) => f.params.includes(nomeFuncao));
      if (externa) {
        console.log(`  COLISAO ${rel}:${i + 1}`);
        console.log(`          function ${nomeFuncao}() tem o mesmo nome de um`);
        console.log(`          PARAMETRO de ${externa.nome}() (linha ${externa.linha})`);
        console.log("          -> o parametro fica inacessivel (recursao silenciosa)");
        colisoes++;
      }
      pilha.push({
        nome: nomeFuncao,
        linha: i + 1,
        profundidadeAtual: profundidade,
        params: params.split(",").map((p) => p.trim().split("=")[0].trim()).filter(Boolean),
      });
    }

    // Controle de profundidade: as funções fecham quando a chave fecha.
    const abre = (linha.match(/\{/g) || []).length;
    const fecha = (linha.match(/\}/g) || []).length;

    // Uma função termina quando a profundidade volta ao nível em que começou.
    while (pilha.length && profundidade + abre - fecha <= pilha[pilha.length - 1].profundidadeAtual) {
      pilha.pop();
    }
    profundidade += abre - fecha;
  });
}

if (colisoes) {
  console.log(`\n${colisoes} COLISAO(OES) DE NOME ENCONTRADA(S)`);
  process.exit(1);
}

// Prova de comportamento: com os nomes separados, o callback executa.
let callbackRodou = false;
function permitir(container, seletor, aoSoltar, chaveDe) {
  let arrastando = true;
  const limpar = () => { arrastando = false; };
  function finalizar() {
    if (!arrastando) { limpar(); return; }
    const ordem = ["a", "b"];
    limpar();
    aoSoltar(ordem);
  }
  return finalizar;
}
permitir(null, null, (o) => { callbackRodou = o.length === 2; }, null)();

console.log(`\nOK   nenhuma colisao de nome em ${arquivos.length} arquivos`);
if (!callbackRodou) {
  console.log("FALHA o callback do padrao correto nao executou");
  process.exit(1);
}
console.log("OK   o padrao correto entrega a ordem ao callback");
