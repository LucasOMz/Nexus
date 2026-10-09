/**
 * Relatórios: gráficos de inventário (visualização rápida), exportação CSV/PDF
 * e filtros salvos.
 * @module views/relatorios
 */
import { api } from "../api.js";
import { state } from "../state.js";
import { ctx } from "../context.js";
import { el, icon, toast, dialog, confirmSheet, skeleton, fmtMoney, fmtMoneyCurto, statusBadge, mostrarErro } from "../ui.js";
import { donut, barsH, barsV, linhaMensal } from "../charts.js";
import { mensagemErro } from "../erros.js";

async function download(url, filename) {
  try {
    const res = await fetch(url, { headers: { Authorization: "Bearer " + state.access } });
    if (!res.ok) { const j = await res.json().catch(() => ({})); toast(mensagemErro(j.detail, res.status)); return; }
    const blob = await res.blob();
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = filename;
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 5000);
  } catch { toast("Sem conexão"); }
}

function chartCard(titulo, subtitulo, svgHtml) {
  const card = el("div", { class: "chart-card" },
    el("h3", {}, titulo),
    subtitulo ? el("p", { class: "chart-sub" }, subtitulo) : null,
    el("div", { html: svgHtml }),
  );
  return card;
}

// ---------------------------------------------------------------------------
// Indicadores rápidos (conteúdo do antigo Dashboard, agora no topo)
// ---------------------------------------------------------------------------
function kpi(label, valor, icone) {
  return el("div", { class: "kpi" },
    el("div", { class: "kpi-icon", html: icon(icone, 28) }),
    el("div", { class: "kpi-value" }, String(valor)),
    el("div", { class: "kpi-label" }, label),
  );
}

/** KPIs do dashboard no topo dos relatórios. Sem dados, não mostra nada. */
function linhaKpis(stats) {
  if (!stats) return null;
  const isTI = state.dominio === "ti";
  const cards = [
    kpi("Total de ativos", stats.total ?? 0, isTI ? "ativos" : "print"),
    kpi("Alocados", stats.alocados ?? 0, "user"),
    kpi("Em manutenção", stats.por_status?.manutencao ?? 0, "manutencoes"),
    isTI
      ? kpi("Em estoque", stats.por_status?.estoque ?? 0, "produtos")
      : kpi("Contador total", stats.extra?.contador_total ?? 0, "counter"),
  ];
  if (!isTI) cards.push(kpi("Suprimentos baixos", stats.extra?.suprimentos_baixos ?? 0, "produtos"));
  return el("div", { class: "kpi-grid" }, ...cards);
}

// ---------------------------------------------------------------------------
// Drill-down: clicar num gráfico abre a lista daquele item
// ---------------------------------------------------------------------------
const ROTULO_PARA_STATUS = {
  "em estoque": "estoque", reservado: "reservado", "em uso": "em_uso",
  manutenção: "manutencao", descartado: "descartado", emprestado: "emprestado",
};

/** Converte o nome exibido no gráfico no id da entidade (categoria, local…). */
async function idPorNome(rota, nome) {
  try {
    const itens = await api.get(`/${rota}`);
    const achado = (itens || []).find((i) => (i.nome || "").toLowerCase() === String(nome).toLowerCase());
    return achado ? achado.id : null;
  } catch { return null; }
}

