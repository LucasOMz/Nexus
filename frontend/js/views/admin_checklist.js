/**
 * Administração → Empréstimos → Checklist.
 *
 * Configura o que se confere na entrega e na devolução do equipamento. Os
 * itens podem valer para tudo ou só para uma categoria — um notebook e um
 * switch não se conferem igual.
 *
 * @module views/admin_checklist
 */
import { api } from "../api.js";
import { el, icon, toast, dialog, confirmSheet, emptyState, skeleton, mostrarErro } from "../ui.js";
import { loadLookups, optionsOf } from "../lookups.js";

let cache = null;

export async function renderChecklist(root) {
  root.innerHTML = "";
  root.append(
    el("div", { class: "row between wrap", style: "gap:10px" },
      el("div", {},
        el("h2", { style: "margin:0" }, "Checklist de empréstimo"),
        el("p", { class: "muted", style: "margin:4px 0 0" },
          "O que se confere na entrega e na devolução. É a comparação entre os dois "
          + "que revela avaria.")),
      el("button", { class: "btn tonal", onclick: () => semear(root),
        html: icon("download", 18) + " Criar itens padrão" }),
    ),
  );

  const lista = el("div", { style: "margin-top:18px" }, skeleton(3));
  root.append(lista);
  await carregar(lista, root);
}

async function carregar(lista, root) {
  if (!cache) cache = await loadLookups(["categorias"]);
  let itens;
  try {
    itens = await api.get("/checklist");
  } catch (e) {
    lista.innerHTML = "";
    lista.append(el("p", { class: "text-error" }, e.message));
    return;
  }

  lista.innerHTML = "";
  if (!itens?.length) {
    lista.append(emptyState(
      "Nenhum item cadastrado",
      "Sem itens, a retirada não pode ser registrada — não há o que conferir. "
      + "Use “Criar itens padrão” para começar e depois edite."));
    return;
  }

  lista.append(el("div", { class: "cartoes" }, ...itens.map((i) => linha(i, root))));
  lista.append(el("button", { class: "btn filled", style: "margin-top:14px",
    onclick: () => abrirForm(null, root), html: icon("plus", 18) + " Novo item" }));
}

function linha(i, root) {
  const momentos = [i.na_entrega ? "entrega" : null, i.na_devolucao ? "devolução" : null]
    .filter(Boolean).join(" e ") || "nenhum momento";

  return el("div", { class: "cartao-contagem" },
    el("div", { class: "row between wrap", style: "gap:10px" },
      el("b", { style: "font-size:15px" }, i.rotulo),
      el("div", { class: "row", style: "gap:6px" },
        i.ativo ? null : el("span", { class: "chip neutro" }, "desativado"),
        i.abre_manutencao ? el("span", { class: "chip aviso" }, "abre manutenção") : null,
        i.categoria_id ? el("span", { class: "chip info" }, "por categoria") : null,
      ),
    ),
    el("div", { class: "muted", style: "font-size:12.5px;margin-top:4px" },
      `Conferido na ${momentos}`),
    i.ajuda ? el("div", { class: "muted", style: "font-size:12.5px;margin-top:4px" }, i.ajuda) : null,
    el("div", { class: "row", style: "gap:8px;margin-top:10px" },
      el("button", { class: "btn tonal small", onclick: () => abrirForm(i, root),
        html: icon("edit", 16) + " Editar" }),
      el("button", { class: "btn text small", onclick: () => excluir(i, root) }, "Remover"),
    ),
  );
}

