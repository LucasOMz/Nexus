/**
 * Inventário cíclico (contagem) — conferência física.
 *
 * Duas telas:
 *
 * * **lista** — as contagens abertas e encerradas, com o progresso de cada uma
 * * **divergências** — em tela cheia: conforme, não encontrado e não cadastrado
 *
 * A tela de divergências é o que dá sentido ao trabalho: sem ela, escanear
 * milhares de itens não prova nada a uma auditoria.
 *
 * @module views/contagens
 */
import { api } from "../api.js";
import { state } from "../state.js";
import { ctx } from "../context.js";
import { el, icon, toast, dialog, confirmSheet, emptyState, skeleton, fmtDate, mostrarErro } from "../ui.js";
import { loadLookups, optionsOf } from "../lookups.js";

const PAGE_SIZE = 20;
let page = 1;
let filtroStatus = "";
let lookupsCache = null;

const ROTULO_STATUS = {
  aberta: "Aberta",
  em_contagem: "Em contagem",
  finalizada: "Finalizada",
  aprovada: "Aprovada",
  cancelada: "Cancelada",
};

const COR_STATUS = {
  aberta: "chip",
  em_contagem: "chip aviso",
  finalizada: "chip info",
  aprovada: "chip ok",
  cancelada: "chip neutro",
};

export async function renderContagens(root) {
  ctx.setTitle("Contagens");
  // O formato do FAB é { label, icon, onClick } — em inglês, como em todas as
  // outras telas. Nomes trocados aqui davam um botão sem ícone e sem ação.
  ctx.setFab(state.canWrite
    ? { label: "Nova contagem", icon: "plus", onClick: () => abrirNova(root) }
    : null);

  root.innerHTML = "";
  // Sem botão no cabeçalho de propósito: o FAB ("+") já abre uma nova contagem
  // e fica sempre visível. Dois botões para a mesma ação só confundem.
  root.append(
    el("h1", { class: "page-title" }, "Inventário cíclico"),
    el("p", { class: "muted", style: "margin:0 0 18px" },
      "Conferência física do inventário: escaneie o que existe e o sistema aponta as divergências."),
  );

  const filtros = el("div", { class: "row wrap", style: "gap:8px;margin-bottom:16px" });
  for (const [valor, rotulo] of [["", "Todas"], ["aberta", "Abertas"], ["em_contagem", "Em andamento"],
                                  ["finalizada", "Aguardando aprovação"], ["aprovada", "Aprovadas"]]) {
    filtros.append(el("button", {
      class: `chip${filtroStatus === valor ? " selected" : ""}`,
      onclick: () => { filtroStatus = valor; page = 1; renderContagens(root); },
    }, rotulo));
  }
  root.append(filtros);

  const lista = el("div", {}, skeleton(4));
  root.append(lista);

  let dados;
  try {
    const q = { page, size: PAGE_SIZE };
    if (filtroStatus) q.status = filtroStatus;
    dados = await api.get("/contagens", q);
  } catch (e) {
    lista.innerHTML = "";
    lista.append(el("p", { class: "text-error" }, e.message));
    return;
  }

  lista.innerHTML = "";
  if (!dados.items?.length) {
    lista.append(emptyState(
      "Nenhuma contagem",
      filtroStatus
        ? "Nenhuma contagem com essa situação."
        : "Use o botão + para abrir a primeira contagem e conferir o inventário da planta.",
    ));
    return;
  }

  lista.append(el("div", { class: "cartoes" }, ...dados.items.map((c) => cartao(c, root))));

  if (dados.pages > 1) {
    lista.append(el("div", { class: "row", style: "justify-content:center;gap:10px;margin-top:16px" },
      el("button", { class: "btn tonal", disabled: page <= 1,
        onclick: () => { page--; renderContagens(root); }, html: icon("chevL") }),
      el("span", { class: "muted", style: "align-self:center" }, `${page} de ${dados.pages}`),
      el("button", { class: "btn tonal", disabled: page >= dados.pages,
        onclick: () => { page++; renderContagens(root); }, html: icon("chevR") }),
    ));
  }
}

