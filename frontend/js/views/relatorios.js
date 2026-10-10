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

/**
 * Filtros dos gráficos.
 *
 * ## O que eles filtram
 *
 * Tudo. O backend calcula as condições **uma vez** e as espalha em todos os
 * blocos (`_condicoes` em `app/routers/graficos.py`) — então o filtro vale do
 * primeiro ao último gráfico.
 *
 * Isso é o que impede o pior caso: alguns gráficos filtrados e outros não, em
 * que os números **parecem** filtrados e não são.
 *
 * `inicio`/`fim` são sobre a DATA DE AQUISIÇÃO: respondem "quanto entrou
 * neste período".
 */
const filtrosGraficos = {
  inicio: "",
  fim: "",
  planta_id: "",
  forma_aquisicao: "",
  contrato_id: "",
};

/** Os filtros que estão ativos, no formato da query. */
function filtrosAtivos() {
  const q = {};
  for (const [k, v] of Object.entries(filtrosGraficos)) {
    if (v) q[k] = v;
  }
  return q;
}


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

// ---------------------------------------------------------------------------
// Parque: comprado x locado
// ---------------------------------------------------------------------------
/**
 * Bloco do parque por forma de aquisição.
 *
 * Depois da locação, "valor do parque" deixou de ser um número só. Somar
 * patrimônio com mensalidade daria um valor sem significado — por isso os
 * dois aparecem **separados**, e nunca somados.
 */
function blocoParque(p) {
  if (!p) return el("div");

  // Duas formatações, de propósito.
  //
  // O mensal de um contrato é da ordem de milhares: os centavos são ruído.
  // Já o custo POR EQUIPAMENTO fica na casa das dezenas — ali "R$ 20" em vez
  // de "R$ 19,89" esconde justamente a diferença que se quer comparar entre
  // contratos.
  const reaisGrande = (v) => Number(v || 0).toLocaleString("pt-BR", {
    style: "currency", currency: "BRL", maximumFractionDigits: 0,
  });
  const reaisExato = (v) => Number(v || 0).toLocaleString("pt-BR", {
    style: "currency", currency: "BRL", minimumFractionDigits: 2,
  });
  const inteiro = (v) => Number(v || 0).toLocaleString("pt-BR");

  const semLocacao = !p.locados;
  const semCompra = !p.comprados;

  const cartoes = [
    el("div", { class: "chart-card" },
      el("h3", {}, "Composição do parque"),
      el("p", { class: "chart-sub" }, "Quanto é nosso e quanto é alugado"),
      el("div", { html: donut(p.composicao || []) }),
    ),
    el("div", { class: "chart-card" },
      el("h3", {}, "Financeiro"),
      el("p", { class: "chart-sub" }, "As duas naturezas, separadas"),
      el("div", { class: "parque-numeros" },
        el("div", {},
          el("div", { class: "dica" }, "Patrimônio (comprado)"),
          el("b", {}, reaisGrande(p.valor_patrimonial)),
          el("div", { class: "muted", style: "font-size:12px" },
            semCompra ? "Nenhum equipamento comprado" : `${p.comprados} ativo(s)`)),
        el("div", {},
          el("div", { class: "dica" }, "Custo mensal (locado)"),
          el("b", {}, reaisGrande(p.custo_mensal)),
          el("div", { class: "muted", style: "font-size:12px" },
            semLocacao ? "Nenhum contrato ativo" : `${p.locados} ativo(s)`)),
        el("div", {},
          el("div", { class: "dica" }, "Locação — próximos 12 meses"),
          el("b", {}, reaisGrande(p.custo_12_meses))),
      ),
      // A frase que evita a leitura errada: sem ela, alguém soma os dois e
      // conclui que o parque vale patrimônio + mensalidade.
      el("p", { class: "muted", style: "font-size:12px;margin:12px 0 0" },
        "Equipamento locado não é patrimônio da empresa: ele não entra no "
        + "valor patrimonial nem deprecia. O custo dele é a mensalidade."),
    ),
  ];

  // O ranking só faz sentido se houver locação.
  if (!semLocacao && (p.top_contratos || []).length) {
    const linhas = p.top_contratos.map((c) => el("tr", {},
      // `num` alinha à direita e usa números tabulares: sem isso, as colunas
      // de valor ficam com os dígitos desencontrados, e comparar duas linhas
      // exige ler cada número inteiro.
      el("td", { class: "col-nome" }, c.contrato),
      el("td", { class: "num" }, inteiro(c.ativos)),
      el("td", { class: "num" }, reaisGrande(c.mensal)),
      el("td", { class: "num destaque" }, reaisExato(c.por_ativo)),
    ));
    cartoes.push(el("div", { class: "chart-card", style: "grid-column:1/-1" },
      el("h3", {}, "Maiores contratos de locação"),
      el("p", { class: "chart-sub" },
        "Onde a renovação vale negociação. O custo por equipamento usa só "
        + "este inventário."),
      el("div", { class: "table-wrap" },
        el("table", { class: "tabela-numeros" },
          el("thead", {}, el("tr", {},
            el("th", {}, "Contrato"),
            el("th", { class: "num" }, "Ativos"),
            el("th", { class: "num" }, "Mensal"),
            el("th", { class: "num" }, "Por equipamento"))),
          el("tbody", {}, ...linhas))),
    ));
  }

  return el("div", {},
    el("h2", { class: "section-title", style: "margin:24px 0 12px" },
      "Parque: comprado e locado"),
    el("div", { class: "charts-grid" }, ...cartoes),
  );
}

