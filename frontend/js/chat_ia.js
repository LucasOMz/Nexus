import { api } from "./api.js";
import { baixarCsv } from "./chat_ia_csv.js";
import { state } from "./state.js";
import { el, icon } from "./ui.js";

const numero = new Intl.NumberFormat("pt-BR");
const dataConversa = new Intl.DateTimeFormat("pt-BR", { dateStyle: "short", timeStyle: "short" });

function botaoIcone(icone, rotulo, classe, tipo = "button") {
  return el("button", { type: tipo, class: classe, title: rotulo, "aria-label": rotulo, html: icon(icone, 20) });
}

function metricas(dados) {
  if (dados.operacao === "percentual" || "percentual" in dados) {
    return dados.percentual === null ? "Sem equipamentos no grupo"
      : `${numero.format(dados.percentual)}% · ${numero.format(dados.correspondentes)} de ${numero.format(dados.total)}`;
  }
  return numero.format(dados.total);
}

function listaEquipamentos(dados) {
  if (dados.aviso) return el("p", {}, dados.aviso);
  const { equipamentos, total } = dados;
  const lista = el("ul", { class: "chat-ia-lista" });
  for (const ativo of equipamentos) {
    const nome = ativo.hostname || ativo.modelo || `Equipamento #${ativo.id}`;
    const detalhes = [ativo.patrimonio ? `Patrimônio ${ativo.patrimonio}` : "Sem patrimônio", ativo.departamento, ativo.planta];
    lista.append(el("li", {}, el("strong", {}, nome), el("small", {}, detalhes.filter(Boolean).join(" · "))));
  }
  const legenda = total
    ? `Mostrando ${numero.format(equipamentos.length)} de ${numero.format(total)} equipamentos`
    : "Nenhum equipamento encontrado.";
  return el("div", {}, el("small", {}, legenda), lista);
}

