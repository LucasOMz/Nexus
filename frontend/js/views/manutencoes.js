/**
 * Manutenções: listagem, abertura, transições de status e anexos.
 * @module views/manutencoes
 */
import { api } from "../api.js";
import { state } from "../state.js";
import { ctx } from "../context.js";
import { el, icon, toast, dialog, confirmSheet, emptyState, skeleton, fmtDate, fmtMoney, mostrarErro } from "../ui.js";
import { loadLookups, optionsOf } from "../lookups.js";
import { seletorDeAtivo } from "../seletor_ativo.js";
import { erroDeResposta } from "../erros.js";

const PAGE_SIZE = 20;
let page = 1;
let filtroStatus = "";

const STATUS_LABEL = { aberta: "Aberta", em_andamento: "Em andamento", concluida: "Concluída", cancelada: "Cancelada" };
const STATUS_BADGE = { aberta: "manutencao", em_andamento: "manutencao", concluida: "estoque", cancelada: "descartado" };

/**
 * Abre o formulário de manutenção.
 *
 * @param {object} lookups cadastros auxiliares (fornecedores etc.)
 * @param {object} [ativoFixo] quando vem da LEITURA: o ativo já está
 *   identificado, então não mostramos o seletor — a pessoa só preenche a
 *   manutenção. A ordem cai na guia Manutenções como qualquer outra.
 */
export async function openForm(lookups, ativoFixo = null) {
  // Com o ativo já identificado (leitura de QR Code) não há o que escolher.
  // Sem ele, usamos um seletor com BUSCA no servidor — antes era uma lista
  // suspensa que trazia apenas os 200 primeiros ativos.
  const seletor = ativoFixo ? null : seletorDeAtivo();

  const desc = el("textarea", { placeholder: "Descrição do problema" });
  const forSel = el("select", { html: optionsOf(lookups.fornecedores) });
  const custo = el("input", { type: "number", step: "0.01", placeholder: "0,00" });
  const tecnico = el("input", { placeholder: "Técnico responsável" });

  const campoAtivo = ativoFixo
    ? el("div", { class: "field" },
        el("label", {}, "Ativo lido"),
        el("div", { style: "font-weight:600" }, `${ativoFixo.patrimonio} — ${ativoFixo.modelo || "sem modelo"}`),
        el("span", { class: "hint" }, "Já identificado pela leitura. Ao abrir, o ativo entra em manutenção."))
    : el("div", { class: "field" },
        el("label", {}, "Ativo *"),
        seletor.elemento,
        el("span", { class: "hint" }, "Digite parte do patrimônio, do modelo ou do nº de série."));

  dialog({
    title: "Abrir manutenção",
    body: el("div", {},
      campoAtivo,
      el("div", { class: "field" }, el("label", {}, "Descrição"), desc),
      el("div", { class: "field" }, el("label", {}, "Fornecedor"), forSel),
      el("div", { class: "field" }, el("label", {}, "Custo (R$)"), custo),
      el("div", { class: "field" }, el("label", {}, "Técnico"), tecnico),
    ),
    actions: [
      { label: "Cancelar", variant: "text" },
      { label: "Abrir", variant: "filled", onClick: async (close) => {
        const idAtivo = ativoFixo ? ativoFixo.id : seletor.id();
        if (!idAtivo) { toast("Selecione o ativo na busca"); return; }
        const payload = { ativo_id: idAtivo, descricao: desc.value || null, fornecedor_id: forSel.value ? Number(forSel.value) : null, custo: custo.value ? Number(custo.value) : null, tecnico: tecnico.value || null };
        try {
          await api.post("/manutencoes", payload);
          close();
          toast("Manutenção aberta — ativo em manutenção", "Ver manutenções", () => { location.hash = "#/manutencoes"; });
          // Veio da LEITURA: continua na tela para ler o próximo equipamento.
          // Veio da guia Manutenções: recarrega a lista.
          if (!ativoFixo) renderManutencoes(document.getElementById("view"));
        } catch (e) { mostrarErro(e, "abrir a manutenção"); }
      } },
    ],
  });
}

async function mudarStatus(m, novoStatus) {
  // Concluir passa por uma janela que EXIGE o comentário do que foi feito.
  if (novoStatus === "concluida") return concluirManutencao(m);

  try {
    await api.patch(`/manutencoes/${m.id}`, { status: novoStatus });
    toast(`Manutenção ${STATUS_LABEL[novoStatus].toLowerCase()}`);
    renderManutencoes(document.getElementById("view"));
  } catch (e) { mostrarErro(e); }
}

/**
 * Janela de conclusão: pede o comentário do que foi feito.
 *
 * O botão só libera com o campo preenchido — e o backend também recusa sem
 * comentário, porque a regra não pode depender só da tela.
 */
