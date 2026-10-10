/**
 * Painel financeiro — valor do parque, garantias, rateio e custo por página.
 *
 * Tudo aqui é **derivado**: o valor vem do cadastro do ativo, a manutenção das
 * ordens de serviço e o consumível das saídas com finalidade "instalação".
 * Nada é digitado duas vezes.
 *
 * @module views/financeiro
 */
import { api } from "../api.js";
import { state } from "../state.js";
import { ctx } from "../context.js";
import { el, icon, fmtMoney, skeleton, mostrarErro } from "../ui.js";

const ABAS = [
  ["resumo", "Resumo do parque"],
  ["garantias", "Garantias"],
  ["rateio", "Centro de custo"],
  ["pagina", "Custo por página"],
];

let aba = "resumo";

export async function renderFinanceiro(root) {
  ctx.setTitle("Financeiro");
  ctx.setFab(null);
  root.innerHTML = "";

  root.append(
    el("h1", { class: "page-title" }, "Financeiro"),
    el("p", { class: "muted", style: "margin:0 0 16px" },
      "Valor do parque, garantias, custo por departamento e custo por página — "
      + "calculados a partir do cadastro e das manutenções."),
    el("div", { class: "tabs", style: "flex-wrap:wrap;margin-bottom:18px" },
      ...ABAS.map(([chave, rotulo]) => el("button", {
        class: chave === aba ? "active" : "",
        onclick: () => { aba = chave; renderFinanceiro(root); },
      }, rotulo))),
  );

  const caixa = el("div", {}, skeleton(4));
  root.append(caixa);

  try {
    if (aba === "resumo") await telaResumo(caixa);
    else if (aba === "garantias") await telaGarantias(caixa);
    else if (aba === "rateio") await telaRateio(caixa);
    else await telaPagina(caixa);
  } catch (e) {
    caixa.innerHTML = "";
    caixa.append(el("p", { class: "text-error" }, e.message));
  }
}

function numero(valor, rotulo, tom = "") {
  return el("div", { class: `numero ${tom}` },
    el("span", { class: "numero-valor" }, valor),
    el("span", { class: "numero-rotulo" }, rotulo));
}

function dinheiro(v) {
  return fmtMoney(v ?? 0) || "R$ 0,00";
}

// ---------------------------------------------------------------------------
async function telaResumo(caixa) {
  const r = await api.get("/financeiro/resumo");
  const g = r.garantias || {};
  caixa.innerHTML = "";

  caixa.append(
    el("div", { class: "resumo-numeros" },
      numero(r.ativos ?? 0, "Ativos"),
      numero(dinheiro(r.valor_aquisicao), "Valor de compra"),
      numero(dinheiro(r.valor_atual), "Valor hoje", "ok"),
      numero(dinheiro(r.valor_depreciado), "Já depreciado", "aviso"),
      numero(`${r.percentual_depreciado ?? 0}%`, "Depreciado"),
      numero(dinheiro(r.custo_manutencao), "Manutenção"),
      numero(dinheiro(r.tco_total), "TCO total"),
      numero(r.garantias_vencendo ?? 0, "Garantias vencendo",
        (r.garantias_vencendo ?? 0) > 0 ? "erro" : ""),
    ),
    el("p", { class: "muted", style: "font-size:12.5px;margin-top:14px" },
      "O valor de hoje usa depreciação linear: 20% ao ano para TI, 10% para impressoras."),
  );

  caixa.append(el("h3", { style: "margin:24px 0 10px" }, "Garantias por situação"));
  caixa.append(el("div", { class: "resumo-numeros" },
    numero(g.vigente ?? 0, "Vigentes", "ok"),
    numero(g.atencao ?? 0, "Atenção (90 dias)"),
    numero(g.vencendo ?? 0, "Vencendo (30 dias)", (g.vencendo ?? 0) > 0 ? "erro" : ""),
    numero(g.vencida ?? 0, "Vencidas"),
    numero(g.nao_informada ?? 0, "Sem data"),
  ));
}

