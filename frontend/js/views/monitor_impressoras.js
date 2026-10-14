/**
 * Monitor de impressoras — cartões com foto, suprimentos e detalhes por SNMP.
 *
 * ## Escopo por unidade
 *
 * O técnico vê **o parque da sua planta**, e não o da empresa toda. Quem
 * decide isso é o backend (`Depends(planta_ativa)`, que já limita a consulta)
 * — a tela apenas mostra o que recebe. Filtrar aqui seria teatro: quem
 * chamasse a API direto veria tudo.
 *
 * O administrador vê todas as unidades, porque é o que `planta_ativa`
 * significa para ele.
 *
 * ## O cartão
 *
 * ```
 * ┌────────┬──────────────────────────────┬──────────┐
 * │        │  Toner preto   ▓▓▓▓▓░░  68%  │          │
 * │  foto  │  Ciano         ▓▓░░░░░  31%  │ Detalhes │
 * │        │  Magenta       ▓░░░░░░  12%  │          │
 * │        │  Coletor       ▓▓▓▓▓▓▓  94%  │          │
 * └────────┴──────────────────────────────┴──────────┘
 * ```
 *
 * ## A atualização de 15 em 15 segundos
 *
 * Só os **suprimentos** são relidos nesse ritmo. Eles são o que muda sozinho —
 * o contador e o cadastro não andam enquanto ninguém imprime.
 *
 * Duas decisões que evitam transformar isso numa sobrecarga:
 *
 * 1. **A aba escondida não consulta.** Sem isto, a tela aberta num
 *    computador esquecido dispararia uma consulta SNMP por impressora a cada
 *    15 segundos, para sempre, sem ninguém olhando.
 * 2. **As consultas se espalham no intervalo.** Disparar o parque inteiro no
 *    mesmo instante cria um pico a cada 15s; escalonar distribui.
 *
 * @module views/monitor_impressoras
 */
import { api } from "../api.js";
import { state } from "../state.js";
import { ctx } from "../context.js";
import { fotoUrl } from "./ativos.js";
import { el, icon, toast, dialog, emptyState, skeleton, fmtDate, mostrarErro } from "../ui.js";

// Intervalo de releitura dos suprimentos. O contador não precisa disso: ele
// só muda quando alguém imprime, e a coleta manual já o atualiza.
const INTERVALO_MS = 15000;

// Guardado no módulo para poder ser cancelado ao sair da tela. Sem isto, cada
// visita ao monitor deixaria um temporizador rodando para sempre — e depois
// de dez visitas seriam dez temporizadores consultando o parque.
let temporizador = null;
let aoTrocarVisibilidade = null;

export async function renderMonitor(root) {
  ctx.setTitle("Monitor de impressoras");
  ctx.setFab(null);
  root.innerHTML = "";

  pararAtualizacao();

  root.append(
    el("div", { class: "row between wrap", style: "gap:10px" },
      el("div", {},
        el("h1", { class: "page-title" }, "Monitor de impressoras"),
        el("p", { class: "muted", style: "margin:4px 0 0" },
          "Contador de páginas e suprimentos lidos direto da impressora, por SNMP. "
          + "Os níveis são relidos a cada 15 segundos.")),
      el("div", { class: "row wrap", style: "gap:8px" },
        el("span", { class: "chip ok", id: "mon-vivo" }, "atualizando"),
        state.canWrite
          ? el("button", { class: "btn filled", id: "mon-coletar",
              onclick: () => coletarTodas(caixa),
              html: icon("download", 18) + " Coletar de todas" })
          : null,
      ),
    ),
  );

  const caixa = el("div", { style: "margin-top:18px" }, skeleton(4));
  root.append(caixa);

  await carregar(caixa);
  ligarAtualizacao(caixa);
}

/** Cancela o temporizador e o observador de visibilidade da tela anterior. */
function pararAtualizacao() {
  if (temporizador) { clearInterval(temporizador); temporizador = null; }
  if (aoTrocarVisibilidade) {
    document.removeEventListener("visibilitychange", aoTrocarVisibilidade);
    aoTrocarVisibilidade = null;
  }
}

function ligarAtualizacao(caixa) {
  const bate = async () => {
    // Aba escondida: não consulta. Ver o comentário no topo do arquivo.
    if (document.hidden) return;
    await relerSuprimentos(caixa);
  };

  temporizador = setInterval(bate, INTERVALO_MS);

  // Ao voltar para a aba, atualiza na hora — esperar até 15s para ver o dado
  // de uma tela que acabou de reaparecer parece travado.
  aoTrocarVisibilidade = () => { if (!document.hidden) bate(); };
  document.addEventListener("visibilitychange", aoTrocarVisibilidade);
}

// ---------------------------------------------------------------------------
// Carga principal
// ---------------------------------------------------------------------------
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
        "Falta a biblioteca pysnmp. Enquanto isso, o contador só pode ser "
        + "informado à mão e os níveis de tonner não são lidos.")));
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
      "Cadastre impressoras no inventário de impressoras para monitorá-las. "
      + "Se elas existem noutra unidade, troque a unidade no topo da tela."));
    return;
  }

  const grade = el("div", { class: "grade-impressoras" },
    ...d.itens.map((p) => cartao(p, caixa)));
  caixa.append(grade);

  // A primeira leitura de suprimentos acontece logo depois de pintar os
  // cartões — assim a tela aparece rápido e os níveis preenchem em seguida.
  relerSuprimentos(caixa);
}