/**
 * Barra de filtros dos gráficos.
 *
 * Carrega as opções de planta e contrato do servidor — e **tolera falha**:
 * se uma delas não vier, a barra aparece sem aquele campo em vez de derrubar
 * o relatório inteiro. Filtro é acessório; os gráficos é que são o conteúdo.
 */
async function barraFiltros(container) {
  const [plantas, contratos] = await Promise.all([
    api.get("/plantas").catch(() => []),
    api.get("/contratos").catch(() => []),
  ]);

  const campo = (rotulo, entrada) =>
    el("div", { class: "field", style: "margin:0" }, el("label", {}, rotulo), entrada);

  const inicio = el("input", { type: "date", value: filtrosGraficos.inicio || "" });
  const fim = el("input", { type: "date", value: filtrosGraficos.fim || "" });
  const planta = el("select", {},
    el("option", { value: "" }, "Todas"),
    ...(plantas || []).map((p) => el("option", {
      value: p.id, selected: String(filtrosGraficos.planta_id) === String(p.id) ? "selected" : null,
    }, `${p.sigla} — ${p.nome}`)));
  const forma = el("select", {},
    el("option", { value: "" }, "Todas"),
    el("option", { value: "comprado", selected: filtrosGraficos.forma_aquisicao === "comprado" ? "selected" : null }, "Comprados"),
    el("option", { value: "locado", selected: filtrosGraficos.forma_aquisicao === "locado" ? "selected" : null }, "Locados"));
  const contrato = el("select", {},
    el("option", { value: "" }, "Todos"),
    ...(contratos || []).map((c) => el("option", {
      value: c.id, selected: String(filtrosGraficos.contrato_id) === String(c.id) ? "selected" : null,
    }, c.numero)));

  // Aplicar recarrega só os gráficos, sem recarregar a página.
  function aplicar() {
    filtrosGraficos.inicio = inicio.value;
    filtrosGraficos.fim = fim.value;
    filtrosGraficos.planta_id = planta.value;
    filtrosGraficos.forma_aquisicao = forma.value;
    filtrosGraficos.contrato_id = contrato.value;
    renderGraficos(container);
  }
  for (const campo_ of [inicio, fim, planta, forma, contrato]) {
    campo_.addEventListener("change", aplicar);
  }

  const limpar = el("button", {
    class: "btn text small", type: "button",
    onclick: () => {
      for (const k of Object.keys(filtrosGraficos)) filtrosGraficos[k] = "";
      inicio.value = ""; fim.value = "";
      planta.value = ""; forma.value = ""; contrato.value = "";
      renderGraficos(container);
    },
  }, "Limpar filtros");

  const ativos = Object.values(filtrosGraficos).filter(Boolean).length;

  return el("div", { class: "card", style: "margin-bottom:14px" },
    el("div", { class: "row between wrap", style: "gap:10px;align-items:center" },
      el("div", {},
        el("div", { class: "section-title", style: "margin:0" }, "Filtros"),
        el("p", { class: "muted", style: "font-size:12.5px;margin:4px 0 0" },
          ativos
            // Dizer que há recorte aplicado evita ler os números como se
            // fossem do parque inteiro.
            ? `${ativos} filtro(s) aplicado(s) — os números abaixo refletem só este recorte.`
            : "Valem para todos os gráficos. A data é a de aquisição.")),
      ativos ? limpar : null),
    el("div", { class: "grade", style: "margin-top:12px" },
      campo("Adquirido de", inicio),
      campo("Adquirido até", fim),
      campo("Planta", planta),
      campo("Aquisição", forma),
      campo("Contrato", contrato),
    ),
  );
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
    g = await api.get("/relatorios/graficos", {
      dominio: state.dominio, meses: 6, ...filtrosAtivos(),
    });
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
    // A barra vem ANTES de tudo: os números abaixo são o resultado dela, e
    // quem chega precisa saber que há um recorte aplicado.
    container.append(await barraFiltros(container));
    if (kpis) container.append(kpis);
    // O parque vem ANTES dos gráficos de composição: é o número que a
    // gestão procura primeiro depois da locação — quanto é nosso e quanto
    // é alugado.
    container.append(blocoParque(g.parque));
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
