/**
 * Bootstrap da aplicação:
 *  - Login → Seleção de inventário → Menu inicial → módulos.
 *  - Shell M3 (topbar + Navigation Rail/Bottom Nav + FAB) com botão
 *    permanente de "voltar ao menu inicial" e botão de 3 barras (drawer).
 * @module app
 */
import { state, ROTULO_INVENTARIO } from "./js/state.js";
import { api, encerrarSessao, replayOfflineQueue } from "./js/api.js";
import { monitorarSessao } from "./js/sessao.js";
import { criarChatIa } from "./js/chat_ia.js";
import { Router } from "./js/router.js";
import { ctx } from "./js/context.js";
import { el, icon, toast, mostrarErro, dialog } from "./js/ui.js";
import { abrirBusca, ligarAtalhoDeBusca } from "./js/views/busca.js";
import { APP_VERSION } from "./js/version.js";
import { renderLogin } from "./js/views/login.js";
import { renderSelecao, renderHome } from "./js/views/inventario.js";
import { renderAtivos } from "./js/views/ativos.js";
import { renderImpressao } from "./js/views/impressao.js";
import { renderCalendario } from "./js/views/calendario.js";
import { renderKanban } from "./js/views/kanban.js";
import { renderMapa } from "./js/views/mapa.js";
import { renderReporte } from "./js/views/reporte.js";
import { renderProdutos } from "./js/views/produtos.js";
import { renderMovimentacoes } from "./js/views/movimentacoes.js";
import { renderContagens } from "./js/views/contagens.js";
import { renderFinanceiro } from "./js/views/financeiro.js";
import { renderContratos } from "./js/views/contratos.js";
import { renderDescarte } from "./js/views/descarte.js";
import { renderSoftware } from "./js/views/software.js";
import { renderEmprestimos } from "./js/views/emprestimos.js";
import { renderMonitor } from "./js/views/monitor_impressoras.js";
import { renderSeguranca } from "./js/views/seguranca.js";
import { renderManutencoes } from "./js/views/manutencoes.js";
import { renderScanner, stopScanner } from "./js/views/scanner.js";
import { renderRelatorios } from "./js/views/relatorios.js";
import { renderCadastros } from "./js/views/cadastros.js";
import { renderAdmin } from "./js/views/admin.js";
import { renderAvisos } from "./js/views/avisos.js";
import { botaoEasterEgg } from "./js/easteregg.js";
import * as barraLateral from "./js/barra_lateral.js";
import * as ordenar from "./js/ordenar.js";
import { conferirVersaoDoServidor } from "./js/versao_servidor.js";
import { sinoNotificacoes } from "./js/notificacoes.js";

const MODULOS = {
  ativos: { rotulo: "Ativos", icone: "ativos" },
  produtos: { rotulo: "Consumíveis", icone: "produtos" },
  movimentacoes: { rotulo: "Transferências", icone: "movimentacoes" },
  manutencoes: { rotulo: "Manutenções", icone: "manutencoes" },
  scanner: { rotulo: "Leitura", icone: "scanner" },
  contagens: { rotulo: "Contagens", icone: "contagens" },
  financeiro: { rotulo: "Financeiro", icone: "wallet" },
  contratos: { rotulo: "Contratos", icone: "contract" },
  descarte: { rotulo: "Certificado de descarte", icone: "certificado" },
  software: { rotulo: "Software e licenças", icone: "software" },
  emprestimos: { rotulo: "Empréstimos", icone: "loan" },
  monitor: { rotulo: "Monitor de impressoras", icone: "printerMonitor" },
  seguranca: { rotulo: "Segurança da conta", icone: "shield" },
  relatorios: { rotulo: "Relatórios", icone: "relatorios" },
  calendario: { rotulo: "Calendário", icone: "calendario" },
  kanban: { rotulo: "Kanban", icone: "kanban" },
  mapa: { rotulo: "Mapa 3D", icone: "cube3d" },
  impressao: { rotulo: "Impressão", icone: "print" },
  cadastros: { rotulo: "Cadastros", icone: "cadastros" },
  reporte: { rotulo: "Reporte de Erro", icone: "reporte" },
  avisos: { rotulo: "Avisos", icone: "bell" },
  admin: { rotulo: "Administração", icone: "settings" },
};

const VIEWS = {
  home: renderHome,
  ativos: renderAtivos,
  produtos: renderProdutos,
  movimentacoes: renderMovimentacoes,
  manutencoes: renderManutencoes,
  scanner: renderScanner,
  contagens: renderContagens,
  financeiro: renderFinanceiro,
  contratos: renderContratos,
  descarte: renderDescarte,
  software: renderSoftware,
  emprestimos: renderEmprestimos,
  monitor: renderMonitor,
  avisos: renderAvisos,
  seguranca: renderSeguranca,
  relatorios: renderRelatorios,
  calendario: renderCalendario,
  kanban: renderKanban,
  mapa: renderMapa,
  impressao: renderImpressao,
  cadastros: renderCadastros,
  reporte: renderReporte,
  admin: renderAdmin,
};

const NAVEGACAO_PRINCIPAL = ["ativos", "produtos", "manutencoes", "emprestimos", "monitor", "mapa", "relatorios", "admin"];
const BOTTOM_NAV = ["relatorios", "ativos", "scanner"];

