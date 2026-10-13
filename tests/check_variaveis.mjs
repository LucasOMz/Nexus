/**
 * Toda variável usada numa view está declarada?
 *
 * ⚠️ **EM AJUSTE. NÃO É TRAVA — não está ligado em nenhum `check_*.mjs`.**
 *
 * ## O erro que ele existe para pegar
 *
 * `financeiro.js` usava `sw.titulos` sem nunca ter declarado `const sw`. O
 * `node --check` passou (é JavaScript válido), o guard de CSS passou, os 1187
 * testes passaram — e a tela quebrou com `sw is not defined`.
 *
 * ## Por que ainda não pode virar trava
 *
 * A varredura é textual, não é um analisador de escopo. Hoje ela acusa ~25
 * falsos positivos, quase todos no mesmo lugar: **getters e métodos de
 * objeto** (`get perms() { ... }`) e templates com interpolação aninhada.
 *
 * Um guard que acusa o que está certo é pior que guard nenhum: alguém o
 * desliga, ou passa a ignorá-lo — e ele deixa de pegar o erro de verdade.
 *
 * Para virar trava, falta tratar:
 *   1. `get nome()` / `set nome()` / `async nome()` em objeto literal
 *   2. template literal que contém `${}` com outra crase dentro
 *   3. `admin.js:229` e `cadastros.js:18` — ainda por diagnosticar
 *
 * ## Uso, enquanto isso
 *
 *     node tests/check_variaveis.mjs
 *
 * Serve como consulta manual: o ruído é conhecido, e um nome NOVO na lista
 * merece olhada.
 *
 * ## Como funciona
 *
 * Para cada arquivo, junta os nomes que existem (imports, declarações, 
 * parâmetros, laços, métodos) e compara com os usados como `nome.` ou
 * `nome(`. Falsos positivos são tratados por lista explícita, nunca
 * afrouxando a regra.
 */
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative } from "node:path";

