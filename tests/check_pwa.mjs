/**
 * Verificação do PWA (service worker) — evita a regressão que causava
 * "carregando infinito".
 *
 * O problema: o SW chamava skipWaiting() + clients.claim() já na PRIMEIRA
 * instalação. Isso dispara `controllerchange`; o app recarregava a página; o
 * recarregamento abortava a instalação do SW; ele instalava de novo na carga
 * seguinte e recarregava outra vez — laço infinito de recarregamento (visto no
 * log do servidor como várias cargas completas da página seguidas).
 *
 * Uso: node tests/check_pwa.mjs
 */
import { readFileSync } from "node:fs";

const app = readFileSync(new URL("../frontend/app.js", import.meta.url), "utf8");
const sw = readFileSync(new URL("../frontend/sw.js", import.meta.url), "utf8");

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

// 1) O reload só pode acontecer em ATUALIZAÇÃO, nunca na primeira instalação.
checar("app.js detecta se a página já era controlada",
  /jaControlado\s*=\s*Boolean\(navigator\.serviceWorker\.controller\)/.test(app));

checar("controllerchange só recarrega quando já havia controle",
  /controllerchange[\s\S]{0,220}if\s*\(!jaControlado\s*\|\|\s*recarregou\)\s*return/.test(app));

checar("recarrega no máximo uma vez por carga",
  /let\s+recarregou\s*=\s*false/.test(app));

// 2) A API nunca deve ser cacheada (resposta é do usuário e muda o tempo todo).
const trechoFetch = sw.slice(sw.indexOf('addEventListener("fetch"'));
checar("sw.js não guarda /api/ no cache",
  /if\s*\(!isApi\s*&&\s*res\s*&&\s*res\.ok\)/.test(trechoFetch));

checar("sw.js responde erro claro quando a API está offline",
  /if\s*\(isApi\)\s*\{[\s\S]{0,220}503/.test(trechoFetch));

// 3) Cache versionado: trocar a versão é o que descarta o cache antigo.
checar("sw.js tem VERSION", /const VERSION = "v\d+"/.test(sw));

// 4) A versão do app e a do SW andam juntas (evita cache preso numa versão).
const version = readFileSync(new URL("../frontend/js/version.js", import.meta.url), "utf8");
const swVersion = (sw.match(/const VERSION = "(v\d+)"/) || [])[1];
const jsVersion = (version.match(/SW_VERSION = "(v\d+)"/) || [])[1];
checar(`SW_VERSION do version.js casa com o sw.js (${jsVersion} / ${swVersion})`, swVersion === jsVersion);

console.log(falhas === 0 ? `\nTODOS OS ${total} CASOS PASSARAM` : `\n${falhas} DE ${total} FALHARAM`);
process.exit(falhas === 0 ? 0 : 1);
