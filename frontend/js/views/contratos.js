/**
 * Contratos de locação — lista, cadastro e exercício da compra.
 *
 * A tela existe para tornar visível o que o financeiro já calcula: quanto
 * cada equipamento custa por mês, quais contratos vencem e o que acontece
 * quando alguém exerce a opção de compra.
 *
 * @module views/contratos
 */
import { api } from "../api.js";
import { state } from "../state.js";
import { ctx } from "../context.js";
import { el, icon, toast, dialog, confirmSheet, mostrarErro, emptyState } from "../ui.js";

const TIPOS = [
  ["locacao", "Locação"],
  ["comodato", "Comodato"],
  ["compra", "Compra"],
];
const TIPO_ROTULO = Object.fromEntries(TIPOS);

const FILTROS = [
  ["todos", "Todos"],
  ["abertos", "Em aberto"],
  ["vencendo", "Vencendo (90 dias)"],
];
let filtro = "todos";

export async function renderContratos(root) {
  ctx.setTitle("Contratos");
  root.innerHTML = "";

  const cabeca = el("div", { style: "margin-bottom:14px" },
    el("p", { class: "muted", style: "margin:0 0 10px" },
      "Locação, comodato e compra em lote. O custo por equipamento é rateado."),
    // "Vencendo" é a pergunta que o alerta do sino provoca: o sino avisa que
    // existe, e a pessoa vem aqui ver QUAIS. Sem o filtro, ela teria de
    // varrer a lista inteira procurando os chips vermelhos.
    el("div", { class: "row between wrap", style: "gap:10px;align-items:center" },
      el("div", { class: "row", style: "gap:6px" },
        ...FILTROS.map(([v, r]) => el("button", {
          class: "chip" + (filtro === v ? " selected" : ""),
          type: "button",
          onclick: () => { filtro = v; renderContratos(root); },
        }, r)),
      ),
      // Planilha de custo mensal. Existe porque o custo de locação não
      // aparece em lugar nenhum do financeiro tradicional — ele não é
      // patrimônio nem deprecia. É o que permite conferir a fatura do
      // fornecedor contra o que o sistema acha que está contratado.
      el("button", {
        class: "btn tonal", type: "button",
        onclick: async (ev) => {
          const b = ev.currentTarget;
          b.disabled = true;
          try {
            const url = await api.blob("/financeiro/contratos.csv");
            const a = document.createElement("a");
            a.href = url;
            a.download = "nexus-contratos.csv";
            a.click();
            // Sem revogar, a URL temporária fica viva até a página recarregar.
            setTimeout(() => URL.revokeObjectURL(url), 5000);
          } catch (e) { mostrarErro(e); }
          b.disabled = false;
        },
      }, "Exportar custos (CSV)"),
    ),
  );
  root.append(cabeca);

  const alvo = el("div", {}, el("p", { class: "muted" }, "Carregando…"));
  root.append(alvo);

  let contratos = [];
  try {
    const parametro = filtro === "abertos" ? "?apenas_abertos=true" : "";
    contratos = await api.get(`/contratos${parametro}`);
  } catch (e) {
    alvo.innerHTML = "";
    alvo.append(el("p", { class: "text-error" }, e.message));
    return;
  }

  if (filtro === "vencendo") {
    // Filtro local: `dias_para_vencer` já vem em cada contrato, e uma
    // consulta a mais ao servidor só para isso seria desperdício.
    contratos = contratos
      .filter((c) => c.dias_para_vencer !== null && c.dias_para_vencer <= 90)
      .sort((a, b) => a.dias_para_vencer - b.dias_para_vencer);
  }

  alvo.innerHTML = "";
  if (!contratos.length) {
    // `emptyState` é POSICIONAL: (icone, titulo, texto).
    //
    // Aqui estava sendo chamado com um objeto — as outras 22 telas usam a
    // forma posicional. Com o objeto, `title` chegava `undefined` e a tela
    // mostrava literalmente a palavra "undefined" no lugar da mensagem.
    //
    // Não havia erro no console: `undefined` interpolado numa template
    // string é uma string válida. O defeito era só visual — e por isso
    // nenhum guard pegou.
    alvo.append(emptyState(
      "relatorios",
      filtro === "vencendo"
        ? "Nenhum contrato vencendo nos próximos 90 dias"
        : filtro === "abertos" ? "Nenhum contrato em aberto" : "Nenhum contrato cadastrado",
      "Cadastre uma locação para acompanhar o custo mensal e o vencimento.",
    ));
  } else {
    for (const c of contratos) alvo.append(cartao(c, root));
  }

  // Só quem escreve vê o botão de criar.
  ctx.setFab(state.canWrite
    ? { label: "Novo contrato", icon: "plus", onClick: () => formulario(null, root) }
    : null);
}

