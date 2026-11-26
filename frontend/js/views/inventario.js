/**
 * Tela inicial de SELEÇÃO DE INVENTÁRIO e o MENU INICIAL de cada inventário.
 * @module views/inventario
 */
import { state } from "../state.js";
import { api } from "../api.js";
import { ctx } from "../context.js";
import { APP_VERSION } from "../version.js";
import { el, icon, skeleton } from "../ui.js";

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
  { path: "seguranca", modulo: "seguranca", rotulo: "Segurança da conta", icone: "settings", desc: "Verificação em duas etapas e códigos de recuperação" },
  { path: "monitor", modulo: "monitor", rotulo: "Monitor de impressoras", icone: "print", desc: "Contador e tonner lidos direto da impressora" },
  { path: "emprestimos", modulo: "emprestimos", rotulo: "Empréstimos", icone: "calendario", desc: "Reserva, retirada com termo, devolução e vistoria" },
  { path: "software", modulo: "software", rotulo: "Software e licenças", icone: "produtos", desc: "Licenças, conformidade e o que está instalado" },
  { path: "descarte", modulo: "descarte", rotulo: "Certificado de descarte", icone: "trash", desc: "Baixa de ativo com destino, fundamento e selo de conferência" },
  { path: "contratos", modulo: "contratos", rotulo: "Contratos", icone: "relatorios", desc: "Locação, comodato e compra — custo mensal e vencimento" },
  { path: "financeiro", modulo: "financeiro", rotulo: "Financeiro", icone: "relatorios", desc: "Valor do parque, garantias, custo por departamento e por página" },
  { path: "contagens", modulo: "contagens", rotulo: "Contagens", icone: "contagens", desc: "Inventário cíclico: conferência física e divergências" },
  { path: "relatorios", modulo: "relatorios", rotulo: "Relatórios", icone: "relatorios", desc: "Indicadores, gráficos, CSV e PDF" },
  { path: "impressao", modulo: "impressao", rotulo: "Impressão", icone: "print", desc: "Impressora da minha planta e etiqueta padrão" },
  { path: "avisos", modulo: "avisos", rotulo: "Avisos", icone: "bell", desc: "Devoluções, contratos vencendo e pendências" },
  { path: "calendario", modulo: "calendario", rotulo: "Calendário", icone: "calendario", desc: "Agenda de empréstimos, devoluções e contratos" },
  // Quadro de tarefas. Liberado por usuário, como as demais telas.
  { path: "kanban", modulo: "kanban", rotulo: "Kanban", icone: "kanban", desc: "Tarefas em colunas, com checklist e prazos" },
  { path: "mapa", modulo: "mapa", rotulo: "Mapa 3D", icone: "grade", desc: "Encontre equipamentos na planta da unidade" },
  { path: "cadastros", modulo: "cadastros", rotulo: "Cadastros", icone: "cadastros", desc: "Departamentos, locais e fornecedores" },
  // Canal de retorno da implantação — some do menu quando desativado.
  { path: "reporte", modulo: "reporte", rotulo: "Reporte de Erro", icone: "reporte", desc: "Encontrou um problema? Avise a equipe de TI" },
  { path: "admin", modulo: "admin", rotulo: "Administração", icone: "settings", desc: "Usuários, permissões, impressoras e fotos" },
];

