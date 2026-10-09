/**
 * Transferências — equipamentos de equipamentos entre plantas.
 *
 * Mostra o inventário da **própria planta**; ao clicar num item, abre a opção
 * de enviá-lo para outra planta. Cada pedido passa por duas aprovações:
 * quem vai receber, e depois o administrador.
 *
 * @module views/movimentacoes
 */
import { api } from "../api.js";
import { ctx } from "../context.js";
import { state } from "../state.js";
import { el, icon, toast, dialog, confirmSheet, emptyState, skeleton, fmtDate, mostrarErro } from "../ui.js";

const MOTIVO_ROTULO = {
  emprestimo: "Empréstimo entre plantas",
  transferencia: "Transferência definitiva do ativo",
  outro: "Outro motivo",
};

const STATUS_CLASSE = {
  aguardando_destino: "aviso",
  aguardando_admin: "aviso",
  aprovada: "ok",
  recusada: "",
  cancelada: "",
};

let abaAtiva = "transferir";

// ---------------------------------------------------------------------------
// Solicitar transferência
// ---------------------------------------------------------------------------
async function abrirTransferencia(ativo, recarregar) {
  const plantas = await api.get("/plantas/opcoes").catch(() => []);
  const destinos = (plantas || []).filter((p) => p.id !== ativo.planta_id && p.ativa !== false);

  if (!destinos.length) {
    toast("Não há outra planta ativa para receber o equipamento");
    return;
  }

  const destino = el("select", {},
    ...destinos.map((p) => el("option", { value: p.id }, `${p.sigla} — ${p.nome}`)));
  const motivo = el("select", {},
    ...Object.entries(MOTIVO_ROTULO).map(([v, l]) => el("option", { value: v }, l)));
  const detalhe = el("input", { placeholder: "Descreva o motivo", maxlength: "200" });
  const campoDetalhe = el("div", { class: "field hidden" },
    el("label", {}, "Qual o motivo? *"), detalhe);
  const obs = el("textarea", { rows: "3", placeholder: "Observações (opcional)" });

  motivo.addEventListener("change", () => {
    campoDetalhe.classList.toggle("hidden", motivo.value !== "outro");
  });

  const botao = el("button", {
    class: "btn filled",
    onclick: async () => {
      if (motivo.value === "outro" && detalhe.value.trim().length < 3) {
        toast("Descreva o motivo da transferência");
        return;
      }
      const dados = new FormData();
      dados.append("ativo_id", ativo.id);
      dados.append("planta_destino_id", destino.value);
      dados.append("motivo", motivo.value);
      if (detalhe.value.trim()) dados.append("motivo_detalhe", detalhe.value.trim());
      if (obs.value.trim()) dados.append("observacoes", obs.value.trim());
      try {
        await api.postForm("/transferencias", dados);
        toast("Transferência solicitada — aguardando aprovação de quem recebe");
        recarregar();
      } catch (e) { mostrarErro(e, "solicitar a transferência"); }
    },
  }, "Solicitar transferência");

  dialog({
    title: `Transferir ${ativo.patrimonio}`,
    body: el("div", {},
      el("div", { class: "field" },
        el("label", {}, "De"),
        el("div", { style: "font-weight:600" },
          `${ativo.planta_sigla || "—"} — ${ativo.modelo || "sem modelo"}`)),
      el("div", { class: "field" }, el("label", {}, "Para a planta *"), destino),
      el("div", { class: "field" }, el("label", {}, "Motivo *"), motivo),
      campoDetalhe,
      el("div", { class: "field" }, el("label", {}, "Observações"), obs),
      el("p", { class: "muted", style: "font-size:12.5px;margin:6px 0 0" },
        "O pedido vai para aprovação dos técnicos da planta de destino e, depois, "
        + "para o administrador. O equipamento só muda de planta após as duas aprovações."),
    ),
    actions: [
      { label: "Cancelar", variant: "text" },
      { elemento: botao },
    ],
  });
}

// ---------------------------------------------------------------------------
// Decidir uma solicitação
// ---------------------------------------------------------------------------
/** Quem pode decidir a etapa atual desta transferência. */
function podeDecidir(t) {
  if (t.status === "aguardando_destino") {
    return state.isAdmin || state.plantaId === t.planta_destino_id;
  }
  if (t.status === "aguardando_admin") return state.isAdmin;
  return false;
}

