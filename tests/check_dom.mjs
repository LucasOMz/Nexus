/**
 * Verificação do helper `el()` do frontend.
 *
 * REGRESSÃO QUE ISTO PROTEGE: `el("button", { disabled: false })` gerava
 * `disabled="false"` no HTML. Como `disabled` é atributo BOOLEANO, o navegador
 * desabilita o botão só pela presença do atributo — então os botões de
 * paginação (Ativos, Consumíveis, Movimentações, Manutenções, Auditoria)
 * ficavam permanentemente desabilitados e nunca avançavam de página.
 *
 * Uso (na raiz do projeto):
 *   node tests/check_dom.mjs
 */
const atributos = new Map();

class NoFalso {
  constructor(tag) {
    this.tagName = String(tag).toUpperCase();
    this._attrs = new Map();
    this._filhos = [];
    this._listeners = new Map();
    this.className = "";
    this.innerHTML = "";
  }
  setAttribute(k, v) { this._attrs.set(k, v == null ? "" : String(v)); }
  removeAttribute(k) { this._attrs.delete(k); }
  hasAttribute(k) { return this._attrs.has(k); }
  getAttribute(k) { return this._attrs.has(k) ? this._attrs.get(k) : null; }
  addEventListener(tipo, fn) { this._listeners.set(tipo, fn); }
  /** Dispara o listener registrado (para simular um clique). */
  disparar(tipo = "click") { const fn = this._listeners.get(tipo); if (fn) fn({ target: this }); }
  remove() { this._removido = true; }
  closest() { return null; }
  querySelectorAll() { return []; }
  append(...cs) { this._filhos.push(...cs); }
}

const bodyFalso = new NoFalso("body");

globalThis.document = {
  createElement: (tag) => new NoFalso(tag),
  createTextNode: (t) => ({ nodeType: 3, texto: t }),
  addEventListener() {},
  body: bodyFalso,
};

const { el, fmtMoney, fmtMoneyCurto } = await import("../frontend/js/ui.js");
const { barsH } = await import("../frontend/js/charts.js");
const { botaoEasterEgg, CLIQUE_ALVO } = await import("../frontend/js/easteregg.js");

let falhas = 0;
let casos = 0;

function verificar(descricao, condicao) {
  casos++;
  if (condicao) {
    console.log(`OK   ${descricao}`);
  } else {
    falhas++;
    console.log(`FALHA ${descricao}`);
  }
}

// 1) O caso do bug: booleano FALSO não pode virar atributo.
const habilitado = el("button", { disabled: false, class: "iconbtn" });
verificar("disabled: false NAO cria o atributo", !habilitado.hasAttribute("disabled"));

// 2) Booleano verdadeiro precisa desabilitar de fato.
const desabilitado = el("button", { disabled: true });
verificar("disabled: true cria o atributo", desabilitado.hasAttribute("disabled"));

// 3) Expressão de comparação, como no código real da paginação.
const pagina2 = el("button", { disabled: 2 <= 1 });
verificar("disabled: (2 <= 1) fica habilitado (botao VOLTAR)", !pagina2.hasAttribute("disabled"));

const ultima = el("button", { disabled: 251 >= 251 });
verificar("disabled: (251 >= 251) fica desabilitado (ultima pagina)", ultima.hasAttribute("disabled"));

// 4) Atributos booleanos vazios continuam funcionando (selected/required).
verificar("selected: '' cria o atributo", el("option", { selected: "" }).hasAttribute("selected"));
verificar("required: true cria o atributo", el("input", { required: true }).hasAttribute("required"));
verificar("required: '' cria o atributo", el("input", { required: "" }).hasAttribute("required"));

// 5) null/undefined não podem virar texto "null"/"undefined".
verificar("null nao cria o atributo", !el("input", { value: null }).hasAttribute("value"));
verificar("undefined nao cria o atributo", !el("input", { value: undefined }).hasAttribute("value"));

// 6) Atributos normais seguem iguais.
const normal = el("input", { type: "email", value: "a@b.com", maxlength: 20 });
verificar("atributo comum mantem o valor", normal.getAttribute("value") === "a@b.com");
verificar("atributo numerico vira texto", normal.getAttribute("maxlength") === "20");

// 7) class e html continuam nos caminhos próprios.
const comClasse = el("div", { class: "card", html: "<b>x</b>" });
verificar("class usa className", comClasse.className === "card");
verificar("html usa innerHTML", comClasse.innerHTML === "<b>x</b>");

// 8) Filhos nulos são ignorados (uso comum: condicional ? no : null).
const pai = el("div", {}, el("span"), null, undefined, "texto");
verificar("filhos nulos sao ignorados", pai._filhos.length === 2);

// 9) Easter egg: só abre depois de CLIQUE_ALVO cliques.
bodyFalso._filhos.length = 0;
const ovo = botaoEasterEgg();
verificar("botao do easter egg tem a classe propria", ovo.className === "easteregg-btn");
verificar("botao do easter egg fica fora do Tab", ovo.getAttribute("tabindex") === "-1");
verificar(`o alvo de cliques e ${CLIQUE_ALVO}`, CLIQUE_ALVO === 22);

for (let i = 0; i < CLIQUE_ALVO - 1; i++) ovo.disparar("click");
verificar(`${CLIQUE_ALVO - 1} cliques NAO abrem a janela`, bodyFalso._filhos.length === 0);

ovo.disparar("click");
verificar(`o ${CLIQUE_ALVO}o clique abre a janela`, bodyFalso._filhos.length === 1);

// O contador reinicia: mais CLIQUE_ALVO-1 cliques não devem reabrir sozinhos.
bodyFalso._filhos.length = 0;
for (let i = 0; i < CLIQUE_ALVO - 1; i++) ovo.disparar("click");
verificar("contador reinicia apos abrir", bodyFalso._filhos.length === 0);

// 10) Valor monetário curto: o valor completo escapava da caixa do gráfico.
verificar("milhares viram 'mil'", fmtMoneyCurto(123456).includes("mil"));
verificar("milhoes viram 'mi'", fmtMoneyCurto(12345678).includes("mi"));
verificar("bilhoes viram 'bi'", fmtMoneyCurto(1.23e10).includes("bi"));
verificar("valor pequeno sai completo", fmtMoneyCurto(850) === fmtMoney(850));
verificar("valor nulo nao quebra", fmtMoneyCurto(null) === "—");
verificar("texto curto e bem menor que o completo",
  fmtMoneyCurto(12345678.9).length <= fmtMoney(12345678.9).length * 0.75);