function concluirManutencao(m) {
  const comentario = el("textarea", {
    placeholder: "O que foi feito nesta manutenção?",
    rows: "4",
  });

  // Botão montado à parte para ficar DESABILITADO até haver comentário.
  const botaoConcluir = el("button", {
    class: "btn filled",
    disabled: true,
    onclick: async () => {
      const texto = comentario.value.trim();
      if (!texto) { toast("Escreva o comentário do que foi feito"); return; }
      try {
        await api.patch(`/manutencoes/${m.id}`, {
          status: "concluida",
          comentario_conclusao: texto,
        });
        fecharDialogo();
        toast("Manutenção concluída");
        renderManutencoes(document.getElementById("view"));
      } catch (e) { mostrarErro(e, "concluir a manutenção"); }
    },
  }, "Concluir manutenção");

  // Libera o botão assim que houver texto (e trava de novo se apagar tudo).
  comentario.addEventListener("input", () => {
    botaoConcluir.disabled = comentario.value.trim().length === 0;
  });

  const { close: fecharDialogo } = dialog({
    title: `Concluir manutenção #${m.id}`,
    body: el("div", {},
      el("p", { class: "muted", style: "margin-top:0;font-size:13px" },
        "Descreva o que foi feito. O comentário fica registrado junto com o seu nome "
        + "como responsável pela conclusão."),
      el("div", { class: "field" }, el("label", {}, "Comentário *"), comentario),
    ),
    actions: [
      { label: "Cancelar", variant: "text" },
      { elemento: botaoConcluir },
    ],
  });

  setTimeout(() => comentario.focus(), 50);
}

async function anexar(m) {
  const input = el("input", { type: "file" });
  dialog({
    title: "Anexar arquivo",
    body: el("div", { class: "field" }, el("label", {}, "Arquivo"), input),
    actions: [
      { label: "Cancelar", variant: "text" },
      { label: "Enviar", variant: "filled", onClick: async (close) => {
        if (!input.files.length) { toast("Selecione um arquivo"); return; }
        const fd = new FormData();
        fd.append("file", input.files[0]);
        try {
          const res = await fetch(`/api/v1/manutencoes/${m.id}/anexos`, { method: "POST", headers: { Authorization: "Bearer " + state.access }, body: fd });
          if (!res.ok) throw erroDeResposta(res.status, await res.json().catch(() => null));
          close(); toast("Anexo enviado");
        } catch (e) { mostrarErro(e, "enviar o anexo"); }
      } },
    ],
  });
}

async function verDetalhe(m, lookups) {
  const anexos = await api.get(`/manutencoes/${m.id}/anexos`).catch(() => []);
  const rows = [
    ["Status", STATUS_LABEL[m.status] || m.status], ["Ativo", `#${m.ativo_id}`],
    ["Fornecedor", lookups.fornecedores.find((f) => f.id === m.fornecedor_id)?.nome || "—"],
    ["Custo", fmtMoney(m.custo)], ["Técnico", m.tecnico || "—"],
    ["Abertura", fmtDate(m.data_abertura, true)], ["Conclusão", m.data_conclusao ? fmtDate(m.data_conclusao, true) : "—"],
    // Preenchido pelo sistema com o usuário logado que fechou a ordem.
    ["Concluída por", m.concluido_por_nome || "—"],
    ["Descrição", m.descricao || "—"],
    ...(m.comentario_conclusao
      ? [["Comentário da conclusão", m.comentario_conclusao]]
      : []),
  ];
  dialog({
    title: `Manutenção #${m.id}`,
    body: el("div", {},
      ...rows.map(([k, v]) => el("div", { class: "row", style: "justify-content:space-between;border-bottom:1px solid var(--md-sys-color-outline-variant);padding:6px 0" }, el("span", { class: "muted" }, k), el("span", {}, String(v)))),
      el("h4", { class: "muted", style: "margin:12px 0 4px" }, "Anexos"),
      ...(anexos.length ? anexos.map((a) => el("div", { class: "row", style: "justify-content:space-between" }, el("span", {}, a.nome_arquivo), el("button", {
        class: "iconbtn", title: "Baixar anexo",
        // O download precisa do token: um `<a href="/api/...">` abriria sem o
        // cabeçalho de autorização e o servidor responderia 401.
        onclick: async () => {
          try {
            const url = await api.blob(`/manutencoes/${m.id}/anexos/${a.id}/download`);
            const link = document.createElement("a");
            link.href = url;
            link.download = a.nome_arquivo;
            link.click();
            setTimeout(() => URL.revokeObjectURL(url), 5000);
          } catch (e) { mostrarErro(e, "baixar o anexo"); }
        },
        html: icon("download", 18),
      }))) : [el("p", { class: "muted" }, "Sem anexos")]),
    ),
    actions: [
      { label: "Fechar", variant: "text" },
      ...(state.canWrite && (m.status === "aberta" || m.status === "em_andamento") ? [
        { label: "Concluir", variant: "filled", onClick: (close) => { close(); mudarStatus(m, "concluida"); } },
        ...(m.status === "aberta" ? [{ label: "Iniciar", variant: "tonal", onClick: (close) => { close(); mudarStatus(m, "em_andamento"); } }] : []),
        { label: "Cancelar", variant: "outlined", onClick: (close) => { close(); mudarStatus(m, "cancelada"); } },
        { label: "Anexar", variant: "outlined", onClick: () => anexar(m) },
      ] : []),
    ],
  });
}

