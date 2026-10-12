/**
 * Inventário de software e licenças.
 *
 * ## Quatro áreas, e a ordem não é arbitrária
 *
 * A tela **abre por Conformidade**, e não pela lista de licenças. Quem entra
 * aqui quer saber se a empresa está em risco numa auditoria — não quantos
 * títulos existem. Abrir pela lista enterraria o problema na quinta página.
 *
 * ## A chave da licença é tratada como senha
 *
 * A listagem mostra `••••-••••-••••-4F2A`. O valor só sai pelo botão
 * **Revelar**, que exige permissão própria e **fica registrado na auditoria**
 * a cada clique — quem leu a chave é uma pergunta que precisa ter resposta.
 *
 * @module views/software
 */
import { api } from "../api.js";
import { state } from "../state.js";
import { ctx } from "../context.js";
import { el, icon, toast, dialog, skeleton, mostrarErro } from "../ui.js";

const ABAS = [
  ["conformidade", "Conformidade", "shield"],
  ["software", "Softwares", "produtos"],
  ["licencas", "Licenças", "auth"],
  ["atribuicoes", "Atribuições", "user"],
];

// Estado do módulo. Mantido entre trocas de aba para não recarregar tudo.
const estado = { aba: "conformidade", softwareId: null };

const SITUACAO = {
  excedente: { rotulo: "Excedente", tom: "danger", dica: "Instalado acima do licenciado — risco em auditoria" },
  sem_licenca: { rotulo: "Sem licença", tom: "danger", dica: "Instalado e nenhuma licença cadastrada" },
  ocioso: { rotulo: "Ocioso", tom: "aviso", dica: "Licença comprada sem uso — dinheiro parado" },
  conforme: { rotulo: "Conforme", tom: "ok", dica: "Instalado dentro do licenciado" },
  nao_instalado: { rotulo: "Não instalado", tom: "", dica: "Cadastrado, sem uso e sem licença" },
};

const dinheiro = (v) => Number(v || 0).toLocaleString("pt-BR", {
  style: "currency", currency: "BRL", maximumFractionDigits: 0,
});

const reais = (v) => Number(v || 0).toLocaleString("pt-BR", {
  style: "currency", currency: "BRL", minimumFractionDigits: 2,
});

export async function renderSoftware(root) {
  ctx.setTitle("Software e licenças");
  ctx.setFab(null);
  root.innerHTML = "";

  const conteudo = el("div", {}, skeleton(5));
  root.append(
    el("h1", { class: "page-title" }, "Software e licenças"),
    el("p", { class: "muted", style: "margin:0 0 16px" },
      "Controle de licenças e conformidade: o que foi comprado contra o que "
      + "está instalado."),
    barraAbas(root),
    conteudo,
  );

  await abrir(estado.aba, conteudo);
}

function barraAbas(root) {
  const barra = el("div", { class: "tabs" });
  for (const [chave, rotulo, icone] of ABAS) {
    barra.append(el("button", {
      // Reusa o padrão de abas que já existe (`.tabs button.active`) em vez
      // de inventar `.aba`, que não teria CSS nenhum.
      class: estado.aba === chave ? "active" : "",
      type: "button",
      onclick: async () => {
        estado.aba = chave;
        for (const b of barra.children) b.classList.remove("active");
        const indice = ABAS.findIndex((a) => a[0] === chave);
        barra.children[indice].classList.add("active");
        await abrir(chave, root.querySelector(".conteudo-software"));
      },
      html: `${icon(icone, 16)} <span>${rotulo}</span>`,
    }));
  }
  return barra;
}

async function abrir(aba, conteudo) {
  if (!conteudo) return;
  conteudo.className = "conteudo-software";
  conteudo.innerHTML = "";
  conteudo.append(skeleton(4));

  const telas = {
    conformidade: abaConformidade,
    software: abaSoftware,
    licencas: abaLicencas,
    atribuicoes: abaAtribuicoes,
  };
  try {
    await telas[aba](conteudo);
  } catch (e) {
    conteudo.innerHTML = "";
    conteudo.append(el("div", { class: "card" },
      el("p", { class: "text-error", style: "margin:0 0 12px" }, e.message),
      el("button", {
        class: "btn tonal small", type: "button",
        onclick: () => abrir(aba, conteudo),
      }, "Tentar novamente")));
  }
}

