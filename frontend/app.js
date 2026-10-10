/**
 * Bootstrap da aplicação:
 *  - Login → Seleção de inventário → Menu inicial → módulos.
 *  - Shell M3 (topbar + Navigation Rail/Bottom Nav + FAB) com botão
 *    permanente de "voltar ao menu inicial" e botão de 3 barras (drawer).
 * @module app
 */
import { state, ROTULO_INVENTARIO } from "./js/state.js";
import { api, replayOfflineQueue } from "./js/api.js";
import { Router } from "./js/router.js";
import { ctx } from "./js/context.js";
import { el, icon, toast, mostrarErro } from "./js/ui.js";
import { APP_VERSION } from "./js/version.js";
import { renderLogin } from "./js/views/login.js";
import { renderSelecao, renderHome } from "./js/views/inventario.js";
import { renderAtivos } from "./js/views/ativos.js";
import { renderImpressao } from "./js/views/impressao.js";
import { renderCalendario } from "./js/views/calendario.js";
import { renderReporte } from "./js/views/reporte.js";
import { renderProdutos } from "./js/views/produtos.js";
import { renderMovimentacoes } from "./js/views/movimentacoes.js";
import { renderContagens } from "./js/views/contagens.js";
import { renderFinanceiro } from "./js/views/financeiro.js";
import { renderEmprestimos } from "./js/views/emprestimos.js";
import { renderMonitor } from "./js/views/monitor_impressoras.js";
import { renderSeguranca } from "./js/views/seguranca.js";
import { renderManutencoes } from "./js/views/manutencoes.js";
import { renderScanner, stopScanner } from "./js/views/scanner.js";
import { renderRelatorios } from "./js/views/relatorios.js";
import { renderCadastros } from "./js/views/cadastros.js";
import { renderAdmin } from "./js/views/admin.js";
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
  financeiro: { rotulo: "Financeiro", icone: "relatorios" },
  emprestimos: { rotulo: "Empréstimos", icone: "calendario" },
  monitor: { rotulo: "Monitor de impressoras", icone: "print" },
  seguranca: { rotulo: "Segurança da conta", icone: "settings" },
  relatorios: { rotulo: "Relatórios", icone: "relatorios" },
  calendario: { rotulo: "Calendário", icone: "calendario" },
  impressao: { rotulo: "Impressão", icone: "print" },
  cadastros: { rotulo: "Cadastros", icone: "cadastros" },
  reporte: { rotulo: "Reporte de Erro", icone: "reporte" },
  admin: { rotulo: "Administração", icone: "cadastros" },
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
  emprestimos: renderEmprestimos,
  monitor: renderMonitor,
  seguranca: renderSeguranca,
  relatorios: renderRelatorios,
  calendario: renderCalendario,
  impressao: renderImpressao,
  cadastros: renderCadastros,
  reporte: renderReporte,
  admin: renderAdmin,
};

// O Dashboard foi incorporado a Relatórios: a tela inicial do inventário
// passa a ser os indicadores + gráficos.
const ROTA_INICIAL = "relatorios";
const BOTTOM_NAV = ["relatorios", "ativos", "scanner"];

const router = new Router();
let shellBuilt = false;
let fabEl = null;
let currentPath = "home";