async function renderList(root, lookups) {
  root.innerHTML = "";
  const q = { page, size: PAGE_SIZE };
  if (filtroStatus) q.status = filtroStatus;
  let data;
  try { data = await api.get("/manutencoes", q); }
  catch (e) { root.append(emptyState("manutencoes", "Erro", e.message)); return; }
  if (!data.items.length) { root.append(emptyState("manutencoes", "Sem manutenções", "Abra uma manutenção para um ativo.")); return; }

  const table = el("table", { class: "data" },
    el("thead", {}, el("tr", {}, ...["#", "Ativo", "Status", "Abertura", "Custo", "Técnico"].map((h) => el("th", {}, h)))),
    el("tbody", {}, ...data.items.map((m) => {
      const tr = el("tr", {},
        el("td", {}, `#${m.id}`),
        el("td", { style: "font-weight:600" }, `Ativo #${m.ativo_id}`),
        el("td", { html: `<span class="badge ${STATUS_BADGE[m.status] || ""}"><span class="dot"></span>${STATUS_LABEL[m.status] || m.status}</span>` }),
        el("td", {}, fmtDate(m.data_abertura)),
        el("td", {}, fmtMoney(m.custo)),
        el("td", {}, m.tecnico || "—"),
      );
      tr.addEventListener("click", () => verDetalhe(m, lookups));
      return tr;
    })),
  );

  root.append(
    el("div", { class: "table-wrap" }, table),
    el("div", { class: "pagination" },
      el("button", { class: "iconbtn", disabled: page <= 1, onclick: () => { page--; renderList(root, lookups); }, html: icon("chevL") }),
      el("span", {}, `Página ${data.page} de ${data.pages || 1} (${data.total} itens)`),
      el("button", { class: "iconbtn", disabled: page >= data.pages, onclick: () => { page++; renderList(root, lookups); }, html: icon("chevR") }),
    ),
  );
}

export async function renderManutencoes(root) {
  ctx.setTitle("Manutenções");
  ctx.setFab(null);

  let lookups = null;
  let listRoot = null;
  function refresh() { if (listRoot && lookups) renderList(listRoot, lookups); }

  // O `refresh()` redesenha só a LISTA; a barra de ferramentas é criada uma vez.
  // Sem sincronizar, o filtro funciona mas a marcação fica na opção anterior.
  const chipsStatus = [];

  function atualizarToolbar() {
    chipsStatus.forEach(([valor, botao]) => botao.classList.toggle("selected", filtroStatus === valor));
  }

  function trocarStatus(valor) {
    filtroStatus = valor;
    page = 1;
    atualizarToolbar();
    refresh();
  }

  const chipTodas = el("button", {
    class: "chip" + (filtroStatus === "" ? " selected" : ""),
    onclick: () => trocarStatus(""),
  }, "Todas");
  chipsStatus.push(["", chipTodas]);

  const toolbar = el("div", { class: "toolbar" },
    el("div", { class: "row", style: "gap:6px" },
      chipTodas,
      ...Object.entries(STATUS_LABEL).map(([v, l]) => {
        const botao = el("button", {
          class: "chip" + (filtroStatus === v ? " selected" : ""),
          onclick: () => trocarStatus(v),
        }, l);
        chipsStatus.push([v, botao]);
        return botao;
      }),
    ),
  );

  atualizarToolbar();

  root.innerHTML = "";
  root.append(el("h1", { class: "page-title" }, "Manutenções"), toolbar, el("div", { id: "manut-list" }, skeleton(6)));
  listRoot = root.querySelector("#manut-list");

  lookups = await loadLookups();
  ctx.setFab(state.canWrite ? { label: "Abrir Manutenção", icon: "add", onClick: () => openForm(lookups) } : null);
  await renderList(listRoot, lookups);
}