// ---------------------------------------------------------------------------
// Conformidade — a área de abertura
// ---------------------------------------------------------------------------
async function abaConformidade(caixa) {
  const d = await api.get("/conformidade");
  caixa.innerHTML = "";

  const kpi = (valor, rotulo, tom = "") => el("div", { class: `numero ${tom}` },
    el("span", { class: "numero-valor" }, String(valor)),
    el("span", { class: "numero-rotulo" }, rotulo));

  caixa.append(
    el("div", { class: "card" },
      el("div", { class: "resumo-numeros" },
        kpi(d.titulos, "Títulos"),
        // Os dois em vermelho porque são risco. O ocioso em âmbar porque é
        // dinheiro parado — não é risco, e misturar os dois faria a pessoa
        // tratar tudo como urgente.
        kpi(d.excedente, "Excedente", d.excedente ? "erro" : ""),
        kpi(d.ocioso, "Ocioso", d.ocioso ? "aviso" : ""),
        kpi(d.sem_licenca, "Sem licença", d.sem_licenca ? "erro" : ""),
        kpi(dinheiro(d.custo_mensal), "Custo mensal")),
      d.excedente || d.sem_licenca
        ? el("p", { class: "recado erro", style: "margin:14px 0 0" },
            `${d.excedente + d.sem_licenca} software(s) precisam de atenção. `
            + "Excedente é risco em auditoria; sem licença é uso irregular.")
        : el("p", { class: "recado ok", style: "margin:14px 0 0" },
            "Nenhum software instalado acima do licenciado."),
    ),
  );

  if (!d.linhas?.length) {
    caixa.append(el("div", { class: "card", style: "margin-top:14px" },
      el("p", { class: "muted", style: "margin:0" },
        "Nada a comparar ainda. Cadastre um software e rode a coleta do OCS "
        + "em Administração → OCS Inventory.")));
    return;
  }

  const linhas = d.linhas.map((x) => {
    const s = SITUACAO[x.situacao] || SITUACAO.conforme;
    return el("tr", {},
      el("td", { class: "col-nome" },
        x.software,
        x.fabricante ? el("div", { class: "muted", style: "font-size:11.5px" }, x.fabricante) : null),
      el("td", { class: "num" }, String(x.licenciado)),
      el("td", { class: "num" }, String(x.instalado)),
      // A diferença com sinal: `+13` e `-19` dizem direções opostas — e a
      // ação é diferente em cada uma.
      el("td", { class: "num" }, x.diferenca > 0 ? `+${x.diferenca}` : String(x.diferenca)),
      el("td", {}, el("span", { class: `chip ${s.tom}`, title: s.dica }, s.rotulo)),
    );
  });

  caixa.append(el("div", { class: "card", style: "margin-top:14px" },
    el("h3", { style: "margin:0 0 4px" }, "Instalado × licenciado"),
    el("p", { class: "chart-sub" },
      "Ordenado pelo que preocupa primeiro. Clique numa linha para ver de qual "
      + "software se trata."),
    el("div", { class: "table-wrap" },
      el("table", { class: "tabela-numeros" },
        el("thead", {}, el("tr", {},
          el("th", {}, "Software"),
          el("th", { class: "num" }, "Licenciado"),
          el("th", { class: "num" }, "Instalado"),
          el("th", { class: "num" }, "Diferença"),
          el("th", {}, "Situação"))),
        el("tbody", {}, ...linhas))),
    el("p", { class: "muted", style: "font-size:12px;margin:12px 0 0" },
      "O \"instalado\" vem do OCS Inventory. Se a taxa de reconhecimento "
      + "estiver baixa, ajuste os padrões do software antes de concluir que "
      + "há uso irregular."),
  ));
}

// ---------------------------------------------------------------------------
// Software
// ---------------------------------------------------------------------------
async function abaSoftware(caixa) {
  const lista = await api.get("/softwares");
  caixa.innerHTML = "";

  caixa.append(el("div", { class: "row between wrap", style: "gap:10px;align-items:center" },
    el("p", { class: "muted", style: "margin:0" }, `${lista.length} software(s) cadastrado(s).`),
    el("button", { class: "btn filled small", type: "button", onclick: () => formSoftware(caixa) },
      "Novo software")));

  if (!lista.length) {
    caixa.append(vazio("Nenhum software cadastrado",
      "Cadastre o software e os padrões de reconhecimento — é por eles que o "
      + "OCS vai casar o que está instalado."));
    return;
  }

  caixa.append(el("div", { class: "card", style: "margin-top:14px" },
    el("div", { class: "table-wrap" },
      el("table", { class: "tabela-numeros" },
        el("thead", {}, el("tr", {},
          el("th", {}, "Nome"), el("th", {}, "Fabricante"),
          el("th", {}, "Plataforma"), el("th", {}, "Padrões"))),
        el("tbody", {}, ...lista.map((s) => el("tr", {},
          el("td", { class: "col-nome" }, s.nome),
          el("td", {}, s.fabricante || "—"),
          el("td", {}, s.plataforma || "—"),
          // Sem padrão, o software nunca casa com o OCS — e apareceria como
          // "sem licença" para sempre. O aviso é aqui, não no relatório.
          el("td", {}, s.padroes
            ? el("code", { style: "font-size:11.5px" }, s.padroes)
            : el("span", { class: "chip erro" }, "sem padrão")),
        )))))));
}