export function criarChatIa() {
  const elemento = el("aside", { class: "chat-ia", "aria-label": "Assistente de inventário" });
  const abrir = botaoIcone("chat", "Abrir chat do inventário", "chat-ia-toggle");
  abrir.setAttribute("aria-controls", "chat-ia-painel");
  const limpar = botaoIcone("plus", "Nova conversa", "chat-ia-acao");
  const historico = botaoIcone("historico", "Histórico de conversas", "chat-ia-acao");
  historico.setAttribute("aria-controls", "chat-ia-historico");
  historico.setAttribute("aria-expanded", "false");
  const fechar = botaoIcone("close", "Fechar chat", "chat-ia-acao");
  const log = el("div", { class: "chat-ia-log", role: "log", "aria-label": "Conversa" });
  const listaHistorico = el("div", { id: "chat-ia-historico", class: "chat-ia-log", hidden: true });
  const entrada = el("textarea", { rows: 2, maxlength: 1000, "aria-label": "Pergunta ao inventário", placeholder: "Pergunte sobre seus equipamentos…" });
  const enviar = botaoIcone("enviar", "Enviar pergunta", "chat-ia-enviar", "submit");
  const formulario = el("form", { class: "chat-ia-form" }, entrada, enviar);
  const painel = el("section", { id: "chat-ia-painel", class: "chat-ia-painel", "aria-labelledby": "chat-ia-titulo", hidden: true },
    el("header", { class: "chat-ia-topo" },
      el("h2", { id: "chat-ia-titulo" }, "Chat do inventário"),
      historico, limpar, fechar),
    log, listaHistorico, formulario);
  elemento.append(painel, abrir);

  let escopo;
  let geracao = 0;
  let conversaId = null;
  let requisicaoHistorico = 0;

  function mostrar(visivel) {
    painel.hidden = !visivel;
    abrir.setAttribute("aria-expanded", String(visivel));
    abrir.setAttribute("aria-label", visivel ? "Fechar chat do inventário" : "Abrir chat do inventário");
    abrir.title = abrir.getAttribute("aria-label");
    abrir.innerHTML = icon(visivel ? "close" : "chat", 24);
    if (visivel) {
      fechar.focus();
      log.scrollTop = log.scrollHeight;
    } else if (elemento.contains(document.activeElement)) {
      abrir.focus();
    }
  }

  function mensagem(texto, classe = "") {
    const bloco = el("div", { class: `chat-ia-mensagem ${classe}` }, texto);
    log.append(bloco);
    log.scrollTop = log.scrollHeight;
    return bloco;
  }

  function reiniciar() {
    geracao++;
    conversaId = null;
    exibirHistorico(false);
    listaHistorico.replaceChildren();
    entrada.value = "";
    enviar.disabled = historico.disabled = limpar.disabled = false;
    log.replaceChildren();
    mensagem("Pergunte sobre o inventário. Por exemplo: quantos computadores estão sem patrimônio por departamento?");
  }

  function exibirHistorico(visivel) {
    requisicaoHistorico++;
    listaHistorico.hidden = !visivel;
    log.hidden = visivel;
    formulario.hidden = visivel;
    historico.setAttribute("aria-expanded", String(visivel));
  }

  function resultado(dados, atual, historica) {
    const bloco = el("div", { class: "chat-ia-resultado" });
    if (dados.aviso) {
      bloco.append(el("p", {}, dados.aviso));
      return bloco;
    }
    const cadastros = dados.cadastros_consultados;
    const escopoConsulta = [...(cadastros?.planta || []), ...(cadastros?.departamento || [])];
    if (escopoConsulta.length) bloco.append(el("small", {}, escopoConsulta.join(" · ")));
    if (dados.operacao === "listar") {
      bloco.append(listaEquipamentos(dados));
      return bloco;
    }
    bloco.append(el("strong", {}, metricas(dados)), el("small", {}, "Total da consulta"));
    if (dados.grupos?.length) {
      const grupos = el("ul", { class: "chat-ia-lista chat-ia-grupos" });
      for (const grupo of dados.grupos) {
        grupos.append(el("li", {}, el("span", {}, grupo.valores.map(v => v || "Sem cadastro").join(" · ")),
          el("strong", {}, metricas(grupo))));
      }
      bloco.append(grupos);
      if (dados.truncado) bloco.append(el("small", {}, "Outros grupos ficaram fora do limite de exibição."));
    }
    if ((dados.correspondentes ?? dados.total) > 0) {
      const ver = el("button", { type: "button", class: "chat-ia-ver" },
        historica ? "Ver equipamentos atuais" : "Ver equipamentos");
      const detalhe = el("div", {});
      ver.addEventListener("click", async () => {
        ver.disabled = true;
        detalhe.textContent = "Carregando equipamentos…";
        try {
          const lista = await api.request("POST", "/ia/equipamentos", { body: dados.consulta, enfileirar: false });
          if (atual !== geracao || !elemento.isConnected) return;
          detalhe.replaceChildren(listaEquipamentos(lista));
          if (!lista.aviso) {
            dados.equipamentos_exibidos = lista.equipamentos;
            dados.total_exibidos = lista.total;
            if (historica) detalhe.prepend(el("small", {}, "Dados atuais do inventário"));
          }
          ver.remove();
        } catch (erro) {
          if (atual !== geracao || !elemento.isConnected) return;
          detalhe.textContent = erro.message || "Não foi possível carregar os equipamentos.";
          ver.disabled = false;
        }
      });
      bloco.append(ver, detalhe);
    }
    return bloco;
  }

  function montarResposta(turno, atual, historica = false) {
    const resposta = el("div", { class: "chat-ia-mensagem" }, turno.resposta);
    for (const item of turno.resultados) resposta.append(resultado(item, atual, historica));
    resposta.append(el("button", { type: "button", class: "chat-ia-ver chat-ia-exportar",
      onclick: () => baixarCsv(turno, historica) }, "Exportar CSV"));
    return resposta;
  }

  async function carregarHistorico(botao, antes) {
    const requisicao = requisicaoHistorico;
    botao.disabled = true;
    try {
      const dados = await api.get("/ia/conversas", { antes_de: antes });
      if (requisicao !== requisicaoHistorico || !elemento.isConnected) return;
      botao.remove();
      for (const item of dados.conversas) {
        listaHistorico.append(el("button", { type: "button", class: "chat-ia-conversa",
          onclick: () => abrirConversa(item.id) },
        el("strong", {}, item.titulo), el("small", {}, dataConversa.format(new Date(item.atualizada_em)))));
      }
      if (!antes && !dados.conversas.length) listaHistorico.append(el("p", {}, "Nenhuma conversa neste escopo."));
      if (dados.proximo) listaHistorico.append(el("button", { type: "button", class: "chat-ia-ver",
        onclick: ev => carregarHistorico(ev.currentTarget, dados.proximo) }, "Mais conversas"));
    } catch (erro) {
      if (requisicao !== requisicaoHistorico || !elemento.isConnected) return;
      botao.disabled = false;
      botao.textContent = "Tentar carregar conversas";
      listaHistorico.append(el("p", { role: "alert" }, erro.message));
    }
  }

  async function carregarMensagens(id, antes = null) {
    return api.get(`/ia/conversas/${id}`, { antes_de: antes });
  }

  function inserirMensagens(dados) {
    const atual = geracao;
    const fragmento = document.createDocumentFragment();
    if (dados.proximo) {
      const id = conversaId;
      const mais = el("button", { type: "button", class: "chat-ia-ver", onclick: async () => {
        mais.disabled = true;
        try {
          const anteriores = await carregarMensagens(id, dados.proximo);
          if (atual !== geracao || !elemento.isConnected) return;
          const altura = log.scrollHeight;
          mais.remove();
          inserirMensagens(anteriores);
          log.scrollTop += log.scrollHeight - altura;
        } catch {
          mais.textContent = "Tentar carregar mensagens anteriores";
          mais.disabled = false;
        }
      } }, "Mensagens anteriores");
      fragmento.append(mais);
    }
    for (const turno of dados.mensagens) {
      fragmento.append(el("div", { class: "chat-ia-mensagem chat-ia-pergunta" }, turno.pergunta),
        montarResposta(turno, atual, true));
    }
    log.prepend(fragmento);
  }

  async function abrirConversa(id) {
    const requisicao = ++requisicaoHistorico;
    try {
      const dados = await carregarMensagens(id);
      if (requisicao !== requisicaoHistorico || !elemento.isConnected) return;
      reiniciar();
      conversaId = id;
      log.replaceChildren();
      inserirMensagens(dados);
      log.scrollTop = log.scrollHeight;
      entrada.focus();
    } catch (erro) {
      if (requisicao !== requisicaoHistorico || !elemento.isConnected) return;
      listaHistorico.append(el("p", { role: "alert" }, erro.message));
    }
  }

  abrir.addEventListener("click", () => mostrar(painel.hidden));
  fechar.addEventListener("click", () => mostrar(false));
  limpar.addEventListener("click", () => { reiniciar(); entrada.focus(); });
  historico.addEventListener("click", () => {
    const visivel = listaHistorico.hidden;
    exibirHistorico(visivel);
    if (!visivel) return;
    const carregando = el("button", { type: "button", class: "chat-ia-ver",
      onclick: ev => carregarHistorico(ev.currentTarget) }, "Carregando conversas…");
    listaHistorico.replaceChildren(carregando);
    carregarHistorico(carregando);
  });
  elemento.addEventListener("keydown", ev => {
    if (ev.key === "Escape" && !painel.hidden) {
      ev.stopPropagation();
      mostrar(false);
    }
  });
  entrada.addEventListener("keydown", ev => {
    if (ev.key === "Enter" && !ev.shiftKey && !ev.isComposing) {
      ev.preventDefault();
      formulario.requestSubmit();
    }
  });
  formulario.addEventListener("submit", async ev => {
    ev.preventDefault();
    const pergunta = entrada.value.trim();
    if (!pergunta || enviar.disabled) return;
    const atual = geracao;
    const body = { pergunta, conversa_id: conversaId };
    mensagem(pergunta, "chat-ia-pergunta");
    entrada.value = "";
    enviar.disabled = historico.disabled = limpar.disabled = true;
    const aguardando = mensagem("Consultando o inventário…", "chat-ia-aguarde");
    try {
      const dados = await api.request("POST", "/ia/chat", { body, enfileirar: false, prazoMs: 315000 });
      if (atual !== geracao || !elemento.isConnected) return;
      conversaId = dados.conversa_id;
      aguardando.remove();
      const resposta = montarResposta({ pergunta, ...dados }, atual);
      log.append(resposta);
      log.scrollTop = resposta.offsetTop - log.offsetTop;
    } catch (erro) {
      if (atual !== geracao || !elemento.isConnected) return;
      aguardando.remove();
      mensagem(erro.message || "Não foi possível consultar o inventário.");
      if (!entrada.value) entrada.value = pergunta;
    } finally {
      if (atual === geracao) enviar.disabled = historico.disabled = limpar.disabled = false;
    }
  });

  mostrar(false);
  return {
    elemento,
    atualizarEscopo() {
      const chave = JSON.stringify([state.user?.id, state.plantaAtiva, state.user?.permissoes_efetivas?.inventarios]);
      if (chave !== escopo) {
        escopo = chave;
        reiniciar();
      }
    },
  };
}
