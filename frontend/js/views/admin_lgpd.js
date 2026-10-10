/**
 * Administração → Privacidade → Retenção e expurgo (LGPD).
 *
 * ## Por que esta tela existe
 *
 * A política de retenção tem **peso legal**: diz por quanto tempo cada dado
 * pessoal é guardado e com que fundamento. Quem responde por isso precisa
 * **ver** a política e o que está vencido — não descobrir por URL.
 *
 * A tela separa três coisas que costumam ser confundidas:
 *
 * 1. **A política** — os prazos e o motivo de cada um
 * 2. **O que venceu** — o que passou do prazo, contado
 * 3. **O expurgo** — a execução, que não tem volta
 *
 * @module views/admin_lgpd
 */
import { api } from "../api.js";
import { el, icon, toast, dialog, mostrarErro, emptyState } from "../ui.js";

const ACAO_ROTULO = {
  apagar: "Apagar",
  anonimizar: "Anonimizar",
  manter: "Manter",
  vincular_ao_ativo: "Vincular ao ativo",
};

const ACAO_EXPLICA = {
  apagar: "O registro deixa de existir.",
  // A distinção que mais importa explicar: anonimizar preserva o fato e
  // remove a pessoa — é o que concilia LGPD com auditoria.
  anonimizar: "O fato permanece; o vínculo com a pessoa sai.",
  manter: "Prazo de guarda MINIMA — passado ele, o dado continua.",
  vincular_ao_ativo: "Vive enquanto o ativo existir.",
};

export async function renderLgpd(root) {
  root.innerHTML = "";
  const alvo = el("div", {}, el("p", { class: "muted" }, "Carregando…"));
  root.append(alvo);

  let d;
  try {
    d = await api.get("/admin/lgpd/retencao");
  } catch (e) {
    alvo.innerHTML = "";
    alvo.append(el("p", { class: "text-error" }, e.message));
    return;
  }

  alvo.innerHTML = "";
  alvo.append(cabecalho(d), tabela(d), notas(d));
}

function cabecalho(d) {
  const vencidos = d.total_vencido ?? 0;
  return el("div", { class: "card" },
    el("div", { class: "section-title", style: "margin:0" }, "Retenção e expurgo de dados"),
    el("p", { class: "muted", style: "font-size:13px;margin:6px 0 0" },
      "Quanto tempo cada tipo de registro é guardado, e por quê. Os prazos "
      + "têm fundamento legal — por isso ficam no código, e não num campo "
      + "editável."),

    vencidos
      ? el("div", { class: "recado aviso", style: "margin-top:14px" },
          el("b", {}, `${vencidos} registro(s) passaram do prazo.`),
          ` ${d.a_apagar} seriam apagados e ${d.a_anonimizar} anonimizados.`)
      : el("div", { class: "recado ok", style: "margin-top:14px" },
          "Nada passou do prazo de retenção."),

    vencidos
      ? el("div", { class: "row", style: "margin-top:14px" },
          el("button", { class: "btn filled", type: "button",
            onclick: () => confirmarExpurgo(d) }, "Executar expurgo"))
      : null,
  );
}