function formSoftware(caixa) {
  const campos = {};
  const campo = (chave, rotulo, dica, tipo = "text") => {
    const entrada = el("input", { type: tipo });
    entrada.addEventListener("input", () => { campos[chave] = entrada.value; });
    return el("div", { class: "field" },
      el("label", {}, rotulo), entrada,
      dica ? el("span", { class: "dica" }, dica) : null);
  };

  dialog({
    title: "Novo software",
    body: el("div", {},
      campo("nome", "Nome *", "Como você quer chamá-lo: Office 2021."),
      campo("fabricante", "Fabricante", null),
      campo("padroes", "Padrões de reconhecimento",
        "Separados por ponto e vírgula. Use * para curinga. "
        + "Ex.: microsoft office*2021; office ltsc*"),
      el("p", { class: "recado info", style: "margin:10px 0 0" },
        "Os padrões são o que faz o cruzamento com o OCS funcionar. Sem eles, "
        + "o software aparece como \"sem licença\" mesmo estando instalado.")),
    actions: [
      { label: "Cancelar", variant: "text" },
      {
        label: "Salvar", variant: "filled",
        onClick: async () => {
          if (!campos.nome) { toast("Informe o nome"); return false; }
          try {
            await api.post("/softwares", campos);
            toast("Software cadastrado");
            await abrir("software", caixa);
          } catch (e) { mostrarErro(e); return false; }
        },
      },
    ],
  });
}

// ---------------------------------------------------------------------------
// Licenças
// ---------------------------------------------------------------------------
async function abaLicencas(caixa) {
  const [lista, softwares] = await Promise.all([
    api.get("/licencas"),
    api.get("/softwares").catch(() => []),
  ]);
  const nome = Object.fromEntries((softwares || []).map((s) => [s.id, s.nome]));
  caixa.innerHTML = "";

  caixa.append(el("div", { class: "row between wrap", style: "gap:10px;align-items:center" },
    el("p", { class: "muted", style: "margin:0" },
      `${lista.length} licença(s). A chave aparece mascarada; revelar exige `
      + "permissão e fica registrado."),
    el("button", { class: "btn filled small", type: "button", onclick: () => formLicenca(caixa, softwares) },
      "Nova licença")));

  if (!lista.length) {
    caixa.append(vazio("Nenhuma licença cadastrada", "Cadastre as licenças compradas."));
    return;
  }

  caixa.append(el("div", { class: "card", style: "margin-top:14px" },
    el("div", { class: "table-wrap" },
      el("table", { class: "tabela-numeros" },
        el("thead", {}, el("tr", {},
          el("th", {}, "Software"), el("th", {}, "Tipo"),
          el("th", { class: "num" }, "Seats"), el("th", { class: "num" }, "Em uso"),
          el("th", {}, "Chave"), el("th", {}, "Validade"))),
        el("tbody", {}, ...lista.map((l) => el("tr", {},
          el("td", { class: "col-nome" }, nome[l.software_id] || `#${l.software_id}`),
          el("td", {}, l.tipo),
          el("td", { class: "num" }, String(l.seats)),
          el("td", { class: "num" }, String(l.seats_usados)),
          el("td", {}, botaoChave(l)),
          el("td", {}, validade(l)),
        )))))));
}

function botaoChave(l) {
  if (!l.tem_chave) return el("span", { class: "muted" }, "—");

  const mascara = el("code", { style: "font-size:11.5px" }, l.chave_mascarada);

  // Sem a permissão, mostra a máscara e uma explicação — nunca um botão que
  // só falha depois do clique.
  if (!state.podeExtra("licencas.ver_chave")) {
    return el("span", { class: "row", style: "gap:6px;align-items:center" },
      mascara,
      el("span", {
        class: "muted", style: "font-size:11.5px",
        title: "Peça a permissão licencas.ver_chave em Administração → Usuários",
      }, "sem permissão"));
  }

  return el("span", { class: "row", style: "gap:6px;align-items:center" },
    mascara,
    el("button", {
      class: "btn text small", type: "button", title: "A consulta fica na auditoria",
      onclick: async (ev) => {
        const b = ev.currentTarget;
        b.disabled = true;
        try {
          const r = await api.get(`/licencas/${l.id}/revelar`);
          dialog({
            title: "Chave da licença",
            body: el("div", {},
              el("p", { class: "recado aviso", style: "margin:0 0 12px" }, r.aviso),
              el("code", { style: "display:block;padding:14px;font-size:15px;word-break:break-all;"
                + "background:var(--md-sys-color-surface-container-high);border-radius:8px" },
                r.chave)),
            actions: [{ label: "Fechar", variant: "text" }],
          });
        } catch (e) { mostrarErro(e); } finally { b.disabled = false; }
      },
    }, "Revelar"));
}

