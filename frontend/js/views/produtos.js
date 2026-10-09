/**
 * Consumíveis (produtos): tabela, CRUD e movimentação de entrada/saída.
 * @module views/produtos
 */
import { api } from "../api.js";
import { state } from "../state.js";
import { ctx } from "../context.js";
import { el, icon, toast, dialog, confirmSheet, emptyState, skeleton, fmtMoney, fmtDate, mostrarErro } from "../ui.js";
import { loadLookups, optionsOf } from "../lookups.js";

const PAGE_SIZE = 20;
let page = 1;
let filtroSearch = "";

const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

function openForm(produto, lookups) {
  const isEdit = Boolean(produto);
  const p = produto || {};
  const form = el("form", { html: `
    <div class="form-grid">
      <div class="field"><label>SKU *</label><input name="sku" required value="${esc(p.sku)}"></div>
      <div class="field"><label>Nome *</label><input name="nome" required value="${esc(p.nome)}"></div>
      <div class="field"><label>Categoria</label><select name="categoria_id">${optionsOf(lookups.categorias)}</select></div>
      <div class="field"><label>Fornecedor</label><select name="fornecedor_id">${optionsOf(lookups.fornecedores)}</select></div>
      <div class="field"><label>Unidade</label><input name="unidade" value="${esc(p.unidade || "un")}"></div>
      <div class="field"><label>Estoque mínimo</label><input type="number" name="estoque_minimo" value="${p.estoque_minimo ?? 0}"></div>
      <div class="field"><label>Preço unitário (R$)</label><input type="number" step="0.01" name="preco_unitario" value="${p.preco_unitario ?? ""}"></div>
    </div>
    <div class="field"><label>Descrição</label><textarea name="descricao">${esc(p.descricao)}</textarea></div>` });
  if (isEdit) {
    form.querySelector('[name="categoria_id"]').value = p.categoria_id || "";
    form.querySelector('[name="fornecedor_id"]').value = p.fornecedor_id || "";
  }
  dialog({
    title: isEdit ? "Editar produto" : "Novo produto",
    body: form,
    wide: true,
    actions: [
      { label: "Cancelar", variant: "text" },
      { label: "Salvar", variant: "filled", onClick: async (close) => {
        const fd = new FormData(form);
        const data = Object.fromEntries(fd.entries());
        for (const k of ["estoque_minimo", "preco_unitario", "categoria_id", "fornecedor_id"]) {
          data[k] = data[k] === "" ? null : Number(data[k]);
        }
        data.dominio = state.dominio;
        data.tipo_item = "consumivel";
        try {
          if (isEdit) await api.put(`/produtos/${p.id}`, data);
          else await api.post("/produtos", data);
          close(); toast(isEdit ? "Produto atualizado" : "Produto criado");
          const root = document.getElementById("view"); renderProdutos(root);
        } catch (e) { mostrarErro(e, isEdit ? "salvar as alterações do produto" : "cadastrar o produto"); }
      } },
    ],
  });
}