function numero(valor, rotulo, tom = "") {
  return el("div", { class: `numero ${tom}` },
    el("span", { class: "numero-valor" }, String(valor)),
    el("span", { class: "numero-rotulo" }, rotulo));
}

// ---------------------------------------------------------------------------
// O cartão
// ---------------------------------------------------------------------------
function cartao(p, caixa) {
  const foto = p.foto_id
    ? el("img", {
        class: "mon-foto", src: fotoUrl(p.foto_id), loading: "lazy",
        alt: `Impressora ${p.patrimonio || p.ativo_id}`,
      })
    : el("div", { class: "mon-foto mon-foto-vazia", html: icon("print", 32) });

  return el("div", { class: "mon-cartao", "data-ativo": p.ativo_id },
    // --- esquerda: a foto -------------------------------------------------
    el("div", { class: "mon-esquerda" }, foto),

    // --- centro: identificação curta e suprimentos -------------------------
    el("div", { class: "mon-centro" },
      el("div", { class: "mon-titulo" },
        el("b", {}, p.patrimonio || `Ativo #${p.ativo_id}`),
        p.com_snmp
          ? el("span", { class: "chip ok" }, p.endereco)
          : el("span", { class: "chip aviso" }, "sem IP"),
      ),
      el("div", { class: "muted mon-sub" },
        [p.marca, p.modelo].filter(Boolean).join(" ") || "—"),

      el("div", { class: "mon-suprimentos", "data-suprimentos": p.ativo_id },
        p.com_snmp
          ? el("span", { class: "muted mon-carregando" }, "lendo níveis…")
          : el("span", { class: "muted mon-carregando" },
              "Sem IP ou hostname — não há como ler os níveis."),
      ),
    ),

    // --- direita: detalhes -------------------------------------------------
    el("div", { class: "mon-direita" },
      el("button", { class: "btn tonal small", onclick: () => verDetalhes(p),
        html: icon("relatorios", 15) + " Detalhes" }),
      p.com_snmp && state.canWrite
        ? el("button", { class: "btn text small",
            onclick: (ev) => coletarUma(ev, p.ativo_id, caixa) }, "Coletar")
        : null,
    ),
  );
}

/** Coleta um ativo. Extraído do `onclick` — a versão inline embutia um
 *  `async` com `try/catch` dentro de um objeto literal, e o aninhamento
 *  ficava ilegível. */
async function coletarUma(evento, ativoId, caixa) {
  const botao = evento.target;
  botao.disabled = true;
  try {
    const r = await api.post(`/monitor/impressoras/${ativoId}/coletar`, {});
    toast(r.contador_gravado
      ? `Contador: ${Number(r.coletado.contador).toLocaleString("pt-BR")}`
      : r.mensagem);
    await carregar(caixa);
  } catch (e) {
    mostrarErro(e);
    botao.disabled = false;
  }
}

// ---------------------------------------------------------------------------
// Suprimentos dentro do cartão — a parte que se atualiza sozinha
// ---------------------------------------------------------------------------
async function relerSuprimentos(caixa) {
  const alvos = [...caixa.querySelectorAll("[data-suprimentos]")];
  if (!alvos.length) return;

  const chip = document.getElementById("mon-vivo");
  if (chip) chip.textContent = "lendo…";

  // Em paralelo, mas tolerante: uma impressora fora do ar não pode impedir as
  // outras de mostrar o nível — e a que falhou precisa dizer isso no lugar
  // onde o nível apareceria.
  const resultados = await Promise.allSettled(
    alvos.map((a) => api.get(`/monitor/impressoras/${a.dataset.suprimentos}/alertas`))
  );

  resultados.forEach((r, i) => {
    const alvo = alvos[i];
    if (!alvo) return;
    alvo.innerHTML = "";

    if (r.status === "rejected") {
      alvo.append(el("span", { class: "muted mon-carregando text-error" },
        r.reason?.message || "Não respondeu"));
      return;
    }
    const sup = r.value?.suprimentos || [];
    if (!sup.length) {
      alvo.append(el("span", { class: "muted mon-carregando" },
        "A impressora não informou suprimentos (marcas usam OIDs próprios)."));
      return;
    }
    alvo.append(...sup.map((s) => barraSuprimento(s)));
  });

  if (chip) {
    chip.textContent = `atualizado ${new Date().toLocaleTimeString("pt-BR")}`;
  }
}

/**
 * Uma linha de suprimento: nome, barra e porcentagem.
 *
 * A cor da barra vem da **situação** informada pelo backend, não do
 * percentual. Algumas impressoras devolvem 100% quando o cartucho é novo e
 * outras usam a mesma faixa para "desconhecido" — quem decide o que é crítico
 * é a regra do servidor, aplicada uma vez, e não uma conta refeita aqui.
 */