function cartao(c, root) {
  const total = c.esperados || 0;
  const lidos = c.lidos || 0;
  const pct = total ? Math.min(100, Math.round((lidos / total) * 100)) : 0;

  return el("div", { class: "cartao-contagem" },
    el("div", { class: "row between wrap", style: "gap:10px" },
      el("b", { style: "font-size:15px" }, c.nome),
      el("span", { class: COR_STATUS[c.status] || "chip" }, ROTULO_STATUS[c.status] || c.status),
    ),
    el("div", { class: "muted", style: "font-size:12.5px;margin-top:4px" },
      [
        c.dominio ? (c.dominio === "ti" ? "Ativos de TI" : "Impressoras") : "Todos os inventários",
        `aberta em ${fmtDate(c.aberta_em, true)}`,
        c.baixados ? `${c.baixados} baixado(s) na aprovação` : null,
      ].filter(Boolean).join(" · "),
    ),

    el("div", { class: "progresso" },
      el("div", { class: "progresso-barra", style: `width:${pct}%` }),
    ),
    el("div", { class: "muted", style: "font-size:12.5px;margin-top:6px" },
      `${lidos} lido(s) de ${total} esperado(s) — ${pct}%`,
      c.nao_cadastrados ? ` · ${c.nao_cadastrados} não cadastrado(s)` : "",
    ),

    el("div", { class: "row wrap", style: "gap:8px;margin-top:12px" },
      el("button", { class: "btn tonal",
        onclick: () => verDivergencias(c.id),
        html: icon("relatorios", 16) + " Divergências" }),
      (c.status === "aberta" || c.status === "em_contagem") && state.canWrite
        ? el("button", { class: "btn tonal", onclick: () => finalizar(c, root),
            html: icon("check", 16) + " Finalizar" })
        : null,
      c.status === "finalizada" && state.isAdmin
        ? el("button", { class: "btn filled", onclick: () => aprovar(c, root),
            html: icon("check", 16) + " Aprovar" })
        : null,
      (c.status === "aberta" || c.status === "em_contagem") && state.canWrite
        ? el("button", { class: "btn text", onclick: () => cancelar(c, root) }, "Cancelar")
        : null,
    ),
  );
}

// ---------------------------------------------------------------------------
async function abrirNova(root) {
  if (!lookupsCache) lookupsCache = await loadLookups(["categorias", "localizacoes"]);

  const nome = el("input", { placeholder: "Ex.: Contagem TI — Galpão A" });
  const dominio = el("select", {},
    el("option", { value: "" }, "Todos os inventários"),
    el("option", { value: "ti" }, "Ativos de TI"),
    el("option", { value: "impressora" }, "Impressoras"),
  );
  const categoria = el("select", {}, el("option", { value: "" }, "Todas as categorias"),
    ...optionsOf(lookupsCache.categorias));
  const localizacao = el("select", {}, el("option", { value: "" }, "Todos os setores"),
    ...optionsOf(lookupsCache.localizacoes));
  const obs = el("input", { placeholder: "Observações (opcional)" });

  const aviso = el("div", { class: "recado info" },
    "Deixe o escopo vazio para conferir o inventário inteiro da planta.");

  dialog({
    title: "Nova contagem",
    body: el("div", {},
      el("div", { class: "field" }, el("label", {}, "Nome"), nome),
      el("div", { class: "field" }, el("label", {}, "Inventário"), dominio),
      el("div", { class: "grade" },
        el("div", { class: "field" }, el("label", {}, "Categoria"), categoria),
        el("div", { class: "field" }, el("label", {}, "Setor / localização"), localizacao),
      ),
      el("div", { class: "field" }, el("label", {}, "Observações"), obs),
      aviso,
    ),
    actions: [
      { label: "Cancelar", variant: "text" },
      { label: "Abrir contagem", variant: "filled", onClick: async (close) => {
        if (!nome.value.trim()) { mostrarErro(new Error("Dê um nome à contagem.")); return; }
        try {
          const c = await api.post("/contagens", {
            nome: nome.value.trim(),
            dominio: dominio.value || null,
            categoria_id: categoria.value ? Number(categoria.value) : null,
            localizacao_id: localizacao.value ? Number(localizacao.value) : null,
            observacoes: obs.value || null,
          });
          close();
          toast(`Contagem aberta — ${c.esperados ?? 0} item(ns) no escopo`);
          renderContagens(root);
        } catch (e) { mostrarErro(e); }
      } },
    ],
  });
}

