/**
 * Verificação de contraste do tema (claro/escuro).
 *
 * Garante que nenhum texto fica preto no modo escuro — o problema relatado era
 * `<button>` sem `color` no CSS, que herda a cor nativa do navegador
 * (`buttontext` = preto) e ignora o tema.
 *
 * Uso: node tests/check_tema.mjs
 */
import { readFileSync } from "node:fs";

const css = readFileSync(new URL("../frontend/styles.css", import.meta.url), "utf8");
const js = ["../frontend/js/ui.js", "../frontend/js/label.js", "../frontend/js/charts.js",
  "../frontend/js/views/admin_auth.js", "../frontend/js/views/admin_backups.js",
  "../frontend/js/views/admin_etiquetas.js"]
  .map((p) => readFileSync(new URL(p, import.meta.url), "utf8"))
  .join("\n");

let falhas = 0;
let total = 0;

function checar(nome, condicao) {
  total++;
  if (condicao) {
    console.log(`OK   ${nome}`);
  } else {
    falhas++;
    console.error(`FALHOU ${nome}`);
  }
}

/** Extrai o bloco de um seletor (do `{` até o `}` correspondente). */
function bloco(seletor) {
  const i = css.indexOf(seletor);
  if (i < 0) return "";
  const inicio = css.indexOf("{", i);
  const fim = css.indexOf("}", inicio);
  return css.slice(inicio, fim);
}

// 1) Controles nativos precisam herdar a cor do tema.
checar("botões/inputs herdam a cor do tema",
  /button,\s*input,\s*select,\s*textarea\s*\{[^}]*color:\s*inherit/.test(css));

// 2) color-scheme nos dois temas (dropdown, scrollbar, calendário).
checar("color-scheme: light no tema claro", /color-scheme:\s*light/.test(css));
checar("color-scheme: dark no tema escuro", /color-scheme:\s*dark/.test(css));

// 3) Os cartões das telas iniciais definem a cor do texto.
checar(".inv-card define color", /color:/.test(bloco(".inv-card {")));
checar(".home-tile define color", /color:/.test(bloco(".home-tile {")));
checar("título do .inv-card em negrito", /\.inv-card h3\s*\{[^}]*font-weight:\s*700/.test(css));
checar("título do .home-tile em negrito", /\.home-tile h3\s*\{[^}]*font-weight:\s*700/.test(css));

// 4) Nada de preto fixo em texto no CSS.
const pretos = css.match(/color:\s*(black|#000000|#000)\b/gi) || [];
checar(`nenhuma cor preta fixa no CSS (encontradas: ${pretos.length})`, pretos.length === 0);

// 5) Cores de apoio têm versão clara e escura.
for (const variavel of ["--cor-aviso", "--cor-saida", "--cor-ok"]) {
  const ocorrencias = (css.match(new RegExp(`${variavel}:`, "g")) || []).length;
  checar(`${variavel} definida nos dois temas (${ocorrencias})`, ocorrencias >= 2);
}

// 6) Os arquivos JS não podem ter cor fixa de texto (usam variáveis do tema).
const fixas = js.match(/(color|background):\s*#[0-9A-Fa-f]{6}/g) || [];
checar(`nenhuma cor fixa de texto no JS (encontradas: ${fixas.length})`, fixas.length === 0);

// 7) O tema é aplicado no elemento raiz (onde o CSS espera).
const app = readFileSync(new URL("../frontend/js/state.js", import.meta.url), "utf8");
checar("tema aplicado em <html> via data-theme",
  /documentElement\.(dataset\.theme|setAttribute\(\s*["']data-theme)/.test(app));

console.log(falhas === 0 ? `\nTODOS OS ${total} CASOS PASSARAM` : `\n${falhas} DE ${total} FALHARAM`);
process.exit(falhas === 0 ? 0 : 1);