function barraSuprimento(s) {
  const pct = s.percentual;
  const tom = s.situacao === "ok" ? "ok"
    : s.situacao === "atencao" ? "aviso"
    : s.situacao === "critico" ? "erro" : "info";

  return el("div", { class: "mon-sup" },
    el("div", { class: "mon-sup-topo" },
      el("span", { class: "mon-sup-nome", title: s.descricao || "" },
        s.descricao || `Suprimento ${s.indice}`),
      el("span", { class: `mon-sup-pct ${tom}` },
        pct != null ? `${Math.round(pct)}%` : "—")),
    el("div", { class: "progresso mon-sup-barra" },
      pct != null
        ? el("div", { class: `progresso-barra ${tom}`, style: `width:${Math.max(0, Math.min(100, pct))}%` })
        : null),
  );
}

// ---------------------------------------------------------------------------
// Detalhes — os dados do SNMP separados por categoria
// ---------------------------------------------------------------------------
async function verDetalhes(p) {
  const corpo = el("div", {}, el("p", { class: "muted" }, "Consultando a impressora…"));

  dialog({
    title: `${p.patrimonio || p.endereco || `Ativo #${p.ativo_id}`}`,
    wide: true,
    body: corpo,
    actions: [{ label: "Fechar", variant: "text" }],
  });

  let d;
  try {
    d = await api.get(`/monitor/impressoras/${p.ativo_id}/alertas`);
  } catch (e) {
    corpo.innerHTML = "";
    corpo.append(el("p", { class: "text-error" }, e.message));
    return;
  }

  corpo.innerHTML = "";

  // --- 1. Identificação --------------------------------------------------
  corpo.append(secao("Identificação", [
    ["Patrimônio", p.patrimonio || "—"],
    ["Endereço", p.endereco || "não cadastrado"],
    ["Marca / modelo", [p.marca, p.modelo].filter(Boolean).join(" ") || "—"],
    ["Tipo de impressão", p.tipo_impressao || "—"],
  ]));

  // --- 2. Contador -------------------------------------------------------
  const consumo = p.consumo_desde_a_anterior;
  corpo.append(secao("Contador de páginas", [
    ["Cadastro", p.contador_cadastro != null ? inteiro(p.contador_cadastro) : "—"],
    ["Última leitura", p.ultima_leitura != null ? inteiro(p.ultima_leitura) : "nunca lido"],
    ["Lido em", p.ultima_leitura_em ? fmtDate(p.ultima_leitura_em, true) : "—"],
    ["Consumo desde a anterior",
      consumo != null && consumo > 0
        ? `+${inteiro(consumo)}${p.dias_entre_leituras ? ` em ${p.dias_entre_leituras} dia(s)` : ""}`
        : "—"],
    ["Média por dia",
      consumo > 0 && p.dias_entre_leituras
        ? `${inteiro(Math.round(consumo / p.dias_entre_leituras))} páginas`
        : "—"],
  ]));

  // --- 3. Suprimentos ----------------------------------------------------
  const sup = d.suprimentos || [];
  if (sup.length) {
    corpo.append(secao("Suprimentos", sup.map((s) => [
      s.descricao || `Suprimento ${s.indice}`,
      [
        s.percentual != null ? `${Math.round(s.percentual)}%` : "nível não informado",
        s.nivel != null && s.capacidade ? `(${inteiro(s.nivel)} de ${inteiro(s.capacidade)})` : "",
        s.estimativa?.aplicavel
          ? `≈ ${s.estimativa.dias_restantes} dia(s) a ${inteiro(s.estimativa.paginas_por_dia)} págs/dia`
          : "",
      ].filter(Boolean).join(" · "),
    ])));
  } else {
    corpo.append(secao("Suprimentos", [
      ["—", "A impressora não informou. Algumas marcas usam OIDs próprios "
           + "em vez dos padrão; nesse caso os níveis não são lidos por SNMP."],
    ]));
  }

  // --- 4. Alertas --------------------------------------------------------
  const alertas = d.alertas || [];
  if (alertas.length) {
    corpo.append(secao("Alertas", alertas.map((a) => [
      a.descricao || "Alerta",
      `${a.gravidade === "alta" ? "⚠ " : ""}${a.mensagem}`,
    ])));
  }
}

function inteiro(n) {
  return Number(n).toLocaleString("pt-BR");
}

/** Um bloco de detalhes com título e pares rótulo/valor. */
function secao(titulo, linhas) {
  return el("div", { class: "mon-secao" },
    el("h3", { class: "mon-secao-titulo" }, titulo),
    el("div", { class: "mon-secao-corpo" },
      ...linhas.map(([rotulo, valor]) => el("div", { class: "mon-linha" },
        el("span", { class: "mon-rotulo" }, rotulo),
        el("span", { class: "mon-valor" }, String(valor ?? "—"))))));
}

// ---------------------------------------------------------------------------
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
    await carregar(caixa);
  } catch (e) {
    mostrarErro(e);
  } finally {
    if (b) b.disabled = false;
  }
}