/** Abre a lista de ativos correspondente ao item clicado no gráfico. */
async function abrirDrill(campo, rotulo) {
  const query = { dominio: state.dominio, size: 200 };
  let aproximado = false;

  if (campo === "status") {
    query.status = ROTULO_PARA_STATUS[String(rotulo).toLowerCase()] || String(rotulo).toLowerCase();
  } else if (campo === "categoria" || campo === "localizacao" || campo === "departamento") {
    const rota = { categoria: "categorias", localizacao: "localizacoes", departamento: "departamentos" }[campo];
    const id = await idPorNome(rota, rotulo);
    if (id) query[`${campo}_id`] = id;
    else { query.search = rotulo; aproximado = true; }
  } else {
    // Garantias, SO, RAM, contador e suprimentos não têm filtro dedicado.
    query.search = String(rotulo).replace(/\s*(dias|GB)$/i, "").trim();
    aproximado = true;
  }

  const box = el("div", {});
  dialog({ title: `${rotulo}`, wide: true, body: box, actions: [{ label: "Fechar", variant: "text" }] });
  box.append(skeleton(2));

  try {
    const dados = await api.get("/ativos", query);
    const itens = dados.items || [];
    box.innerHTML = "";
    box.append(el("p", { class: "muted", style: "margin-top:0" },
      `${dados.total} ativo(s) neste inventário${aproximado ? " — resultado aproximado (busca por texto)" : ""}.`));
    if (!itens.length) {
      box.append(el("p", { class: "muted" }, "Nenhum ativo encontrado com esse critério."));
      return;
    }
    const lista = el("div", {});
    itens.forEach((a) => {
      const linha = el("div", { class: "list-row", style: "cursor:pointer" },
        el("div", { class: "list-main" },
          el("div", { class: "list-title" }, a.patrimonio),
          el("div", { class: "list-sub" }, `${a.modelo || "sem modelo"} · ${a.marca || "sem marca"}`),
        ),
        el("div", { class: "row" }, el("span", { html: statusBadge(a.status) })),
      );
      linha.addEventListener("click", () => {
        // Leva para Ativos já filtrado pelo item e com ele destacado, para a
        // pessoa não se perder na lista depois de clicar no gráfico.
        location.hash = `#/ativos?busca=${encodeURIComponent(a.patrimonio)}&destaque=${a.id}`;
      });
      lista.append(linha);
    });
    box.append(lista);
  } catch (e) {
    box.innerHTML = "";
    box.append(el("p", { class: "text-error" }, e.message));
  }
}

// ---------------------------------------------------------------------------
// Gráficos
// ---------------------------------------------------------------------------
async function renderGraficos(container) {
  container.innerHTML = "";
  container.append(skeleton(4));

  const falhar = (mensagem) => {
    container.innerHTML = "";
    container.append(
      el("div", { class: "card" },
        el("p", { class: "text-error", style: "margin:0 0 12px" }, mensagem),
        el("button", {
          class: "btn tonal small",
          onclick: () => renderGraficos(container),
          html: icon("refresh", 18) + " Tentar novamente",
        }),
      ),
    );
  };

  let g;
  let stats = null;
  try {
    g = await api.get("/relatorios/graficos", { dominio: state.dominio, meses: 6 });
    // Indicadores do antigo Dashboard, agora no topo (best-effort).
    stats = await api.get("/dashboard/stats", { dominio: state.dominio }).catch(() => null);
  } catch (e) {
    falhar(e.message);
    return;
  }

  // A montagem dos gráficos também pode falhar (dado inesperado). Sem este
  // try, o esqueleto de carregamento ficava na tela para sempre e sem aviso.
  try {
    const isTI = state.dominio === "ti";

    // `texto` é a versão curta (cabe na barra); `completo` vai no tooltip.
    const valorCategoria = (g.valor_categoria || []).map((d) => ({
      rotulo: d.rotulo,
      valor: d.valor,
      texto: fmtMoneyCurto(d.valor),
      completo: fmtMoney(d.valor),
    }));

    const cards = [
      chartCard("Ativos por status", "Situação atual do inventário", donut(g.status, { campo: "status" })),
      chartCard("Ativos por categoria", "Onde está concentrado o parque", barsH(g.categoria, { campo: "categoria" })),
      chartCard("Ativos por localização", "Distribuição física", barsH(g.localizacao, { campo: "localizacao" })),
      chartCard("Ativos por departamento", "Responsabilidade por área", barsH(g.departamento, { campo: "departamento" })),
      chartCard("Valor patrimonial por categoria", "Investimento por tipo de item", barsH(valorCategoria, { campo: "categoria" })),
      chartCard("Garantias a vencer", "Próximos 30, 60 e 90 dias", barsV(g.garantias, { campo: "garantia" })),
      chartCard("Movimentações por mês", "Entradas x saídas (últimos 6 meses)", linhaMensal(g.movimentacoes_mes)),
      chartCard("Manutenções por situação", "Ordens abertas, em andamento e concluídas", donut(g.manutencoes_status, { campo: "manutencao" })),
    ];

    if (isTI) {
      cards.push(chartCard("Sistemas operacionais", "Distribuição do parque de TI", barsH((g.extra || {}).por_so || [], { campo: "so" })));
      cards.push(chartCard("Memória RAM", "Capacidade instalada", barsH((g.extra || {}).por_ram || [], { campo: "ram" })));
    } else {
      cards.push(chartCard("Contador por impressora", "Volume de páginas impressas", barsH((g.extra || {}).contador_por_impressora || [], { campo: "contador" })));
      cards.push(chartCard("Suprimentos abaixo do mínimo", "Itens que precisam de reposição", barsH((g.extra || {}).suprimentos_baixos || [], { campo: "suprimento" })));
    }

    const grid = el("div", { class: "charts-grid" }, ...cards);

    // Um único listener para todos os gráficos: clicar abre a lista do item.
    grid.addEventListener("click", (ev) => {
      const alvo = ev.target.closest("[data-drill]");
      if (!alvo) return;
      abrirDrill(alvo.dataset.drill || "", alvo.dataset.rotulo || "");
    });

    const kpis = linhaKpis(stats);
    container.innerHTML = "";
    if (kpis) container.append(kpis);
    container.append(grid);
  } catch (e) {
    falhar(`Não foi possível montar os gráficos: ${e.message}`);
  }
}

