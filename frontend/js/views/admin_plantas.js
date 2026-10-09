/**
 * Administração → Plantas (localidades).
 *
 * Cada planta é um inventário próprio: os ativos e as etiquetas pertencem a
 * uma planta, e o usuário só trabalha na planta dele.
 * @module views/admin_plantas
 */
import { api } from "../api.js";
import { el, icon, toast, dialog, confirmSheet, emptyState, mostrarErro } from "../ui.js";

const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

let _root = null;

/** Recarrega a aba depois de salvar/excluir. */
const recarregar = () => _root && renderPlantas(_root);

function abrirPlanta(planta) {
  const p = planta || { nome: "", sigla: "", ativa: true };
  const form = el("form", {});
  form.innerHTML = `
    <div class="form-grid">
      <div class="field span-2"><label>Nome da planta *</label>
        <input name="nome" required value="${esc(p.nome)}" placeholder="Ex.: Unidade Campinas"></div>
      <div class="field"><label>Sigla *</label>
        <input name="sigla" required maxlength="20" value="${esc(p.sigla)}" placeholder="Ex.: CPS">
        <span class="hint">É o que aparece na coluna <b>Planta</b> da tela de Ativos. Use algo curto.</span></div>
      <div class="field"><label>CNPJ</label><input name="cnpj" value="${esc(p.cnpj)}" placeholder="00.000.000/0000-00"></div>
      <div class="field span-2"><label>Endereço</label><input name="endereco" value="${esc(p.endereco)}"></div>
      <div class="field"><label>Cidade</label><input name="cidade" value="${esc(p.cidade)}"></div>
      <div class="field"><label>UF</label><input name="uf" maxlength="2" value="${esc(p.uf)}" placeholder="SP"></div>
      <div class="field span-2"><label>Observações</label><textarea name="observacoes">${esc(p.observacoes)}</textarea></div>
    </div>
    <label class="switch" style="margin-top:8px"><input type="checkbox" name="ativa" ${p.ativa !== false ? "checked" : ""}> Planta ativa (aparece nos seletores)</label>`;

  dialog({
    title: planta ? `Editar planta: ${planta.nome}` : "Nova planta",
    body: form,
    wide: true,
    actions: [
      { label: "Cancelar", variant: "text" },
      { label: "Salvar", variant: "filled", onClick: async (close) => {
        const fd = new FormData(form);
        const dados = {
          nome: (fd.get("nome") || "").trim(),
          sigla: (fd.get("sigla") || "").trim().toUpperCase(),
          cnpj: fd.get("cnpj") || null,
          endereco: fd.get("endereco") || null,
          cidade: fd.get("cidade") || null,
          uf: fd.get("uf") || null,
          observacoes: fd.get("observacoes") || null,
          ativa: Boolean(fd.get("ativa")),
        };
        if (!dados.nome || !dados.sigla) { toast("Informe o nome e a sigla"); return; }
        try {
          if (planta) await api.put(`/admin/plantas/${planta.id}`, dados);
          else await api.post("/admin/plantas", dados);
          close();
          toast(planta ? "Planta atualizada" : "Planta cadastrada");
          recarregar();
        } catch (e) { mostrarErro(e, planta ? "salvar a planta" : "cadastrar a planta"); }
      } },
    ],
  });
}

export async function renderPlantas(root) {
  _root = root;
  const plantas = await api.get("/admin/plantas").catch((e) => { mostrarErro(e, "carregar as plantas"); return []; });

  root.innerHTML = "";
  root.append(el("div", { class: "card" },
    el("div", { class: "row between" },
      el("div", {},
        el("div", { class: "section-title", style: "margin:0" }, "Plantas / localidades"),
        el("div", { class: "muted", style: "font-size:13px" },
          "Cada planta tem o seu inventário. O usuário trabalha apenas na planta dele; "
          + "o administrador enxerga todas e escolhe qual acessar."),
      ),
      el("button", { class: "btn tonal small", onclick: () => abrirPlanta(null), html: icon("add", 18) + " Nova planta" }),
    ),
  ));

  const lista = el("div", { class: "card" });
  if (!plantas.length) {
    lista.append(emptyState("ativos", "Nenhuma planta", "Cadastre a primeira planta para começar a usar o inventário."));
    root.append(lista);
    return;
  }

  for (const p of plantas) {
    lista.append(el("div", { class: "list-row" },
      el("div", { class: "list-main" },
        el("div", { class: "list-title" }, `${p.sigla} — ${p.nome}${p.ativa ? "" : " (inativa)"}`),
        el("div", { class: "list-sub" },
          `${p.total_ativos} ativo(s) · ${p.total_usuarios} usuário(s)`
          + (p.cidade ? ` · ${p.cidade}${p.uf ? `/${p.uf}` : ""}` : "")),
      ),
      el("div", { class: "row" },
        el("button", { class: "iconbtn", title: "Editar", onclick: () => abrirPlanta(p), html: icon("edit", 20) }),
        el("button", { class: "iconbtn danger", title: "Excluir", onclick: async () => {
          if (!await confirmSheet("Excluir planta", `Excluir a planta ${p.sigla}? Só é possível se ela não tiver ativos nem usuários.`)) return;
          try {
            await api.del(`/admin/plantas/${p.id}`);
            toast("Planta excluída");
            recarregar();
          } catch (e) { mostrarErro(e, "excluir a planta"); }
        }, html: icon("trash", 20) }),
      ),
    ));
  }
  root.append(lista);
}
