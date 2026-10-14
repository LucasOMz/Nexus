/**
 * Varredura: funções chamadas com menos argumentos do que a assinatura exige.
 *
 * ## O que procura
 *
 * O caso do `emptyState` — `(iconName, title, text)` chamado com um objeto —
 * não era único: é uma **classe** de defeito, e o console fica limpo porque
 * `undefined` interpolado numa template string é uma string válida.
 *
 * ## O que a primeira versão errou
 *
 * A versão inicial acusou **292 ocorrências**, quase todas falsas:
 *
 * - `linha(rotulo, valor, extra = {})` chamado com 2 — **correto**: o 3º tem
 *   valor padrão, logo é opcional;
 * - chamadas **multi-linha** — a contagem por linha lia meia chamada;
 * - funções de **mesmo nome em arquivos diferentes** — `carregar` existe em
 *   vários, com aridades diferentes, e eram somadas numa só.
 *
 * **Guarda que acusa o que não é problema é pior que guarda nenhum**: ensina
 * quem lê a ignorá-lo. Por isso a versão corrigida conta apenas argumentos
 * **obrigatórios**, lê a chamada **inteira**, e mantém assinatura **por
 * arquivo**.
 *
 * ## Como usar
 *
 *     node tests/varredura_assinaturas.mjs            # relatório
 *     node tests/varredura_assinaturas.mjs --guardar  # sai 1 se houver falha
 */
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";

/** O corpo de uma função declarada no arquivo, para inspecionar os usos. */
function corpoDaFuncao(texto, nome) {
  const re = new RegExp(`(?:export\\s+)?(?:async\\s+)?function\\s+${nome}\\s*\\([^)]*\\)\\s*\\{`, "g");
  const m = re.exec(texto);
  if (!m) return "";
  let nivel = 0;
  for (let i = m.index + m[0].length - 1; i < texto.length; i++) {
    if (texto[i] === "{") nivel++;
    else if (texto[i] === "}") { nivel--; if (nivel === 0) return texto.slice(m.index + m[0].length, i); }
  }
  return texto.slice(m.index + m[0].length);
}

// Nomes de parâmetro que indicam, por si, que a função recebe um objeto.
const PARAM_DE_OBJETO =
  /^(opcoes|opções|opts|options|config|conf|dados|data|obj|params|props|attrs|atributos|meta|item|registro|body|payload)$/i;

// Aceitam número variável de argumentos.
const VARIAVEIS = new Set(["el", "cn", "join", "log", "toast", "Promise", "console"]);

function arquivosJs(dir) {
  const saida = [];
  for (const nome of readdirSync(dir)) {
    const caminho = join(dir, nome);
    if (statSync(caminho).isDirectory()) saida.push(...arquivosJs(caminho));
    else if (nome.endsWith(".js")) saida.push(caminho);
  }
  return saida;
}

/**
 * Assinaturas por arquivo: nome → { obrigatorios, total, nomes, objetoOk }.
 *
 * `obrigatorios` desconta os parâmetros COM VALOR PADRÃO (`extra = {}`), que
 * são opcionais na chamada — era a maior fonte de falso positivo.
 */
function assinaturasDoArquivo(texto) {
  const mapa = new Map();
  const re = /(?:export\s+)?(?:async\s+)?function\s+(\w+)\s*\(([^)]*)\)/g;
  let m;
  while ((m = re.exec(texto))) {
    const nome = m[1];
    const bruto = m[2].trim();
    if (!bruto) { mapa.set(nome, { obrigatorios: 0, total: 0, nomes: [], objetoOk: true }); continue; }

    // Divide por vírgula no nível zero (evita quebrar dentro de `{}` ou `()`).
    const partes = [];
    let nivel = 0, atual = "";
    for (const c of bruto) {
      if ("([{".includes(c)) nivel++;
      else if (")]}".includes(c)) nivel--;
      if (c === "," && nivel === 0) { partes.push(atual); atual = ""; continue; }
      atual += c;
    }
    if (atual.trim()) partes.push(atual);

    const nomes = partes.map((p) => p.trim().split(/[=\s:]/)[0].replace(/^\.\.\./, ""));
    const obrigatorios = partes.filter((p) => !p.includes("=") && !p.includes("...")).length;
    const objetoOk = partes.length === 1 && PARAM_DE_OBJETO.test(nomes[0]);

    const anterior = mapa.get(nome);
    if (!anterior || obrigatorios > anterior.obrigatorios) {
      mapa.set(nome, { obrigatorios, total: partes.length, nomes, objetoOk });
    }
  }
  return mapa;
}

