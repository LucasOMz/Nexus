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
import { fotoProtegida } from "../fotos.js";
import { state } from "../state.js";
import { ctx } from "../context.js";
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
  ctx.limpar = pararAtualizacao;

  root.append(
    el("div", { class: "row between wrap monitor-topo", style: "gap:10px" },
      el("div", { class: "nexus-pagina-titulo" },
        el("span", { class: "nexus-pagina-icone", html: icon("printerMonitor", 26) }),
        el("div", {}, el("h1", { class: "page-title" }, "Monitor de impressoras"),
          el("p", { class: "page-sub" }, "Acompanhe os contadores e níveis de suprimentos por SNMP."))),
      el("div", { class: "row wrap", style: "gap:8px" },
        el("span", { class: "chip ok", id: "mon-vivo" }, "atualizando"),
        el("button", { class: "btn outline", type: "button", onclick: () => relerSuprimentos(caixa),
          html: icon("refresh", 18) + " Atualizar leituras" }),
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
  if (caixa.isConnected) ligarAtualizacao(caixa);
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

  const numeroAlertas = numero("—", "Com alertas", "reporte", "aviso");
  const numeroOnline = numero("—", "Online por SNMP", "check", "ok");
  caixa.append(
    el("div", { class: "monitor-indicadores" }, numero(d.total ?? 0, "Impressoras", "printerMonitor"), numeroOnline, numeroAlertas),
    el("p", { class: "muted monitor-cobertura" },
      `${d.com_snmp ?? 0} com endereço · ${(d.total ?? 0) - (d.com_snmp ?? 0)} sem IP ou hostname`),
  );

  if (!d.itens?.length) {
    caixa.append(emptyState("print", "Nenhuma impressora",
      "Cadastre impressoras no inventário de impressoras para monitorá-las. "
      + "Se elas existem noutra unidade, troque a unidade no topo da tela."));
    return;
  }

  const lista = el("div", { class: "card monitor-lista" },
    el("h2", { class: "section-title" }, "Impressoras"));
  const painel = el("div", { class: "monitor-ficha" });
  const busca = el("input", { class: "search-input", type: "search", placeholder: "Patrimônio, modelo, endereço ou departamento" });
  const filtro = el("select", { class: "search-input" },
    ...[["", "Todos os estados"], ["alerta", "Com alertas"], ["lida", "Com leitura"], ["sem-leitura", "Sem leitura"], ["sem-endereco", "Sem IP ou hostname"]]
      .map(([value, rotulo]) => el("option", { value }, rotulo)));
  const vazio = el("p", { class: "muted", hidden: true, role: "status" }, "Nenhuma impressora corresponde aos filtros.");
  lista.append(el("div", { class: "monitor-filtros" }, el("label", {}, "Buscar", busca), el("label", {}, "Estado da leitura", filtro)));
  lista.append(el("div", { class: "monitor-lista-colunas", "aria-hidden": "true" },
    el("span", {}, ""), el("span", {}, "Patrimônio"), el("span", {}, "Modelo"), el("span", {}, "Departamento"), el("span", {}, "Estado")));
  const registros = d.itens.map(p => {
    const id = String(p.ativo_id);
    const estado = el("small", { class: "monitor-estado", "data-monitor-estado": id, "data-estado": p.com_snmp ? "pendente" : "sem-endereco" },
      p.com_snmp ? "Aguardando leitura" : "Sem IP/hostname");
    const botao = el("button", { type: "button", class: "monitor-item", onclick: () => selecionar(id) },
      el("span", { class: "monitor-item-icone", html: icon("printerMonitor", 21) }),
      el("strong", {}, p.patrimonio || `Ativo #${id}`),
      el("span", { class: "monitor-item-modelo" }, [p.marca, p.modelo].filter(Boolean).join(" ") || "Sem modelo"),
      el("span", { class: "monitor-item-departamento" }, p.departamento || "—"),
      estado);
    const ficha = cartao(p, caixa);
    lista.append(botao);
    painel.append(ficha);
    const termos = normalizarBusca([p.patrimonio, p.marca, p.modelo, p.endereco, p.departamento].filter(Boolean).join(" "));
    return { id, botao, ficha, estado, termos };
  });
  lista.append(vazio);

  function selecionar(id) {
    if (id) caixa.dataset.impressora = id;
    for (const registro of registros) {
      const atual = registro.id === id;
      registro.botao.setAttribute("aria-pressed", String(atual));
      registro.ficha.hidden = !atual;
    }
  }

  function filtrar() {
    const consulta = normalizarBusca(busca.value);
    for (const r of registros) {
      r.botao.hidden = !r.termos.includes(consulta) || (Boolean(filtro.value) && r.estado.dataset.estado !== filtro.value);
    }
    const visiveis = registros.filter(r => !r.botao.hidden);
    vazio.hidden = visiveis.length > 0;
    selecionar((visiveis.find(r => r.id === caixa.dataset.impressora) || visiveis[0])?.id);
  }

  const layout = el("div", { class: "monitor-layout" }, lista, painel);
  layout.addEventListener("leiturasatualizadas", () => {
    const alertas = registros.filter(r => r.estado.dataset.estado === "alerta").length;
    const leiturasValidas = registros.some(r => ["lida", "alerta"].includes(r.estado.dataset.estado));
    const online = registros.filter(r => r.estado.dataset.online === "true").length;
    const houveVerificacao = registros.some(r => r.estado.dataset.online !== undefined);
    numeroAlertas.querySelector(".numero-valor").textContent = leiturasValidas ? String(alertas) : "—";
    numeroOnline.querySelector(".numero-valor").textContent = houveVerificacao ? String(online) : "—";
    if (filtro.value) filtrar();
  });
  busca.addEventListener("input", filtrar);
  filtro.addEventListener("change", filtrar);
  filtrar();
  caixa.append(layout);

  // A primeira leitura de suprimentos acontece logo depois de pintar os
  // cartões — assim a tela aparece rápido e os níveis preenchem em seguida.
  relerSuprimentos(caixa);
}

function normalizarBusca(valor) {
  return valor.normalize("NFD").replace(/\p{Diacritic}/gu, "").toLowerCase().trim();
}

function numero(valor, rotulo, icone, tom = "") {
  return el("div", { class: `card monitor-indicador ${tom}` },
    el("span", { class: "monitor-indicador-icone", html: icon(icone, 25) }),
    el("div", {}, el("span", {}, rotulo), el("strong", { class: "numero-valor" }, String(valor))));
}

// ---------------------------------------------------------------------------
// O cartão
// ---------------------------------------------------------------------------
function cartao(p, caixa) {
  const foto = p.foto_id
    ? fotoProtegida(p.foto_id, {
        class: "mon-foto", loading: "lazy",
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
      el("dl", { class: "monitor-ficha-dados" },
        el("div", {}, el("dt", {}, "Departamento"), el("dd", {}, p.departamento || "Sem departamento")),
        el("div", {}, el("dt", {}, "Última coleta do contador"), el("dd", {}, p.ultima_leitura_em ? fmtDate(p.ultima_leitura_em, true) : "Sem coleta")),
      ),

      el("div", { class: "mon-suprimentos", "data-suprimentos": p.com_snmp ? p.ativo_id : null },
        p.com_snmp
          ? el("span", { class: "muted mon-carregando" }, "lendo níveis…")
          : el("span", { class: "muted mon-carregando" },
              "Sem IP ou hostname — não há como ler os níveis."),
      ),
    ),

    // --- direita: detalhes -------------------------------------------------
    el("div", { class: "mon-direita" },
      el("button", { class: "btn tonal small", onclick: () => abrirMonitoramentoImpressora(p.ativo_id, p.patrimonio || p.endereco),
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
  if (!alvos.length || caixa.dataset.lendo) return;
  caixa.dataset.lendo = "true";

  const chip = document.getElementById("mon-vivo");
  if (chip) chip.textContent = "lendo…";

  // Em paralelo, mas tolerante: uma impressora fora do ar não pode impedir as
  // outras de mostrar o nível — e a que falhou precisa dizer isso no lugar
  // onde o nível apareceria.
  const resultados = await Promise.allSettled(
    alvos.map(a => state.podeInventario("impressora")
      ? consultarSituacaoImpressora(a.dataset.suprimentos)
      : api.get(`/monitor/impressoras/${a.dataset.suprimentos}/alertas`))
  );

  resultados.forEach((r, i) => {
    const alvo = alvos[i];
    if (!alvo) return;
    if (!caixa.contains(alvo)) return;
    const estado = caixa.querySelector(`[data-monitor-estado="${alvo.dataset.suprimentos}"]`);
    if (estado) {
      const suprimentos = r.value?.suprimentos || [];
      const alerta = suprimentos.some(s => ["atencao", "critico", "vazio"].includes(s.situacao));
      const comunicacao = r.value?.comunicacao;
      estado.textContent = r.status === "rejected" ? "Leitura indisponível" : alerta ? "Alerta de suprimento"
        : comunicacao === "online" ? "Online" : comunicacao === "sem_resposta" ? "Sem resposta"
          : suprimentos.length ? "Suprimentos lidos" : "Sem leitura de suprimentos";
      estado.classList.toggle("aviso", alerta);
      estado.classList.toggle("ok", comunicacao === "online" && !alerta);
      if (["online", "sem_resposta"].includes(comunicacao)) estado.dataset.online = String(comunicacao === "online");
      else delete estado.dataset.online;
      estado.dataset.estado = alerta ? "alerta" : comunicacao === "online" || suprimentos.length ? "lida" : "sem-leitura";
    }
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

  caixa.querySelector(".monitor-layout")?.dispatchEvent(new Event("leiturasatualizadas"));
  if (chip) {
    chip.textContent = `atualizado ${new Date().toLocaleTimeString("pt-BR")}`;
  }
  delete caixa.dataset.lendo;
}

/**
 * Uma linha de suprimento: nome, barra e porcentagem.
 *
 * A cor da barra vem da **situação** informada pelo backend, não do
 * percentual. Algumas impressoras devolvem 100% quando o cartucho é novo e
 * outras usam a mesma faixa para "desconhecido" — quem decide o que é crítico
 * é a regra do servidor, aplicada uma vez, e não uma conta refeita aqui.
 */
export function barraSuprimento(s) {
  const pct = s.percentual;
  const tom = s.situacao === "ok" ? "ok"
    : s.situacao === "atencao" ? "aviso"
    : ["critico", "vazio"].includes(s.situacao) ? "erro" : "info";

  const descricao = normalizarBusca(s.descricao || "");
  const cor = descricao.match(/\b(cyan|ciano|magenta|yellow|amarelo|black|preto)\b/)?.[0];
  const cores = { cyan: "#007ea5", ciano: "#007ea5", magenta: "#c12474", yellow: "#b68100", amarelo: "#b68100", black: "#34403b", preto: "#34403b" };
  return el("div", { class: "mon-sup", style: cor ? `--monitor-toner: ${cores[cor]}` : null },
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
export function consultarSituacaoImpressora(ativoId) {
  return api.get(`/monitor/impressoras/${ativoId}/situacao`);
}

export function abrirMonitoramentoImpressora(ativoId, nome, signal, leituraInicial = null) {
  const focoAnterior = document.activeElement;
  const titulo = `Monitoramento · ${nome || `Ativo #${ativoId}`}`;
  const status = el("p", { class: "muted", role: "status" });
  const dados = el("div");
  const atualizar = el("button", { class: "btn tonal", type: "button", onclick: consultar }, "Atualizar leitura");
  const janela = dialog({
    title: titulo,
    wide: true,
    body: el("div", {}, status, dados),
    actions: [{ elemento: atualizar }, { label: "Fechar", onClick: fechar }],
  });
  janela.dlg.setAttribute("role", "dialog");
  janela.dlg.setAttribute("aria-label", titulo);
  janela.dlg.tabIndex = -1;
  janela.dlg.focus();
  signal?.addEventListener("abort", fechar, { once: true });
  janela.overlay.addEventListener("click", ev => { if (ev.target === janela.overlay) fechar(); });
  janela.dlg.addEventListener("keydown", ev => {
    if (ev.key === "Escape") fechar();
  });
  consultar();

  function fechar() {
    signal?.removeEventListener("abort", fechar);
    janela.close();
    if (!signal?.aborted && focoAnterior?.isConnected) focoAnterior.focus();
  }

  async function consultar() {
    atualizar.disabled = true;
    status.textContent = "Consultando a impressora…";
    dados.replaceChildren();
    try {
      const pedido = leituraInicial || consultarSituacaoImpressora(ativoId);
      leituraInicial = null;
      const leitura = await pedido;
      if (!janela.overlay.isConnected) return;
      const [tom, mensagem] = comunicacaoImpressora[leitura.comunicacao] || comunicacaoImpressora.falha_na_consulta;
      status.replaceChildren(el("span", { class: `chip ${tom}` }, mensagem),
        ` · ${fmtDate(leitura.verificado_em, true)}`);
      mostrarMonitoramento(dados, leitura);
    } catch (e) {
      if (janela.overlay.isConnected) status.textContent = e.message;
    } finally {
      atualizar.disabled = false;
    }
  }
}

export const comunicacaoImpressora = {
  online: ["ok", "Online · respondeu por SNMP"],
  sem_resposta: ["aviso", "Sem resposta por SNMP"],
  sem_endereco: ["info", "Sem IP ou hostname cadastrado"],
  indisponivel: ["aviso", "SNMP indisponível no servidor"],
  falha_na_consulta: ["aviso", "Falha ao consultar por SNMP"],
};

function mostrarMonitoramento(corpo, p) {
  if (p.alertas.length) {
    corpo.append(secao("Alertas de suprimentos", p.alertas.map(a => [a.descricao, a.mensagem])));
  }
  const suprimentos = el("div", { class: "mon-secao" },
    el("h3", { class: "mon-secao-titulo" }, "Suprimentos"),
    p.suprimentos.length ? el("div", { class: "mon-suprimentos" }, ...p.suprimentos.map(s =>
      el("div", {}, barraSuprimento(s), s.estimativa?.aplicavel
        ? el("small", { class: "muted" }, `≈ ${s.estimativa.dias_restantes} dia(s) a ${inteiro(s.estimativa.paginas_por_dia)} págs/dia`)
        : null))) : el("p", { class: "muted" }, p.comunicacao === "online"
      ? "A impressora respondeu, mas não informou os níveis dos suprimentos."
      : "Níveis indisponíveis nesta consulta."));
  corpo.append(suprimentos);

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
