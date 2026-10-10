/**
 * Tela inicial de SELEÇÃO DE INVENTÁRIO e o MENU INICIAL de cada inventário.
 * @module views/inventario
 */
import { state } from "../state.js";
import { ctx } from "../context.js";
import { APP_VERSION } from "../version.js";
import { el, icon } from "../ui.js";

const DESCRICAO_INVENTARIO = {
  ti: "Notebooks, monitores, switches, celulares e periféricos",
  impressora: "Impressoras, suprimentos, contadores e manutenções",
};

const TILES = [
  { path: "ativos", modulo: "ativos", rotulo: "Ativos", icone: "ativos", desc: "Cadastro, patrimônio e QR Code" },
  { path: "produtos", modulo: "produtos", rotulo: "Consumíveis", icone: "produtos", desc: "Toners, cabos, lotes e mínimo" },
  { path: "movimentacoes", modulo: "movimentacoes", rotulo: "Transferências", icone: "movimentacoes", desc: "Entradas, saídas e transferências" },
  { path: "manutencoes", modulo: "manutencoes", rotulo: "Manutenções", icone: "manutencoes", desc: "Ordens, custos e anexos" },
  { path: "scanner", modulo: "scanner", rotulo: "Leitura", icone: "scanner", desc: "Leitor de QR Code e baixa por patrimônio" },
  { path: "emprestimos", modulo: "emprestimos", rotulo: "Empréstimos", icone: "calendario", desc: "Reserva, retirada com termo, devolução e vistoria" },
  { path: "financeiro", modulo: "financeiro", rotulo: "Financeiro", icone: "relatorios", desc: "Valor do parque, garantias, custo por departamento e por página" },
  { path: "contagens", modulo: "contagens", rotulo: "Contagens", icone: "contagens", desc: "Inventário cíclico: conferência física e divergências" },
  { path: "relatorios", modulo: "relatorios", rotulo: "Relatórios", icone: "relatorios", desc: "Indicadores, gráficos, CSV e PDF" },
  { path: "impressao", modulo: "impressao", rotulo: "Impressão", icone: "print", desc: "Impressora da minha planta e etiqueta padrão" },
  { path: "calendario", modulo: "calendario", rotulo: "Calendário", icone: "calendario", desc: "Agenda de empréstimos e devoluções" },
  { path: "cadastros", modulo: "cadastros", rotulo: "Cadastros", icone: "cadastros", desc: "Departamentos, locais e fornecedores" },
  // Canal de retorno da implantação — some do menu quando desativado.
  { path: "reporte", modulo: "reporte", rotulo: "Reporte de Erro", icone: "reporte", desc: "Encontrou um problema? Avise a equipe de TI" },
  { path: "admin", modulo: "admin", rotulo: "Administração", icone: "settings", desc: "Usuários, permissões, impressoras e fotos" },
];

/** Tela de seleção de inventário (após o login). */
export function renderSelecao(root) {
  document.title = "Selecionar inventário — Gestão Patrimonial";
  ctx.setFab(null);
  ctx.setChrome(false);

  const permitidos = state.inventariosPermitidos();
  const cards = permitidos.map((d) => {
    const card = el("button", { class: "inv-card", type: "button" },
      el("div", { class: "inv-icon", html: icon(d === "ti" ? "ativos" : "print", 44) }),
      el("h3", {}, d === "ti" ? "Inventário de TI" : "Inventário de Impressoras"),
      el("p", {}, DESCRICAO_INVENTARIO[d] || ""),
    );
    card.addEventListener("click", () => {
      state.setDominio(d);
      ctx.goHome();
    });
    return card;
  });

  root.innerHTML = "";
  const wrap = el("div", { class: "inv-select" },
    el("h1", { class: "inv-title" }, "O que você vai gerenciar?"),
    el("p", { class: "inv-sub" }, `Bem-vindo(a), ${state.user?.nome || ""}. Escolha um inventário para começar.`),
    el("div", { class: "inv-cards" }, ...cards),
  );
  if (!cards.length) {
    wrap.append(el("p", { class: "text-error" }, "Seu usuário não tem acesso a nenhum inventário. Fale com o administrador."));
  }

  const bar = el("div", { class: "row", style: "margin-top:34px;gap:12px" },
    el("button", { class: "btn text", onclick: () => { state.setTheme(state.theme === "dark" ? "light" : "dark"); ctx.rerender(); },
      html: icon(state.theme === "dark" ? "sun" : "moon", 18) + (state.theme === "dark" ? " Tema claro" : " Tema escuro") }),
    el("button", { class: "btn outlined", onclick: () => { state.logout(); location.reload(); }, html: icon("logout", 18) + " Sair" }),
  );
  wrap.append(bar);
  wrap.append(el("p", { class: "muted", style: "font-size:12px;margin-top:26px" }, `Versão ${APP_VERSION}`));
  root.append(wrap);
}

/** Menu inicial do inventário selecionado. */
export function renderHome(root) {
  document.title = `${state.dominioLabel} — Menu`;
  ctx.setFab(null);
  ctx.setChrome(true);

  const disponiveis = TILES.filter((t) => state.podeModulo(t.modulo));

  const tiles = disponiveis.map((t) => {
    const tile = el("button", { class: "home-tile", type: "button" },
      el("div", { class: "tile-icon", html: icon(t.icone === "settings" ? "cadastros" : t.icone, 26) }),
      el("h3", {}, t.rotulo),
      el("p", {}, t.desc),
    );
    tile.addEventListener("click", () => ctx.navigate(t.path));
    return tile;
  });

  root.innerHTML = "";
  root.append(
    el("h1", { class: "page-title" }, state.dominioLabel),
    el("p", { class: "page-sub" }, "Escolha um módulo para trabalhar. Use o botão de menu no topo para voltar aqui a qualquer momento."),
    el("div", { class: "home-grid" }, ...tiles),
    el("div", { class: "card mt", style: "margin-top:24px" },
      el("div", { class: "row between" },
        el("div", {},
          el("div", { class: "section-title", style: "margin:0" }, "Trocar de inventário"),
          el("div", { class: "muted", style: "font-size:13px" }, "Voltar para a tela inicial de seleção."),
        ),
        el("button", { class: "btn tonal", onclick: () => ctx.navigate("selecao"), html: icon("back", 18) + " Trocar inventário" }),
      ),
    ),
  );
}