/**
 * Lê uma chamada a partir do `(` e devolve quantos argumentos tem e se o
 * primeiro é um objeto literal.
 *
 * Percorre o texto INTEIRO — não só a linha — para funcionar com chamadas
 * escritas em várias linhas, que era o segundo falso positivo.
 */
function lerChamada(texto, posAbre) {
  let nivel = 0, args = 0, i = posAbre;
  let emString = null, primeiroNaoEspaco = null;
  let houveConteudo = false;
  // O `(` de abertura da PRÓPRIA chamada não incrementa o nível — só ele.
  //
  // Sem esta trava, `f(g(x), "y")` tratava o `(` de `g` como se fosse a
  // abertura de `f`: o `)` de `g` descia o nível para -1, e daí em diante a
  // contagem de vírgulas saía errada. Era a origem dos falsos positivos em
  // `numero(dinheiro(x), "rótulo")`.
  let abriu = false;

  for (; i < texto.length; i++) {
    const c = texto[i];
    const ant = texto[i - 1];

    if (emString) {
      if (c === emString && ant !== "\\") emString = null;
      continue;
    }
    if (c === "/" && texto[i + 1] === "*") { const fim = texto.indexOf("*/", i); i = fim === -1 ? texto.length : fim + 1; continue; }
    if (c === "/" && texto[i + 1] === "/") { const fim = texto.indexOf("\n", i); i = fim === -1 ? texto.length : fim; continue; }
    if (c === '"' || c === "'" || c === "`") { emString = c; if (primeiroNaoEspaco === null) primeiroNaoEspaco = c; houveConteudo = true; continue; }

    if (c === "(") {
      if (!abriu) { abriu = true; continue; }   // a abertura da chamada
      nivel++; houveConteudo = true; continue;
    }
    if (c === "[" || c === "{") { nivel++; if (primeiroNaoEspaco === null) primeiroNaoEspaco = c; houveConteudo = true; continue; }
    if (c === ")" || c === "]" || c === "}") {
      if (c === ")" && nivel === 0 && abriu) { i++; break; }
      nivel--; continue;
    }
    if (c === "," && nivel === 0) { args++; houveConteudo = false; primeiroNaoEspaco = null; continue; }
    if (!/\s/.test(c)) { if (primeiroNaoEspaco === null) primeiroNaoEspaco = c; houveConteudo = true; }
  }
  if (houveConteudo || args > 0) args++;
  return { total: args, primeiro: primeiroNaoEspaco, fim: i };
}

const guardar = process.argv.includes("--guardar");
const arquivos = arquivosJs("frontend/js");

const problemas = [];
let verificadas = 0;
let funcoes = 0;