function movimentar(produto) {
  const tipoSel = el("select", {}, el("option", { value: "entrada" }, "Entrada"), el("option", { value: "saida" }, "Saída"));
  const qtd = el("input", { type: "number", min: 1, value: 1 });
  const obs = el("input", { placeholder: "Observações" });

  // --- Finalidade (só em SAÍDA) -----------------------------------------
  // "Saíram 2 unidades" não responde o que importa: foi descarte ou foi usado
  // numa máquina — e em qual.
  const finalidadeSel = el("select", {},
    el("option", { value: "" }, "— não informar —"),
    el("option", { value: "descarte" }, "Descarte"),
    el("option", { value: "instalacao" }, "Instalação em um ativo"),
  );
  const buscaAtivo = el("input", { placeholder: "Patrimônio, hostname ou nº de série" });
  const resultados = el("div", { class: "busca-ativos" });
  const escolhido = el("div", { class: "ativo-escolhido oculto" });

  const blocoFinalidade = el("div", { class: "field" },
    el("label", {}, "Finalidade"), finalidadeSel);
  const blocoAtivo = el("div", { class: "field" },
    el("label", {}, "Em qual ativo foi instalado?"),
    buscaAtivo, escolhido, resultados);

  // O ativo escolhido fica guardado aqui — a busca só preenche a lista.
  let ativoEscolhido = null;
  // Número da última busca: respostas fora de ordem são descartadas. Sem isto
  // uma consulta lenta sobrescrevia o resultado de outra mais recente, e a
  // lista "piscava" com o conteúdo errado.
  let buscaAtual = 0;

  function limparResultados() {
    resultados.innerHTML = "";
    resultados.classList.remove("aberto");
  }

  function mostrarEscolhido(ativo) {
    ativoEscolhido = ativo;
    buscaAtivo.value = "";
    limparResultados();
    escolhido.innerHTML = "";
    escolhido.classList.remove("oculto");
    escolhido.append(
      el("span", { class: "chip" }, `${ativo.patrimonio}${ativo.hostname ? ` · ${ativo.hostname}` : ""}`),
      el("button", {
        type: "button", class: "iconbtn", title: "Trocar de ativo", html: icon("close", 16),
        onclick: () => {
          ativoEscolhido = null;
          escolhido.classList.add("oculto");
          escolhido.innerHTML = "";
          buscaAtivo.focus();
        },
      }),
    );
  }

  function hostnameDe(a) {
    // Na listagem o hostname vem dentro de `ti`; aceitamos as duas formas para
    // não depender do formato exato do resumo.
    return a.ti?.hostname || a.hostname || "";
  }

  let timer = null;
  buscaAtivo.addEventListener("input", () => {
    ativoEscolhido = null;
    escolhido.classList.add("oculto");
    clearTimeout(timer);
    const termo = buscaAtivo.value.trim();
    if (termo.length < 2) { limparResultados(); return; }

    timer = setTimeout(async () => {
      const meu = ++buscaAtual;
      try {
        const r = await api.get("/ativos", { search: termo, size: 15, dominio: state.dominio });
        if (meu !== buscaAtual) return;   // chegou atrasada: ignora
        const itens = r.items || [];
        resultados.innerHTML = "";
        resultados.classList.add("aberto");

        if (!itens.length) {
          resultados.append(el("div", { class: "busca-vazia" },
            `Nenhum ativo encontrado para "${termo}".`));
          return;
        }
        for (const a of itens) {
          const host = hostnameDe(a);
          resultados.append(el("button", {
            type: "button", class: "busca-item",
            onclick: () => mostrarEscolhido({ id: a.id, patrimonio: a.patrimonio, hostname: host }),
          },
            el("b", {}, a.patrimonio || "(sem patrimônio)"),
            host ? el("span", { class: "busca-host" }, host) : null,
            el("span", { class: "busca-modelo" }, [a.marca, a.modelo].filter(Boolean).join(" ") || ""),
          ));
        }
      } catch (e) {
        if (meu !== buscaAtual) return;
        resultados.innerHTML = "";
        resultados.classList.add("aberto");
        resultados.append(el("div", { class: "busca-vazia" }, e.message || "Falha na busca."));
      }
    }, 250);
  });

  const atualizarVisibilidade = () => {
    const ehSaida = tipoSel.value === "saida";
    blocoFinalidade.classList.toggle("oculto", !ehSaida);
    blocoAtivo.classList.toggle("oculto", !ehSaida || finalidadeSel.value !== "instalacao");
    if (!ehSaida) { finalidadeSel.value = ""; }
    if (finalidadeSel.value !== "instalacao") {
      buscaAtivo.value = "";
      ativoEscolhido = null;
      escolhido.classList.add("oculto");
      limparResultados();
    }
  };
  tipoSel.addEventListener("change", atualizarVisibilidade);
  finalidadeSel.addEventListener("change", atualizarVisibilidade);

  atualizarVisibilidade();

  dialog({
    title: `Movimentar: ${produto.nome}`,
    body: el("div", {},
      el("div", { class: "field" }, el("label", {}, "Tipo"), tipoSel),
      el("div", { class: "field" }, el("label", {}, "Quantidade"), qtd),
      blocoFinalidade,
      blocoAtivo,
      el("div", { class: "field" }, el("label", {}, "Observações"), obs),
    ),
    actions: [
      { label: "Cancelar", variant: "text" },
      { label: "Registrar", variant: "filled", onClick: async (close) => {
        const corpo = {
          tipo: tipoSel.value,
          produto_id: produto.id,
          quantidade: Number(qtd.value) || 1,
          observacoes: obs.value || null,
        };
        if (tipoSel.value === "saida" && finalidadeSel.value) {
          corpo.finalidade = finalidadeSel.value;
          if (finalidadeSel.value === "instalacao") {
            if (!ativoEscolhido) {
              mostrarErro(new Error(
                "Escolha o ativo na lista — digite ao menos 2 letras do patrimônio ou do hostname."));
              return;
            }
            corpo.ativo_instalado_id = ativoEscolhido.id;
          }
        }
        try {
          await api.post("/movimentacoes", corpo);
          close();
          toast(tipoSel.value === "entrada" ? "Entrada registrada" : "Saída registrada");
        } catch (e) { mostrarErro(e); }
      } },
    ],
  });
}