function validade(l) {
  if (!l.validade) return el("span", { class: "muted" }, "não vence");
  const dias = l.dias_para_vencer;
  const tom = l.vencida ? "erro" : (dias !== null && dias <= 60 ? "aviso" : "");
  const texto = l.vencida ? "vencida" : (dias !== null && dias <= 60 ? `${dias} dias` : l.validade);
  return el("span", { class: `chip ${tom}` }, texto);
}

function formLicenca(caixa, softwares) {
  if (!softwares?.length) {
    toast("Cadastre um software primeiro");
    return;
  }
  const campos = { tipo: "perpetua" };
  const selSoftware = el("select", {},
    ...softwares.map((s) => el("option", { value: s.id }, s.nome)));
  selSoftware.addEventListener("change", () => { campos.software_id = Number(selSoftware.value); });
  campos.software_id = softwares[0].id;

  const selTipo = el("select", {},
    el("option", { value: "perpetua" }, "Perpétua"),
    el("option", { value: "assinatura" }, "Assinatura"),
    el("option", { value: "volume" }, "Volume"),
    el("option", { value: "oem" }, "OEM"),
    el("option", { value: "open_source" }, "Open source"),
    el("option", { value: "trial" }, "Trial"));
  selTipo.addEventListener("change", () => { campos.tipo = selTipo.value; });

  const entrada = (chave, rotulo, tipo = "text", dica = null) => {
    const i = el("input", { type: tipo });
    i.addEventListener("input", () => { campos[chave] = i.value; });
    return el("div", { class: "field" }, el("label", {}, rotulo), i,
      dica ? el("span", { class: "dica" }, dica) : null);
  };

  dialog({
    title: "Nova licença",
    body: el("div", {},
      el("div", { class: "field" }, el("label", {}, "Software *"), selSoftware),
      el("div", { class: "field" }, el("label", {}, "Tipo *"), selTipo),
      entrada("seats", "Seats *", "number"),
      entrada("chave", "Chave", "text",
        "Cifrada ao salvar. Não é devolvida em nenhuma listagem."),
      entrada("validade", "Validade", "date", "Deixe vazio em perpétua."),
      entrada("valor_mensal", "Valor mensal", "text", "Obrigatório em assinatura.")),
    actions: [
      { label: "Cancelar", variant: "text" },
      {
        label: "Salvar", variant: "filled",
        onClick: async () => {
          if (!campos.seats) { toast("Informe os seats"); return false; }
          try {
            await api.post("/licencas", campos);
            toast("Licença cadastrada");
            await abrir("licencas", caixa);
          } catch (e) { mostrarErro(e); return false; }
        },
      },
    ],
  });
}

// ---------------------------------------------------------------------------
// Atribuições
// ---------------------------------------------------------------------------
async function abaAtribuicoes(caixa) {
  const lista = await api.get("/licencas");
  caixa.innerHTML = "";

  const comUso = lista.filter((l) => l.seats_usados > 0);
  if (!comUso.length) {
    caixa.append(vazio("Nenhuma atribuição",
      "As atribuições ligam uma licença a uma máquina ou a uma pessoa. "
      + "São elas que mostram quais seats estão em uso."));
    return;
  }

  caixa.append(el("p", { class: "muted", style: "margin:0 0 14px" },
    "Cada licença mostra quantos seats estão atribuídos. Libere um seat para "
    + "reaproveitá-lo noutra máquina."));

  for (const l of comUso) {
    caixa.append(el("div", { class: "card", style: "margin-bottom:12px" },
      el("div", { class: "row between wrap", style: "gap:8px;align-items:center" },
        el("b", {}, `Licença #${l.id} — ${l.tipo}`),
        el("span", { class: `chip ${l.seats_livres ? "ok" : "erro"}` },
          `${l.seats_usados}/${l.seats} em uso`)),
      el("p", { class: "muted", style: "font-size:12.5px;margin:6px 0 0" },
        l.seats_livres
          ? `${l.seats_livres} seat(s) livre(s).`
          : "Todos os seats em uso. Atribuir outro é risco em auditoria.")));
  }
}

// ---------------------------------------------------------------------------
function vazio(titulo, texto) {
  return el("div", { class: "card", style: "margin-top:14px;text-align:center;padding:32px" },
    el("b", { style: "display:block;margin-bottom:6px" }, titulo),
    el("p", { class: "muted", style: "margin:0" }, texto));
}