// ---------------------------------------------------------------------------
// Exportação
// ---------------------------------------------------------------------------
function reportCard(title, desc, { buildUrl, inputs = [] }) {
  return el("div", { class: "card" },
    el("h3", { style: "margin:0 0 4px;font-size:15px" }, title),
    el("p", { class: "muted", style: "margin:0 0 14px;font-size:13px" }, desc),
    ...inputs,
    el("div", { class: "row", style: "gap:8px" },
      el("button", { class: "btn tonal small", onclick: () => download(buildUrl("csv"), `${title.toLowerCase().replace(/\s/g, "_")}.csv`) }, "Baixar CSV"),
      el("button", { class: "btn tonal small", onclick: () => download(buildUrl("pdf"), `${title.toLowerCase().replace(/\s/g, "_")}.pdf`) }, "Baixar PDF"),
    ),
  );
}

async function saveFilter() {
  const nome = el("input", { placeholder: "Nome do filtro" });
  const status = el("select", {}, el("option", { value: "" }, "Todos"), ...["estoque", "em_uso", "manutencao", "descartado"].map((s) => el("option", { value: s }, s)));
  dialog({
    title: "Salvar filtro de inventário",
    body: el("div", {},
      el("div", { class: "field" }, el("label", {}, "Nome"), nome),
      el("div", { class: "field" }, el("label", {}, "Status"), status),
    ),
    actions: [
      { label: "Cancelar", variant: "text" },
      { label: "Salvar", variant: "filled", onClick: async (close) => {
        if (!nome.value.trim()) { toast("Informe um nome"); return; }
        try {
          await api.post("/relatorios/filtros", { nome: nome.value.trim(), tipo: "inventario", filtros: { dominio: state.dominio, status: status.value } });
          close(); toast("Filtro salvo"); renderRelatorios(document.getElementById("view"));
        } catch (e) { mostrarErro(e); }
      } },
    ],
  });
}