async function aprovar(t, recarregar) {
  const confirmado = await confirmSheet(
    "Aprovar transferência",
    `Aprovar a vinda de ${t.patrimonio} (${t.planta_origem} → ${t.planta_destino})?`
    + (t.status === "aguardando_destino"
      ? " Depois desta aprovação, o pedido segue para o administrador."
      : " Esta é a aprovação final: o equipamento muda de planta."),
  );
  if (!confirmado) return;
  try {
    await api.post(`/transferencias/${t.id}/aprovar`);
    toast("Transferência aprovada");
    recarregar();
  } catch (e) { mostrarErro(e, "aprovar a transferência"); }
}

function recusar(t, recarregar) {
  const motivo = el("textarea", { rows: "3", placeholder: "Por que está recusando?" });
  const botao = el("button", {
    class: "btn danger", disabled: true,
    onclick: async () => {
      const texto = motivo.value.trim();
      if (texto.length < 3) { toast("Escreva o motivo da recusa"); return; }
      const dados = new FormData();
      dados.append("motivo_recusa", texto);
      try {
        await api.postForm(`/transferencias/${t.id}/recusar`, dados);
        fechar();
        toast("Transferência recusada");
        recarregar();
      } catch (e) { mostrarErro(e, "recusar a transferência"); }
    },
  }, "Recusar");
  motivo.addEventListener("input", () => { botao.disabled = motivo.value.trim().length < 3; });

  const { close: fechar } = dialog({
    title: `Recusar transferência #${t.id}`,
    body: el("div", {},
      el("p", { class: "muted", style: "margin-top:0" },
        `${t.patrimonio} · ${t.planta_origem} → ${t.planta_destino}`),
      el("div", { class: "field" }, el("label", {}, "Motivo da recusa *"), motivo),
    ),
    actions: [{ label: "Cancelar", variant: "text" }, { elemento: botao }],
  });
}

// ---------------------------------------------------------------------------
// Cartões
// ---------------------------------------------------------------------------
function cartaoTransferencia(t, recarregar) {
  const decisao = podeDecidir(t);
  return el("div", { class: "card transferencia-item" },
    el("div", { class: "row between", style: "flex-wrap:wrap;gap:8px" },
      el("div", {},
        el("strong", {}, `${t.patrimonio} — ${t.modelo || "sem modelo"}`),
        el("div", { class: "muted", style: "font-size:12.5px" },
          `${t.planta_origem} → ${t.planta_destino} · ${t.motivo_rotulo}`
          + (t.motivo_detalhe ? ` (${t.motivo_detalhe})` : "")
          + ` · pedido por ${t.solicitado_por || "—"} · ${fmtDate(t.criado_em, true)}`),
      ),
      el("span", { class: `badge ${STATUS_CLASSE[t.status] || ""}` }, t.status_rotulo),
    ),
    el("div", { class: "transferencia-trilha" },
      el("span", { class: `passo ${t.aprovado_destino_em ? "feito" : "atual"}` },
        `1. Quem recebe${t.aprovado_destino_por ? ` — ${t.aprovado_destino_por}` : ""}`),
      el("span", { class: `passo ${t.aprovado_admin_em ? "feito" : t.status === "aguardando_admin" ? "atual" : ""}` },
        `2. Administrador${t.aprovado_admin_por ? ` — ${t.aprovado_admin_por}` : ""}`),
    ),
    t.motivo_recusa
      ? el("p", { class: "muted", style: "margin:10px 0 0;font-size:13px;border-left:3px solid var(--md-sys-color-error);padding-left:10px" },
          `Recusada por ${t.recusado_por || "—"}: ${t.motivo_recusa}`)
      : null,
    decisao
      ? el("div", { class: "row", style: "gap:8px;margin-top:12px;justify-content:flex-end" },
          el("button", { class: "btn text small", onclick: () => recusar(t, recarregar) }, "Recusar"),
          el("button", { class: "btn filled small", onclick: () => aprovar(t, recarregar) }, "Aprovar"),
        )
      : null,
  );
}