/**
 * Histórico de entrada e saída de um consumível.
 *
 * Mostra **quem** movimentou e **quando** — os dois dados já existiam na
 * movimentação; o que faltava era uma forma legível de lê-los.
 */
async function verHistorico(produto) {
  const caixa = el("div", {}, el("p", { class: "muted" }, "Carregando…"));

  dialog({
    title: `Histórico — ${produto.nome}`,
    wide: true,
    body: caixa,
    actions: [{ label: "Fechar", variant: "text" }],
  });

  let r;
  try {
    r = await api.get("/movimentacoes", { produto_id: produto.id, size: 100 });
  } catch (e) {
    caixa.innerHTML = "";
    caixa.append(el("p", { class: "text-error" }, e.message));
    return;
  }

  caixa.innerHTML = "";
  const itens = r.items || [];
  if (!itens.length) {
    caixa.append(el("p", { class: "muted", style: "margin:0" },
      "Nenhuma entrada ou saída registrada para este consumível ainda."));
    return;
  }

  const entrada = (t) => String(t).toLowerCase().includes("entrada");
  const totalE = itens.filter((m) => entrada(m.tipo)).reduce((s, m) => s + m.quantidade, 0);
  const totalS = itens.filter((m) => !entrada(m.tipo)).reduce((s, m) => s + m.quantidade, 0);

  caixa.append(
    el("div", { class: "row", style: "gap:8px;flex-wrap:wrap;margin-bottom:14px" },
      el("span", { class: "chip" }, `${itens.length} movimentação(ões)`),
      el("span", { class: "chip" }, `Entradas: ${totalE}`),
      el("span", { class: "chip" }, `Saídas: ${totalS}`),
    ),
    el("div", { class: "historico" },
      ...itens.map((m) => el("div", { class: `hist-linha ${entrada(m.tipo) ? "entrada" : "saida"}` },
        el("span", { class: "hist-tipo", html: icon(entrada(m.tipo) ? "down" : "up", 16) }),
        el("span", { class: "hist-qtd" }, `${entrada(m.tipo) ? "+" : "−"}${m.quantidade}`),
        el("span", { class: "hist-info" },
          el("b", {}, entrada(m.tipo) ? "Entrada" : "Saída"),
          ` · ${m.usuario_nome || "usuário não identificado"}`,
          ` · ${fmtDate(m.data_mov, true)}`,
          m.observacoes ? el("span", { class: "muted" }, ` — ${m.observacoes}`) : null,
          // Finalidade da saída: descarte, ou em qual equipamento foi instalado.
          // O hostname acompanha o patrimônio: é por ele que a máquina é
          // conhecida no dia a dia.
          m.finalidade_rotulo
            ? el("span", { class: "hist-finalidade" },
                m.finalidade === "instalacao" && m.ativo_instalado_patrimonio
                  ? ` · ${m.finalidade_rotulo}: ${m.ativo_instalado_patrimonio}`
                    + (m.ativo_instalado_hostname ? ` (${m.ativo_instalado_hostname})` : "")
                  : ` · ${m.finalidade_rotulo}`)
            : null,
        ),
      )),
    ),
  );
}