function cartao(c, root) {
  const dias = c.dias_para_vencer;

  // A faixa de vencimento é a informação que a lista precisa dar de longe.
  let chipVenc = el("span", { class: "chip" }, "Prazo indeterminado");
  if (dias !== null) {
    if (dias < 0) chipVenc = el("span", { class: "chip erro" }, `Venceu há ${Math.abs(dias)}d`);
    else if (dias === 0) chipVenc = el("span", { class: "chip erro" }, "Vence hoje");
    else if (dias <= 30) chipVenc = el("span", { class: "chip aviso" }, `Vence em ${dias}d`);
    else if (dias <= 90) chipVenc = el("span", { class: "chip aviso" }, `${dias} dias`);
    else chipVenc = el("span", { class: "chip ok" }, `${dias} dias`);
  }

  const rateio = c.valor_mensal_por_ativo;
  const mensal = c.valor_mensal ? Number(c.valor_mensal) : null;

  return el("button", {
    type: "button", class: "cartao-contrato",
    onclick: () => detalhe(c.id, root),
  },
    el("div", { class: "row between wrap", style: "gap:10px" },
      el("b", { style: "font-size:15px" }, c.numero),
      el("div", { class: "row", style: "gap:6px" },
        el("span", { class: "chip" }, TIPO_ROTULO[c.tipo] || c.tipo),
        chipVenc,
      ),
    ),
    el("div", { class: "muted", style: "font-size:12.5px;margin-top:6px" },
      `${c.total_ativos} equipamento(s)`
      + (c.inicio ? ` · desde ${new Date(c.inicio + "T12:00").toLocaleDateString("pt-BR")}` : "")
      + (c.fim ? ` até ${new Date(c.fim + "T12:00").toLocaleDateString("pt-BR")}` : "")),
    mensal
      ? el("div", { style: "margin-top:8px;font-size:13px" },
          `R$ ${mensal.toLocaleString("pt-BR", { minimumFractionDigits: 2 })}/mês`,
          rateio
            ? el("span", { class: "muted" },
                ` · R$ ${Number(rateio).toLocaleString("pt-BR", { minimumFractionDigits: 2 })} por equipamento`)
            : null)
      : null,
  );
}