async function abrirForm(item, root) {
  if (!cache) cache = await loadLookups(["categorias"]);
  const e = item || {};

  const rotulo = el("input", { value: e.rotulo || "", placeholder: "Ex.: Tela sem trinca" });
  const ajuda = el("input", { value: e.ajuda || "", placeholder: "Texto de apoio (opcional)" });
  const ordem = el("input", { type: "number", value: e.ordem ?? 0 });
  const categoria = el("select", {}, el("option", { value: "" }, "Vale para todos"),
    ...optionsOf(cache.categorias));
  categoria.value = e.categoria_id ?? "";
  const dominio = el("select", {},
    el("option", { value: "" }, "Todos os inventários"),
    el("option", { value: "ti" }, "Ativos de TI"),
    el("option", { value: "impressora" }, "Impressoras"));
  dominio.value = e.dominio || "";

  const cbEntrega = el("input", { type: "checkbox" });
  cbEntrega.checked = e.na_entrega !== false;
  const cbDevolucao = el("input", { type: "checkbox" });
  cbDevolucao.checked = e.na_devolucao !== false;
  const cbManutencao = el("input", { type: "checkbox" });
  cbManutencao.checked = e.abre_manutencao !== false;
  const cbAtivo = el("input", { type: "checkbox" });
  cbAtivo.checked = e.ativo !== false;

  dialog({
    title: item ? "Editar item do checklist" : "Novo item do checklist",
    wide: true,
    body: el("div", {},
      el("div", { class: "field" }, el("label", {}, "O que conferir"), rotulo),
      el("div", { class: "field" }, el("label", {}, "Ajuda"), ajuda),
      el("div", { class: "grade" },
        el("div", { class: "field" }, el("label", {}, "Ordem"), ordem),
        el("div", { class: "field" }, el("label", {}, "Categoria"), categoria),
      ),
      el("div", { class: "field" }, el("label", {}, "Inventário"), dominio),

      el("label", { class: "opcao" }, cbEntrega,
        el("span", { class: "opcao-texto" },
          el("span", { class: "opcao-titulo" }, "Conferir na entrega"),
          el("span", { class: "opcao-dica" }, "Registra como o equipamento saiu."))),
      el("label", { class: "opcao" }, cbDevolucao,
        el("span", { class: "opcao-texto" },
          el("span", { class: "opcao-titulo" }, "Conferir na devolução"),
          el("span", { class: "opcao-dica" },
            "Sem os dois lados não há como afirmar que voltou pior."))),
      el("label", { class: "opcao" }, cbManutencao,
        el("span", { class: "opcao-texto" },
          el("span", { class: "opcao-titulo" }, "Avaria aqui abre manutenção"),
          el("span", { class: "opcao-dica" },
            "Desmarque para itens que não são avaria do equipamento, como um cabo faltando."))),
      el("label", { class: "opcao" }, cbAtivo,
        el("span", { class: "opcao-texto" },
          el("span", { class: "opcao-titulo" }, "Ativo"),
          el("span", { class: "opcao-dica" }, "Desmarque para esconder sem apagar."))),
    ),
    actions: [
      { label: "Cancelar", variant: "text" },
      { label: item ? "Salvar" : "Criar", variant: "filled", onClick: async (close) => {
        if (!rotulo.value.trim()) { mostrarErro(new Error("Dê um nome ao item.")); return; }
        const corpo = {
          rotulo: rotulo.value.trim(),
          ajuda: ajuda.value.trim() || null,
          ordem: Number(ordem.value) || 0,
          categoria_id: categoria.value ? Number(categoria.value) : null,
          dominio: dominio.value || null,
          na_entrega: cbEntrega.checked,
          na_devolucao: cbDevolucao.checked,
          abre_manutencao: cbManutencao.checked,
          ativo: cbAtivo.checked,
        };
        try {
          if (item) await api.put(`/checklist/${item.id}`, corpo);
          else await api.post("/checklist", corpo);
          close();
          toast(item ? "Item atualizado" : "Item criado");
          renderChecklist(root);
        } catch (e) { mostrarErro(e); }
      } },
    ],
  });
}

async function excluir(item, root) {
  if (!(await confirmSheet("Remover item",
      `Remover "${item.rotulo}" do checklist? O que já foi conferido não é afetado.`))) return;
  try {
    await api.del(`/checklist/${item.id}`);
    toast("Item removido");
    renderChecklist(root);
  } catch (e) { mostrarErro(e); }
}

async function semear(root) {
  if (!(await confirmSheet("Criar itens padrão",
      "Criar os 7 itens padrão de conferência? Você pode editar depois."))) return;
  try {
    const criados = await api.post("/checklist/semente", {});
    toast(criados?.length ? `${criados.length} item(ns) criado(s)` : "Já estavam todos lá");
    renderChecklist(root);
  } catch (e) { mostrarErro(e); }
}