async function renderList(root) {
  root.innerHTML = "";
  const q = { dominio: state.dominio, page, size: PAGE_SIZE };
  if (filtroSearch) q.search = filtroSearch;
  let data;
  try { data = await api.get("/produtos", q); }
  catch (e) { root.append(emptyState("produtos", "Erro", e.message)); return; }

  if (!data.items.length) { root.append(emptyState("produtos", "Nenhum consumível", "Cadastre consumíveis deste domínio.")); return; }

  const table = el("table", { class: "data" },
    el("thead", {}, el("tr", {}, ...["SKU", "Nome", "Unidade", "Mínimo", "Preço", "Ações"].map((h) => el("th", {}, h)))),
    el("tbody", {}, ...data.items.map((p) => el("tr", {},
      el("td", { style: "font-weight:600" }, p.sku),
      el("td", {}, p.nome),
      el("td", {}, p.unidade || "un"),
      el("td", {}, String(p.estoque_minimo)),
      el("td", {}, fmtMoney(p.preco_unitario)),
      el("td", { class: "actions" },
        // O histórico é leitura: fica disponível mesmo para quem não escreve.
        el("button", {
          class: "iconbtn", title: "Histórico de entrada e saída",
          onclick: () => verHistorico(p), html: icon("historico"),
        }),
        ...(state.canWrite ? [
          el("button", { class: "iconbtn", title: "Movimentar", onclick: () => movimentar(p), html: icon("swap") }),
          el("button", { class: "iconbtn", title: "Editar", onclick: () => openForm(p, lookupsCache), html: icon("edit") }),
          el("button", { class: "iconbtn", title: "Excluir", onclick: async () => {
            if (await confirmSheet("Excluir produto", `Excluir ${p.nome}?`)) { await api.del(`/produtos/${p.id}`); toast("Excluído"); renderList(root); }
          }, html: icon("trash") }),
        ] : []),
      ),
    ))),
  );

  root.append(
    el("div", { class: "table-wrap" }, table),
    el("div", { class: "pagination" },
      el("button", { class: "iconbtn", disabled: page <= 1, onclick: () => { page--; renderList(root); }, html: icon("chevL") }),
      el("span", {}, `Página ${data.page} de ${data.pages || 1} (${data.total} itens)`),
      el("button", { class: "iconbtn", disabled: page >= data.pages, onclick: () => { page++; renderList(root); }, html: icon("chevR") }),
    ),
  );
}

let lookupsCache = null;

export async function renderProdutos(root) {
  ctx.setTitle("Consumíveis");
  ctx.setFab(state.canWrite ? { label: "Novo Consumível", icon: "add", onClick: () => openForm(null, lookupsCache) } : null);

  let listRoot = null;
  function refresh() { if (listRoot) renderList(listRoot); }

  const toolbar = el("div", { class: "toolbar" },
    el("div", { class: "field", style: "margin:0;flex:1;min-width:220px" },
      el("input", { class: "search-input", placeholder: "Buscar por nome ou SKU…", value: filtroSearch, oninput: (e) => { filtroSearch = e.target.value; page = 1; refresh(); } }),
    ),
  );

  root.innerHTML = "";
  root.append(el("h1", { class: "page-title" }, `${state.dominioLabel} — Consumíveis`), toolbar, el("div", { id: "produtos-list" }, skeleton(6)));
  listRoot = root.querySelector("#produtos-list");

  lookupsCache = await loadLookups();
  ctx.setFab(state.canWrite ? { label: "Novo Consumível", icon: "add", onClick: () => openForm(null, lookupsCache) } : null);
  await renderList(listRoot);
}