async function finalizar(c, root) {
  if (!(await confirmSheet("Finalizar contagem",
      `Encerrar a leitura de "${c.nome}"? Depois disso não é mais possível escanear.`))) return;
  try {
    await api.post(`/contagens/${c.id}/finalizar`, {});
    toast("Contagem finalizada");
    renderContagens(root);
  } catch (e) { mostrarErro(e); }
}

async function cancelar(c, root) {
  if (!(await confirmSheet("Cancelar contagem",
      `Descartar "${c.nome}"? As leituras ficam guardadas para consulta.`))) return;
  try {
    await api.post(`/contagens/${c.id}/cancelar`, {});
    toast("Contagem cancelada");
    renderContagens(root);
  } catch (e) { mostrarErro(e); }
}

// ---------------------------------------------------------------------------
/**
 * Aprovação — a etapa que decide sobre patrimônio.
 *
 * A baixa dos não encontrados vem **desmarcada** de propósito: ausência numa
 * contagem é indício, não prova. O ativo pode estar em manutenção, emprestado
 * ou no setor errado. Apagar patrimônio por ausência é o tipo de erro que não
 * se desfaz.
 */
async function aprovar(c, root) {
  let divergencias = { nao_encontrados: [], nao_cadastrados: [] };
  try {
    divergencias = await api.get(`/contagens/${c.id}/divergencias`);
  } catch { /* segue sem o número exato */ }

  const qtdNaoEncontrados = divergencias.nao_encontrados?.length || 0;
  const baixar = el("input", { type: "checkbox" });
  baixar.checked = false;

  dialog({
    title: "Aprovar contagem",
    wide: true,
    body: el("div", {},
      el("p", { class: "muted", style: "margin:0 0 14px" },
        `Aprovar o resultado de "${c.nome}"? A contagem será encerrada.`),
      el("div", { class: "recado info", style: "margin:0" },
        el("b", {}, "Encontrado na conferência"),
        el("ul", { style: "margin-top:6px" },
          el("li", {}, `${divergencias.conformes ?? 0} de ${divergencias.esperados ?? 0} ativos conferidos`),
          el("li", {}, `${qtdNaoEncontrados} não encontrado(s)`),
          el("li", {}, `${divergencias.nao_cadastrados?.length || 0} não cadastrado(s)`),
        ),
      ),
      qtdNaoEncontrados
        ? el("label", { class: "opcao", style: "margin-top:14px" },
            baixar,
            el("span", {},
              el("strong", {}, `Dar baixa nos ${qtdNaoEncontrados} não encontrados`),
              el("span", { class: "dica" },
                "Sai das listas e relatórios; o histórico permanece. Deixe desmarcado se "
                + "algum item pode estar em manutenção, emprestado ou em outro setor."),
            ),
          )
        : el("p", { class: "muted", style: "margin-top:12px" }, "Nada a baixar: tudo foi conferido."),
    ),
    actions: [
      { label: "Cancelar", variant: "text" },
      { label: "Aprovar", variant: "filled", onClick: async (close) => {
        try {
          const r = await api.post(`/contagens/${c.id}/aprovar`, {
            baixar_nao_encontrados: baixar.checked,
          });
          close();
          toast(r.baixados ? `Aprovada — ${r.baixados} baixado(s)` : "Contagem aprovada");
          renderContagens(root);
        } catch (e) { mostrarErro(e); }
      } },
    ],
  });
}

