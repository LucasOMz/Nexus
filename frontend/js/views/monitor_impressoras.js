/**
 * Monitor de impressoras — contador, tonner e alertas por SNMP.
 *
 * O OCS enxerga bem computador e mal impressora. Aqui a coleta é direta, pelo
 * protocolo que a impressora já fala — e o contador de páginas deixa de ser
 * digitado à mão.
 *
 * @module views/monitor_impressoras
 */
import { api } from "../api.js";
import { state } from "../state.js";
import { ctx } from "../context.js";
import { el, icon, toast, dialog, emptyState, skeleton, fmtDate, mostrarErro } from "../ui.js";

export async function renderMonitor(root) {
  ctx.setTitle("Monitor de impressoras");
  ctx.setFab(null);
  root.innerHTML = "";

  root.append(
    el("div", { class: "row between wrap", style: "gap:10px" },
      el("div", {},
        el("h1", { class: "page-title" }, "Monitor de impressoras"),
        el("p", { class: "muted", style: "margin:4px 0 0" },
          "Contador de páginas e nível de tonner lidos direto da impressora, por SNMP.")),
      state.canWrite
        ? el("button", { class: "btn filled", id: "mon-coletar",
            onclick: () => coletarTodas(caixa), html: icon("download", 18) + " Coletar de todas" })
        : null,
    ),
  );

  const caixa = el("div", { style: "margin-top:18px" }, skeleton(4));
  root.append(caixa);
  await carregar(caixa);
}

async function carregar(caixa) {
  let d;
  try {
    d = await api.get("/monitor/impressoras");
  } catch (e) {
    caixa.innerHTML = "";
    caixa.append(el("p", { class: "text-error" }, e.message));
    return;
  }

  caixa.innerHTML = "";

  if (!d.snmp_disponivel) {
    caixa.append(el("div", { class: "recado erro", style: "margin-bottom:16px" },
      el("b", {}, "A leitura por SNMP não está disponível neste servidor."),
      el("div", { style: "margin-top:6px" },
        "Falta a biblioteca pysnmp. Enquanto isso, o contador só pode ser informado à mão.")));
  }

  caixa.append(
    el("div", { class: "resumo-numeros", style: "margin-bottom:18px" },
      numero(d.total ?? 0, "Impressoras"),
      numero(d.com_snmp ?? 0, "Com endereço", (d.com_snmp ?? 0) > 0 ? "ok" : ""),
      numero((d.total ?? 0) - (d.com_snmp ?? 0), "Sem IP/hostname",
        (d.total ?? 0) - (d.com_snmp ?? 0) > 0 ? "aviso" : ""),
    ),
  );

  if (!d.itens?.length) {
    caixa.append(emptyState("Nenhuma impressora",
      "Cadastre impressoras no inventário de impressoras para monitorá-las."));
    return;
  }

  caixa.append(el("div", { class: "cartoes" }, ...d.itens.map((p) => cartao(p, caixa))));
}

function numero(valor, rotulo, tom = "") {
  return el("div", { class: `numero ${tom}` },
    el("span", { class: "numero-valor" }, String(valor)),
    el("span", { class: "numero-rotulo" }, rotulo));
}