// ---------------------------------------------------------------------------
// Abas
// ---------------------------------------------------------------------------
async function abaTransferir(alvo) {
  const plantas = await api.get("/plantas/opcoes").catch(() => []);
  const minha = (plantas || []).find((p) => p.id === state.plantaId);

  alvo.innerHTML = "";
  alvo.append(el("div", { class: "card" },
    el("div", { class: "row between", style: "flex-wrap:wrap;gap:10px" },
      el("div", {},
        el("h3", { style: "margin:0 0 4px;font-size:16px" }, "Equipamentos da minha planta"),
        el("div", { class: "muted", style: "font-size:13px" },
          state.isAdmin
            ? "Como administrador você vê todas as plantas. Clique num equipamento para transferi-lo."
            : `Planta ${minha ? `${minha.sigla} — ${minha.nome}` : "não definida"}. `
              + "Clique num equipamento para enviá-lo a outra planta."),
      ),
      el("input", { class: "search-input", id: "mov-busca", placeholder: "Buscar patrimônio ou modelo…" }),
    ),
  ));

  const lista = el("div", {});
  alvo.append(lista);

  // Não oferece transferir o que já está a caminho de outra planta.
  const transferencias = await api.get("/transferencias").catch(() => ({ itens: [] }));
  const emAndamento = new Map(
    (transferencias.itens || [])
      .filter((t) => t.status === "aguardando_destino" || t.status === "aguardando_admin")
      .map((t) => [t.ativo_id, t]),
  );

  async function carregar(termo = "") {
    lista.innerHTML = "";
    lista.append(skeleton(3));
    let dados;
    try {
      dados = await api.get("/ativos", { page: 1, size: 50, ...(termo ? { search: termo } : {}) });
    } catch (e) {
      lista.innerHTML = "";
      lista.append(el("p", { class: "text-error" }, e.message));
      return;
    }

    lista.innerHTML = "";
    if (!dados.items.length) {
      lista.append(emptyState("ativos", "Nenhum equipamento", "Nada encontrado com esse filtro."));
      return;
    }

    dados.items.forEach((a) => {
      const pendente = emAndamento.get(a.id);
      lista.append(el("div", { class: "list-row" },
        el("div", { class: "list-main" },
          el("div", { class: "list-title" }, `${a.patrimonio} — ${a.modelo || "sem modelo"}`),
          el("div", { class: "list-sub" },
            `${a.planta_sigla || "—"}${a.marca ? ` · ${a.marca}` : ""}`
            + (pendente ? ` · em transferência para ${pendente.planta_destino}` : "")),
        ),
        el("div", { class: "row", style: "gap:6px" },
          pendente
            ? el("span", { class: "badge aviso" }, "Em transferência")
            : el("button", {
                class: "btn tonal small",
                onclick: () => abrirTransferencia(a, () => carregar(termo)),
                html: icon("movimentacoes", 16) + " Transferir",
              }),
        ),
      ));
    });
  }

  const campo = alvo.querySelector("#mov-busca");
  let timer = null;
  campo.addEventListener("input", () => {
    clearTimeout(timer);
    timer = setTimeout(() => carregar(campo.value.trim()), 300);
  });

  await carregar();
}

async function abaAprovacoes(alvo) {
  alvo.innerHTML = "";
  const dados = await api.get("/transferencias").catch(() => ({ itens: [] }));
  const todos = dados.itens || [];
  const minhas = todos.filter(podeDecidir);
  const outras = todos.filter((t) => !podeDecidir(t));

  alvo.append(el("div", { class: "card" },
    el("h3", { style: "margin:0 0 4px;font-size:16px" }, "Aprovações"),
    el("div", { class: "muted", style: "font-size:13px" },
      minhas.length
        ? `${minhas.length} transferência(s) esperando a sua decisão.`
        : "Nada esperando você no momento."),
  ));

  minhas.forEach((t) => alvo.append(cartaoTransferencia(t, () => abaAprovacoes(alvo))));

  if (outras.length) {
    alvo.append(el("h3", { style: "margin:18px 0 8px;font-size:15px" }, "Histórico"));
    outras.forEach((t) => alvo.append(cartaoTransferencia(t, () => abaAprovacoes(alvo))));
  }
}

export async function renderMovimentacoes(root) {
  ctx.setTitle("Transferências");
  ctx.setFab(null);

  const alvo = el("div", {});
  const barra = el("div", { class: "row", style: "gap:6px;margin-bottom:14px" });

  const dados = await api.get("/transferencias").catch(() => ({ itens: [] }));
  const aguardando = (dados.itens || []).filter(podeDecidir).length;

  const abas = [
    { chave: "transferir", rotulo: "Transferir equipamento" },
    { chave: "aprovacoes", rotulo: aguardando ? `Aprovações (${aguardando})` : "Aprovações" },
  ];

  function trocar(chave) {
    abaAtiva = chave;
    [...barra.children].forEach((b) => b.classList.toggle("selected", b.dataset.chave === chave));
    alvo.innerHTML = "";
    if (chave === "aprovacoes") abaAprovacoes(alvo);
    else abaTransferir(alvo);
  }

  abas.forEach((a) => {
    const b = el("button", {
      class: "chip" + (a.chave === abaAtiva ? " selected" : ""),
      onclick: () => trocar(a.chave),
    }, a.rotulo);
    b.dataset.chave = a.chave;
    barra.append(b);
  });

  root.innerHTML = "";
  root.append(
    el("h1", { class: "page-title" }, "Transferências entre plantas"),
    barra,
    alvo,
  );
  trocar(abaAtiva);
}