for (const arq of arquivos) {
  const texto = readFileSync(arq, "utf8");
  const assin = assinaturasDoArquivo(texto);
  funcoes += assin.size;

  for (const [nome, info] of assin) {
    if (VARIAVEIS.has(nome) || info.obrigatorios === 0) continue;

    const re = new RegExp(`(?<![\\w.$])${nome}\\s*\\(`, "g");
    let m;
    while ((m = re.exec(texto))) {
      const posAbre = m.index + m[0].length - 1;
      // A própria declaração.
      //
      // O teste anterior era `/function\s+\w+\s*$/` sobre o texto ANTERIOR —
      // mas esse texto termina em `function `, sem o nome (o nome é
      // justamente o que casa agora). O padrão nunca fechava, e a varredura
      // reportava cada `function foo(...)` como se fosse uma chamada errada.
      // Era daí que vinha boa parte dos 51.
      if (/function\s*$/.test(texto.slice(Math.max(0, m.index - 24), m.index))) continue;
      if (/[\w$.]\s*\.\s*$/.test(texto.slice(Math.max(0, m.index - 14), m.index))) continue;

      const { total, primeiro } = lerChamada(texto, posAbre);
      verificadas++;

      const linha = texto.slice(0, m.index).split("\n").length;
      const trecho = texto.split("\n")[linha - 1].trim().slice(0, 70);

      const objetoIndevido = primeiro === "{" && !info.objetoOk;
      const faltam = total < info.obrigatorios;

      if (objetoIndevido || faltam) {
        // --- O parâmetro ausente é usado SEM guarda? -------------------
        //
        // Este código trata argumento opcional por **checagem de falso**, e
        // não por valor padrão:
        //
        //     function pintarModo(loginAd, nomeAd) {
        //       ... `${nomeAd ? ` — ${nomeAd}` : ""}`   ← ausente é ok
        //
        // Chamar com menos argumentos, nesses casos, é **uso correto** — e
        // foi o que fez a varredura acusar 45 problemas que não existem.
        //
        // O que quebra de verdade é o parâmetro interpolado DIRETO, sem
        // teste — como era o `title` do `emptyState`, que virava a palavra
        // "undefined" na tela.
        const corpo = corpoDaFuncao(texto, nome);
        const faltantes = info.nomes.slice(total);
        const desprotegidos = faltantes.filter((p) => {
          if (!p) return false;
          const re = new RegExp(`\\b${p}\\b`, "g");
          let u;
          while ((u = re.exec(corpo))) {
            // A janela ao redor do uso: pega `p ?`, `p ||`, `?? p`, `p &&`.
            const janela = corpo.slice(Math.max(0, u.index - 24), u.index + p.length + 12);
            const guardado = /(\?\?|\|\||&&|\?)/.test(janela) || /if\s*\(\s*$/.test(janela);
            if (!guardado) return true;
          }
          return false;
        });

        if (desprotegidos.length || objetoIndevido) {
          problemas.push({
            arq, linha, nome, total,
            obrigatorios: info.obrigatorios, nomes: info.nomes,
            objetoIndevido, faltam, trecho,
            desprotegidos,
          });
        }
      }
    }
  }
}

// ---------------------------------------------------------------------------
if (guardar) {
  if (problemas.length) {
    console.log(`${problemas.length} chamada(s) com menos argumentos do que a assinatura exige:\n`);
    for (const p of problemas) {
      const porque = p.objetoIndevido
        ? `recebe objeto, mas espera \`${p.nomes[0]}\``
        : `exige ${p.obrigatorios} (${p.nomes.slice(0, p.obrigatorios).join(", ")}), recebeu ${p.total}`;
      console.log(`  ${p.arq}:${p.linha}  ${p.nome}() — ${porque}`);
      console.log(`        ${p.trecho}`);
    }
    process.exit(1);
  }
  console.log(`Assinaturas OK — ${verificadas} chamadas conferidas em ${funcoes} funções.`);
  process.exit(0);
}

// --- relatório --------------------------------------------------------------
console.log(`Funções analisadas: ${funcoes}`);
console.log(`Chamadas conferidas: ${verificadas}`);
console.log();

if (!problemas.length) {
  console.log("Nenhuma chamada com menos argumentos do que a assinatura exige.");
} else {
  const porFuncao = new Map();
  for (const p of problemas) {
    const chave = `${p.arq}|${p.nome}`;
    if (!porFuncao.has(chave)) porFuncao.set(chave, []);
    porFuncao.get(chave).push(p);
  }

  console.log(`${problemas.length} ocorrência(s), em ${porFuncao.size} função(ões):`);
  console.log();
  for (const [, lista] of [...porFuncao].sort((a, b) => b[1].length - a[1].length)) {
    const p0 = lista[0];
    const tipo = p0.objetoIndevido
      ? `recebe OBJETO, mas espera \`${p0.nomes[0]}\``
      : `exige ${p0.obrigatorios} (${p0.nomes.slice(0, p0.obrigatorios).join(", ")})`;
    console.log(`  ${p0.nome}() — ${tipo}  [${lista.length}x em ${p0.arq}]`);
    for (const p of lista.slice(0, 3)) console.log(`      :${p.linha}  ${p.trecho}`);
    if (lista.length > 3) console.log(`      ... e mais ${lista.length - 3}`);
    console.log();
  }
}