function cartao(p, caixa) {
  const consumo = p.consumo_desde_a_anterior;
  return el("div", { class: "cartao-contagem" },
    el("div", { class: "row between wrap", style: "gap:10px" },
      el("b", { style: "font-size:15px" }, p.patrimonio || `Ativo #${p.ativo_id}`),
      p.com_snmp
        ? el("span", { class: "chip ok" }, p.endereco)
        : el("span", { class: "chip aviso" }, "sem IP/hostname"),
    ),

    el("div", { class: "muted", style: "font-size:12.5px;margin-top:4px" },
      [p.marca, p.modelo].filter(Boolean).join(" ") || "—"),

    el("div", { class: "muted", style: "font-size:12.5px;margin-top:8px" },
      p.ultima_leitura != null
        ? `Contador: ${Number(p.ultima_leitura).toLocaleString("pt-BR")}`
          + (p.ultima_leitura_em ? ` · lido em ${fmtDate(p.ultima_leitura_em, true)}` : "")
        : "Nenhuma leitura de contador registrada"),

    consumo != null && consumo > 0
      ? el("div", { class: "muted", style: "font-size:12px;margin-top:2px" },
          `+${Number(consumo).toLocaleString("pt-BR")} páginas`
          + (p.dias_entre_leituras ? ` em ${p.dias_entre_leituras} dia(s)` : ""))
      : null,

    el("div", { class: "row wrap", style: "gap:8px;margin-top:12px" },
      p.com_snmp && state.canWrite
        ? el("button", { class: "btn tonal", onclick: async (ev) => {
            ev.target.disabled = true;
            try {
              const r = await api.post(`/monitor/impressoras/${p.ativo_id}/coletar`, {});
              toast(r.contador_gravado
                ? `Contador: ${Number(r.coletado.contador).toLocaleString("pt-BR")}`
                : r.mensagem);
              carregar(caixa);
            } catch (e) { mostrarErro(e); ev.target.disabled = false; }
          }, html: icon("download", 16) + " Coletar agora" })
        : null,

      p.com_snmp
        ? el("button", { class: "btn tonal", onclick: () => verSuprimentos(p),
            html: icon("relatorios", 16) + " Tonner" })
        : null,
    ),
  );
}

async function coletarTodas(caixa) {
  const b = document.getElementById("mon-coletar");
  if (b) b.disabled = true;
  toast("Consultando as impressoras…");
  try {
    const r = await api.post("/monitor/impressoras/coletar-todas", {});
    const partes = [`${r.atualizadas} atualizada(s)`];
    if (r.falharam?.length) partes.push(`${r.falharam.length} não responderam`);
    if (r.sem_endereco) partes.push(`${r.sem_endereco} sem endereço`);
    if (r.sem_contador) partes.push(`${r.sem_contador} sem contador`);
    toast(partes.join(" · "));
    carregar(caixa);
  } catch (e) {
    mostrarErro(e);
  } finally {
    if (b) b.disabled = false;
  }
}

async function verSuprimentos(p) {
  const caixa = el("div", {}, el("p", { class: "muted" }, "Consultando a impressora…"));
  dialog({
    title: `Tonner — ${p.patrimonio || p.endereco}`,
    wide: true,
    body: caixa,
    actions: [{ label: "Fechar", variant: "text" }],
  });

  let d;
  try {
    d = await api.get(`/monitor/impressoras/${p.ativo_id}/alertas`);
  } catch (e) {
    caixa.innerHTML = "";
    caixa.append(el("p", { class: "text-error" }, e.message));
    return;
  }

  caixa.innerHTML = "";
  const sup = d.suprimentos || [];
  if (!sup.length) {
    caixa.append(el("p", { class: "muted" },
      "A impressora não informou nenhum suprimento. Algumas marcas usam OIDs próprios "
      + "em vez dos padrão."));
    return;
  }

  for (const a of d.alertas || []) {
    caixa.append(el("div", { class: `recado ${a.gravidade === "alta" ? "erro" : "info"}`,
      style: "margin-bottom:8px" },
      el("b", {}, a.descricao), " — ", a.mensagem));
  }

  caixa.append(el("div", { class: "cartoes", style: "margin-top:12px" },
    ...sup.map((s) => {
      const pct = s.percentual;
      return el("div", { class: "cartao-contagem" },
        el("div", { class: "row between wrap", style: "gap:10px" },
          el("b", {}, s.descricao || `Suprimento ${s.indice}`),
          el("span", { class: `chip ${s.situacao === "ok" ? "ok" : s.situacao === "atencao" ? "aviso" : "info"}` },
            pct != null ? `${pct}%` : s.situacao)),
        pct != null
          ? el("div", { class: "progresso" },
              el("div", { class: "progresso-barra", style: `width:${pct}%` }))
          : el("div", { class: "muted", style: "font-size:12.5px;margin-top:8px" },
              "Nível não informado pela impressora"),
        s.estimativa?.aplicavel
          ? el("div", { class: "muted", style: "font-size:12.5px;margin-top:6px" },
              `≈ ${s.estimativa.dias_restantes} dia(s) — ` +
              `${Number(s.estimativa.paginas_por_dia).toLocaleString("pt-BR")} páginas/dia`)
          : null,
      );
    })));
}