// ---------------------------------------------------------------------------
/** Divergências em tela cheia: é o documento que a auditoria lê. */
async function verDivergencias(id) {
  const overlay = el("div", { class: "tela-cheia" });
  const corpo = el("div", { class: "tela-cheia-corpo" }, skeleton(5));

  const fechar = () => {
    overlay.remove();
    document.removeEventListener("keydown", esc);
  };
  const esc = (e) => { if (e.key === "Escape") fechar(); };
  document.addEventListener("keydown", esc);

  overlay.append(
    el("header", { class: "tela-cheia-topo" },
      el("button", { class: "iconbtn", onclick: fechar, html: icon("close", 22), title: "Fechar" }),
      el("b", { id: "titulo-divergencias" }, "Divergências"),
      el("div", { class: "spacer" }),
      el("button", { class: "iconbtn", title: "Imprimir / salvar em PDF",
        onclick: () => window.print(), html: icon("print", 20) }),
    ),
    corpo,
  );
  document.body.append(overlay);

  let d;
  try {
    d = await api.get(`/contagens/${id}/divergencias`);
  } catch (e) {
    corpo.innerHTML = "";
    corpo.append(el("p", { class: "text-error" }, e.message));
    return;
  }

  corpo.innerHTML = "";
  corpo.append(
    el("div", { class: "resumo-numeros" },
      numero(d.esperados ?? 0, "Esperados"),
      numero(d.conformes ?? 0, "Conferidos", "ok"),
      numero(d.nao_encontrados?.length || 0, "Não encontrados", "erro"),
      numero(d.nao_cadastrados?.length || 0, "Não cadastrados", "aviso"),
      numero(`${d.percentual ?? 0}%`, "Conformidade"),
    ),
    el("div", { class: "progresso", style: "margin:18px 0 24px" },
      el("div", { class: "progresso-barra", style: `width:${Math.min(100, d.percentual || 0)}%` }),
    ),

    secao("Não encontrados",
      "Estão no cadastro deste escopo e não foram lidos na conferência.",
      d.nao_encontrados, (x) => [
        el("b", {}, x.patrimonio || "(sem patrimônio)"),
        el("span", { class: "muted" }, [x.marca, x.modelo].filter(Boolean).join(" ")),
        x.numero_serie ? el("span", { class: "muted" }, `série ${x.numero_serie}`) : null,
      ], "erro"),

    secao("Não cadastrados",
      "Foram lidos e não pertencem a este escopo — achado que precisa de análise.",
      d.nao_cadastrados, (x) => [
        el("b", {}, x.patrimonio || x.codigo_lido),
        x.patrimonio ? el("span", { class: "muted" }, `código lido: ${x.codigo_lido}`) : null,
        el("span", { class: "muted" },
          [x.lido_por, x.lido_em ? fmtDate(x.lido_em, true) : null].filter(Boolean).join(" · ")),
      ], "aviso"),

    d.repetidos?.length
      ? secao("Lidos mais de uma vez",
          "Podem indicar etiqueta duplicada ou leitura repetida sem perceber.",
          d.repetidos, (x) => [
            el("b", {}, `Ativo #${x.ativo_id}`),
            el("span", { class: "muted" }, `${x.vezes} leituras`),
          ], "neutro")
      : null,
  );
}

function numero(valor, rotulo, tom = "") {
  return el("div", { class: `numero ${tom}` },
    el("span", { class: "numero-valor" }, String(valor)),
    el("span", { class: "numero-rotulo" }, rotulo),
  );
}

function secao(titulo, descricao, itens, render, tom) {
  const lista = itens?.length ? itens : [];
  return el("section", { class: "secao-divergencia" },
    el("div", { class: `secao-topo ${tom}` },
      el("b", {}, `${titulo} (${lista.length})`),
      el("p", { class: "muted", style: "margin:4px 0 0" }, descricao),
    ),
    lista.length
      ? el("div", { class: "lista-divergencia" },
          ...lista.map((x) => el("div", { class: "linha-divergencia" },
            ...render(x).filter(Boolean))))
      : el("p", { class: "muted", style: "padding:14px" }, "Nada aqui. 👍"),
  );
}