async function filtrosSection(root) {
  const wrap = el("div", { class: "card mt" }, el("h3", { style: "margin:0 0 10px;font-size:15px" }, "Filtros salvos"));
  try {
    const filtros = await api.get("/relatorios/filtros");
    if (!filtros.length) wrap.append(el("p", { class: "muted", style: "margin:0" }, "Nenhum filtro salvo."));
    for (const f of filtros) {
      wrap.append(el("div", { class: "list-row" },
        el("div", { class: "list-main" },
          el("div", { class: "list-title" }, f.nome),
          el("div", { class: "list-sub" }, JSON.stringify(f.filtros || {})),
        ),
        el("div", { class: "row" },
          el("button", { class: "iconbtn", title: "Aplicar", onclick: () => { sessionStorage.setItem("filtro_status", f.filtros?.status || ""); ctx.navigate("ativos"); }, html: icon("check", 20) }),
          el("button", { class: "iconbtn", title: "Excluir", onclick: async () => {
            if (await confirmSheet("Excluir filtro", `Excluir ${f.nome}?`)) { await api.del(`/relatorios/filtros/${f.id}`); filtrosSection(root); }
          }, html: icon("trash", 20) }),
        ),
      ));
    }
  } catch (e) { wrap.append(el("p", { class: "muted" }, e.message)); }
  root.append(wrap);
}

export async function renderRelatorios(root) {
  ctx.setTitle("Relatórios");
  ctx.setFab(null);

  const base = "/api/v1/relatorios";
  const invStatus = el("select", { class: "chip" }, el("option", { value: "" }, "Todos os status"), ...["estoque", "em_uso", "manutencao", "descartado", "emprestado", "reservado"].map((s) => el("option", { value: s }, s.replace(/_/g, " "))));
  const garDias = el("input", { type: "number", min: 1, max: 365, value: 90, class: "chip", style: "width:96px" });
  const movDe = el("input", { type: "date", class: "chip" });
  const movAte = el("input", { type: "date", class: "chip" });

  root.innerHTML = "";
  root.append(
    el("h1", { class: "page-title" }, "Relatórios"),
    el("p", { class: "page-sub" }, `${state.dominioLabel} — gráficos para leitura rápida e exportação em CSV/PDF.`),
    el("h2", { class: "section-title" }, "Visão geral"),
  );

  const graficosBox = el("div", {});
  root.append(graficosBox);
  // Sem o catch, qualquer falha virava "rejeição não tratada" e o esqueleto
  // de carregamento ficava na tela para sempre.
  renderGraficos(graficosBox).catch((e) => {
    graficosBox.innerHTML = "";
    graficosBox.append(el("p", { class: "text-error" }, `Não foi possível carregar os gráficos: ${e.message}`));
  });

  root.append(el("h2", { class: "section-title", style: "margin-top:32px" }, "Exportar dados"));

  const cards = [
    reportCard("Inventário", "Lista de ativos do inventário atual.", {
      inputs: [invStatus],
      buildUrl: (f) => `${base}/inventario?dominio=${state.dominio}&status=${invStatus.value}&formato=${f}`,
    }),
    reportCard("Ativos por usuário", "Ativos atribuídos a colaboradores.", { buildUrl: (f) => `${base}/ativos-por-usuario?formato=${f}` }),
    reportCard("Movimentações", "Histórico por período.", {
      inputs: [el("div", { class: "row" }, movDe, movAte)],
      buildUrl: (f) => `${base}/movimentacoes?formato=${f}&data_inicio=${movDe.value ? new Date(movDe.value).toISOString() : ""}&data_fim=${movAte.value ? new Date(movAte.value + "T23:59:59").toISOString() : ""}`,
    }),
    reportCard("Manutenções", "Histórico completo de manutenções.", { buildUrl: (f) => `${base}/manutencoes?formato=${f}` }),
    reportCard("Garantias", "Garantias a vencer no período.", {
      inputs: [el("div", { class: "row" }, el("span", { class: "muted" }, "Dias:"), garDias)],
      buildUrl: (f) => `${base}/garantias?dias=${garDias.value || 90}&formato=${f}`,
    }),
    reportCard("Consumíveis abaixo do mínimo", "Itens com saldo abaixo do estoque mínimo.", { buildUrl: (f) => `${base}/consumiveis-minimo?dominio=${state.dominio}&formato=${f}` }),
  ];
  root.append(el("div", { class: "charts-grid" }, ...cards));

  root.append(el("button", { class: "btn tonal mt", onclick: () => saveFilter(), html: icon("add", 18) + " Salvar filtro atual" }));
  await filtrosSection(root);
}