const currentRoute = () => (location.hash || "#/home").replace(/^#\/?/, "").split("?")[0] || "home";

// ---------------------------------------------------------------------------
// Shell
// ---------------------------------------------------------------------------
function buildShell() {
  const root = document.getElementById("app");
  root.innerHTML = "";

  const menuBtn = el("button", { class: "iconbtn", title: "Menu", onclick: openDrawer, html: icon("menu") });
  const homeBtn = el("button", { class: "iconbtn", title: "Menu inicial do inventário", onclick: () => router.go("home"), html: icon("home") });
  const badge = seletorInventario();

  const topbar = el("header", { class: "topbar" },
    menuBtn,
    homeBtn,
    el("div", { class: "brand", html: `<span class="long">Gestão Patrimonial</span><small>v${APP_VERSION}</small>` }),
    el("div", { class: "spacer" }),
    badge,
    sinoNotificacoes(),
    el("button", { class: "iconbtn", title: "Alternar tema", onclick: toggleTheme, html: icon(state.theme === "dark" ? "sun" : "moon") }),
    el("button", { class: "iconbtn", title: "Sair", onclick: logout, html: icon("logout") }),
  );

  const rail = el("nav", { class: "rail", "data-nav": "rail", id: "rail" });
  const content = el("main", { class: "content", id: "view" });
  const bottomnav = el("nav", { class: "bottomnav", "data-nav": "bottom", id: "bottomnav" });

  root.append(topbar, el("div", { class: "shell" }, rail, content), bottomnav);

  fabEl = el("button", { class: "fab hidden" });
  document.body.append(fabEl);

  shellBuilt = true;
  updateBadge();
}

function destroyShell() {
  if (fabEl) { fabEl.remove(); fabEl = null; }
  shellBuilt = false;
}

function updateBadge() {
  const b = document.getElementById("inv-badge");
  if (b) b.innerHTML = icon(state.dominio === "ti" ? "ativos" : "print", 18) + `<span>${state.dominioLabel}</span>`;
}

function toggleTheme() {
  state.setTheme(state.theme === "dark" ? "light" : "dark");
  if (shellBuilt) {
    // Atualiza só o ícone do botão de tema.
    const btns = document.querySelectorAll(".topbar .iconbtn");
    btns.forEach((b) => { if (b.title === "Alternar tema" || b.getAttribute("title") === "Alternar tema") b.innerHTML = icon(state.theme === "dark" ? "sun" : "moon"); });
  }
  ctx.rerender();
}

function logout() {
  state.logout();
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

// Qualquer módulo que o usuário possa acessar pode virar favorito na barra
// lateral — inclusive Administração e Reporte de Erro.
//
// Não existe lista de exceções aqui de propósito: **ao criar uma aba nova,
// basta registrá-la em MODULOS** e ela já aparece na gaveta com estrela e pode// ser favoritada. Uma lista de exclusão daria manutenção e explicaria o
// sintoma de "favoritei e não apareceu".
//
// A barra lateral fica vazia por padrão (só o Menu) — os atalhos são escolha
// do usuário, feita na gaveta.

function navItemsFor(container) {  const permitidos = Object.keys(MODULOS).filter((m) => state.podeModulo(m));
  if (container === "rail") {
    // A barra rápida mostra APENAS os favoritos. As demais telas continuam na
    // gaveta (as três barras) e no menu inicial.
    return ["home", ...barraLateral.favoritosOrdenados(permitidos)];
  }
  return BOTTOM_NAV.filter((m) => state.podeModulo(m));
}


function navButton(key, active, compact = false) {
  const meta = key === "home" ? { rotulo: "Menu", icone: "home" } : MODULOS[key];
  if (!meta) return null;
  return el("button", {
    class: "nav-item" + (key === active ? " active" : ""),
    title: meta.rotulo,
    onclick: () => router.go(key),
    html: icon(meta.icone, 24) + `<span>${meta.rotulo}</span>`,
  });
}

/**
 * Estrela que marca/desmarca um módulo.
 *
 * Usada na **gaveta** (as três barras), que lista todas as opções: é ali que o
 * usuário escolhe o que sobe para a barra lateral rápida.
 */
function estrelaFavorito(key, aoMudar) {
  const marcado = barraLateral.ehFavorito(key);
  const textoDe = (m) => (m ? "Remover da barra lateral" : "Adicionar à barra lateral");

  const b = el("button", {
    class: `favorito${marcado ? " marcado" : ""}`,
    type: "button",
    title: textoDe(marcado),
    "aria-pressed": marcado ? "true" : "false",
    html: icon("star", 18),
  });

  b.addEventListener("click", async (ev) => {
    // Sem isto o clique marcaria a estrela E navegaria para o módulo.
    ev.stopPropagation();
    ev.preventDefault();
    try {
      const novo = await barraLateral.alternar(key);
      b.classList.toggle("marcado", novo);
      b.title = textoDe(novo);
      b.setAttribute("aria-pressed", novo ? "true" : "false");
      if (aoMudar) aoMudar();
    } catch (e) {
      mostrarErro(e, "salvar os favoritos");
    }
  });
  return b;
}

function updateNav(active) {
  for (const [id, tipo] of [["rail", "rail"], ["bottomnav", "bottom"]]) {
    const cont = document.getElementById(id);
    if (!cont) continue;
    cont.innerHTML = "";

    if (tipo === "rail") {
      // A barra rápida mostra os FAVORITOS. O resto vive na gaveta.
      navItemsFor("rail").forEach((k) => {
        const b = navButton(k, active);
        if (b) cont.append(b);
      });
      // Sem nenhum favorito a barra ficaria vazia e sem saída: o botão abaixo
      // abre a gaveta, que é onde se escolhe.
      if (!barraLateral.favoritos().length) {
        cont.append(el("button", {
          class: "nav-item nav-vazio",
          title: "Escolher os atalhos da barra lateral",
          html: icon("star", 22) + "<span>Adicionar</span>",
          onclick: openDrawer,
        }));
      }
      cont.append(botaoEasterEgg());
    } else {
      navItemsFor(tipo).forEach((k) => {
        const b = navButton(k, active);
        if (b) cont.append(b);
      });
    }
  }
}



// ---------------------------------------------------------------------------
// Drawer (menu de 3 barras) — com fechamento por clique fora e ESC
// ---------------------------------------------------------------------------
function openDrawer() {
  const overlay = el("div", { class: "drawer-overlay" });
  const panel = el("div", { class: "drawer" });
  overlay.append(panel);

  const close = () => {
    overlay.remove();
    document.removeEventListener("keydown", onKey);
  };
  const onKey = (e) => { if (e.key === "Escape") close(); };
  overlay.addEventListener("click", (e) => { if (e.target === overlay) close(); });
  document.addEventListener("keydown", onKey);

  panel.append(
    el("div", { class: "row between", style: "padding:4px 8px 16px" },
      el("div", {},
        el("div", { style: "font-weight:600" }, state.user?.nome || ""),
        el("div", { class: "muted", style: "font-size:12px" }, state.user?.papel || ""),
      ),
      el("button", { class: "iconbtn", title: "Fechar", onclick: close, html: icon("close") }),
    ),
  );

  const permitidos = Object.keys(MODULOS).filter((m) => state.podeModulo(m));
  // A gaveta precisa abrir NA ORDEM GRAVADA — senão o usuário reordena, sai,
  // volta e encontra tudo embaralhado de novo.
  const ordenados = barraLateral.ordenarModulos(permitidos);
  const entradas = [["home", "Menu inicial", "home"], ...ordenados.map((m) => [m, MODULOS[m].rotulo, MODULOS[m].icone])];
  for (const [key, rotulo, icone] of entradas) {
    const btn = el("button", {
      class: "drawer-item" + (key === currentPath ? " active" : ""),
      onclick: () => { close(); router.go(key); },
      html: icon(icone, 22) + `<span>${rotulo}</span>`,
    });

    // "Menu inicial" não é favoritável — é a porta para todas as telas.
    if (key === "home") {
      panel.append(btn);
      continue;
    }
    // A estrela fica AQUI, na lista completa: é onde se escolhe o que sobe
    // para a barra lateral rápida. A gaveta continua aberta ao marcar.
    panel.append(el("div", { class: "drawer-linha", "data-chave": key },
      el("span", { class: "empunhadura", title: "Segure e arraste para reordenar",
        html: icon("grip", 16) }),
      estrelaFavorito(key, () => updateNav(currentPath)),
      btn,
    ));
  }

  // Segurar um item o levanta; arrastar muda a ordem na barra lateral.
  ordenar.permitirReordenar(
    panel,
    ".drawer-linha",
    async (ordem) => {
      // Grava a ordem da LISTA INTEIRA. Gravar só a dos favoritos fazia a
      // posição dos demais se perder ao reabrir a gaveta.
      try {
        await barraLateral.definirOrdem(ordem);
        updateNav(currentPath);
        toast("Ordem atualizada");
      } catch (e) {
        mostrarErro(e, "salvar a ordem");
      }
    },
    (el) => el.dataset.chave,
  );

  panel.append(el("div", { style: "flex:1" }));
  panel.append(el("div", { style: "border-top:1px solid var(--md-sys-color-outline-variant);margin:12px 0 8px" }));
  panel.append(el("div", { class: "muted", style: "font-size:11.5px;padding:0 16px 8px" }, `Versão ${APP_VERSION}`));
  panel.append(el("button", {
    class: "drawer-item",
    onclick: () => { close(); router.go("selecao"); },
    html: icon("swap", 22) + "<span>Trocar inventário</span>",
  }));
  panel.append(el("button", {
    class: "drawer-item",
    title: "Limpa o cache do navegador e recarrega a versão mais recente",
    onclick: () => { close(); toast("Atualizando…"); limparCacheFrontend(false); },
    html: icon("download", 22) + "<span>Atualizar aplicativo</span>",
  }));
  panel.append(el("button", {
    class: "drawer-item", onclick: () => { close(); logout(); },
    html: icon("logout", 22) + "<span>Sair</span>",
  }));

  document.body.append(overlay);
}

// ---------------------------------------------------------------------------
// Roteamento
// ---------------------------------------------------------------------------
function renderRoute(path) {
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
      resultado.catch((e) => mostrarTelaQuebrada(path, e));
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
  state.applyDominio();

  // Registro do service worker é feito em registrarServiceWorker() no final.

  if (!state.isAuthed) {
    const root = document.getElementById("app");
    root.innerHTML = "";
    root.append(el("div", { class: "login-wrap", id: "login-root" }));
    renderLogin(document.getElementById("login-root"));
    return;
  }

  // Injeta as funções de UI no contexto global das views.
  ctx.navigate = (p) => router.go(p);
  ctx.goHome = () => router.go("home");
  ctx.rerender = () => renderRoute(currentRoute());
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
      : `${state.dominioLabel} — Gestão Patrimonial`;
  };

  router.add("selecao", renderRoute);
  for (const rota of ["home", ...Object.keys(MODULOS)]) router.add(rota, renderRoute);
  router.onChange = () => {};

  // Atualiza permissões a partir do servidor (podem ter mudado).
  api.get("/auth/me").then((me) => state.setUser(me)).catch(() => {}).finally(() => {
    // Se o domínio salvo não for permitido, começa pela seleção.
    if (!state.podeInventario(state.dominio)) {
      router.go("selecao");
    } else if (!location.hash || location.hash === "#/" || location.hash === "#") {
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