function tabela(d) {
  const linhas = (d.itens || []).map((i) => el("tr", {},
    el("td", { style: "font-weight:600" }, i.tipo),
    el("td", {}, i.dias ? `${i.dias} dias` : "sem prazo"),
    el("td", {}, el("span", {
      class: `chip ${i.acao === "apagar" ? "erro" : i.acao === "anonimizar" ? "aviso" : ""}`,
      title: ACAO_EXPLICA[i.acao] || "",
    }, ACAO_ROTULO[i.acao] || i.acao)),
    el("td", {}, String(i.total)),
    el("td", {}, i.vencidos
      ? el("span", { class: "chip erro" }, String(i.vencidos))
      : el("span", { class: "muted" }, "—")),
    el("td", { class: "muted", style: "font-size:12.5px" }, i.motivo || ""),
  ));

  // O que a política prevê mas o sistema ainda não tem tabela. Aparecer com
  // zero sugeriria "nada vencido", quando o certo é "não se aplica".
  for (const tipo of d.sem_tabela || []) {
    linhas.push(el("tr", { class: "muted" },
      el("td", {}, tipo),
      el("td", {}, "—"),
      el("td", {}, el("span", { class: "chip" }, "não se aplica")),
      el("td", {}, "—"),
      el("td", {}, "—"),
      el("td", { style: "font-size:12.5px" }, "A política prevê; o sistema ainda não tem este registro."),
    ));
  }

  return el("div", { class: "card", style: "margin-top:14px" },
    el("div", { class: "table-wrap" },
      el("table", {},
        el("thead", {}, el("tr", {},
          el("th", {}, "Registro"), el("th", {}, "Prazo"), el("th", {}, "Ação"),
          el("th", {}, "Total"), el("th", {}, "Vencidos"), el("th", {}, "Fundamento"))),
        el("tbody", {}, ...linhas))),
  );
}

function notas(d) {
  return el("div", { class: "card", style: "margin-top:14px" },
    el("p", { class: "dica", style: "margin:0 0 8px" }, "O que cada ação significa"),
    el("div", { class: "muted", style: "font-size:13px;line-height:1.8" },
      el("div", {}, el("b", {}, "Apagar"), " — ", ACAO_EXPLICA.apagar),
      el("div", {}, el("b", {}, "Anonimizar"), " — ", ACAO_EXPLICA.anonimizar),
      el("div", {}, el("b", {}, "Manter"), " — ", ACAO_EXPLICA.manter),
      el("div", {}, el("b", {}, "Vincular ao ativo"), " — ", ACAO_EXPLICA.vincular_ao_ativo),
    ),
    d.a_anonimizar
      ? el("div", { class: "recado info", style: "margin-top:12px" },
          "A auditoria é anonimizada, e não apagada: a linha que registra quem "
          + "excluiu um ativo é prova. Apagá-la destruiria a prova; mantê-la "
          + "identificando a pessoa violaria a lei. O que sai é o vínculo.")
      : null,
  );
}

/**
 * Confirmação do expurgo.
 *
 * Duas travas, de propósito: o expurgo **não tem volta**, e a pessoa precisa
 * dizer QUANTOS registros vai tratar para ter noção do alcance.
 */
function confirmarExpurgo(d) {
  const limite = el("input", { type: "number", min: "1", max: "50000", value: "5000" });
  dialog({
    title: "Executar expurgo",
    body: el("div", {},
      el("div", { class: "recado erro" },
        el("b", {}, "Esta operação não tem volta."),
        " Os registros que passaram do prazo serão apagados ou anonimizados."),
      el("div", { class: "grade", style: "margin-top:14px" },
        el("div", {}, el("div", { class: "dica" }, "A apagar"),
          el("b", {}, String(d.a_apagar))),
        el("div", {}, el("div", { class: "dica" }, "A anonimizar"),
          el("b", {}, String(d.a_anonimizar))),
      ),
      el("div", { class: "field", style: "margin-top:14px" },
        el("label", {}, "Máximo por execução"),
        limite,
        el("span", { class: "dica" },
          "O expurgo roda em transação: um lote grande demais trava o banco. "
          + "Se ficar registro, rode de novo.")),
    ),
    actions: [
      { label: "Cancelar", variant: "text" },
      { label: "Executar", variant: "filled", onClick: async (close) => {
        try {
          const r = await api.post(
            `/admin/lgpd/expurgar?confirmo=true&limite=${Number(limite.value) || 5000}`, {});
          close();
          toast(r.mensagem || "Expurgo concluído");
          const view = document.getElementById("view");
          if (view) renderLgpd(view);
        } catch (e) { mostrarErro(e); }
      } },
    ],
  });
}