// ---------------------------------------------------------------------------
async function detalhe(id, root) {
  let c;
  try {
    c = await api.get(`/contratos/${id}`);
  } catch (e) { return mostrarErro(e); }

  let ativos = [];
  try {
    const r = await api.get(`/ativos?contrato_id=${id}&size=100`);
    ativos = r.items || [];
  } catch { /* a lista de ativos é complemento */ }

  const corpo = el("div", {},
    el("div", { class: "row between wrap", style: "gap:10px" },
      el("div", {},
        el("b", { style: "font-size:16px" }, c.numero),
        el("div", { class: "muted", style: "font-size:12.5px" },
          TIPO_ROTULO[c.tipo] || c.tipo)),
      c.valor_mensal
        ? el("div", { style: "text-align:right" },
            el("b", {}, `R$ ${Number(c.valor_mensal).toLocaleString("pt-BR", { minimumFractionDigits: 2 })}`),
            el("div", { class: "muted", style: "font-size:12px" }, "por mês"))
        : null,
    ),

    el("div", { class: "grade", style: "margin-top:16px" },
      campo("Início", fmtData(c.inicio)),
      campo("Fim", c.fim ? fmtData(c.fim) : "Prazo indeterminado"),
      campo("Equipamentos", String(c.total_ativos)),
      campo("Rateio por equipamento",
        c.valor_mensal_por_ativo
          ? `R$ ${Number(c.valor_mensal_por_ativo).toLocaleString("pt-BR", { minimumFractionDigits: 2 })}`
          : "—"),
    ),

    c.observacoes
      ? el("div", { class: "recado info" }, c.observacoes)
      : null,

    el("p", { class: "dica", style: "margin:18px 0 8px" },
      `Equipamentos vinculados (${ativos.length})`),
    ativos.length
      ? el("div", {}, ...ativos.map((a) => linhaDeAtivo(a, c, root)))
      : el("p", { class: "muted" }, "Nenhum equipamento vinculado ainda."),

    el("div", { class: "row", style: "margin-top:14px" },
      el("button", { class: "btn tonal", type: "button",
        onclick: () => vincularAtivos(c, root, ativos), _fecha: true },
        "Vincular equipamentos"),
    ),
  );

  dialog({
    title: "Contrato",
    wide: true,
    body: corpo,
    actions: [
      { label: "Editar", variant: "text", onClick: () => formulario(c, root) },
      { label: "Fechar", variant: "filled" },
    ],
  });
}

function linhaDeAtivo(a, c, root) {
  const locado = a.forma_aquisicao === "locado";
  return el("div", { class: "row between wrap", style: "gap:8px;padding:8px 0;border-bottom:1px solid var(--md-sys-color-outline-variant)" },
    el("div", {},
      el("b", {}, a.patrimonio),
      el("div", { class: "muted", style: "font-size:12px" },
        [a.hostname, a.modelo, a.marca].filter(Boolean).join(" · ") || "sem detalhes")),
    locado
      ? el("button", {
          class: "btn tonal", type: "button",
          onclick: () => exercerCompra(c, a, root),
        }, "Exercer compra")
      : el("span", { class: "chip ok" }, "Comprado"),
  );
}

function campo(rotulo, valor) {
  return el("div", {},
    el("div", { class: "dica" }, rotulo),
    el("div", {}, valor));
}

function fmtData(iso) {
  return new Date(iso + "T12:00").toLocaleDateString("pt-BR");
}

