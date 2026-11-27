import { api } from "./api.js";
import { avisoSoftwareAusente, baixarCsv, rotuloSoftware } from "./chat_ia_csv.js";
import { state } from "./state.js";
import { el, icon } from "./ui.js";

const numero = new Intl.NumberFormat("pt-BR");
const dataConversa = new Intl.DateTimeFormat("pt-BR", { dateStyle: "short", timeStyle: "short" });
const atributosTecnicos = {
  ram_gb: ["RAM", " GB"],
  armazenamento_gb: ["Armazenamento", " GB"],
  cpu: ["Processador", ""],
  so: ["Sistema operacional", ""],
};

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
    const detalhes = [ativo.patrimonio ? `Patrimônio ${ativo.patrimonio}` : "Sem patrimônio",
      ativo.numero_serie, ativo.departamento, ativo.planta];
    const linha = el("li", {}, el("strong", {}, nome), el("small", {}, detalhes.filter(Boolean).join(" · ")));
    for (const campo of dados.atributos || []) {
      const [rotulo, unidade] = atributosTecnicos[campo];
      const valor = ativo[campo];
      const texto = valor == null || valor === "" ? "Sem informação cadastrada" : `${valor}${unidade}`;
      linha.append(el("small", {}, `${rotulo} · ${texto}`));
    }
    for (const software of ativo.softwares || []) {
      linha.append(el("small", {}, `${software.nome} · ${software.versao || "Sem versão registrada"}`));
    }
    lista.append(linha);
  }
  const legenda = total
    ? `Mostrando ${numero.format(equipamentos.length)} de ${numero.format(total)} equipamentos`
    : "Nenhum equipamento encontrado.";
  return el("div", {}, el("small", {}, legenda), lista);
}