/** Tela de seleção de inventário (após o login). */
export function renderSelecao(root) {
  document.title = "Selecionar inventário — Nexus";
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

const atalhos = ["mapa", "monitor", "produtos", "relatorios"];
const numero = new Intl.NumberFormat("pt-BR");

function indicador(rotulo, valor, icone) {
  return el("div", { class: "card inicio-indicador" },
    el("span", { class: "inicio-indicador-rotulo" }, el("span", { html: icon(icone, 23) }), rotulo),
    el("strong", {}, numero.format(valor ?? 0)));
}

function pendencia(rotulo, valor, icone, destino) {
  return el("button", { type: "button", class: "inicio-pendencia", onclick: () => ctx.navigate(destino) },
    el("span", { class: "inicio-pendencia-icone", html: icon(icone, 20) }), rotulo,
    el("strong", {}, numero.format(valor)), el("span", { html: icon("chevR", 16) }));
}

async function carregarResumo(root) {
  const dominio = state.dominio;
  const temRelatorios = state.podeModulo("relatorios");
  const temEmprestimos = state.podeModulo("emprestimos");
  const [stats, graficos, avisos] = await Promise.allSettled([
    temRelatorios ? api.get("/dashboard/stats", { dominio }) : null,
    temRelatorios ? api.get("/relatorios/graficos", { dominio }) : null,
    temEmprestimos ? api.get("/notificacoes") : null,
  ]);
  if (!root.isConnected) return;
  const dados = stats.value;
  const departamentos = graficos.value?.departamento?.slice(0, 5) || [];
  const maximo = Math.max(1, ...departamentos.map(d => d.valor));
  const fila = el("div", { class: "inicio-paineis" });
  root.replaceChildren();
  if (dados) {
    const status = dados.por_status || {};
    root.append(el("div", { class: "inicio-indicadores" },
      indicador("Total de ativos", dados.total, "ativos"), indicador("Alocados", dados.alocados, "user"),
      indicador("Em estoque", status.estoque, "produtos"), indicador("Em manutenção", status.manutencao, "manutencoes")));
  } else if (temRelatorios) {
    root.append(el("p", { class: "muted", role: "status" }, "Os indicadores estão indisponíveis. Os módulos continuam acessíveis abaixo."));
  }
  if (graficos.value) {
    fila.append(el("section", { class: "card inicio-departamentos" },
      el("h2", { class: "section-title" }, "Ativos por departamento"),
      departamentos.length ? el("ul", {},
        ...departamentos.map(d => el("li", {},
          el("span", {}, d.rotulo),
          el("span", { class: "inicio-barra", "aria-hidden": "true" },
            el("span", { style: `width:${100 * d.valor / maximo}%` })),
          el("strong", {}, numero.format(d.valor))))) : el("p", { class: "muted" }, "Nenhum ativo por departamento neste inventário.")));
  }
  const itens = [];
  if (dados) itens.push(pendencia("Garantias a vencer em 30 dias", dados.garantias?.["30"] ?? 0, "shield", "relatorios"));
  if (graficos.value && state.podeModulo("manutencoes")) {
    const abertas = graficos.value.manutencoes_status?.find(x => x.rotulo === "Aberta")?.valor ?? 0;
    itens.push(pendencia("Manutenções abertas", abertas, "manutencoes", "manutencoes"));
  }
  if (avisos.value) {
    const atrasados = (avisos.value.itens || []).filter(x => x.tipo === "emprestimo_atrasado").length;
    itens.push(pendencia("Devoluções atrasadas na planta", atrasados, "historico", "emprestimos"));
  }
  if (itens.length) fila.append(el("section", { class: "card inicio-pendencias" },
    el("h2", { class: "section-title" }, "Pendências"), ...itens));
  if (fila.childElementCount) root.append(fila);
}

/** Visão geral do inventário e acesso a todos os módulos disponíveis. */
export function renderHome(root) {
  document.title = `${state.dominioLabel} — Menu`;
  ctx.setFab(null);
  ctx.setChrome(true);

  const disponiveis = TILES.filter((t) => state.podeModulo(t.modulo));
  const resumo = el("div", { class: "inicio-resumo" });
  const rapidos = atalhos.map(path => disponiveis.find(t => t.path === path)).filter(Boolean);

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
    el("div", { class: "inicio-cabecalho row between wrap" },
      el("div", {}, el("h1", { class: "page-title" }, "Visão geral"),
        el("p", { class: "page-sub" }, state.dominioLabel)),
      state.podeModulo("ativos") ? el("button", { class: "btn filled", onclick: () => ctx.navigate("ativos") }, "Ver ativos") : null),
    resumo,
    rapidos.length ? el("section", { class: "inicio-atalhos" }, el("h2", { class: "section-title" }, "Acessos rápidos"),
      el("div", { class: "inicio-atalhos-grade" }, ...rapidos.map(t =>
        el("button", { class: "card inicio-atalho", type: "button", onclick: () => ctx.navigate(t.path) },
          el("span", { html: icon(t.icone, 23) }), t.rotulo)))) : null,
    el("h2", { class: "section-title inicio-modulos-titulo" }, "Todos os módulos"),
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
  if (state.podeModulo("relatorios") || state.podeModulo("emprestimos")) {
    resumo.append(skeleton(2));
    carregarResumo(resumo);
  }
}
