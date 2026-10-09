/**
 * Dashboard com KPIs distintos por domínio.
 * @module views/dashboard
 */
import { api } from "../api.js";
import { state } from "../state.js";
import { ctx } from "../context.js";
import { el, icon, skeleton, toast, mostrarErro } from "../ui.js";

function kpi(label, value, iconName) {
  return el("div", { class: "kpi" },
    el("div", { class: "kpi-icon", html: icon(iconName, 28) }),
    el("div", { class: "kpi-value" }, String(value)),
    el("div", { class: "kpi-label" }, label),
  );
}

function bar(label, value, max) {
  const pct = max > 0 ? Math.min(100, Math.round((value / max) * 100)) : 0;
  return el("div", { class: "bar-row" },
    el("div", { class: "bar-label" }, label),
    el("div", { class: "bar-track" }, el("div", { class: "bar-fill", style: `width:${pct}%` })),
    el("div", { class: "bar-val" }, String(value)),
  );
}

export async function renderDashboard(root) {
  ctx.setTitle("Dashboard");
  ctx.setFab(null);
  root.innerHTML = "";
  root.append(skeleton(6));

  try {
    const s = await api.get("/dashboard/stats", { dominio: state.dominio });
    root.innerHTML = "";

    const isTI = state.dominio === "ti";
    const cards = [
      kpi("Total de ativos", s.total, isTI ? "ativos" : "print"),
      kpi("Alocados", s.alocados, "user"),
      kpi("Em manutenção", s.por_status.manutencao, "manutencoes"),
      kpi(isTI ? "Em estoque" : "Contador total", isTI ? s.por_status.estoque : (s.extra.contador_total ?? 0), isTI ? "produtos" : "counter"),
    ];
    if (!isTI) cards.push(kpi("Suprimentos baixos", s.extra.suprimentos_baixos ?? 0, "produtos"));
    root.append(el("div", { class: "kpi-grid" }, ...cards));

    // Garantias (30/60/90d)
    const maxGar = Math.max(1, ...Object.values(s.garantias));
    const garantiaCard = el("div", { class: "card" },
      el("h3", { style: "margin:0 0 12px" }, "Garantias a vencer"),
      bar("30 dias", s.garantias["30"], maxGar),
      bar("60 dias", s.garantias["60"], maxGar),
      bar("90 dias", s.garantias["90"], maxGar),
    );

    let extraCard;
    if (isTI) {
      const soRows = Object.entries(s.extra.por_so || {});
      const maxSo = Math.max(1, ...soRows.map(([, c]) => c));
      extraCard = el("div", { class: "card" },
        el("h3", { style: "margin:0 0 12px" }, "Distribuição por Sistema Operacional"),
        ...(soRows.length ? soRows.map(([k, c]) => bar(k, c, maxSo)) : [el("p", { class: "muted" }, "Sem dados")]),
      );
    } else {
      extraCard = el("div", { class: "card" },
        el("h3", { style: "margin:0 0 12px" }, "Indicadores de Impressão"),
        bar("Contador total (págs)", s.extra.contador_total ?? 0, Math.max(1, s.extra.contador_total || 1)),
        bar("Suprimentos abaixo do mínimo", s.extra.suprimentos_baixos ?? 0, Math.max(1, s.extra.suprimentos_baixos || 1)),
        el("p", { class: "muted", style: "margin:10px 0 0" }, `Custo por página: R$ ${Number(s.extra.custo_pagina || 0).toFixed(4)}`),
      );
    }

    root.append(el("div", { class: "grid-2" }, garantiaCard, extraCard));
  } catch (e) {
    root.innerHTML = "";
    root.append(el("div", { class: "empty", html: `${icon("relatorios", 72)}<h3>Erro ao carregar</h3><p>${e.message}</p>` }));
    mostrarErro(e);
  }
}
