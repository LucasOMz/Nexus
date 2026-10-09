/**
 * Cadastros (lookups): departamentos, localizações, fornecedores e categorias.
 * Usuários e permissões ficam na área de Administração.
 * @module views/cadastros
 */
import { api } from "../api.js";
import { state } from "../state.js";
import { ctx } from "../context.js";
import { el, icon, toast, dialog, confirmSheet, emptyState, skeleton, semVazios, mostrarErro } from "../ui.js";
import { loadLookups } from "../lookups.js";

const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

let abaAtiva = "departamentos";

function campo(f) {
  if (f.type === "select") {
    return `<div class="field ${f.span ? "span-2" : ""}"><label>${f.label}</label>
      <select name="${f.name}">${f.options.map((o) => `<option value="${o.value}" ${String(o.value) === String(f.value ?? "") ? "selected" : ""}>${esc(o.label)}</option>`).join("")}</select>
      ${f.hint ? `<span class="hint">${esc(f.hint)}</span>` : ""}</div>`;
  }
  if (f.type === "textarea") {
    return `<div class="field span-2"><label>${f.label}</label><textarea name="${f.name}">${esc(f.value)}</textarea></div>`;
  }
  return `<div class="field ${f.span ? "span-2" : ""}"><label>${f.label}</label>
    <input type="${f.type || "text"}" name="${f.name}" value="${esc(f.value)}" ${f.required ? "required" : ""}
      ${f.placeholder ? `placeholder="${esc(f.placeholder)}"` : ""}>
    ${f.hint ? `<span class="hint">${esc(f.hint)}</span>` : ""}</div>`;
}

const CONFIGS = {
  departamentos: {
    titulo: "Departamentos",
    singular: "departamento",
    descricao: "Áreas da empresa usadas para responsabilizar ativos.",
    campos: (d) => [
      { name: "nome", label: "Nome do departamento", required: true, value: d.nome },
      { name: "sigla", label: "Sigla", value: d.sigla, placeholder: "Ex.: TI" },
    ],
    tituloItem: (d) => d.nome,
    subItem: (d) => d.sigla || "",
  },
  localizacoes: {
    titulo: "Localizações",
    singular: "localização",
    descricao: "Onde fisicamente os itens ficam (salas, prédios, filiais).",
    campos: (l) => [
      { name: "nome", label: "Nome do local", required: true, value: l.nome },
      { name: "descricao", label: "Descrição", type: "textarea", value: l.descricao },
    ],
    tituloItem: (l) => l.nome,
    subItem: (l) => l.descricao || "",
  },
  fornecedores: {
    titulo: "Fornecedores",
    singular: "fornecedor",
    descricao: "Quem fornece equipamentos, consumíveis e serviços.",
    campos: (f) => [
      { name: "nome", label: "Razão social / nome", required: true, value: f.nome },
      { name: "cnpj", label: "CNPJ", value: f.cnpj, placeholder: "00.000.000/0000-00" },
      { name: "contato", label: "Pessoa de contato", value: f.contato },
      { name: "telefone", label: "Telefone", value: f.telefone },
      { name: "email", label: "E-mail", type: "email", value: f.email, span: true },
    ],
    tituloItem: (f) => f.nome,
    subItem: (f) => [f.cnpj, f.contato, f.telefone].filter(Boolean).join(" · "),
  },
  categorias: {
    titulo: "Categorias",
    singular: "categoria",
    descricao: "Agrupamento dos itens (notebook, monitor, toner…).",
    campos: (c) => [
      { name: "nome", label: "Nome da categoria", required: true, value: c.nome },
      { name: "dominio", label: "Inventário", type: "select", value: c.dominio ?? "", options: [{ value: "", label: "Ambos" }, { value: "ti", label: "TI" }, { value: "impressora", label: "Impressoras" }] },
      { name: "descricao", label: "Descrição", type: "textarea", value: c.descricao },
    ],
    tituloItem: (c) => c.nome,
    subItem: (c) => (c.dominio ? (c.dominio === "ti" ? "Inventário de TI" : "Inventário de Impressoras") : "Ambos os inventários"),
    limpar: (data) => { if (data.dominio === "") data.dominio = null; },
  },
};