const router = new Router();
let shellBuilt = false;
let fabEl = null;
let chatIa = null;
let consultaChat = 0;
let timerChat;
let currentPath = "home";
let revisaoTela = 0;

const currentRoute = () => (location.hash || "#/home").replace(/^#\/?/, "").split("?")[0] || "home";

// ---------------------------------------------------------------------------
// Shell
// ---------------------------------------------------------------------------
function buildShell() {
  const root = document.getElementById("app");
  root.innerHTML = "";

  const menuMobile = el("button", { class: "iconbtn nexus-menu-mobile", type: "button",
    title: "Todos os módulos", "aria-label": "Todos os módulos", "aria-haspopup": "dialog",
    onclick: () => openDrawer(), html: icon("menu") });
  const homeBtn = el("button", { class: "iconbtn nexus-home-mobile", title: "Menu inicial do inventário", onclick: () => router.go("home"), html: icon("home") });

/**
 * Seletor da planta que a tela está mostrando.
 *
 * ## Por que só o administrador vê
 *
 * Usuário comum tem planta fixa no cadastro — o servidor já escopa. Para ele
 * um seletor seria um botão que não faz nada.
 *
 * O administrador não tem planta: `planta_id` nulo significa "todas". Sem
 * escolher, tudo o que ele cria nasce sem planta e aparece em todas as
 * plantas — que é o problema que este controle resolve.
 *
 * ## "Todas" não é o mesmo que "nenhuma"
 *
 * É uma visão consolidada legítima, e continua disponível. O que muda é que
 * agora dá para trabalhar dentro de uma planta específica.
 */
function seletorDePlanta() {
  if (!state.isAdmin) return state.user?.planta_sigla
    ? el("span", { class: "nexus-planta-fixa", title: "Planta da sua conta" }, state.user.planta_sigla)
    : null;

  const caixa = el("select", {
    class: "seletor-planta",
    title: "Planta que esta tela está mostrando",
    "aria-label": "Planta que esta tela está mostrando",
    onchange: (ev) => {
      const valor = ev.target.value;
      state.plantaAtiva = valor === "" ? null : Number(valor);
      // Redesenha a tela atual: os dados visíveis mudam de escopo. `ctx.rerender`
      // é o mesmo caminho que o botão de recarregar usa — não inventa navegação.
      if (ctx.rerender) ctx.rerender();
      else location.reload();
    },
  },
    el("option", { value: "" }, "Todas as plantas"),
  );

  // As plantas vêm do servidor. Falha em silêncio: sem a lista, o seletor
  // fica só com "Todas", que é o comportamento anterior.
  api.get("/plantas/opcoes").then((lista) => {
    const atual = state.plantaAtiva;
    for (const p of lista || []) {
      caixa.append(el("option", { value: String(p.id) }, p.nome || p.sigla || String(p.id)));
    }
    caixa.value = atual === null || atual === undefined ? "" : String(atual);
  }).catch(() => {});

  return caixa;
}

  const badge = seletorInventario();
  const nome = state.user?.nome?.trim() || "Nexus";
  const iniciais = nome.split(/\s+/).slice(0, 2).map(parte => parte[0]).join("").toUpperCase();
  const conta = el("details", { class: "nexus-conta" },
    el("summary", { class: "nexus-avatar", "aria-label": `Menu da conta de ${nome}`, title: nome }, iniciais),
    el("div", { class: "nexus-conta-menu" },
      el("strong", {}, nome),
      el("button", { class: "btn outline", title: TITULO_TEMA, onclick: () => { conta.open = false; abrirSeletorDeTema(); } },
        el("span", { class: "nexus-conta-tema", html: iconeDoModo() }), "Aparência"),
      el("button", { class: "btn outline", onclick: atualizarAplicativo },
        el("span", { html: icon("download", 18) }), "Atualizar aplicativo"),
      el("button", { class: "btn outline", onclick: logout }, el("span", { html: icon("logout", 18) }), "Sair"),
      el("small", { class: "muted" }, `Versão ${APP_VERSION}`)));
  conta.addEventListener("focusout", ev => {
    if (ev.relatedTarget && !conta.contains(ev.relatedTarget)) conta.open = false;
  });
  conta.addEventListener("keydown", ev => {
    if (ev.key === "Escape" && conta.open) {
      conta.open = false;
      conta.querySelector("summary").focus();
    }
  });

  const topbar = el("header", { class: "topbar" },
    menuMobile,
    homeBtn,
    el("div", { class: "brand", html: '<span class="long">Nexus</span>' }),
    el("button", { class: "nexus-busca", type: "button", onclick: abrirBusca,
      "aria-label": "Buscar patrimônio, hostname ou série", "aria-keyshortcuts": "Control+K Meta+K" },
      el("span", { html: icon("search", 20) }),
      el("span", { class: "nexus-busca-texto" }, "Buscar patrimônio, hostname ou série")),
    el("div", { class: "spacer" }),
    seletorDePlanta(),
    badge,
    sinoNotificacoes(),
    conta,
  );

  const lateral = el("aside", { class: "nexus-lateral" },
    el("button", { class: "nexus-marca", type: "button", onclick: () => router.go("home"), "aria-label": "Nexus, início" },
      el("span", { class: "nexus-marca-icone", "aria-hidden": "true" }), "Nexus"),
    el("nav", { class: "nexus-nav", id: "rail", "aria-label": "Atalhos da barra lateral" }),
    el("div", { class: "nexus-nav nexus-nav-admin", id: "nexus-nav-admin" }));
  const content = el("main", { class: "content", id: "view" });
  const bottomnav = el("nav", { class: "bottomnav", "data-nav": "bottom", id: "bottomnav" });

  root.append(topbar, el("div", { class: "shell" }, lateral, content), bottomnav);

  fabEl = el("button", { class: "fab hidden" });
  document.body.append(fabEl);

  shellBuilt = true;
  timerChat = setInterval(() => {
    if (!document.hidden) atualizarChat();
  }, 30000);
  window.addEventListener("focus", atualizarChat);
  updateBadge();
}

async function atualizarChat() {
  if (!shellBuilt) return;
  const consulta = ++consultaChat;
  const dados = await api.get("/ia/disponibilidade").catch(() => null);
  if (!shellBuilt || consulta !== consultaChat) return;
  if (!dados?.disponivel) {
    chatIa?.elemento.remove();
    chatIa = null;
    return;
  }
  if (!chatIa) {
    chatIa = criarChatIa();
    document.body.append(chatIa.elemento);
  }
  chatIa.atualizarEscopo();
}

function destroyShell() {
  if (fabEl) { fabEl.remove(); fabEl = null; }
  clearInterval(timerChat);
  window.removeEventListener("focus", atualizarChat);
  consultaChat++;
  chatIa?.elemento.remove();
  chatIa = null;
  shellBuilt = false;
}

function updateBadge() {
  const b = document.getElementById("inv-badge");
  if (!b) return;
  b.querySelector("svg").outerHTML = icon(state.dominio === "ti" ? "ativos" : "print", 18);
  b.querySelector("span").textContent = state.dominioLabel;
  b.setAttribute("aria-label", state.inventariosPermitidos().length > 1
    ? `Trocar de inventário. Atual: ${state.dominioLabel}` : state.dominioLabel);
}

/**
 * As duas escolhas visuais, em eixos separados.
 *
 * `MODOS` e iluminacao (claro/escuro); `PALETAS` e identidade (a cor de
 * destaque). Juntar as duas num so campo obrigaria a repetir cada cor nos dois
 * modos — e acrescentar uma cor exigiria dois blocos de CSS.
 *
 * Os valores sao os MESMOS de `[data-theme]` e `[data-paleta]` no CSS.
 */
/**
 * As três listas de aparência — com a MESMA forma.
 *
 * Cada opção tem sempre os mesmos campos:
 *   sw     cor do quadrado (o "fundo" daquela opção)
 *   borda  cor da borda do quadrado
 *   marca  cor do elemento central (o "cartão")
 *   icone  quando a opção é categórica (modo), em vez de cromática
 *   tinta  cor do ícone, quando houver
 *
 * Antes os modos usavam as cores do tema ATUAL e as cores usavam as próprias
 * — então a mesma lista se desenhava de dois jeitos. Agora toda opção mostra
 * as SUAS cores, e o desenho é um só (`opcaoDeTema`).
 */
const MODOS = [
  { valor: "light", rotulo: "Claro", icone: "sun",
    sw: "#F7FBF7", borda: "#C1C9C1", tinta: "#2F6B4F" },
  { valor: "dark", rotulo: "Escuro", icone: "moon",
    sw: "#111A13", borda: "#414942", tinta: "#99D5B3" },
];
// Cor dos ÍCONES e dos botões — o destaque da tela.
const PALETAS = [
  { valor: "nexus", rotulo: "Verde Nexus", sw: "#B4F1CE", borda: "#2F6B4F", marca: "#2F6B4F" },
  { valor: "azul", rotulo: "Azul", sw: "#D3E4FF", borda: "#2C5A8C", marca: "#2C5A8C" },
  { valor: "roxo", rotulo: "Roxo", sw: "#EBDCFF", borda: "#6A4C93", marca: "#6A4C93" },
  { valor: "ambar", rotulo: "Âmbar", sw: "#FFDF9E", borda: "#8A6000", marca: "#8A6000" },
  { valor: "classico", rotulo: "Clássico", sw: "#FFDAD6", borda: "#B3261E", marca: "#B3261E" },
];
// Cor de FUNDO — escolha separada, para combinar como quiser.
const FUNDOS = [
  { valor: "verde", rotulo: "Verde", sw: "#F1F7F1", borda: "#C1C9C1", marca: "#EBF3EC" },
  { valor: "neutro", rotulo: "Neutro", sw: "#F4F4F4", borda: "#C6C6C6", marca: "#EFEFEF" },
  { valor: "azul", rotulo: "Azul", sw: "#F2F6FB", borda: "#C0C8D2", marca: "#EAF0F7" },
  { valor: "areia", rotulo: "Areia", sw: "#F8F4ED", borda: "#CCC4B6", marca: "#F2EDE4" },
];
const TITULO_TEMA = "Aparência";
const ICONE_TEMA = { light: "sun", dark: "moon" };

/** Icone do botao, conforme o modo atual. */
function iconeDoModo() {
  return icon(ICONE_TEMA[state.theme] || "moon");
}

function atualizarIconeDoTema() {
  const glyph = document.querySelector(".nexus-conta-tema");
  if (glyph) glyph.innerHTML = iconeDoModo();
}

/**
 * Janela de aparencia: modo e cor no mesmo lugar.
 *
 * A janela NAO fecha ao escolher — o tema aplica na hora, entao a pessoa ve o
 * resultado enquanto decide e pode trocar de ideia ali mesmo.
 *
 * As duas escolhas vao para a CONTA (`state.setTheme`/`state.setPaleta` gravam
 * no servidor), entao acompanham a pessoa em qualquer computador.
 */
function abrirSeletorDeTema() {
  const GRUPOS = [
    { chave: "theme", lista: MODOS, atual: () => state.theme, titulo: "Modo",
      aplica: (v) => { state.setTheme(v); atualizarIconeDoTema(); } },
    { chave: "paleta", lista: PALETAS, atual: () => state.paleta,
      titulo: "Cor dos ícones e botões", aplica: (v) => state.setPaleta(v) },
    { chave: "fundo", lista: FUNDOS, atual: () => state.fundo,
      titulo: "Cor de fundo e cartões", aplica: (v) => state.setFundo(v) },
  ];

  // Um bloco por eixo, desenhado pela MESMA função. Antes cada lista tinha o
  // seu próprio JSX, e por isso divergiam: o modo usava as cores do tema
  // atual, as cores usavam as próprias.
  const blocos = GRUPOS.map((g) => {
    const div = el("div", { class: "cartoes" },
      ...g.lista.map((o) => opcaoDeTema(o, g.atual() === o.valor, () => {
        g.aplica(o.valor);
        repintar();
        toast(`${g.chave === "theme" ? "Modo" : g.chave === "paleta" ? "Cor" : "Fundo"} `
              + `${o.rotulo.toLowerCase()}`);
      })));
    return { ...g, div };
  });

  /**
   * Redesenha SÓ as marcas de seleção, sem fechar a janela.
   *
   * Recriar a janela inteira perderia a posição de rolagem e piscaria a cada
   * clique — e a pessoa está justamente experimentando as combinações.
   *
   * Lê o estado atual em vez de receber parâmetros: com três eixos, passar
   * cada um por argumento virava uma lista que podia sair de sincronia.
   */
  function repintar() {
    blocos.forEach(({ div, lista, atual }) => {
      div.querySelectorAll(".tema-opcao").forEach((b, i) => {
        const ativo = lista[i].valor === atual();
        b.classList.toggle("ativa", ativo);
        const marca = b.querySelector(".tema-atual");
        if (ativo && !marca) b.append(el("span", { class: "tema-atual", html: icon("check", 16) }));
        else if (!ativo && marca) marca.remove();
      });
    });
  }

  dialog({
    title: "Aparência",
    body: el("div", {},
      // Prévia ao vivo: mostra a combinação ANTES de decidir. Sem ela, a
      // pessoa precisa aplicar cada opção para descobrir como fica.
      el("div", { class: "tema-previa" },
        el("div", { class: "tema-previa-topo" },
          el("span", { class: "tema-previa-ponto" }),
          el("span", { class: "tema-previa-linha" }),
        ),
        el("div", { class: "tema-previa-corpo" },
          el("b", { class: "tema-previa-titulo" }, "Como vai ficar"),
          el("span", { class: "tema-previa-desc" },
            "Fundo, cartões e ícones — a combinação escolhida, aplicada agora."),
          el("span", { class: "tema-previa-btn" }, "Botão"),
        ),
      ),
      ...blocos.flatMap((b, i) => [
        el("p", { class: "dica", style: i === 0 ? "margin:0 0 10px" : "margin:18px 0 10px" },
          b.titulo),
        b.div,
      ]),
      el("p", { class: "muted", style: "margin:16px 0 0;font-size:12.5px" },
        "As três escolhas são independentes e ficam salvas na sua conta — "
        + "acompanham você em qualquer computador onde entrar."),
    ),
    actions: [{ label: "Fechar", variant: "text" }],
  });
}

/**
 * Desenha UMA opção de aparência.
 *
 * Usada pelas três listas — é o que garante que modo, cor e fundo tenham
 * exatamente o mesmo tamanho, borda, espaçamento e marca de seleção. Enquanto
 * cada lista tinha o seu próprio desenho, elas divergiam a cada mudança.
 *
 * O quadrado mostra sempre as cores DA PRÓPRIA opção, nunca as do tema atual:
 * é o que a pessoa vai receber se clicar nela.
 */
function opcaoDeTema(o, ativo, aoEscolher) {
  return el("button", {
    type: "button",
    class: `tema-opcao${ativo ? " ativa" : ""}`,
    onclick: aoEscolher,
  },
    el("span", { class: "tema-sw", style: `background:${o.sw};border-color:${o.borda}` },
      o.icone
        // Modo é categórico: mostra o ícone do sol/lua, na tinta daquele modo.
        ? el("span", { class: "tema-sw-tinta", style: `color:${o.tinta}`,
                       html: icon(o.icone, 17) })
        // Cor e fundo são cromáticos: mostram o "cartão" sobre o fundo.
        : el("span", { class: "tema-sw-marca", style: `background:${o.marca}` })),
    el("span", { class: "tema-nome" }, o.rotulo),
    ativo ? el("span", { class: "tema-atual", html: icon("check", 16) }) : null,
  );
}

function toggleTheme() {
  state.setTheme(state.theme === "dark" ? "light" : "dark");
  atualizarIconeDoTema();
  ctx.rerender();
}

async function logout() {
  await encerrarSessao();
  location.hash = "#/";
  location.reload();
}

/**
 * Indicador de inventário na barra superior — e, havendo mais de um
 * disponível, um atalho para trocar.
 *
 * Antes era só um rótulo: para trocar, era preciso abrir o menu e procurar
 * "Trocar inventário". Quem tem acesso aos dois alterna com frequência, e o
 * caminho longo não se justifica. Sem acesso ao outro inventário, o indicador
 * continua apenas informativo.
 */
function seletorInventario() {
  const permitidos = state.inventariosPermitidos();
  const atual = state.dominio;
  const iconeDe = (chave) => icon(chave === "ti" ? "ativos" : "print", 18);

  const botao = el("button", {
    type: "button",
    class: "inv-badge",
    id: "inv-badge",
    html: iconeDe(atual) + `<span>${state.dominioLabel}</span>`,
  });

  // Com um inventário só não há escolha a oferecer.
  if (permitidos.length < 2) {
    botao.classList.add("sem-troca");
    botao.title = "Seu acesso é somente a este inventário";
    return botao;
  }

  botao.title = "Trocar de inventário";
  botao.append(el("span", { class: "inv-seta", html: icon("chevron", 14) }));

  let menu = null;
  const fora = (ev) => {
    if (menu && !menu.contains(ev.target) && !botao.contains(ev.target)) fechar();
  };
  const porEsc = (ev) => { if (ev.key === "Escape") fechar(); };

  function fechar() {
    if (!menu) return;
    menu.remove();
    menu = null;
    document.removeEventListener("click", fora, true);
    document.removeEventListener("keydown", porEsc, true);
  }

  function abrir() {
    menu = el("div", { class: "inv-seletor" },
      el("div", { class: "titulo" }, "Trocar inventário"),
      ...permitidos.map((chave) => el("button", {
        type: "button",
        class: `inv-opcao${chave === atual ? " atual" : ""}`,
        // O ícone vai pelo `html`, e não como filho: um texto passado como
        // filho vira `textContent`, e a marcação do SVG aparecia escrita na
        // tela em vez de desenhada.
        html: iconeDe(chave)
          + `<span>${ROTULO_INVENTARIO[chave] || chave}</span>`
          + (chave === atual ? `<span class="marca">${icon("check", 16)}</span>` : ""),
        onclick: () => (chave === state.dominio ? fechar() : trocarInventario(chave)),
      })),
    );

    // Ancorado na barra superior, que já serve de referência de posição.
    const ancora = botao.parentElement;
    ancora.style.position = "relative";
    ancora.append(menu);

    // Um tick para o clique atual não fechar o menu na hora.
    setTimeout(() => {
      document.addEventListener("click", fora, true);
      document.addEventListener("keydown", porEsc, true);
    }, 0);
  }

  botao.addEventListener("click", (ev) => {
    ev.stopPropagation();
    menu ? fechar() : abrir();
  });
  return botao;
}

/**
 * Troca o inventário ativo **mantendo a tela atual**.
 *
 * Quem está vendo "Ativos" no TI quer ver "Ativos" nas impressoras — não voltar
 * ao menu inicial a cada troca. A rota atual é preservada, e a página recarrega
 * porque tudo no sistema é filtrado por inventário (listas, contadores,
 * relatórios, leituras): recarregar garante que nenhuma tela continue com dado
 * do inventário anterior.
 *
 * A estrutura já está pronta para o seletor ganhar outros recursos no futuro:
 * basta que a troca preserve a rota, como faz agora.
 */
function trocarInventario(chave) {
  state.setDominio(chave);

  // Um módulo que só existe no outro inventário (ou uma tela removida) não
  // deve levar a um lugar vazio: nesse caso, cai no menu inicial.
  const rota = (location.hash.replace(/^#\/?/, "").split("?")[0] || "home");
  if (rota !== "home" && !MODULOS[rota]) {
    location.hash = "#/";
  }
  location.reload();
}

function modulosPermitidos() {
  return Object.keys(MODULOS).filter(chave => state.podeModulo(chave));
}

function navButton(key, active) {
  const meta = key === "home" ? { rotulo: "Início", icone: "home" } : MODULOS[key];
  return el("button", {
    class: "nav-item" + (key === active ? " active" : ""),
    type: "button",
    title: meta.rotulo,
    "aria-current": key === active ? "page" : null,
    onclick: () => router.go(key),
  }, el("span", { class: "nexus-nav-icone", html: icon(meta.icone, 21) }), el("span", {}, meta.rotulo));
}

function updateNav(active) {
  const permitidos = modulosPermitidos();
  const atalhos = barraLateral.atalhos(permitidos, NAVEGACAO_PRINCIPAL);
  const adminNoRodape = atalhos.includes("admin") && !barraLateral.favoritos().length && !barraLateral.ordem().length;
  const rail = document.getElementById("rail");
  rail?.replaceChildren(
    ...["home", ...atalhos.filter(chave => !adminNoRodape || chave !== "admin")].map(chave => navButton(chave, active)),
    botaoEasterEgg(),
  );
  document.getElementById("nexus-nav-admin")?.replaceChildren(
    ...(adminNoRodape ? [navButton("admin", active)] : []),
    el("button", { class: "nav-item nexus-personalizar", type: "button", onclick: () => openDrawer(true) },
      el("span", { class: "nexus-nav-icone", html: icon("sliders", 21) }), "Personalizar barra lateral"),
  );
  document.getElementById("bottomnav")?.replaceChildren(
    ...BOTTOM_NAV.filter(chave => state.podeModulo(chave)).map(chave => navButton(chave, active)),
  );
}

function atualizarAplicativo() {
  toast("Atualizando…");
  limparCacheFrontend(false);
}

function openDrawer(personalizar = false) {
  const focoAnterior = document.activeElement;
  const painel = el("dialog", {
    class: "nexus-drawer" + (personalizar ? " nexus-drawer-editar" : ""),
    "aria-labelledby": "nexus-drawer-titulo",
  });
  const lista = el("div", { class: "nexus-drawer-lista" });
  const retorno = el("p", { class: "nexus-drawer-retorno", role: "alert", hidden: true });
  const permitidos = modulosPermitidos();
  const telaAmpla = personalizar ? null : matchMedia("(min-width: 769px)");
  let salvando = false;

  function fechar() { painel.close(); }
  function aoMudarTela(evento) { if (evento.matches) fechar(); }
  telaAmpla?.addEventListener("change", aoMudarTela);
  painel.addEventListener("close", () => {
    telaAmpla?.removeEventListener("change", aoMudarTela);
    painel.remove();
    const origemVisivel = !telaAmpla?.matches && focoAnterior !== document.body
      && focoAnterior?.isConnected && focoAnterior.getClientRects().length;
    const controle = matchMedia("(min-width: 769px)").matches
      ? ".nexus-personalizar"
      : ".nexus-menu-mobile";
    const foco = origemVisivel ? focoAnterior : document.querySelector(controle);
    foco?.focus();
  });
  painel.addEventListener("click", ev => { if (ev.target === painel) fechar(); });

  async function salvar(acao, foco) {
    if (salvando) return;
    salvando = true;
    retorno.hidden = true;
    lista.setAttribute("inert", "");
    try {
      await acao();
      updateNav(currentPath);
    } catch (e) {
      if (painel.open) {
        retorno.textContent = "Não foi possível salvar. " + (e.message || "");
        retorno.hidden = false;
      } else mostrarErro(e, "salvar a barra lateral");
    } finally {
      salvando = false;
      lista.removeAttribute("inert");
      if (painel.open) {
        pintarLista();
        if (foco) {
          const controle = lista.querySelector(foco);
          (controle?.disabled ? controle.closest(".drawer-linha").querySelector(".favorito") : controle)?.focus();
        }
      }
    }
  }

  function pintarLista() {
    const ativos = barraLateral.atalhos(permitidos, NAVEGACAO_PRINCIPAL);
    const padrao = [...new Set([...NAVEGACAO_PRINCIPAL, ...permitidos])].filter(chave => permitidos.includes(chave));
    const ordem = barraLateral.ordenarModulos(padrao);
    if (!personalizar) {
      lista.replaceChildren(...["home", ...ordem].map(chave => {
        const item = navButton(chave, currentPath);
        item.classList.add("drawer-item");
        item.addEventListener("click", fechar, { capture: true });
        return item;
      }));
      return;
    }
    lista.replaceChildren(...ordem.map((key, indice) => {
      const { rotulo, icone } = MODULOS[key];
      const marcado = ativos.includes(key);
      const seletor = '[data-chave="' + key + '"] ';
      const mover = (deslocamento, iconeSeta, texto) => el("button", {
        class: "nexus-mover", type: "button", disabled: !ordem[indice + deslocamento],
        "data-direcao": iconeSeta, title: texto + " " + rotulo, "aria-label": texto + " " + rotulo,
        html: icon(iconeSeta, 16),
        onclick: () => {
          const nova = [...ordem];
          nova.splice(indice + deslocamento, 0, ...nova.splice(indice, 1));
          salvar(() => barraLateral.definirOrdem(nova), seletor + '[data-direcao="' + iconeSeta + '"]');
        },
      });

      return el("div", { class: "drawer-linha", "data-chave": key },
        el("span", { class: "empunhadura", title: "Segure e arraste para reordenar", html: icon("grip", 16) }),
        el("button", { class: "favorito" + (marcado ? " marcado" : ""), type: "button",
          "aria-pressed": String(marcado),
          "aria-label": (marcado ? "Remover " : "Adicionar ") + rotulo + (marcado ? " da barra lateral" : " à barra lateral"),
          title: marcado ? "Remover da barra lateral" : "Adicionar à barra lateral",
          html: icon("star", 18),
          onclick: () => salvar(() => barraLateral.alternar(key, ativos), seletor + ".favorito"),
        }),
        el("span", { class: "nexus-drawer-modulo" }, el("span", { html: icon(icone, 20) }), rotulo),
        mover(-1, "up", "Subir"),
        mover(1, "down", "Descer"),
      );
    }));
  }

  if (personalizar) {
    ordenar.permitirReordenar(lista, ".drawer-linha", ordem => salvar(() => barraLateral.definirOrdem(ordem)), linha => linha.dataset.chave);
  }

  const titulo = personalizar ? "Personalizar barra lateral" : "Todos os módulos";
  const cabecalho = el("header", { class: "nexus-drawer-topo" },
    el("h2", { id: "nexus-drawer-titulo" }, titulo),
    el("button", { class: "iconbtn", type: "button", title: "Fechar", "aria-label": "Fechar", onclick: fechar, html: icon("close") }),
  );
  const atualizar = () => { fechar(); atualizarAplicativo(); };
  const acaoRodape = (icone, texto, acao) => el("button", { class: "btn outline", type: "button", onclick: acao },
    el("span", { html: icon(icone, 18) }), texto);

  painel.append(el("div", { class: "nexus-drawer-conteudo" },
    cabecalho,
    personalizar ? el("p", { class: "nexus-drawer-dica" }, "Marque os atalhos que deseja ver. Arraste os módulos ou use as setas para mudar a ordem.") : null,
    !personalizar ? acaoRodape("sliders", "Personalizar barra lateral", () => { fechar(); openDrawer(true); }) : null,
    retorno,
    lista,
    el("footer", { class: "nexus-drawer-rodape" },
      ...(personalizar
        ? [acaoRodape("refresh", "Restaurar padrão", () => salvar(barraLateral.restaurarPadrao))]
        : [
          acaoRodape("swap", "Trocar inventário", () => { fechar(); router.go("selecao"); }),
          acaoRodape("download", "Atualizar aplicativo", atualizar),
          acaoRodape("logout", "Sair", () => { fechar(); logout(); }),
          el("small", {}, "Versão " + APP_VERSION),
        ]),
    ),
  ));
  pintarLista();
  document.body.append(painel);
  painel.showModal();
}

let verificarSessao = () => state.isAuthed;

function renderRoute(path) {
  if (!verificarSessao()) return;
  const revisao = ++revisaoTela;
  ctx.limpar();
  ctx.limpar = () => {};
  currentPath = path;

  if (path === "selecao") {
    stopScanner();
    destroyShell();
    ctx.setFab(null);
    renderSelecao(document.getElementById("app"));
    return;
  }

  // Sem inventário permitido → volta para a seleção.
  if (!state.podeInventario(state.dominio)) {
    router.go("selecao");
    return;
  }

  const modulo = path === "home" ? null : path;
  if (modulo && !state.podeModulo(modulo)) {
    toast("Seu usuário não tem acesso a este módulo");
    router.go("home");
    return;
  }

  if (!shellBuilt) buildShell();
  chatIa?.atualizarEscopo();
  atualizarChat();
  ctx.setChrome(true);
  updateNav(path);
  updateBadge();

  const view = VIEWS[path] || renderHome;
  stopScanner();

  // Se uma tela quebrar, mostra o erro em vez de deixar a página em branco.
  // Já aconteceu: uma exceção na montagem da lista deixava a tela vazia, sem
  // nenhuma pista do que havia ocorrido.
  try {
    const resultado = view(document.getElementById("view"));
    if (resultado instanceof Promise) {
      resultado.catch((e) => {
        if (revisao === revisaoTela) mostrarTelaQuebrada(path, e);
      });
    }
  } catch (e) {
    mostrarTelaQuebrada(path, e);
  }
}

/** Substitui a tela por uma mensagem de erro legível (em vez de tela branca). */
function mostrarTelaQuebrada(path, erro) {
  console.error(`Falha ao montar a tela "${path}":`, erro);
  const alvo = document.getElementById("view");
  if (!alvo) return;
  alvo.innerHTML = "";
  alvo.append(
    el("div", { class: "card" },
      el("h2", { style: "margin:0 0 6px;font-size:17px" }, "Não foi possível montar esta tela"),
      el("p", { class: "muted", style: "margin:0 0 14px;font-size:13.5px" },
        "Ocorreu um erro inesperado ao desenhar a página. O restante do sistema continua funcionando."),
      el("pre", { class: "erro-tecnico" }, String(erro && erro.message ? erro.message : erro)),
      el("div", { class: "row", style: "gap:8px;margin-top:14px" },
        el("button", { class: "btn tonal small", onclick: () => renderRoute(path) }, "Tentar novamente"),
        el("button", { class: "btn text small", onclick: () => router.go("home") }, "Voltar ao menu"),
      ),
    ),
  );
}

// ---------------------------------------------------------------------------
// Bootstrap
// ---------------------------------------------------------------------------
function boot() {
  state.applyTheme();
  state.applyPaleta();
  state.applyFundo();
  state.applyDominio();
  // Ctrl+K fica ligado uma vez, e não a cada tela: o atalho é global.
  //
  // Os módulos vão por parâmetro: a busca os usa para oferecer "Ir para …",
  // e importá-los aqui de dentro do `busca.js` criaria dependência circular.
  ligarAtalhoDeBusca(MODULOS);

  // Registro do service worker é feito em registrarServiceWorker() no final.

  if (state.acaoRequerida === "trocar_senha") state.logout();
  if (state.isAuthed && state.acaoRequerida === "cadastrar_mfa") {
    const root = document.getElementById("app");
    const view = el("div", { class: "login-card card elevated", id: "view" });
    root.replaceChildren(el("div", { class: "login-wrap" }, view));
    document.title = "Configurar verificação em duas etapas — Nexus";
    renderSeguranca(view);
    return;
  }

  if (!state.isAuthed) {
    history.replaceState(null, "", "#/login");
    const root = document.getElementById("app");
    root.innerHTML = "";
    root.append(el("div", { class: "login-wrap", id: "login-root" }));
    const expirou = sessionStorage.getItem("nexus.sessaoExpirada");
    sessionStorage.removeItem("nexus.sessaoExpirada");
    renderLogin(document.getElementById("login-root"), expirou ? "Sua sessão expirou. Entre novamente." : undefined);
    return;
  }

  window.addEventListener("nexus:sessao-expirada", () => {
    sessionStorage.setItem("nexus.sessaoExpirada", "1");
    history.replaceState(null, "", "#/login");
    document.getElementById("app").replaceChildren();
    document.querySelectorAll("dialog[open], .overlay").forEach((item) => item.remove());
    location.reload();
  }, { once: true });
  verificarSessao = monitorarSessao();
  if (!verificarSessao()) return;

  // Injeta as funções de UI no contexto global das views.
  ctx.navigate = (p) => router.go(p);
  ctx.goHome = () => router.go("home");
  ctx.rerender = () => renderRoute(currentRoute());
  ctx.atualizarChat = atualizarChat;
  ctx.setChrome = () => {};
  ctx.setFab = (fab) => {
    if (!fabEl) return;
    if (!fab) { fabEl.classList.add("hidden"); return; }
    fabEl.classList.remove("hidden");
    fabEl.innerHTML = icon(fab.icon, 22) + (fab.label ? `<span>${fab.label}</span>` : "");
    fabEl.onclick = fab.onClick;
  };
  // O título da aba diz em QUAL inventário se está. É o canal que continua
  // visível mesmo com a janela atrás de outra, e o que aparece ao alternar
  // entre abas do navegador.
  ctx.setTitle = (t) => {
    document.title = t
      ? `${t} — ${state.dominioLabel}`
      : `${state.dominioLabel} — Nexus`;
  };

  router.add("selecao", renderRoute);
  for (const rota of ["home", ...Object.keys(MODULOS)]) router.add(rota, renderRoute);
  router.onChange = () => {};

  // Atualiza permissões a partir do servidor (podem ter mudado).
  api.get("/auth/me").then((me) => {
    if (state.isAuthed) state.setUser(me);
  }).catch(() => {
    // A API sinaliza a expiração. Falhas temporárias não apagam a sessão local.
  }).finally(() => {
    if (!verificarSessao()) return;
    // Se o domínio salvo não for permitido, começa pela seleção.
    if (!state.podeInventario(state.dominio)) {
      router.go("selecao");
    } else if (!location.hash || location.hash === "#/" || location.hash === "#" || location.hash === "#/login") {
      router.go("selecao");
    }
    router.start();
  });

  if (navigator.onLine) replayOfflineQueue();
}

// ---------------------------------------------------------------------------
// Service worker: garante que o usuário receba sempre a versão mais nova.
// O cache é versionado; quando um SW novo assume, a página recarrega sozinha.
// ---------------------------------------------------------------------------
function registrarServiceWorker() {
  if (!("serviceWorker" in navigator)) return;

  // Havia um service worker controlando a página ANTES deste carregamento?
  // Isso distingue "primeira instalação" de "atualização".
  const jaControlado = Boolean(navigator.serviceWorker.controller);

  navigator.serviceWorker.register("/sw.js").then((reg) => {
    reg.update?.().catch(() => {});
    // Se já existe um SW novo esperando, pede para assumir já.
    if (reg.waiting) reg.waiting.postMessage("skip-waiting");
    reg.addEventListener("updatefound", () => {
      const novo = reg.installing;
      novo?.addEventListener("statechange", () => {
        if (novo.state === "installed" && navigator.serviceWorker.controller) {
          novo.postMessage("skip-waiting");
        }
      });
    });
  }).catch(() => {});

  // Quando o controle muda (SW novo assumiu), recarrega UMA vez.
  //
  // ATENÇÃO: só recarrega se a página JÁ era controlada. Sem esta condição,
  // a PRIMEIRA instalação (clients.claim) dispara `controllerchange`, o reload
  // aborta a instalação do SW, ele reinstala no carregamento seguinte e
  // recarrega de novo — um laço infinito de recarregamento.
  let recarregou = false;
  navigator.serviceWorker.addEventListener("controllerchange", () => {
    if (!jaControlado || recarregou) return;
    recarregou = true;
    location.reload();
  });
}

/**
 * Limpa service worker + caches + sessão local e recarrega.
 * Serve como "botão de pânico" quando o navegador insiste em uma versão antiga.
 */
async function limparCacheFrontend(limparSessao = true) {
  try {
    if ("serviceWorker" in navigator) {
      const registros = await navigator.serviceWorker.getRegistrations();
      await Promise.all(registros.map((r) => r.unregister()));
    }
  } catch { /* segue */ }
  try {
    if (globalThis.caches) {
      const chaves = await caches.keys();
      await Promise.all(chaves.map((k) => caches.delete(k)));
    }
  } catch { /* segue */ }
  try {
    if (limparSessao) localStorage.clear();
  } catch { /* segue */ }
  // Recarrega sem os parâmetros de reset.
  location.replace("/");
}

/** Suporta `?reset=1` na URL para forçar a limpeza total. */
async function tratarResetPorUrl() {
  const params = new URLSearchParams(location.search);
  if (params.get("reset") !== "1") return false;
  await limparCacheFrontend(true);
  return true;
}

// Se a URL pedir reset (?reset=1), limpa cache/sessão antes de iniciar.
tratarResetPorUrl().then((resetando) => {
  if (resetando) return;
  boot();
  registrarServiceWorker();
  // Avisa se o processo do servidor for mais antigo que este frontend.
  conferirVersaoDoServidor();
});