export function criarChatIa() {
  const elemento = el("aside", { class: "chat-ia", "aria-label": "Assistente do Nexus" });
  const abrir = botaoIcone("chat", "Abrir assistente do Nexus", "chat-ia-toggle");
  abrir.setAttribute("aria-controls", "chat-ia-painel");
  const limpar = botaoIcone("plus", "Nova conversa", "chat-ia-acao");
  const historico = botaoIcone("historico", "Histórico de conversas", "chat-ia-acao");
  historico.setAttribute("aria-controls", "chat-ia-historico");
  historico.setAttribute("aria-expanded", "false");
  const fechar = botaoIcone("close", "Fechar chat", "chat-ia-acao");
  const log = el("div", { class: "chat-ia-log", role: "log", "aria-label": "Conversa" });
  const listaHistorico = el("div", { id: "chat-ia-historico", class: "chat-ia-log", hidden: true });
  const entrada = el("textarea", { rows: 2, maxlength: 1000, "aria-label": "Pergunta ao Nexus", placeholder: "Pergunte sobre telas, recursos ou dados…" });
  const enviar = botaoIcone("enviar", "Enviar pergunta", "chat-ia-enviar", "submit");
  const formulario = el("form", { class: "chat-ia-form" }, entrada, enviar);
  const painel = el("section", { id: "chat-ia-painel", class: "chat-ia-painel", "aria-labelledby": "chat-ia-titulo", hidden: true },
    el("header", { class: "chat-ia-topo" },
      el("h2", { id: "chat-ia-titulo" }, "Assistente do Nexus"),
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
    abrir.setAttribute("aria-label", visivel ? "Fechar assistente do Nexus" : "Abrir assistente do Nexus");
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
    mensagem("Pergunte como usar o Nexus, onde encontrar uma tela ou quais dados estão cadastrados.");
  }

  function exibirHistorico(visivel) {
    requisicaoHistorico++;
    listaHistorico.hidden = !visivel;
    log.hidden = visivel;
    formulario.hidden = visivel;
    historico.setAttribute("aria-expanded", String(visivel));
  }

  function resultado(dados, atual, historica, mensagemId, indice) {
    const bloco = el("div", { class: "chat-ia-resultado" });
    if (dados.tipo === "informacoes") {
      for (const secao of dados.blocos || []) {
        const lista = el("dl", { class: "chat-ia-ficha" });
        for (const [campo, valor] of secao.linhas) lista.append(el("dt", {}, campo), el("dd", {}, valor));
        bloco.append(el("strong", {}, secao.titulo), lista);
      }
      for (const link of dados.links || []) {
        const rota = /^#\/([a-z]+)(?:\?[^#]*)?$/.exec(link.rota);
        if (rota?.[1] !== link.modulo || !state.podeModulo(link.modulo)) continue;
        if (link.dominio && !state.podeInventario(link.dominio)) continue;
        bloco.append(el("a", { class: "chat-ia-ver", href: link.rota, onclick: ev => {
          if (ev.ctrlKey || ev.metaKey || ev.shiftKey || ev.altKey) return;
          if (link.dominio) state.dominio = link.dominio;
          mostrar(false);
        } }, link.rotulo));
      }
      return bloco.childNodes.length ? bloco : null;
    }
    if (dados.aviso) {
      bloco.append(el("p", {}, dados.aviso));
      return bloco;
    }
    const cadastros = dados.cadastros_consultados;
    const escopoConsulta = [...(cadastros?.planta || []), ...(cadastros?.departamento || [])];
    const filtrosSoftware = [...(dados.consulta?.softwares || []), ...(dados.consulta?.softwares_numerador || [])];
    escopoConsulta.push(...filtrosSoftware.map(rotuloSoftware));
    if (escopoConsulta.length) bloco.append(el("small", {}, escopoConsulta.join(" · ")));
    if (filtrosSoftware.some(filtro => filtro.situacao === "ausente")) bloco.append(el("small", {}, avisoSoftwareAusente));
    if (dados.operacao !== "listar") bloco.append(el("strong", {}, metricas(dados)), el("small", {}, "Total da consulta"));
    if (dados.grupos?.length) {
      const grupos = el("ul", { class: "chat-ia-lista chat-ia-grupos" });
      for (const grupo of dados.grupos) {
        grupos.append(el("li", {}, el("span", {}, grupo.valores.map(v => v || "Sem cadastro").join(" · ")),
          el("strong", {}, metricas(grupo))));
      }
      bloco.append(grupos);
      if (dados.truncado) bloco.append(el("small", {}, "Todos os grupos estão disponíveis no CSV."));
    }
    const primeira = dados.operacao === "listar" ? dados : historica ? null : dados.amostra_equipamentos;
    const detalhe = el("div", {});
    if (primeira) detalhe.append(listaEquipamentos(primeira));
    const proximo = primeira?.proximo ?? (primeira?.equipamentos.length < primeira?.total ? primeira.equipamentos.length : null);
    if ((dados.correspondentes ?? dados.total) > 0 && (!primeira || proximo != null)) {
      const ver = el("button", { type: "button", class: "chat-ia-ver" },
        primeira ? "Carregar mais equipamentos" : historica ? "Ver equipamentos atuais" : "Ver equipamentos");
      const aviso = el("small", { role: "status" });
      let inicio = proximo ?? 0;
      let carregados = primeira?.equipamentos || [];
      ver.addEventListener("click", async () => {
        ver.disabled = true;
        aviso.textContent = "Carregando equipamentos…";
        try {
          const lista = await api.get(`/ia/mensagens/${mensagemId}/resultados/${indice}`, { inicio });
          if (atual !== geracao || !elemento.isConnected) return;
          carregados = [...carregados, ...(lista.equipamentos || [])];
          detalhe.replaceChildren(listaEquipamentos({ ...lista, equipamentos: carregados }));
          if (historica) detalhe.prepend(el("small", {}, "Dados atuais do inventário"));
          aviso.textContent = "";
          inicio = lista.proximo;
          if (inicio == null) ver.remove();
          else ver.textContent = "Carregar mais equipamentos";
        } catch (erro) {
          if (atual !== geracao || !elemento.isConnected) return;
          aviso.textContent = erro.message || "Não foi possível carregar os equipamentos.";
        } finally {
          ver.disabled = false;
        }
      });
      bloco.append(detalhe, ver, aviso);
    } else if (primeira) {
      bloco.append(detalhe);
    }
    return bloco;
  }

  function montarResposta(turno, atual, historica = false) {
    const resposta = el("div", { class: "chat-ia-mensagem" }, turno.resposta);
    for (const [indice, item] of turno.resultados.entries()) {
      const conteudo = resultado(item, atual, historica, turno.id, indice);
      if (conteudo) resposta.append(conteudo);
    }
    if (turno.resultados.length) {
      const aviso = el("small", { role: "status" });
      const botao = el("button", { type: "button", class: "chat-ia-ver chat-ia-exportar",
        onclick: async () => {
          botao.disabled = true;
          aviso.textContent = "Buscando todos os resultados…";
          try {
            const dados = await api.request("GET", `/ia/mensagens/${turno.id}/exportacao`, { prazoMs: 120000 });
            if (atual !== geracao || !resposta.isConnected) return;
            baixarCsv(dados, historica);
            aviso.textContent = "";
          } catch (erro) {
            aviso.textContent = erro.message || "Não foi possível exportar.";
          } finally {
            botao.disabled = false;
          }
        } }, "Exportar CSV completo");
      resposta.append(botao, aviso);
    }
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
    const aguardando = mensagem("Consultando o Nexus…", "chat-ia-aguarde");
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
      const chave = JSON.stringify([state.user?.id, state.plantaAtiva, state.perms.inventarios, state.perms.modulos]);
      if (chave !== escopo) {
        escopo = chave;
        reiniciar();
      }
    },
  };
}