function abrirFormulario(cfg, item) {
  const isEdit = Boolean(item);
  const form = el("form", { html: `<div class="form-grid">${cfg.campos(item || {}).map(campo).join("")}</div>` });
  dialog({
    title: `${isEdit ? "Editar" : "Novo"} ${cfg.singular}`,
    body: form,
    wide: true,
    actions: [
      { label: "Cancelar", variant: "text" },
      { label: "Salvar", variant: "filled", onClick: async (close) => {
        const data = semVazios(Object.fromEntries(new FormData(form).entries()));
        cfg.limpar?.(data);
        try {
          if (isEdit) await api.put(`/${abaAtiva}/${item.id}`, data);
          else await api.post(`/${abaAtiva}`, data);
          close(); toast("Registro salvo");
          renderCadastros(document.getElementById("view"));
        } catch (e) { mostrarErro(e, `salvar o cadastro de ${cfg.titulo.toLowerCase()}`); }
      } },
    ],
  });
}

async function renderAba(root) {
  const cfg = CONFIGS[abaAtiva];
  const itens = await api.get(`/${abaAtiva}`).catch(() => []);

  const cabecalho = el("div", { class: "card" },
    el("div", { class: "row between" },
      el("div", {},
        el("div", { class: "section-title", style: "margin:0" }, cfg.titulo),
        el("div", { class: "muted", style: "font-size:13px" }, cfg.descricao),
      ),
      state.canWrite
        ? el("button", { class: "btn tonal small", onclick: () => abrirFormulario(cfg, null), html: icon("add", 18) + ` Novo` })
        : null,
    ),
  );
  root.append(cabecalho);

  const lista = el("div", { class: "card" });
  if (!itens.length) {
    lista.append(emptyState("cadastros", "Nada cadastrado", `Cadastre o primeiro ${cfg.singular}.`));
  } else {
    itens.forEach((it) => {
      lista.append(el("div", { class: "list-row" },
        el("div", { class: "list-main" },
          el("div", { class: "list-title" }, cfg.tituloItem(it)),
          cfg.subItem(it) ? el("div", { class: "list-sub" }, cfg.subItem(it)) : null,
        ),
        state.canWrite ? el("div", { class: "row" },
          el("button", { class: "iconbtn", title: "Editar", onclick: () => abrirFormulario(cfg, it), html: icon("edit", 20) }),
          el("button", { class: "iconbtn", title: "Excluir", onclick: async () => {
            if (await confirmSheet(`Excluir ${cfg.singular}`, `Excluir "${cfg.tituloItem(it)}"?`)) {
              try { await api.del(`/${abaAtiva}/${it.id}`); toast("Excluído"); renderCadastros(document.getElementById("view")); }
              catch (e) { mostrarErro(e); }
            }
          }, html: icon("trash", 20) }),
        ) : null,
      ));
    });
  }
  root.append(lista);
}

export async function renderCadastros(root) {
  ctx.setTitle("Cadastros");
  ctx.setFab(null);

  root.innerHTML = "";
  root.append(
    el("h1", { class: "page-title" }, "Cadastros"),
    el("p", { class: "page-sub" }, "Dados de apoio usados nos formulários dos dois inventários."),
  );

  const tabs = el("div", { class: "tabs" });
  Object.entries(CONFIGS).forEach(([chave, cfg]) => {
    tabs.append(el("button", {
      class: chave === abaAtiva ? "active" : "",
      onclick: () => { abaAtiva = chave; renderCadastros(document.getElementById("view")); },
    }, cfg.titulo));
  });
  root.append(tabs);

  const alvo = el("div", {}, skeleton(4));
  root.append(alvo);
  await loadLookups(true).catch(() => {});
  alvo.innerHTML = "";
  await renderAba(alvo);
}
