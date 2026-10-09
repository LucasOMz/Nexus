/**
 * Administração → Auditoria → Logs.
 * Histórico imutável: quem fez, o que, quando e de qual IP.
 * @module views/admin_auditoria
 */
import { api } from "../api.js";
import { el, icon, toast, dialog, emptyState, fmtDate, mostrarErro } from "../ui.js";

const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

let pagina = 1;
const filtros = { usuario_id: "", acao: "", entidade: "", busca: "", inicio: "", fim: "" };

/** Mostra o diff (o que mudou) numa janela. */
function verDiff(log) {
  const diff = log.diff || {};
  const linhas = Object.entries(diff);
  dialog({
    title: `${log.acao_rotulo} — ${log.entidade_rotulo}`,
    wide: true,
    body: el("div", {},
      el("div", { class: "row between", style: "border-bottom:1px solid var(--md-sys-color-outline-variant);padding:8px 0" },
        el("span", { class: "muted" }, "Quando"), el("span", {}, fmtDate(log.criado_em, true))),
      el("div", { class: "row between", style: "border-bottom:1px solid var(--md-sys-color-outline-variant);padding:8px 0" },
        el("span", { class: "muted" }, "Quem"), el("span", {}, `${log.usuario_nome || "—"}${log.usuario_email ? ` (${log.usuario_email})` : ""}`)),
      el("div", { class: "row between", style: "border-bottom:1px solid var(--md-sys-color-outline-variant);padding:8px 0" },
        el("span", { class: "muted" }, "Alvo"),
        el("span", {}, `${log.entidade_rotulo}${log.referencia ? ` — ${log.referencia}` : ""}${log.entidade_id ? ` (#${log.entidade_id})` : ""}`)),
      el("div", { class: "row between", style: "border-bottom:1px solid var(--md-sys-color-outline-variant);padding:8px 0" },
        el("span", { class: "muted" }, "Origem (IP)"), el("span", { class: "mono" }, log.ip || "—")),
      linhas.length
        ? el("div", { style: "margin-top:14px" },
            el("div", { class: "muted", style: "font-size:13px;margin-bottom:6px" }, "O que mudou:"),
            ...linhas.map(([k, v]) => el("div", { class: "row between", style: "padding:4px 0;gap:16px" },
              el("span", { class: "muted", style: "font-size:13px" }, k),
              el("span", { style: "font-size:13px;word-break:break-word;text-align:right" }, v === null ? "—" : JSON.stringify(v)))))
        : el("p", { class: "muted", style: "margin-top:14px" }, "Este registro não guarda detalhes da alteração."),
    ),
    actions: [{ label: "Fechar", variant: "text" }],
  });
}

async function renderLista(root, opcoes) {
  const alvo = root.querySelector("#auditoria-lista") || root;
  alvo.innerHTML = "";
  try {
    const query = { pagina, por_pagina: 50 };
    for (const [k, v] of Object.entries(filtros)) if (v) query[k] = v;

    const dados = await api.get("/admin/auditoria", query);
    if (!dados.itens.length) {
      alvo.append(emptyState("check", "Nenhum registro", "Nada encontrado com esses filtros."));
      return;
    }

    const lista = el("div", {});
    for (const log of dados.itens) {
      const linha = el("div", { class: "list-row", style: "cursor:pointer" },
        el("div", { class: "list-main" },
          el("div", { class: "list-title" }, `${log.acao_rotulo} ${log.entidade_rotulo}${log.referencia ? ` — ${log.referencia}` : ""}`),
          el("div", { class: "list-sub" },
            `${log.usuario_nome || "—"} · ${fmtDate(log.criado_em, true)}${log.ip ? ` · ${log.ip}` : ""}`),
        ),
        el("div", { class: "row" }, el("span", { class: "muted", style: "font-size:12px" }, "ver detalhes")),
      );
      linha.addEventListener("click", () => verDiff(log));
      lista.append(linha);
    }
    alvo.append(lista);

    const totalPaginas = Math.max(1, Math.ceil(dados.total / dados.por_pagina));
    alvo.append(el("div", { class: "pagination" },
      el("span", {}, `${dados.total} registro(s) — página ${dados.pagina} de ${totalPaginas}`),
      el("button", { class: "iconbtn", disabled: pagina <= 1, onclick: () => { pagina--; renderLista(root, opcoes); }, html: icon("chevL") }),
      el("button", { class: "iconbtn", disabled: pagina >= totalPaginas, onclick: () => { pagina++; renderLista(root, opcoes); }, html: icon("chevR") }),
    ));
  } catch (e) {
    mostrarErro(e, "carregar a auditoria");
  }
}

export async function renderAuditoria(root) {
  pagina = 1;
  root.innerHTML = "";

  const [resumo, opcoes] = await Promise.all([
    api.get("/admin/auditoria/resumo").catch(() => ({})),
    api.get("/admin/auditoria/filtros").catch(() => ({ acoes: [], entidades: [], usuarios: [] })),
  ]);

  const selUsuario = el("select", {}, el("option", { value: "" }, "Todos os usuários"),
    ...(opcoes.usuarios || []).map((u) => el("option", { value: u.id }, u.nome)));
  const selAcao = el("select", {}, el("option", { value: "" }, "Todas as ações"),
    ...(opcoes.acoes || []).map((a) => el("option", { value: a.valor }, a.rotulo)));
  const selEntidade = el("select", {}, el("option", { value: "" }, "Todos os tipos"),
    ...(opcoes.entidades || []).map((e) => el("option", { value: e.valor }, e.rotulo)));
  const campoBusca = el("input", { class: "search-input", placeholder: "Buscar por IP, usuário ou conteúdo…" });
  const campoInicio = el("input", { type: "date" });
  const campoFim = el("input", { type: "date" });

  const aplicar = () => {
    filtros.usuario_id = selUsuario.value;
    filtros.acao = selAcao.value;
    filtros.entidade = selEntidade.value;
    filtros.busca = campoBusca.value.trim();
    filtros.inicio = campoInicio.value ? `${campoInicio.value}T00:00:00` : "";
    filtros.fim = campoFim.value ? `${campoFim.value}T23:59:59` : "";
    pagina = 1;
    renderLista(root, opcoes);
  };
  [selUsuario, selAcao, selEntidade, campoInicio, campoFim].forEach((c) => c.addEventListener("change", aplicar));
  let timer = null;
  campoBusca.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(aplicar, 350); });

  root.append(
    el("div", { class: "card" },
      el("div", { class: "section-title", style: "margin:0" }, "Histórico de auditoria"),
      el("p", { class: "muted", style: "font-size:13px;margin:6px 0 0" },
        "Registro imutável: o sistema só acrescenta linhas, nunca altera nem apaga. "
        + "Mostra quem criou, alterou, excluiu, imprimiu ou gerou etiquetas — nos dois inventários."),
      el("p", { style: "margin:14px 0 0;font-weight:600" },
        `${resumo.total ?? 0} registro(s) · ${resumo.ultimos_7_dias ?? 0} nos últimos 7 dias`
        + (resumo.ultimo_em ? ` · último em ${fmtDate(resumo.ultimo_em, true)}` : "")),
    ),
    el("div", { class: "card" },
      el("div", { class: "form-grid" },
        el("div", { class: "field" }, el("label", {}, "Usuário"), selUsuario),
        el("div", { class: "field" }, el("label", {}, "Ação"), selAcao),
        el("div", { class: "field" }, el("label", {}, "Tipo"), selEntidade),
        el("div", { class: "field" }, el("label", {}, "Buscar"), campoBusca),
        el("div", { class: "field" }, el("label", {}, "De"), campoInicio),
        el("div", { class: "field" }, el("label", {}, "Até"), campoFim),
      ),
    ),
    el("div", { class: "card", id: "auditoria-lista" }),
  );

  await renderLista(root, opcoes);
}