// 11) O gráfico de barras não pode deixar o valor sair da área desenhada.
//     (Era o bug: viewBox fixo de 300 com o texto começando em 286.)
function valoresDentroDoGrafico(dados) {
  const svg = barsH(dados);
  const largura = Number(svg.match(/viewBox="0 0 ([\d.]+) /)[1]);
  // Todas as coordenadas x dos textos de valor, com a mesma estimativa que o
  // próprio gráfico usa para dimensionar (6.4 unidades por caractere).
  const textos = [...svg.matchAll(/<text x="([\d.]+)"[^>]*class="chart-value">([^<]*)<\/text>/g)];
  return textos.every(([, x, txt]) => Number(x) + txt.length * 6.4 <= largura + 0.5);
}

const amostraCurta = [
  { rotulo: "Notebook", valor: 50, texto: "R$ 50,00" },
  { rotulo: "Desktop", valor: 30, texto: "R$ 30,00" },
];
verificar("barras com valores pequenos ficam dentro", valoresDentroDoGrafico(amostraCurta));

const amostraGigante = [
  { rotulo: "Notebook", valor: 12345678.9, texto: fmtMoneyCurto(12345678.9), completo: fmtMoney(12345678.9) },
  { rotulo: "Impressora", valor: 98765432.1, texto: fmtMoneyCurto(98765432.1), completo: fmtMoney(98765432.1) },
  { rotulo: "Monitor", valor: 1.23e10, texto: fmtMoneyCurto(1.23e10), completo: fmtMoney(1.23e10) },
];
verificar("barras com valores em milhoes ficam dentro", valoresDentroDoGrafico(amostraGigante));

// O gráfico precisa ter CRESCIDO para acomodar o texto maior.
const larguraCurta = Number(barsH(amostraCurta).match(/viewBox="0 0 ([\d.]+) /)[1]);
const larguraGigante = Number(barsH(amostraGigante).match(/viewBox="0 0 ([\d.]+) /)[1]);
verificar("largura do grafico se adapta ao texto", larguraGigante > larguraCurta);

// O valor exato continua acessível no tooltip da barra.
verificar("tooltip guarda o valor completo", barsH(amostraGigante).includes("12.345.678,90"));

// 12) Seleção em lote NÃO pode redesenhar a lista.
//     Redesenhar devolvia a rolagem ao topo, obrigando a pessoa a descer de
//     novo a cada item marcado.
const fs = await import("node:fs");
const fonteAtivos = fs.readFileSync(new URL("../frontend/js/views/ativos.js", import.meta.url), "utf8");

verificar("a selecao atualiza no lugar (atualizarSelecao)", fonteAtivos.includes("function atualizarSelecao()"));
verificar(
  "o clique na caixa NAO chama renderList",
  !/cx\.addEventListener\("change"[\s\S]{0,220}?renderList\(/.test(fonteAtivos),
);
verificar(
  "a caixa do cabecalho NAO chama renderList",
  !/caixaTodos\.addEventListener\("change"[\s\S]{0,260}?renderList\(/.test(fonteAtivos),
);
verificar("atualizarSelecao nao chama renderList", !/function atualizarSelecao[\s\S]{0,700}?renderList\(/.test(fonteAtivos));

// 13) Itens por página: 25 por padrão, com opção de 50.
verificar("padrao de 25 itens por pagina", /let pageSize = 25;/.test(fonteAtivos));
verificar("oferece 50 itens por pagina", /TAMANHOS_PAGINA = \[25, 50\]/.test(fonteAtivos));
verificar("a consulta usa pageSize", /size: pageSize/.test(fonteAtivos));

// 14) A linha da tabela precisa EXISTIR antes de ser guardada.
//     Guardar `tr` dentro da própria montagem lançava "Cannot access 'tr'
//     before initialization" e a lista inteira ficava em branco.
const posCriaTr = fonteAtivos.indexOf('const tr = el("tr"');
const posGuarda = fonteAtivos.indexOf("linhas.push({ tr");
verificar("a linha e criada antes de ser guardada", posCriaTr > 0 && posGuarda > posCriaTr);
verificar("a caixa da linha e criada antes da linha", posCriaTr > fonteAtivos.indexOf("const caixaLinha"));

// 15) Uma tela que quebra não pode deixar a página em branco.
const fonteApp = fs.readFileSync(new URL("../frontend/app.js", import.meta.url), "utf8");
const fonteInventario = fs.readFileSync(new URL("../frontend/js/views/inventario.js", import.meta.url), "utf8");
const fonteUiApi = fs.readFileSync(new URL("../frontend/js/api.js", import.meta.url), "utf8");
verificar("renderRoute protege a montagem da tela", /try \{\s*const resultado = view\(/.test(fonteApp));
verificar("existe tela de erro legivel", fonteApp.includes("function mostrarTelaQuebrada"));

// 16) Filtro e tamanho de página precisam ATUALIZAR a marcação visual.
//     O refresh redesenha só a lista; sem sincronizar a barra, o filtro
//     funcionava mas o botão continuava marcado na opção anterior.
verificar("existe atualizarToolbar", /function atualizarToolbar\(\)/.test(fonteAtivos));
verificar("atualizarToolbar sincroniza os chips de status",
  /chipsStatus\.forEach\(\(\[valor, botao\]\)[\s\S]{0,120}classList\.toggle\("selected"/.test(fonteAtivos));
verificar("atualizarToolbar sincroniza os botoes de tamanho",
  /botoesTamanho\.forEach\(\(\[valor, botao\]\)[\s\S]{0,120}classList\.toggle\("selected"/.test(fonteAtivos));
verificar("trocarStatus chama atualizarToolbar",
  /function trocarStatus[\s\S]{0,220}?atualizarToolbar\(\)/.test(fonteAtivos));
verificar("trocar tamanho chama atualizarToolbar",
  /pageSize = n;[\s\S]{0,120}?atualizarToolbar\(\)/.test(fonteAtivos));
verificar("os chips usam trocarStatus (nao atribuem direto)",
  !/onclick: \(\) => \{ filtroStatus =/.test(fonteAtivos));

// 17) O mesmo bug de filtro existia na tela de Manutenções.
const fonteManut = fs.readFileSync(new URL("../frontend/js/views/manutencoes.js", import.meta.url), "utf8");
verificar("manutencoes: existe atualizarToolbar", /function atualizarToolbar\(\)/.test(fonteManut));
verificar("manutencoes: chips sincronizam a marcacao",
  /chipsStatus\.forEach\(\(\[valor, botao\]\)[\s\S]{0,120}classList\.toggle\("selected"/.test(fonteManut));
verificar("manutencoes: trocarStatus chama atualizarToolbar",
  /function trocarStatus[\s\S]{0,200}?atualizarToolbar\(\)/.test(fonteManut));
verificar("manutencoes: chips nao atribuem filtroStatus direto",
  !/onclick: \(\) => \{ filtroStatus =/.test(fonteManut));
// Quem concluiu aparece no detalhe (preenchido pelo sistema).
verificar("manutencoes: detalhe mostra quem concluiu", fonteManut.includes("Concluída por"));

// 18) Concluir manutenção exige comentário.
verificar("manutencoes: existe janela de conclusao", /function concluirManutencao\(/.test(fonteManut));
verificar("manutencoes: concluir pede o comentario",
  /novoStatus === "concluida"\) return concluirManutencao/.test(fonteManut));
verificar("manutencoes: envio inclui comentario_conclusao",
  /status: "concluida",\s*\n\s*comentario_conclusao: texto/.test(fonteManut));
verificar("manutencoes: botao comeca desabilitado", /disabled: true/.test(fonteManut));
verificar("manutencoes: botao valida o texto", /if \(!texto\) \{ toast\(/.test(fonteManut));
verificar("manutencoes: concluir sem comentario e recusado localmente",
  /comentario\.value\.trim\(\)\.length === 0/.test(fonteManut));

// O dialog() precisa aceitar um botão já montado (para poder desabilitá-lo).
const fonteUi = fs.readFileSync(new URL("../frontend/js/ui.js", import.meta.url), "utf8");
verificar("ui: dialog aceita elemento proprio", /if \(a\.elemento\)/.test(fonteUi));

// 19) Abrir manutenção usa BUSCA do ativo, não lista suspensa.
//     O <select> trazia só os 200 primeiros ativos — com milhares cadastrados,
//     o resto ficava inalcançável.
const fonteSeletor = fs.readFileSync(new URL("../frontend/js/seletor_ativo.js", import.meta.url), "utf8");
verificar("existe o seletor de ativo com busca", fonteSeletor.includes("export function seletorDeAtivo"));
verificar("o seletor consulta o servidor", /api\.get\("\/ativos", \{ dominio: state\.dominio, search: alvo/.test(fonteSeletor));
verificar("a busca espera a digitacao parar", /setTimeout\(\(\) => buscar\(campo\.value\), ESPERA_MS\)/.test(fonteSeletor));
verificar("ignora resposta de busca antiga", fonteSeletor.includes("ultimaBusca !== alvo"));
verificar("existe cartao do ativo escolhido", fonteSeletor.includes("seletor-escolhido"));
verificar("da para trocar o ativo escolhido", fonteSeletor.includes("Trocar de ativo"));
verificar("manutencoes usa o seletor com busca", /const seletor = ativoFixo \? null : seletorDeAtivo\(\)/.test(fonteManut));
verificar("manutencoes NAO usa mais select com limite de 200",
  !/api\.get\("\/ativos", \{ dominio: state\.dominio, size: 200 \}\)/.test(fonteManut));
verificar("manutencoes valida o ativo escolhido", /if \(!idAtivo\) \{ toast\("Selecione o ativo na busca"\)/.test(fonteManut));
// Na leitura (ativo já identificado) o seletor não deve aparecer.
verificar("leitura de QR nao pede busca", /ativoFixo \? null : seletorDeAtivo/.test(fonteManut));

// 20) Clicar num ativo dentro do filtro do RELATÓRIO leva para Ativos já
//     filtrado e com o item DESTACADO — antes só navegava e a pessoa se perdia.
const fonteRel = fs.readFileSync(new URL("../frontend/js/views/relatorios.js", import.meta.url), "utf8");
verificar("relatorio passa o item escolhido na URL",
  /location\.hash = `#\/ativos\?busca=\$\{encodeURIComponent\(a\.patrimonio\)\}&destaque=\$\{a\.id\}`/.test(fonteRel));
verificar("relatorio nao navega mais sem contexto",
  !/location\.hash = "#\/ativos";/.test(fonteRel));

verificar("ativos le o destaque da URL", /function aplicarDestaqueDaUrl\(\)/.test(fonteAtivos));
verificar("ativos aplica o filtro vindo da URL", /filtroSearch = decodeURIComponent\(busca\[1\]\)/.test(fonteAtivos));
verificar("ativos guarda o id a destacar", /destaqueId = Number\(alvo\[1\]\)/.test(fonteAtivos));
verificar("ativos limpa a URL depois de aplicar", /history\.replaceState\(null, "", "#\/ativos"\)/.test(fonteAtivos));
verificar("ativos marca a linha com a classe de destaque",
  /class: destacado \? "row-destaque" : ""/.test(fonteAtivos));
verificar("ativos rola ate o item destacado", /linhaDestacada\.scrollIntoView/.test(fonteAtivos));
verificar("o destaque e aplicado antes de montar a tela",
  /aplicarDestaqueDaUrl\(\);/.test(fonteAtivos));

// 21) A barra lateral rápida mostra só os FAVORITOS.
//     Não existe lista de módulos "proibidos" de aparecer: qualquer aba
//     registrada em MODULOS pode ser favoritada, inclusive Administração e
//     Reporte de Erro. Uma lista de exceções foi o que causou o sintoma de
//     "favoritei e não apareceu".
verificar("nao existe lista de modulos excluidos da barra",
  !/FORA_DA_BARRA/.test(fonteApp));
verificar("a gaveta lista TODOS os modulos permitidos",
  /const permitidos = Object\.keys\(MODULOS\)\.filter\(\(m\) => state\.podeModulo\(m\)\);[\s\S]{0,600}drawer-item/.test(fonteApp));
verificar("a barra usa a MESMA fonte da gaveta",
  /barraLateral\.favoritosOrdenados\(permitidos\)/.test(fonteApp)
  && /const permitidos = Object\.keys\(MODULOS\)\.filter\(\(m\) => state\.podeModulo\(m\)\)/.test(fonteApp));

// 24) O acesso aos inventários é UM campo no cadastro do usuário.
//     Antes eram dois checkboxes soltos, que permitiam salvar sem nenhum
//     inventário — o usuário entrava e não enxergava nada.
const fonteAdmin = fs.readFileSync(new URL("../frontend/js/views/admin.js", import.meta.url), "utf8");

// 25) A ordem das abas da Administração é definida pelo usuário.
//     E o despacho precisa acompanhar — aba fora do despacho abriria em branco.
const ORDEM_ABAS = ["usuarios", "plantas", "dispositivos", "etiquetas", "checklist", "fotos", "auditoria", "backups", "auth", "ocs", "reconciliacao", "banco"];
const blocoAbas = /const abas = \[([\s\S]*?)\n  \];/.exec(fonteAdmin);
const abasNoArquivo = blocoAbas ? [...blocoAbas[1].matchAll(/\["(\w+)",/g)].map((m) => m[1]) : [];
verificar("abas da administracao na ordem pedida",
  JSON.stringify(abasNoArquivo) === JSON.stringify(ORDEM_ABAS));

const despacho = [...fonteAdmin.matchAll(/abaAtiva === "(\w+)"\)/g)].map((m) => m[1]);
verificar("toda aba tem seu despacho",
  ORDEM_ABAS.every((k) => despacho.includes(k)));
verificar("o despacho segue a mesma ordem das abas",
  JSON.stringify(despacho.filter((k) => ORDEM_ABAS.includes(k))) === JSON.stringify(ORDEM_ABAS));
verificar("nao sobrou o else generico escondendo a aba padrao",
  !/else await abaFotos\(alvo\)/.test(fonteAdmin));
verificar("cadastro de usuario tem o campo de inventarios",
  /<select name="inventarios" id="usuario-inventarios">/.test(fonteAdmin));
verificar("oferece Ambos / Somente TI / Somente Impressoras",
  /Ambos — TI e Impressoras/.test(fonteAdmin)
  && /Somente TI/.test(fonteAdmin) && /Somente Impressoras/.test(fonteAdmin));
verificar("'ambos' vira a lista completa no envio",
  /escolhaInv === "ambos" \? \["ti", "impressora"\] : \[escolhaInv\]/.test(fonteAdmin));
verificar("nao sobraram os checkboxes antigos de inventario",
  !/name="inv_\$\{/.test(fonteAdmin) && !/invAtuais/.test(fonteAdmin));
verificar("reporte aparece no menu inicial", /path: "reporte", modulo: "reporte"/.test(fonteInventario));

// 22) Arquivo protegido NÃO pode ser aberto por link/`src` direto.
//     O navegador não envia o cabeçalho Authorization nesses casos, e o
//     servidor responde 401 — era o "Credenciais inválidas ou expiradas" ao
//     tentar ver o print do reporte numa aba nova.
const fonteReporte = fs.readFileSync(new URL("../frontend/js/views/reporte.js", import.meta.url), "utf8");
verificar("reporte busca o print com token (api.blob)", /api\.blob\(`\/reportes\/\$\{r\.id\}\/imagem`\)/.test(fonteReporte));
verificar("reporte NAO usa src direto na API", !/src: `\/api\//.test(fonteReporte));
verificar("abrir em nova aba usa a URL local", /window\.open\(urlBlob, "_blank"\)/.test(fonteReporte));

verificar("api expoe o download autenticado (blob)", /async blob\(path\)/.test(fonteUiApi));
verificar("api.blob manda o Authorization", /headers\["Authorization"\] = "Bearer " \+ state\.access/.test(fonteUiApi));

const fonteManut2 = fs.readFileSync(new URL("../frontend/js/views/manutencoes.js", import.meta.url), "utf8");
verificar("anexo de manutencao tambem usa api.blob", /api\.blob\(`\/manutencoes\/\$\{m\.id\}\/anexos/.test(fonteManut2));
verificar("anexo NAO usa href direto na API", !/href: `\/api\/v1\/manutencoes/.test(fonteManut2));

// Nenhuma tela pode linkar arquivo protegido direto.
const telas = fs.readdirSync(new URL("../frontend/js/views", import.meta.url));
const suspeitas = telas.filter((f) => {
  const t = fs.readFileSync(new URL(`../frontend/js/views/${f}`, import.meta.url), "utf8");
  return /(href|src): `\/api\/v1\/(reportes|manutencoes|admin\/backups)/.test(t);
});
verificar("nenhuma tela linka arquivo protegido direto", suspeitas.length === 0);

// 23) Nunca concatenar o RESULTADO de el() com texto.
//     `el("div", {...}, "a") + " b"` vira "[object HTMLDivElement] b" na tela —
//     foi o que apareceu no relato do reporte ("teste[object HTMLDivElement] · tela: teste").
const arquivosJs = [];
(function varrer(dir) {
  for (const item of fs.readdirSync(dir, { withFileTypes: true })) {
    const caminho = new URL(`${dir.href.replace(/\/$/, "")}/${item.name}`);
    if (item.isDirectory()) varrer(caminho);
    else if (item.name.endsWith(".js")) arquivosJs.push(caminho);
  }
})(new URL("../frontend/js/", import.meta.url));

const concatenacoes = [];
for (const caminho of arquivosJs) {
  const linhas = fs.readFileSync(caminho, "utf8").split("\n");
  let profundidade = 0; // parênteses abertos e ainda não fechados
  for (let i = 0; i < linhas.length - 1; i++) {
    const a = linhas[i].trimEnd();
    const b = linhas[i + 1].trimStart();

    const abre = (linhas[i].match(/\(/g) || []).length;
    const fecha = (linhas[i].match(/\)/g) || []).length;
    profundidade += abre - fecha;

    // Só é bug quando a linha FECHA uma chamada completa (profundidade volta a
    // zero) e a seguinte começa com "+". Se ainda estamos DENTRO do el(...),
    // o "+" é só a continuação do texto e está correto.
    if (a.endsWith(")") && b.startsWith("+") && profundidade === 0 && !a.includes("icon(")) {
      concatenacoes.push(`${caminho.pathname.split("/js/")[1]}:${i + 1}`);
    }
  }
}
verificar(
  `nenhuma concatenacao de el() com texto${concatenacoes.length ? " -> " + concatenacoes.join(", ") : ""}`,
  concatenacoes.length === 0,
);

// E a linha do relato usa o texto DENTRO do elemento.
verificar("a linha do reporte monta o texto por dentro",
  /\+ `\$\{r\.tela \? ` · tela: \$\{r\.tela\}` : ""\}`\)/.test(fonteReporte));

console.log();

// 26) Autenticação (AD): os interruptores NÃO podem voltar para dentro da
//     grade de campos de texto — era isso que deixava a tela desorganizada.
const fonteAuth = fs.readFileSync(new URL("../frontend/js/views/admin_auth.js", import.meta.url), "utf8");
const fonteCss = fs.readFileSync(new URL("../frontend/styles.css", import.meta.url), "utf8");

const gruposDeCampos = [...fonteAuth.matchAll(/form-grid"[\s\S]*?<\/div>\s*<\/div>/g)].map((m) => m[0]);
verificar("nenhum interruptor dentro da grade de campos",
  gruposDeCampos.every((g) => !g.includes('type="checkbox"')));

const interruptoresAuth = [...fonteAuth.matchAll(/opcao\("(\w+)"/g)].map((m) => m[1]);
verificar("os 3 interruptores do AD usam a linha padronizada",
  ["ldap_ativo", "ldap_tls", "ldap_ignorar_certificado"]
    .every((k) => interruptoresAuth.includes(k)));

verificar("os campos do AD continuam existindo",
  ["ldap_servidor", "ldap_porta", "ldap_base_dn", "ldap_bind_dn", "ldap_bind_senha",
   "ldap_filtro_usuario"]
    .every((k) => fonteAuth.includes(`name="${k}"`))
  && interruptoresAuth.length === 3);

verificar("o estilo das opcoes existe no CSS",
  /\.opcao \{/.test(fonteCss) && /\.opcoes \{/.test(fonteCss) && /\.opcao-dica \{/.test(fonteCss));

verificar("a situacao do AD reage ao interruptor",
  /interruptorAd\?\.addEventListener\("change"/.test(fonteAuth));

// 27) O AD autentica; o sistema autoriza.
//     O cadastro busca o nome no diretório, mas nada é liberado sozinho — e o
//     acesso por grupo do AD deixou de existir.
const fonteAdminForm = fs.readFileSync(new URL("../frontend/js/views/admin.js", import.meta.url), "utf8");
verificar("cadastro tem o campo de usuario de rede",
  /name="login_ad"/.test(fonteAdminForm));
verificar("cadastro tem o botao de buscar no AD",
  /usuario-buscar-ad/.test(fonteAdminForm) && /\/admin\/config\/buscar-ad/.test(fonteAdminForm));
verificar("conta de rede nao exige senha no formulario",
  !/name="senha" \$\{isEdit \? "" : "required"\}/.test(fonteAdminForm));
verificar("a tela do AD nao tem mais grupo de acesso",
  !/ldap_grupo_acesso|ldap_grupo_admin/.test(fonteAuth));
verificar("a tela do AD nao provisiona mais ninguem",
  !/ldap_provisionar|ldap_grupos_aninhados/.test(fonteAuth));
verificar("a tela do AD explica quem libera o acesso",
  /O AD não libera mais o acesso/.test(fonteAuth));

// 28) Favoritos da barra lateral.
//     A estrela fica na GAVETA (as três barras), que lista todas as opções.
//     A barra lateral rápida mostra só o que foi favoritado.
const fonteBarra = fs.readFileSync(new URL("../frontend/js/barra_lateral.js", import.meta.url), "utf8");
verificar("existe o modulo de favoritos da barra lateral",
  /export function favoritos/.test(fonteBarra) && /export function ehFavorito/.test(fonteBarra));
verificar("favoritar grava no servidor, nao no navegador",
  /api\.put\("\/auth\/preferencias"/.test(fonteBarra) && !/localStorage/.test(fonteBarra));
verificar("o favorito acompanha o usuario (vem do state)",
  /state\.user\?\.barra_favoritos/.test(fonteBarra));
verificar("a ESTRELA fica na gaveta (tres barras)",
  /function estrelaFavorito\(key, aoMudar\)/.test(fonteApp)
  && /panel\.append\(el\("div", \{ class: "drawer-linha", "data-chave": key \}/.test(fonteApp));
verificar("a barra lateral rapida mostra so os favoritos",
  /favoritosOrdenados\(disponiveis\) \{[\s\S]{0,140}filter\(\(c\) => ehFavorito\(c\)\)/.test(fonteBarra)
  && /barraLateral\.favoritosOrdenados\(permitidos\)/.test(fonteApp));
verificar("clicar na estrela nao navega",
  /ev\.stopPropagation\(\)/.test(fonteApp));
verificar("a gaveta continua aberta ao favoritar",
  /estrelaFavorito\(key, \(\) => updateNav\(currentPath\)\)/.test(fonteApp));
verificar("o Menu inicial nao e favoritavel",
  /if \(key === "home"\) \{[\s\S]{0,60}continue;/.test(fonteApp));
verificar("barra vazia tem atalho para escolher",
  /nav-vazio/.test(fonteApp) && /icon\("star", 22\) \+ "<span>Adicionar<\/span>"/.test(fonteApp));
verificar("a estrela marcada fica amarela",
  /\.favorito\.marcado \{[\s\S]{0,120}#f5b301/.test(fonteCss));
verificar("o easter egg continua no rodape da barra",
  /cont\.append\(botaoEasterEgg\(\)\);/.test(fonteApp));

// 29) PADRONIZAÇÃO das abas.
//     Toda aba nova precisa: (a) estar em MODULOS, (b) ter card no menu
//     inicial, (c) poder ser favoritada. Assim "favoritei e não apareceu"
//     não volta a acontecer quando uma aba for criada.
const blocoModulos = /const MODULOS = \{([\s\S]*?)\n\};/.exec(fonteApp);
const chavesModulos = blocoModulos
  ? [...blocoModulos[1].matchAll(/^ {2}(\w+):/gm)].map((m) => m[1])
  : [];
const tilesDoMenu = [...fonteInventario.matchAll(/path: "(\w+)"/g)].map((m) => m[1]);

verificar("todo modulo esta registrado em MODULOS", chavesModulos.length >= 10);
verificar("todo modulo tem card no menu inicial",
  chavesModulos.every((c) => tilesDoMenu.includes(c)));
verificar("nenhum modulo esta fora do menu inicial",
  tilesDoMenu.every((c) => chavesModulos.includes(c)));
verificar("nenhum modulo e excluido de favoritar",
  !/FORA_DA_BARRA|naoFavoritavel|semFavorito/.test(fonteApp));
verificar("a gaveta itera MODULOS (aba nova entra sozinha)",
  /Object\.keys\(MODULOS\)\.filter\(\(m\) => state\.podeModulo\(m\)\)/.test(fonteApp));

// 30) Reordenar por "clique e segure".
//     Segurar o item o levanta numa janelinha flutuante; arrastar muda a ordem
//     e a ordem vale para os favoritos (é a barra que ela organiza).
const fonteOrdenar = fs.readFileSync(new URL("../frontend/js/ordenar.js", import.meta.url), "utf8");
verificar("existe o modulo de reordenacao",
  /export function permitirReordenar/.test(fonteOrdenar));
verificar("a gaveta permite reordenar",
  /ordenar\.permitirReordenar\(\s*panel,\s*"\.drawer-linha"/.test(fonteApp));
verificar("o item carrega a chave para a ordenacao",
  /class: "drawer-linha", "data-chave": key/.test(fonteApp));
verificar("so levanta DEPOIS de segurar (nao no clique)",
  /const SEGURAR_MS = \d+/.test(fonteOrdenar)
  && /timer = setTimeout\(\(\) => \{/.test(fonteOrdenar));
verificar("mover o dedo antes da hora cancela o arraste",
  /Math\.abs\(ev\.clientX - inicio\.x\) > TOLERANCIA_PX/.test(fonteOrdenar));
verificar("o item levantado vira uma janelinha flutuante",
  /clone\.classList\.add\("item-flutuante"\)/.test(fonteOrdenar)
  && /document\.body\.append\(clone\)/.test(fonteOrdenar));
verificar("clicar na estrela nao inicia arraste",
  /closest\("button\.favorito"\)/.test(fonteOrdenar));
verificar("a ordem e gravada no servidor",
  /barraLateral\.definirOrdem\(ordem\)/.test(fonteApp)
  && /export async function definirOrdem/.test(fonteBarra));
verificar("a ordem gravada e a da LISTA INTEIRA",
  /Grava a ordem da LISTA INTEIRA/.test(fonteApp)
  && !/const favs = ordem\.filter/.test(fonteApp));
verificar("o estilo da janelinha flutuante existe",
  /\.item-flutuante \{/.test(fonteCss) && /\.drawer-linha\.arrastando/.test(fonteCss));

// 31) A gaveta precisa ABRIR na ordem gravada.
//     Sem isso o usuário reordena, sai, volta e encontra tudo embaralhado —
//     a ordem valia só para a barra, não para a tela onde ele a define.
verificar("a gaveta abre na ordem salva",
  /const ordenados = barraLateral\.ordenarModulos\(permitidos\)/.test(fonteApp)
  && /\.\.\.ordenados\.map\(\(m\) => \[m, MODULOS\[m\]\.rotulo/.test(fonteApp));
verificar("a ordem fica em campo SEPARADO dos favoritos",
  /barra_ordem/.test(fonteBarra) && /export function ordem\(\)/.test(fonteBarra)
  && !/ordenarComFavoritosPrimeiro/.test(fonteApp));

// 32) Aba "Conexão com DBA" — SOMENTE VISUALIZAÇÃO.
//     A conexão é fixada quando o sistema sobe. Se pudesse ser trocada daqui e
//     estivesse errada, esta própria tela deixaria de abrir — e o sistema
//     perderia a única forma de se consertar pela interface.
const fonteBanco = fs.readFileSync(new URL("../frontend/js/views/admin_banco.js", import.meta.url), "utf8");
const routerBanco = fs.readFileSync(new URL("../app/routers/banco.py", import.meta.url), "utf8");

verificar("a aba fica depois de OCS Inventory",
  /\["ocs", "OCS Inventory"\],[\s\S]*?\["banco", "Conexão com DBA"\],/.test(fonteAdmin));
verificar("a tela do banco so LE (nenhuma escrita no frontend)",
  /api\.get\("\/admin\/banco"\)/.test(fonteBanco)
  && !/api\.(put|post|patch|delete)\(\s*"\/admin\/banco/.test(fonteBanco));
verificar("o backend nao expoe escrita de conexao",
  !/router\.(put|post|patch|delete)/.test(routerBanco));
verificar("a senha e mascarada pelo SQLAlchemy, nao a mao",
  /render_as_string\(hide_password=True\)/.test(routerBanco));
verificar("a tela explica por que nao altera",
  /não altera a conexão — de propósito/.test(fonteBanco)
  && /DATABASE_URL/.test(routerBanco));
verificar("os ouvintes do arraste ficam no DOCUMENTO",
  /document\.addEventListener\("pointermove", aoMover, true\)/.test(fonteOrdenar)
  && /document\.addEventListener\("pointerup", finalizar, true\)/.test(fonteOrdenar)
  // O nome NAO pode voltar a ser "aoSoltar": colidiria com o parametro e o
  // callback nunca rodaria (era o bug da ordem que nao salvava).
  && !/function aoSoltar\(\)/.test(fonteOrdenar));
verificar("o item na mao nao dispara navegacao ao soltar",
  /closest\?\.\("\.drawer-linha\.arrastando"\)/.test(fonteOrdenar));
verificar("os ouvintes sao removidos ao terminar",
  /function removerOuvintes\(\)/.test(fonteOrdenar)
  && /document\.removeEventListener\("pointermove", aoMover, true\)/.test(fonteOrdenar));

// 33) Atalho de troca de inventário na barra superior.
//     Só aparece para quem tem acesso aos dois — e o indicador nunca some.
verificar("o indicador de inventario virou botao",
  /const badge = seletorInventario\(\);/.test(fonteApp));
verificar("respeita o acesso do usuario",
  /const permitidos = state\.inventariosPermitidos\(\)/.test(fonteApp)
  && /if \(permitidos\.length < 2\) \{/.test(fonteApp));
verificar("sem acesso ao outro, fica so informativo",
  /botao\.classList\.add\("sem-troca"\)/.test(fonteApp));
verificar("a troca grava a escolha e recarrega",
  /function trocarInventario\(chave\) \{[\s\S]{0,140}state\.setDominio\(chave\)/.test(fonteApp)
  && /location\.reload\(\)/.test(fonteApp));
verificar("a opcao atual e marcada",
  /inv-opcao\$\{chave === atual \? " atual" : ""\}/.test(fonteApp));
verificar("fecha com ESC e clique fora",
  /document\.addEventListener\("keydown", porEsc, true\)/.test(fonteApp)
  && /document\.addEventListener\("click", fora, true\)/.test(fonteApp));
verificar("o estilo do seletor existe",
  /\.inv-seletor \{/.test(fonteCss) && /\.inv-opcao\.atual/.test(fonteCss));

// 34) O ícone do seletor vai pelo `html`, não como filho.
//     Um texto passado como filho de el() vira textContent, e a marcação do
//     SVG aparecia ESCRITA na tela em vez de desenhada.
verificar("o icone das opcoes vai pelo html",
  /html: iconeDe\(chave\)/.test(fonteApp));
verificar("nenhum icone passado como filho de el()",
  !/el\("[a-z]+", \{\}, icon\(/.test(fonteApp));

// 35) Trocar de inventário MANTÉM a tela atual.
//     Quem está em "Ativos" no TI quer ver "Ativos" nas impressoras — não
//     voltar ao menu a cada troca.
//
// O escopo é o CORPO da função, não o arquivo: o `logout()` também faz
// hash + reload, e uma checagem solta acabava apontando para ele.
const corpoTroca = /function trocarInventario\(chave\) \{([\s\S]*?)\n\}/.exec(fonteApp)?.[1] || "";
verificar("a troca preserva a tela atual",
  /location\.reload\(\)/.test(corpoTroca)
  && !/location\.hash = "#\/";\s*\n\s*location\.reload/.test(corpoTroca));
verificar("tela inexistente cai no menu",
  /if \(rota !== "home" && !MODULOS\[rota\]\)/.test(corpoTroca));

// 36) O FAB usa { label, icon, onClick } — em inglês.
//     Nomes trocados (icone/titulo/onclick) produzem um botão que APARECE e
//     não faz nada: sem ícone, sem rótulo, sem ação. Nada quebra, nada avisa.
//
// A checagem é sobre o ARGUMENTO INTEIRO da chamada, não linha a linha: numa
// primeira versão ela passava batido porque as propriedades costumam ficar na
// linha seguinte ao `setFab(`.
{
  const fs = await import("node:fs");
  const path = await import("node:path");
  const ruins = [];
  const varrer = (dir) => {
    for (const nome of fs.readdirSync(dir)) {
      const p = path.join(dir, nome);
      if (fs.statSync(p).isDirectory()) { varrer(p); continue; }
      if (!nome.endsWith(".js")) continue;

      const texto = fs.readFileSync(p, "utf8");
      const rel = path.relative(process.cwd(), p);
      // Captura o que vai entre os parênteses do setFab, atravessando linhas.
      const chamadas = texto.matchAll(/\.setFab\(([\s\S]{0,300}?)\);/g);
      for (const m of chamadas) {
        if (/\b(icone|titulo|onclick)\s*:/.test(m[1])) {
          const linha = texto.slice(0, m.index).split("\n").length;
          ruins.push(`${rel}:${linha}`);
        }
      }
    }
  };
  varrer("frontend");
  verificar("nenhum FAB com nome de propriedade errado", ruins.length === 0);
  if (ruins.length) console.log("       " + ruins.join(", "));
}

// 37) A busca da Administracao nao pode esconder aba nenhuma.
//     As abas sao agrupadas para apresentacao; se uma ficar de fora dos grupos,
//     ela sai da tela sem aviso. Aqui toda aba de `abas` precisa estar num
//     grupo — o fallback "Outros" existe como rede, nao como desculpa.
{
  const chaves = [...blocoAbas[1].matchAll(/\["(\w+)",/g)].map((m) => m[1]);
  const blocoGrupos = /const GRUPOS = \[([\s\S]*?)\n  \];/.exec(fonteAdmin);
  const nosGrupos = blocoGrupos
    ? [...blocoGrupos[1].matchAll(/"(\w+)"/g)].map((m) => m[1])
    : [];
  const faltando = chaves.filter((k) => !nosGrupos.includes(k));

  verificar("toda aba da administracao esta num grupo", faltando.length === 0);
  if (faltando.length) console.log("       fora dos grupos: " + faltando.join(", "));

  verificar("o fallback 'Outros' existe para aba nova",
    /\["Outros", semGrupo\]/.test(fonteAdmin));
  verificar("a busca filtra por rotulo E palavras-chave",
    // A variavel pode se chamar k ou chave: o que importa e a busca consultar
    // o rótulo E as palavras-chave da aba.
    /AJUDA_ABA\[/.test(fonteAdmin) && /busca\.value\.trim\(\)\.toLowerCase\(\)/.test(fonteAdmin));
  verificar("existe o campo de busca das abas",
    /class: "busca-abas"/.test(fonteAdmin));
  verificar("busca sem resultado avisa em vez de ficar vazio",
    /Nenhuma opção encontrada/.test(fonteAdmin));
}

﻿// 38) A administracao navega por CATEGORIAS, com as opcoes logo ABAIXO delas.
//     A barra comeca OCULTA: o painel abre limpo, so com as categorias, e as
//     opcoes aparecem quando se clica numa delas.
{
  const blocoGrupos = /const GRUPOS = \[([\s\S]*?)\n  \];/.exec(fonteAdmin);
  verificar("existem categorias declaradas", Boolean(blocoGrupos));
  verificar("as categorias ficam alinhadas no topo",
    /class: "categorias-admin"/.test(fonteAdmin));
  verificar("as opcoes ficam logo abaixo das categorias",
    /el\("div", \{ class: "tabs-wrap" \}, busca, filaCategorias, barra\)/.test(fonteAdmin)
    && !/document\.body\.append\(barra\)/.test(fonteAdmin));
  verificar("a barra comeca OCULTA",
    /let barraAberta = false;/.test(fonteAdmin)
    && /if \(barraAberta && categoriaAberta === titulo\)/.test(fonteAdmin));
  verificar("clicar na categoria abre as opcoes dela",
    /categoriaAberta = titulo;[\s\S]{0,80}barraAberta = true;/.test(fonteAdmin));
  verificar("clicar de novo na mesma categoria fecha a barra",
    /if \(barraAberta && categoriaAberta === titulo\) \{[\s\S]{0,120}barraAberta = false;/.test(fonteAdmin));
  verificar("a barra sobrevive ao redesenho",
    /let barraAberta = false;/.test(fonteAdmin)
    && /categoriaAberta = barraAberta \?/.test(fonteAdmin));
  verificar("so as opcoes da categoria ativa aparecem sem busca",
    /if \(!termo && titulo !== categoriaAberta\) continue;/.test(fonteAdmin));
  verificar("o trilho de opcoes rola de lado",
    /\.barra-trilho \{[\s\S]{0,220}overflow-x: auto/.test(fonteCss)
    && /\.opcao-admin \{[\s\S]{0,160}flex: 0 0 auto/.test(fonteCss));
  verificar("a barra some na impressao",
    /@media print \{[^}]*\.opcoes-admin \{ display: none/.test(fonteCss));
  verificar("durante a busca a categoria nao navega",
    /if \(termo\) return;/.test(fonteAdmin));
}
﻿
// 39) As caixas de marcacao dos templates de etiqueta seguem o padrao do site.
//     Antes, .switch so tinha "display:inline-flex" e .perm-item nao tinha base
//     nenhuma: o navegador desenhava a caixa nativa e a tela destoava do resto.
{
  const bloco = /\.switch,\s*\n\.perm-item \{([\s\S]*?)\n\}/.exec(fonteCss);
  verificar("marcacao de etiqueta tem base propria", Boolean(bloco));
  verificar("a marcacao usa borda e raio do sistema",
    Boolean(bloco) && /border-radius: var\(--shape-xs\)/.test(bloco[1])
    && /border: 1px solid var\(--md-sys-color-outline-variant\)/.test(bloco[1]));
  verificar("a marcacao marca o estado escolhido",
    /\.switch:has\(input:checked\),[\s\S]{0,120}\.perm-item\.checked \{[\s\S]{0,120}border-color: var\(--md-sys-color-primary\)/.test(fonteCss));
  verificar("a caixa tem tamanho e cor do sistema",
    /\.switch input\[type="checkbox"\],[\s\S]{0,140}width: 18px; height: 18px/.test(fonteCss)
    && /accent-color: var\(--md-sys-color-primary\)/.test(fonteCss));
  verificar("os campos ficam em grade, nao empilhados",
    /\.perm-grid \{[\s\S]{0,120}grid-template-columns: repeat\(auto-fill/.test(fonteCss));
}

// 40) Todo nome de ui.js usado num modulo esta IMPORTADO nele.
//     Esta classe de erro ja custou caro: o botao de tema existia, mas
//     `dialog` nao estava importado no app.js — clicar lancava ReferenceError
//     e NADA acontecia, sem mensagem nenhuma.
//     Verificacao estatica nao pega isso (o codigo esta sintaticamente certo),
//     so a execucao — e executar cada tela nao e viavel aqui.
{
  const fs = await import("node:fs");
  const path = await import("node:path");

  const FUNCOES = ["dialog", "toast", "icon", "el", "mostrarErro", "confirmSheet",
                   "emptyState", "skeleton", "fmtDate", "fmtMoney"];

  function varrerUi(dir) {
    const faltando = [];
    for (const nome of fs.readdirSync(dir)) {
      const p = path.join(dir, nome);
      if (fs.statSync(p).isDirectory()) { faltando.push(...varrerUi(p)); continue; }
      if (!nome.endsWith(".js")) continue;

      const c = fs.readFileSync(p, "utf8");
      const m = /import \{([^}]*)\} from "(?:\.\.\/ui\.js|\.\/js\/ui\.js)"/.exec(c);
      if (!m) continue;

      const importadas = new Set(m[1].split(",").map((s) => s.trim()));
      // Sem os comentários: um comentário pode CITAR `dialog()` justamente
      // para explicar por que não se usa ele — e a busca por texto casaria
      // com a explicação, não com o código.
      const corpo = c.slice(m.index + m[0].length)
        .replace(/\/\*[\s\S]*?\*\//g, "")
        .replace(/\/\/[^\n]*/g, "");
      for (const f of FUNCOES) {
        // Ignora `obj.f(` e `function f(`; pega so a chamada direta.
        const usada = new RegExp("(?<![\\w.])" + f + "\\s*\\(").test(corpo);
        if (usada && !importadas.has(f)) {
          faltando.push(path.relative(process.cwd(), p) + " -> " + f);
        }
      }
    }
    return faltando;
  }

  const faltando = varrerUi("frontend");
  verificar("todo nome de ui.js usado esta importado", faltando.length === 0);
  if (faltando.length) console.log("       " + faltando.join(" | "));
}

// 41) Toda classe CSS usada no JS existe em styles.css.
//     Esta trava existe por um motivo concreto: duas vezes um corte feito por
//     marcador de texto apagou o CSS do seletor de tema, e os botoes
//     renderizaram SEM ESTILO — sem erro, sem aviso, com as 181 travas
//     passando. Sintaxe e imports nao pegam isso: o JS esta correto, e o CSS
//     simplesmente nao existe.
{
  const fs = await import("node:fs");
  const path = await import("node:path");

  const css = fs.readFileSync("frontend/styles.css", "utf8");
  // Classes definidas no CSS (fora de comentarios, para nao casar exemplos).
  const cssSemComentario = css.replace(/\/\*[\s\S]*?\*\//g, "");
  const definidas = new Set(
    [...cssSemComentario.matchAll(/\.([a-zA-Z][\w-]*)/g)].map((m) => m[1])
  );

  // Classes usadas no JS: pega `class: "a b c"` e `class: \`a b ${x}\``.
  const faltandoCss = [];
  function varrerClasses(dir) {
    for (const nome of fs.readdirSync(dir)) {
      const p = path.join(dir, nome);
      if (fs.statSync(p).isDirectory()) { varrerClasses(p); continue; }
      if (!nome.endsWith(".js")) continue;

      const c = fs.readFileSync(p, "utf8");
      for (const m of c.matchAll(/class:\s*[`"]([^`"]*)[`"]/g)) {
        // Só a parte ANTES da primeira interpolação: dentro de `${...}` há
        // código (`chave === abaAtiva ? ...`), não nomes de classe.
        const literal = m[1].split("${")[0];
        for (const cls of literal.split(/\s+/)) {
          const limpo = cls.trim();
          // Ignora o que vem de interpolacao (${...}) e nomes muito curtos.
          if (!limpo || limpo.length < 3) continue;
          if (!/^[a-zA-Z][\w-]*$/.test(limpo)) continue;
          if (!definidas.has(limpo)) {
            faltandoCss.push(path.relative(process.cwd(), p) + " -> ." + limpo);
          }
        }
      }
    }
  }
  varrerClasses("frontend");

  const unicos = [...new Set(faltandoCss)];
  verificar("toda classe CSS usada no JS existe", unicos.length === 0);
  if (unicos.length) console.log("       " + unicos.slice(0, 8).join(" | "));
}
if (falhas) {
  console.log(`${falhas} DE ${casos} CASOS FALHARAM`);
  process.exit(1);
}
console.log(`TODOS OS ${casos} CASOS PASSARAM`);