// ---------------------------------------------------------------------------
function formulario(c, root) {
  const v = (nome, valor = "") => el("input", { name: nome, value: valor });
  const campos = {
    numero: v("numero", c?.numero || ""),
    tipo: el("select", { name: "tipo" },
      ...TIPOS.map(([k, r]) => el("option", { value: k, selected: c?.tipo === k ? "selected" : null }, r))),
    inicio: el("input", { type: "date", name: "inicio", value: c?.inicio || "" }),
    fim: el("input", { type: "date", name: "fim", value: c?.fim || "" }),
    valor_mensal: el("input", { name: "valor_mensal", inputmode: "decimal",
      value: c?.valor_mensal ? String(c.valor_mensal) : "" }),
    dia_vencimento: el("input", { name: "dia_vencimento", type: "number", min: "1", max: "31",
      value: c?.dia_vencimento ? String(c.dia_vencimento) : "" }),
    observacoes: el("textarea", { name: "observacoes", rows: "3" }, c?.observacoes || ""),
  };

  // O campo de mensalidade some no comodato: não há cobrança, e deixá-lo à
  // vista convidaria a preencher um valor que o servidor vai recusar.
  const campoMensal = el("div", { class: "field" },
    el("label", {}, "Valor mensal (R$)"), campos.valor_mensal,
    el("span", { class: "dica" }, "O valor do CONTRATO, não de cada equipamento."));
  const atualizarTipo = () => {
    const t = campos.tipo.value;
    campoMensal.classList.toggle("oculto", t === "comodato" || t === "compra");
    campos.valor_mensal.required = t === "locacao";
  };
  campos.tipo.addEventListener("change", atualizarTipo);
  atualizarTipo();

  dialog({
    title: c ? "Editar contrato" : "Novo contrato",
    wide: true,
    body: el("div", { class: "grade" },
      el("div", { class: "field" }, el("label", {}, "Número *"), campos.numero),
      el("div", { class: "field" }, el("label", {}, "Tipo"), campos.tipo),
      el("div", { class: "field" }, el("label", {}, "Início *"), campos.inicio),
      el("div", { class: "field" }, el("label", {}, "Fim"),
        campos.fim,
        el("span", { class: "dica" }, "Em branco = prazo indeterminado.")),
      campoMensal,
      el("div", { class: "field" }, el("label", {}, "Dia do vencimento"), campos.dia_vencimento),
      el("div", { class: "field", style: "grid-column:1/-1" },
        el("label", {}, "Observações"), campos.observacoes),
    ),
    actions: [
      { label: "Cancelar", variant: "text" },
      { label: "Salvar", variant: "filled", onClick: async (close) => {
        const corpo = {
          numero: campos.numero.value.trim(),
          tipo: campos.tipo.value,
          inicio: campos.inicio.value,
          fim: campos.fim.value || null,
          valor_mensal: campos.valor_mensal.value || null,
          dia_vencimento: campos.dia_vencimento.value || null,
          observacoes: campos.observacoes.value.trim() || null,
        };
        if (!corpo.numero || !corpo.inicio) {
          return mostrarErro(new Error("Número e início são obrigatórios."));
        }
        try {
          if (c) await api.put(`/contratos/${c.id}`, corpo);
          else await api.post("/contratos", corpo);
          close();
          toast(c ? "Contrato atualizado" : "Contrato criado");
          renderContratos(root);
        } catch (e) { mostrarErro(e); }
      } },
    ],
  });
}

// ---------------------------------------------------------------------------
/**
 * Vincular equipamentos ao contrato.
 *
 * Busca no servidor e deixa marcar vários: um contrato de locação costuma
 * chegar com dezenas de equipamentos de uma vez, e vincular um a um seria
 * inviável.
 */