async function telaGarantias(caixa) {
  const r = await api.get("/financeiro/garantias", { dias: 120 });
  caixa.innerHTML = "";

  const itens = r.itens || [];
  if (!itens.length) {
    caixa.append(el("p", { class: "muted" },
      "Nenhuma garantia vencendo nos próximos 120 dias. 👍"));
    return;
  }

  caixa.append(
    el("p", { class: "muted", style: "margin:0 0 14px" },
      `${itens.length} equipamento(s) com garantia vencendo — vale reparar antes de perdê-la.`),
    el("div", { class: "cartoes" },
      ...itens.map((g) => el("div", { class: "cartao-contagem" },
        el("div", { class: "row between wrap", style: "gap:10px" },
          el("b", {}, g.patrimonio || "(sem patrimônio)"),
          el("span", { class: `chip ${g.situacao === "vencendo" ? "aviso" : "info"}` },
            `${g.dias_restantes} dia(s)`),
        ),
        el("div", { class: "muted", style: "font-size:12.5px;margin-top:4px" },
          [g.marca, g.modelo].filter(Boolean).join(" "),
          g.departamento ? ` · ${g.departamento}` : "",
          g.valor ? ` · ${dinheiro(g.valor)}` : ""),
      ))),
  );
}

async function telaRateio(caixa) {
  const r = await api.get("/financeiro/rateio");
  const itens = r.itens || [];
  caixa.innerHTML = "";

  if (!itens.length) {
    caixa.append(el("p", { class: "muted" }, "Nenhum ativo cadastrado ainda."));
    return;
  }

  const maior = Math.max(...itens.map((x) => x.total || 0), 1);
  caixa.append(el("div", { class: "cartoes" },
    ...itens.map((d) => el("div", { class: "cartao-contagem" },
      el("div", { class: "row between wrap", style: "gap:10px" },
        el("b", { style: "font-size:15px" }, d.departamento),
        el("span", { class: "chip" }, `${d.ativos} ativo(s)`)),
      el("div", { class: "progresso" },
        el("div", { class: "progresso-barra",
          style: `width:${Math.round(((d.total || 0) / maior) * 100)}%` })),
      el("div", { class: "muted", style: "font-size:12.5px;margin-top:8px" },
        `Compra ${dinheiro(d.valor_aquisicao)} · hoje ${dinheiro(d.valor_atual)} `
        + `· manutenção ${dinheiro(d.custo_manutencao)}`),
      el("div", { style: "font-weight:600;margin-top:4px" }, `Total ${dinheiro(d.total)}`),
    ))),
  );
}

async function telaPagina(caixa) {
  const r = await api.get("/financeiro/custo-por-pagina");
  caixa.innerHTML = "";

  const itens = r.items || [];
  if (!itens.length) {
    caixa.append(el("p", { class: "muted" },
      r.sem_dados
        ? `${r.sem_dados} impressora(s) sem contador ou consumível registrado — `
          + "sem esses dados o custo por página não é confiável."
        : "Nenhuma impressora cadastrada ainda."));
    return;
  }

  caixa.append(
    el("p", { class: "muted", style: "margin:0 0 14px" },
      "Da mais cara para a mais barata, por página impressa. "
      + "O custo do consumível é o REAL — gasto dividido pelas páginas do período."),
    el("div", { class: "cartoes" },
      ...itens.map((p, i) => el("div", { class: "cartao-contagem" },
        el("div", { class: "row between wrap", style: "gap:10px" },
          el("b", {}, `${i + 1}. ${p.patrimonio || "(sem patrimônio)"}`),
          el("span", { class: "chip aviso" }, `${dinheiro(p.custo_por_pagina_total)}/pág.`)),
        el("div", { class: "muted", style: "font-size:12.5px;margin-top:6px" },
          [p.marca, p.modelo].filter(Boolean).join(" "),
          p.paginas_impressas ? ` · ${Number(p.paginas_impressas).toLocaleString("pt-BR")} páginas` : ""),
        el("div", { class: "muted", style: "font-size:12px;margin-top:6px" },
          `consumível ${p.custo_por_pagina_consumivel_real != null ? dinheiro(p.custo_por_pagina_consumivel_real) : "—"}`
          + ` · manutenção ${p.custo_por_pagina_manutencao != null ? dinheiro(p.custo_por_pagina_manutencao) : "—"}`
          + ` · depreciação ${p.custo_por_pagina_depreciacao != null ? dinheiro(p.custo_por_pagina_depreciacao) : "—"}`),
        p.custo_total_estimado
          ? el("div", { style: "margin-top:6px;font-weight:600" },
              `Gasto estimado no período: ${dinheiro(p.custo_total_estimado)}`)
          : null,
      ))),
    r.sem_dados
      ? el("p", { class: "muted", style: "margin-top:14px;font-size:12.5px" },
          `${r.sem_dados} impressora(s) ficaram de fora por falta de contador ou consumível.`)
      : null,
  );
}