const RAIZ = new URL("..", import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1");
const DIR = join(RAIZ, "frontend", "js");

/** Palavras da linguagem: aparecem antes de `(` mas não são variáveis. */
const PALAVRAS = new Set([
  "if", "for", "while", "switch", "catch", "return", "typeof", "instanceof",
  "new", "delete", "void", "in", "of", "do", "else", "try", "finally", "throw",
  "case", "break", "continue", "yield", "await", "async", "function", "class",
  "const", "let", "var", "import", "export", "default", "from", "super", "with",
  // Métodos chamados por engano quando o `nome.` é a própria propriedade
  "then", "catch", "map", "filter", "forEach", "find", "some", "every", "join",
]);

/** Nomes que existem sem declaração: linguagem e navegador. */
const GLOBAIS = new Set([
  // Linguagem
  "Math", "JSON", "Object", "Array", "String", "Number", "Boolean", "Date",
  "Promise", "Map", "Set", "RegExp", "Error", "TypeError", "Symbol", "BigInt",
  "Intl", "Reflect", "Proxy", "WeakMap", "WeakSet", "parseInt", "parseFloat",
  "isNaN", "isFinite", "encodeURIComponent", "decodeURIComponent", "structuredClone",
  "Infinity", "NaN", "undefined", "globalThis", "arguments",
  // Navegador
  "window", "document", "console", "localStorage", "sessionStorage", "navigator",
  "location", "history", "fetch", "Request", "Response", "Headers", "FormData",
  "URL", "URLSearchParams", "Blob", "File", "FileReader", "Image", "Audio",
  "HTMLElement", "Element", "Node", "Event", "CustomEvent", "AbortController",
  "setTimeout", "clearTimeout", "setInterval", "clearInterval",
  "requestAnimationFrame", "cancelAnimationFrame", "queueMicrotask",
  "matchMedia", "getComputedStyle", "alert", "confirm", "prompt", "print",
  "crypto", "performance", "indexedDB", "Notification", "ServiceWorker",
  "MediaRecorder", "BarcodeDetector", "CanvasRenderingContext2D",
  "TextEncoder", "TextDecoder", "DOMException", "CSS", "this", "self",
]);

function arquivosJs(dir) {
  const saida = [];
  for (const nome of readdirSync(dir)) {
    const caminho = join(dir, nome);
    if (statSync(caminho).isDirectory()) saida.push(...arquivosJs(caminho));
    else if (nome.endsWith(".js")) saida.push(caminho);
  }
  return saida;
}

/** Remove comentários e strings, para não confundir texto com código.
 *
 * ## Por que troca por espaços, e não apaga
 *
 * Apagar muda a contagem de linhas e de colunas — e aí o número de linha
 * reportado aponta para outro lugar do arquivo. Foi o que aconteceu na
 * primeira versão: `reporte.js:26` era acusado, e a linha 26 é `};`.
 *
 * Trocando cada caractere por espaço (menos `\n`), o texto some para a
 * análise e a posição continua exata.
 */
function limpar(fonte) {
  const esconder = (m) => m.replace(/[^\n]/g, " ");
  // Mantém os DELIMITADORES e esconde só o conteúdo. Sem isso, `from "x.js"`
  // vira `from      ` e o padrão de import não encontra mais nada — foi o que
  // fez o contador saltar de 93 para 395.
  const esconderMiolo = (abre, fecha) => (m) =>
    abre + " ".repeat(Math.max(0, m.length - 2)) + fecha;

  return fonte
    .replace(/\/\*[\s\S]*?\*\//g, esconder)
    .replace(/\/\/[^\n]*/g, esconder)
    .replace(/`(?:[^`\\]|\\.)*`/g, esconderMiolo("`", "`"))
    .replace(/"(?:[^"\\\n]|\\.)*"/g, esconderMiolo('"', '"'))
    .replace(/'(?:[^'\\\n]|\\.)*'/g, esconderMiolo("'", "'"));
}

/** Nomes que passam a existir no arquivo. */
function declarados(codigo) {
  const nomes = new Set();

  const juntar = (texto) => {
    if (!texto) return;
    for (const m of texto.matchAll(/[A-Za-z_$][\w$]*/g)) nomes.add(m[0]);
  };

  // import { a, b as c } from ... / import x from ...
  //
  // O caminho entre aspas já virou `""` em `limpar()` — por isso o padrão
  // aceita string VAZIA. Exigir conteúdo fazia todos os imports passarem
  // despercebidos, e o script acusava `el`, `api`, `ctx` como soltos.
  for (const m of codigo.matchAll(/import\s+([\s\S]*?)\s+from\s*["'][^"']*["']/g)) {
    juntar(m[1].replace(/\bas\b/g, " "));
  }
  // const/let/var — inclusive desestruturação
  for (const m of codigo.matchAll(/\b(?:const|let|var)\s+([\s\S]*?)(?:=|;|\))/g)) {
    juntar(m[1]);
  }
  // function nome(...) e (a, b) => 
  for (const m of codigo.matchAll(/function\s*\*?\s*([\w$]*)\s*\(([^)]*)\)/g)) {
    nomes.add(m[1]);
    juntar(m[2]);
  }
  for (const m of codigo.matchAll(/\(([^()]*)\)\s*=>/g)) juntar(m[1]);
  for (const m of codigo.matchAll(/([\w$]+)\s*=>/g)) nomes.add(m[1]);
  // for (const x of ...) / catch (e)
  for (const m of codigo.matchAll(/\bfor\s*\(\s*(?:const|let|var)?\s*([\w$]+)/g)) nomes.add(m[1]);
  for (const m of codigo.matchAll(/\bcatch\s*\(\s*([\w$]+)/g)) nomes.add(m[1]);
  // class/atribuição simples de topo
  for (const m of codigo.matchAll(/\bclass\s+([\w$]+)/g)) nomes.add(m[1]);
  // Método de objeto: `{ logout() { ... } }` — o nome existe sem `const`.
  //
  // `nome(...)  {` é específico o bastante: chamada de função é seguida de
  // `;`, `,` ou `)`, nunca de um bloco. As palavras da linguagem já estão
  // fora, então `if (...) {` não entra.
  for (const m of codigo.matchAll(/(?:^|[{,;\n])\s*(?:async\s+)?([\w$]+)\s*\([^()]*\)\s*\{/g)) {
    nomes.add(m[1]);
  }

  nomes.delete("");
  return nomes;
}

/** Nomes usados como `nome.` ou `nome(` — os que precisam existir. */
function usados(codigo) {
  const nomes = new Map();
  const padrao = /(?<![\w$.])([A-Za-z_$][\w$]*)\s*(\.|\(|\[)/g;
  for (const m of codigo.matchAll(padrao)) {
    if (!nomes.has(m[1])) {
      const linha = codigo.slice(0, m.index).split("\n").length;
      nomes.set(m[1], linha);
    }
  }
  return nomes;
}

let problemas = 0;
let checados = 0;

for (const arquivo of arquivosJs(DIR)) {
  const bruto = readFileSync(arquivo, "utf8");
  const codigo = limpar(bruto);
  const existem = declarados(codigo);
  const rel = relative(RAIZ, arquivo).replace(/\\/g, "/");

  for (const [nome, linha] of usados(codigo)) {
    if (existem.has(nome) || GLOBAIS.has(nome) || PALAVRAS.has(nome)) continue;
    console.log(`  FALHA  ${rel}:${linha}  '${nome}' é usado mas não foi declarado`);
    problemas++;
  }
  checados++;
}

console.log("");
if (problemas === 0) {
  console.log(`  ${checados} arquivo(s) verificados, nenhuma variável solta.`);
  process.exit(0);
}
console.log(`  ${problemas} variável(is) não declarada(s) em ${checados} arquivo(s).`);
process.exit(1);