async function vincularAtivos(c, root, jaVinculados) {
  const escolhidos = new Set();
  const lista = el("div", { class: "vinculo-lista" },
    el("p", { class: "muted" }, "Digite para buscar equipamentos."));
  const campo = el("input", {
    placeholder: "Patrimônio, hostname, série, modelo…",
    autocomplete: "off",
  });
  const contagem = el("span", { class: "muted", style: "font-size:12.5px" }, "Nenhum selecionado");
  const marcarLocado = el("input", { type: "checkbox", checked: "checked" });

  let timer = null;
  let geracao = 0;

  async function buscar() {
    const termo = campo.value.trim();
    if (termo.length < 2) {
      lista.innerHTML = "";
      lista.append(el("p", { class: "muted" }, "Digite ao menos 2 letras."));
      return;
    }
    const meu = ++geracao;
    try {
      const r = await api.get(`/ativos?search=${encodeURIComponent(termo)}&size=20`);
      if (meu !== geracao) return;
      pintar(r.items || []);
    } catch { /* busca auxiliar */ }
  }

  function pintar(itens) {
    lista.innerHTML = "";
    if (!itens.length) {
      lista.append(el("p", { class: "muted" }, "Nada encontrado."));
      return;
    }
    for (const a of itens) {
      // Quem já está no contrato aparece marcado e travado: vincular de novo
      // não muda nada, e desmarcar aqui daria a impressão de desvincular —
      // que é outra operação, com outra consequência no rateio.
      const jaEsta = jaVinculados.some((x) => x.id === a.id);
      const cx = el("input", {
        type: "checkbox",
        checked: jaEsta || escolhidos.has(a.id) ? "checked" : null,
        disabled: jaEsta ? "disabled" : null,
      });
      if (!jaEsta) {
        cx.addEventListener("change", () => {
          if (cx.checked) escolhidos.add(a.id);
          else escolhidos.delete(a.id);
          contagem.textContent = escolhidos.size
            ? `${escolhidos.size} selecionado(s)`
            : "Nenhum selecionado";
        });
      }
      lista.append(el("label", { class: "vinculo-item" }, cx,
        el("span", {},
          el("b", {}, a.patrimonio),
          el("span", { class: "muted", style: "font-size:12px;display:block" },
            [a.hostname, a.modelo, a.marca].filter(Boolean).join(" · ")
            || "sem detalhes"))));
    }
  }

  campo.addEventListener("input", () => {
    clearTimeout(timer);
    timer = setTimeout(buscar, 220);
  });

  dialog({
    title: "Vincular equipamentos",
    wide: true,
    body: el("div", {},
      el("p", { class: "muted", style: "margin:0 0 10px;font-size:13px" },
        `Equipamentos entram no contrato ${c.numero} e passam a ser rateados `
        + "entre os demais."),
      el("div", { class: "field" }, campo),
      lista,
      el("div", { class: "row between wrap", style: "gap:10px;margin-top:14px" },
        contagem,
        el("label", { class: "opcao", style: "margin:0" }, marcarLocado,
          el("span", { class: "opcao-texto" },
            el("span", { class: "opcao-titulo" }, "Marcar como locado"),
            el("span", { class: "opcao-dica" },
              "Desmarque para contrato de compra em lote.")))),
    ),
    actions: [
      { label: "Cancelar", variant: "text" },
      { label: "Vincular", variant: "filled", onClick: async (close) => {
        if (!escolhidos.size) {
          return mostrarErro(new Error("Selecione ao menos um equipamento."));
        }
        try {
          await api.post(`/contratos/${c.id}/ativos`, {
            ativo_ids: [...escolhidos],
            marcar_como_locado: marcarLocado.checked,
          });
          close();
          toast(`${escolhidos.size} equipamento(s) vinculado(s)`);
          renderContratos(root);
        } catch (e) { mostrarErro(e); }
      } },
    ],
  });
  setTimeout(() => campo.focus(), 100);
}

// ---------------------------------------------------------------------------
/**
 * Exercer a opção de compra.
 *
 * A confirmação explica o que muda — é uma mudança de natureza patrimonial, e
 * quem clica precisa saber que o equipamento sai do rateio e passa a
 * depreciar.
 */
async function exercerCompra(c, a, root) {
  const valor = el("input", {
    inputmode: "decimal",
    value: a.valor_residual ? String(a.valor_residual) : "",
  });
  const data = el("input", { type: "date", value: new Date().toISOString().slice(0, 10) });

  dialog({
    title: "Exercer a compra",
    body: el("div", {},
      el("div", { class: "recado info" },
        el("b", {}, `Comprar ${a.patrimonio}.`),
        " O equipamento sai da locação e passa a ser patrimônio da empresa."),
      el("p", { class: "muted", style: "font-size:13px;margin:12px 0" },
        "A depreciação começa na data da compra — não retroage ao início da "
        + "locação. E o rateio dos equipamentos que ficam no contrato sobe, "
        + "porque a mensalidade não muda."),
      el("div", { class: "grade" },
        el("div", { class: "field" }, el("label", {}, "Valor pago (R$) *"), valor),
        el("div", { class: "field" }, el("label", {}, "Data da compra"), data),
      ),
    ),
    actions: [
      { label: "Cancelar", variant: "text" },
      { label: "Confirmar compra", variant: "filled", onClick: async (close) => {
        try {
          await api.post(`/contratos/${c.id}/ativos/${a.id}/exercer-compra`, {
            valor: valor.value, data: data.value || null,
          });
          close();
          toast("Compra registrada");
          renderContratos(root);
        } catch (e) { mostrarErro(e); }
      } },
    ],
  });
}
