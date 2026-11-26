/** Espaço de trabalho para localizar ativos e editar a planta da unidade. */
import { api } from "../api.js";
import { ctx } from "../context.js";
import { criarPlantaConsulta } from "../mapa_planta.js";
import { state } from "../state.js";
import { dialog, el, icon, mostrarErro, skeleton, STATUS_LABEL as statusAtivo, toast } from "../ui.js";
import { abrirDetalhes } from "./ativo_detalhes.js";
import { abrirMonitoramentoImpressora, barraSuprimento, comunicacaoImpressora, consultarSituacaoImpressora } from "./monitor_impressoras.js";

const tipoAtivo = { ti: "TI", impressora: "Impressora" };
const passoLista = 60;
const formatar = (valor, casas = 1) =>
  Number(valor).toLocaleString("pt-BR", { maximumFractionDigits: casas });
const normalizar = valor => String(valor ?? "").normalize("NFD").replace(/\p{Diacritic}/gu, "").toLowerCase();

function botao(rotulo, acao, { classe = "", icone, titulo } = {}) {
  return el("button", { type: "button", class: `mapa-button ${classe}`, onclick: acao, title: titulo },
    icone ? el("span", { html: icon(icone, 17) }) : null, rotulo);
}

function filtro(rotulo, opcoes, mudar) {
  return el("select", { "aria-label": rotulo, onchange: mudar },
    ...opcoes.map(([value, texto]) => el("option", { value }, texto)));
}

function campo(rotulo, input) {
  return el("label", { class: "mapa-campo" }, el("span", {}, rotulo), input);
}

function numero(value, min, max, step = "0.01") {
  return el("input", { type: "number", value: String(value), min: String(min), max: String(max), step, required: "" });
}

export async function renderMapa(root) {
  ctx.setTitle("Mapa 3D");
  ctx.setFab(null);
  const ciclo = new AbortController();
  const { signal } = ciclo;
  let viewer, store, imagemUrl;

  ctx.limpar = () => {
    ciclo.abort();
    viewer?.dispose();
    if (imagemUrl) URL.revokeObjectURL(imagemUrl);
    store?.flushSave().catch(e => toast(`Mapa: ${e.message}`));
  };
  const pagina = el("section", { class: "mapa-workspace" }, skeleton(5));
  root.replaceChildren(pagina);

  const planta = state.isAdmin ? state.plantaAtiva : state.plantaId;
  const opcoes = api.get("/plantas/opcoes").catch(() => []);
  if (!planta) {
    const lista = state.isAdmin ? await opcoes : [];
    if (signal.aborted) return;
    pagina.replaceChildren(
      tituloMapa("Visualização por unidade"),
      el("div", { class: "mapa-bemvindo" },
        el("span", { class: "mapa-vazio-icone", html: icon("cube3d", 30) }),
        el("h2", {}, state.isAdmin ? "Escolha uma planta" : "Conta sem planta vinculada"),
        el("p", {}, state.isAdmin
          ? "Abra uma unidade para visualizar seus espaços e equipamentos."
          : "Peça ao administrador para vincular sua conta a uma planta."),
        lista.length ? el("div", { class: "mapa-opcoes-plantas" },
          ...lista.map(p => botao(p.nome || p.sigla, () => {
            state.plantaAtiva = p.id;
            const seletor = document.querySelector(".seletor-planta");
            if (seletor) seletor.value = String(p.id);
            ctx.rerender();
          }, { icone: "grade" }))) : null),
    );
    return;
  }

  try {
    const [{ StoreNexus }, projeto, dados, plantas] = await Promise.all([
      import("../../lib/mapa3d/store_nexus.js"),
      api.get(`/mapas/${planta}`),
      api.get(`/mapas/${planta}/ativos`),
      opcoes,
    ]);
    if (signal.aborted) return;
    let falhaImagem = "";
    if (projeto.imagem) {
      try { imagemUrl = await api.blob(`/mapas/${planta}/imagem`); }
      catch (e) { falhaImagem = e.message; }
    }
    if (signal.aborted) {
      if (imagemUrl) URL.revokeObjectURL(imagemUrl);
      return;
    }

    store = new StoreNexus(planta, dados, projeto, imagemUrl);
    const unidade = plantas.find(p => p.id === Number(planta));
    const nome = unidade?.nome || state.user?.planta_sigla || `Planta ${planta}`;
    let carregamento;
    const painel = montarPainel(pagina, nome, store, projeto, signal, {
      acesso: dados.acesso,
      falhaImagem,
      imagemAlterada(url) {
        if (imagemUrl) URL.revokeObjectURL(imagemUrl);
        imagemUrl = url;
      },
      obterViewer: () => viewer,
      carregarViewer() {
        if (viewer) return Promise.resolve(viewer);
        carregamento ??= abrirViewer().finally(() => { carregamento = null; });
        return carregamento;
      },
    });
    async function abrirViewer() {
      try {
        const { Viewer } = await import("../../lib/mapa3d/viewer.js");
        if (signal.aborted) return null;
        viewer = new Viewer(painel.viewport, painel.canvas, store, {
          editable: false, thumbnails: false, showPlaceholder: false,
        });
        viewer.init();
        painel.ligarViewer(viewer);
        return viewer;
      } catch (e) {
        viewer?.dispose();
        viewer = null;
        console.warn("Mapa 3D indisponível", e);
        return null;
      }
    }
  } catch (e) {
    if (signal.aborted) return;
    pagina.replaceChildren(tituloMapa("Visualização por unidade"),
      el("div", { class: "mapa-bemvindo", role: "alert" },
        el("h2", {}, "Não foi possível abrir o mapa"),
        el("p", {}, e.message),
        botao("Tentar novamente", () => ctx.rerender(), { icone: "refresh" })));
  }
}

function tituloMapa(unidade, acoes = null) {
  return el("header", { class: "mapa-cabecalho" },
    el("div", { class: "nexus-pagina-titulo" },
      el("span", { class: "nexus-pagina-icone", html: icon("cube3d", 26) }),
      el("div", {}, el("h1", {}, "Mapa 3D"), el("p", {}, unidade))),
    acoes);
}

function montarPainel(pagina, unidade, store, projeto, signal, { acesso, falhaImagem, imagemAlterada, obterViewer, carregarViewer }) {
  const { editar: canWrite, departamento } = acesso;
  const podeMonitorar = state.podeModulo("monitor") && state.podeInventario("impressora");
  let editando = false;
  let vista3d = false;
  let aba = store.project.equipment.some(eq => !eq.pendente) ? "mapa" : "pendentes";
  let limite = passoLista;
  let ativoSelecionado = null;
  let paredeSelecionada = null;
  let cenaPronta = false;
  let leituraSelecao = null;
  const desinscrever = [];

  const canvas = el("canvas", { class: "mapa-canvas", hidden: "", tabindex: "0", "aria-label": "Cena do mapa da unidade" });
  const viewport = el("div", { class: "mapa-viewport" }, canvas);
  const consulta = criarPlantaConsulta(id => {
    const eq = store.findEquipment(id);
    if (!eq) return;
    selecionar(eq, false);
    if (podeMonitorar && !editando && eq.ativo.dominio === "impressora") {
      abrirMonitoramentoImpressora(eq.id, eq.name, signal, leituraSelecao?.pedido);
    }
  }, signal);
  const aviso = el("span", { role: "status" });
  const coordenada = el("span", { class: "mapa-coordenada" }, "X —  Z —");
  const vazioCena = el("div", { class: "mapa-vazio-cena", hidden: "" },
    el("span", { class: "mapa-vazio-icone", html: icon("cube3d", 27) }),
    el("strong", {}, "Mapa em preparação"),
    el("p", {}, canWrite ? "Use Editar mapa para adicionar a planta baixa ou posicionar equipamentos."
      : "A planta baixa e os equipamentos aparecerão aqui conforme a TI preparar o mapa."));
  const concluirParede = botao("Concluir parede", () => obterViewer()?.finishWall(), { classe: "mapa-scene-button" });
  const cancelar = botao("Cancelar ferramenta", () => obterViewer()?.cancelCurrent(), { classe: "mapa-scene-button" });
  concluirParede.hidden = cancelar.hidden = true;

  const cenaAcoes = el("div", { class: "mapa-cena-acoes" }, concluirParede, cancelar);
  const modos = el("div", { class: "mapa-modos", role: "group", "aria-label": "Visualização do mapa" });
  const modoBotoes = [
    ["3d", botao("3D", () => obterViewer()?.setMode("3d"))],
    ["top", botao("Planta baixa", () => obterViewer()?.setMode("top"))],
    ["walk", botao("Caminhar", () => obterViewer()?.setMode("walk"))],
  ];
  modoBotoes[2][1].hidden = !canvas.requestPointerLock || matchMedia("(hover: none) and (pointer: coarse)").matches;
  modos.append(...modoBotoes.map(([, b]) => b));
  const enquadrar = botao("Enquadrar", () => {
    const v = obterViewer();
    if (v?.mode === "walk") v.setMode("3d");
    v?.fitAll();
  }, { classe: "mapa-scene-button", icone: "qr" });
  const telaCheia = botao("Tela cheia", async () => {
    try {
      if (document.fullscreenElement) await document.exitFullscreen();
      else await viewport.requestFullscreen();
    } catch (e) { mostrarErro(e, "abrir a tela cheia"); }
  }, { classe: "mapa-scene-button" });
  telaCheia.hidden = !viewport.requestFullscreen;
  const controles3d = el("div", { class: "mapa-cena-topo" }, modos,
    el("div", { class: "mapa-cena-acoes" }, enquadrar, telaCheia));
  const rodape3d = el("div", { class: "mapa-cena-rodape" },
    el("div", { class: "mapa-cena-info" }, aviso, coordenada), cenaAcoes);
  viewport.append(consulta.elemento, vazioCena, controles3d, rodape3d);

  const legenda = el("div", { class: "mapa-legenda" },
    el("span", {}, pontoTipo("ti"), "Equipamentos de TI"),
    departamento ? null : el("span", {}, pontoTipo("impressora"), "Impressoras"));
  const dimensoes = el("span", { class: "mapa-dimensoes" });
  const cobertura = el("span", { class: "mapa-cobertura" });
  const estado = el("span", { class: "mapa-save", role: "status" });
  const tentarSalvar = botao("Tentar salvar", () => store.flushSave().catch(() => {}), { classe: "mapa-button-quiet" });
  tentarSalvar.hidden = true;
  const editar = botao("Editar mapa", alternarEdicao, { classe: "mapa-button-primary", icone: "edit" });
  const cabAcoes = el("div", { class: "mapa-cab-acoes" }, estado, tentarSalvar, canWrite ? editar : null);

  const busca = el("input", { type: "search", placeholder: "Buscar patrimônio, nome ou modelo", "aria-label": "Buscar equipamentos" });
  const dominios = filtro("Tipo de ativo", [["", "Todos os tipos"], ["ti", "TI"], ["impressora", "Impressoras"]], refiltrar);
  const setores = Array.from(new Set(store.project.equipment.map(eq => eq.sector).filter(Boolean))).sort((a, b) => a.localeCompare(b, "pt-BR"));
  const setoresFiltro = filtro("Departamento", [["", "Todos os setores"], ...setores.map(s => [s, s])], refiltrar);
  const situacoes = filtro("Situação do ativo", [["", "Todos os status"], ...Object.entries(statusAtivo)], refiltrar);
  const tabs = el("div", { class: "mapa-tabs", role: "group", "aria-label": "Situação no mapa" });
  const noMapa = botao("", () => mudarAba("mapa"));
  const pendentes = botao("", () => mudarAba("pendentes"));
  tabs.append(noMapa, pendentes);
  const lista = el("ul", { class: "mapa-lista", "aria-label": "Equipamentos" });
  const ficha = el("div", { class: "mapa-ficha", "aria-label": "Detalhes da seleção" });
  const lateral = el("aside", { class: "mapa-lateral" },
    el("div", { class: "mapa-lateral-head" },
      el("h2", {}, departamento || "Equipamentos da unidade"), cobertura,
      el("label", { class: "mapa-busca" }, el("span", { html: icon("search", 18) }), busca),
      el("div", { class: "mapa-filtros" }, departamento ? null : dominios, departamento ? null : setoresFiltro, situacoes), tabs),
    ficha, lista);

  const camadas = el("details", { class: "mapa-camadas" }, el("summary", {}, "Camadas"),
    el("div", { class: "mapa-camadas-menu" }, ...[
      ["showLabels", "Etiquetas"], ["showGrid", "Grade"], ["showWalls", "Paredes"],
    ].map(([chave, rotulo]) => {
      const input = el("input", { type: "checkbox", onchange: () => store.setSettings({ [chave]: input.checked }) });
      input.checked = store.project.settings[chave];
      return el("label", {}, input, rotulo);
    })));
  const medir = botao("Medir distância", () => ativarFerramenta(v => v.startMeasure()), { icone: "counter" });
  const limparMedidas = botao("Limpar medidas", () => {
    obterViewer()?.clearMeasurements();
    atualizarFerramentas();
  }, { classe: "mapa-button-quiet" });
  limparMedidas.hidden = true;
  const plantaBaixa = botao("Planta baixa", configurarImagem, { icone: "image" });
  const desenhar = botao("Desenhar parede", () => ativarFerramenta(v => v.startWall()), { icone: "plus" });
  const calibrar = botao("Calibrar escala", () => ativarFerramenta(v => v.startCalibration()), { icone: "counter" });
  const desfazer = botao("Desfazer", () => store.undo());
  const refazer = botao("Refazer", () => store.redo());
  const encaixe = el("input", { type: "checkbox", checked: "", onchange: () => store.setSettings({ snap: encaixe.checked }) });
  const acoesEdicao = el("div", { class: "mapa-edicao" }, plantaBaixa, desenhar, calibrar, desfazer, refazer,
    el("label", { class: "mapa-encaixe" }, encaixe, "Encaixe 25 cm"));
  acoesEdicao.hidden = true;
  const barra = el("div", { class: "mapa-barra" },
    el("div", { class: "mapa-barra-grupo" }, camadas, medir, limparMedidas), acoesEdicao);
  const vistaPlanta = botao("Planta baixa", () => { if (vista3d) alternarVista(); }, { icone: "grade" });
  const vista = botao("Vista 3D", () => { if (!vista3d) alternarVista(); }, { icone: "cube3d" });
  const seletorVista = el("div", { class: "mapa-modos mapa-modos-consulta", role: "group", "aria-label": "Visualização da unidade" }, vistaPlanta, vista);
  const menos = botao("−", () => consulta.ampliar(1 / 1.3), { titulo: "Diminuir zoom" });
  const mais = botao("+", () => consulta.ampliar(1.3), { titulo: "Aumentar zoom" });
  menos.setAttribute("aria-label", "Diminuir zoom");
  mais.setAttribute("aria-label", "Aumentar zoom");
  const zoomConsulta = el("div", { class: "mapa-zoom-consulta", role: "group", "aria-label": "Navegação da planta" },
    menos, mais, botao("Enquadrar", consulta.enquadrar));
  const tituloPalco = el("h2", {}, "Planta baixa");
  const mensagemMapa = el("p", { class: "mapa-aviso-consulta", role: "status" }, falhaImagem ? "A imagem da planta baixa está indisponível." : "");
  const verDetalhes = botao("Ver detalhes", () => ficha.focus(), { classe: "mapa-detalhes-mobile mapa-button-quiet" });
  ficha.tabIndex = -1;
  const palco = el("section", { class: "mapa-palco", "aria-label": "Visualização da planta" },
    el("div", { class: "mapa-palco-topo" }, tituloPalco, departamento ? null : seletorVista, zoomConsulta), barra, viewport,
    el("div", { class: "mapa-palco-rodape" }, legenda, dimensoes, verDetalhes), mensagemMapa);
  pagina.replaceChildren(tituloMapa(unidade, cabAcoes),
    el("div", { class: "mapa-grade-layout" }, palco, lateral));

  busca.addEventListener("input", refiltrar, { signal });
  pagina.addEventListener("keydown", ev => {
    if (ev.key === "Escape" && obterViewer()?.tool !== "select") {
      obterViewer()?.cancelCurrent();
    }
  }, { signal });
  window.addEventListener("beforeunload", ev => {
    if (store._dirty) ev.preventDefault();
  }, { signal });
  signal.addEventListener("abort", () => desinscrever.forEach(off => off()), { once: true });
  desinscrever.push(
    store.on("change", () => atualizar()),
    store.on("history", atualizarFerramentas),
    store.on("plan:change", () => atualizar()),
    store.on("save:state", data => {
      estado.dataset.state = data.state;
      estado.textContent = { saving: "Salvando…", saved: "Mapa salvo", error: "Falha ao salvar" }[data.state] || "";
      estado.title = data.message || "";
      tentarSalvar.hidden = data.state !== "error";
      if (data.state === "error" && data.message) aviso.textContent = data.message;
    }),
  );

  function abrirDialogo(config) {
    const avisoDialogo = dialog(config);
    signal.addEventListener("abort", avisoDialogo.close, { once: true });
    return avisoDialogo;
  }

  async function alternarEdicao() {
    editando = !editando;
    vista3d = editando;
    editar.setAttribute("aria-pressed", String(editando));
    editar.lastChild.textContent = editando ? "Concluir edição" : "Editar mapa";
    paredeSelecionada = null;
    if (editando) {
      await abrirCena("top");
    } else {
      const v = obterViewer();
      if (v) {
        v.editable = false;
        v.cancelCurrent();
        if (v.mode === "walk") v.setMode("3d");
      }
      restaurarMensagem();
      store.flushSave().catch(e => mostrarErro(e, "salvar o mapa"));
    }
    if (!signal.aborted) atualizar();
  }

  async function alternarVista() {
    vista3d = !vista3d;
    paredeSelecionada = null;
    if (vista3d) await abrirCena("3d");
    else {
      const v = obterViewer();
      if (v?.mode === "walk") v.setMode("3d");
      restaurarMensagem();
    }
    if (!signal.aborted) atualizar();
  }

  function restaurarMensagem() {
    mensagemMapa.textContent = falhaImagem ? "A imagem da planta baixa está indisponível." : "";
  }

  async function abrirCena(modo) {
    vista.disabled = editar.disabled = true;
    mensagemMapa.textContent = "Abrindo visualização…";
    const v = await carregarViewer();
    if (signal.aborted) return;
    vista.disabled = editar.disabled = false;
    if (!v) {
      vista3d = false;
      mensagemMapa.textContent = editando
        ? "Cena 3D indisponível. Você ainda pode enviar uma planta baixa e editar posições pelas coordenadas."
        : "Vista 3D indisponível. Use a planta baixa para localizar os equipamentos.";
      return;
    }
    restaurarMensagem();
    atualizarFerramentas();
    v.editable = editando;
    v.resize();
    v.setMode(modo);
    v.fitAll();
    const eq = store.findEquipment(ativoSelecionado);
    v.select(eq && !eq.pendente ? "equipment" : null, eq?.id, { silent: true });
  }

  function mudarAba(valor) {
    aba = valor;
    limite = passoLista;
    atualizar();
  }

  function refiltrar() {
    limite = passoLista;
    atualizar();
  }

  function selecionar(eq, centralizar = true) {
    ativoSelecionado = eq.id;
    paredeSelecionada = null;
    aba = eq.pendente ? "pendentes" : "mapa";
    const v = obterViewer();
    if (vista3d && v) {
      if (v.mode === "walk") v.setMode("top");
      if (!eq.pendente) v.select("equipment", eq.id, { focus: true, silent: true });
      else v.select(null, null, { silent: true });
    } else if (centralizar && !eq.pendente) consulta.focar(eq);
    atualizar();
  }

  function atualizar() {
    const todos = store.project.equipment;
    const q = normalizar(busca.value).trim();
    const filtrados = todos.filter(eq => {
      const a = eq.ativo;
      return (!dominios.value || a.dominio === dominios.value)
        && (!setoresFiltro.value || eq.sector === setoresFiltro.value)
        && (!situacoes.value || a.status === situacoes.value)
        && (!q || [eq.name, eq.model, eq.serial, eq.notes, a.hostname, eq.ip, eq.sector]
          .some(valor => normalizar(valor).includes(q)));
    });
    const noPiso = todos.filter(eq => !eq.pendente).length;
    noMapa.textContent = `No mapa · ${noPiso}`;
    pendentes.textContent = `Sem posição · ${todos.length - noPiso}`;
    noMapa.setAttribute("aria-pressed", String(aba === "mapa"));
    pendentes.setAttribute("aria-pressed", String(aba === "pendentes"));
    cobertura.textContent = `${noPiso} de ${todos.length} posicionados`;

    const visiveis = filtrados.filter(eq => eq.pendente === (aba === "pendentes"));
    if (ativoSelecionado && !visiveis.some(eq => eq.id === ativoSelecionado)) {
      ativoSelecionado = null;
      obterViewer()?.select(null, null, { silent: true });
    }
    lista.replaceChildren(...visiveis.slice(0, limite).map(eq =>
      el("li", {}, botaoAtivo(eq, ativoSelecionado === eq.id, () => selecionar(eq)))));
    if (!visiveis.length) {
      lista.append(el("li", { class: "mapa-lista-vazia" }, q || dominios.value || setoresFiltro.value || situacoes.value
        ? "Nenhum ativo corresponde aos filtros."
        : aba === "mapa" ? "Nenhum ativo no mapa." : "Todos os ativos têm posição."));
    } else if (visiveis.length > limite) {
      lista.append(el("li", {}, botao(`Mostrar mais (${visiveis.length - limite})`, () => {
        limite += passoLista;
        atualizar();
      }, { classe: "mapa-button-quiet" })));
    }
    const posicionados = filtrados.filter(eq => !eq.pendente);
    consulta.atualizar(store.project, posicionados, ativoSelecionado);
    obterViewer()?.setEquipmentFilter(new Set(posicionados.map(eq => eq.id)));
    const plan = store.project.plan;
    vazioCena.hidden = !!plan || noPiso > 0 || store.project.walls.length > 0;
    dimensoes.textContent = editando && plan ? `${formatar(plan.widthM)} × ${formatar(plan.heightM)} m` : "";
    desenhar.disabled = !cenaPronta || store.project.walls.length >= 400;
    calibrar.disabled = !cenaPronta || !plan;
    renderFicha();
    atualizarFerramentas();
  }

  function atualizarFerramentas() {
    const v = obterViewer();
    const ferramenta = v?.getState();
    const historico = store.historyState();
    const cena = vista3d && cenaPronta;
    if (v) v.suspended = !cena;
    canvas.hidden = controles3d.hidden = rodape3d.hidden = !cena;
    consulta.elemento.hidden = cena;
    viewport.classList.toggle("mapa-vista-consulta", !cena);
    tituloPalco.textContent = editando ? "Edição da planta" : cena ? "Vista 3D" : "Planta baixa";
    tituloPalco.hidden = !departamento && !editando;
    seletorVista.hidden = editando;
    vistaPlanta.setAttribute("aria-pressed", String(!vista3d));
    vista.setAttribute("aria-pressed", String(vista3d));
    zoomConsulta.hidden = cena;
    barra.hidden = !editando;
    acoesEdicao.hidden = !editando;
    desfazer.disabled = !historico.canUndo;
    refazer.disabled = !historico.canRedo;
    modos.hidden = !cenaPronta;
    medir.disabled = !cenaPronta;
    enquadrar.hidden = !cenaPronta;
    camadas.hidden = !cenaPronta;
    limparMedidas.hidden = !v?.measureCount?.();
    concluirParede.hidden = ferramenta?.tool !== "wall";
    cancelar.hidden = !ferramenta || ferramenta.tool === "select";
    for (const [modo, elemento] of modoBotoes) {
      elemento.setAttribute("aria-pressed", String(modo === ferramenta?.mode));
    }
    const texto = ferramenta?.mode === "walk"
      ? "Clique na cena · WASD ou setas para andar · Esc libera o cursor"
      : editando ? "Arraste um ativo para mover ou ajuste as coordenadas na ficha."
        : "Selecione um ativo para consultar sua ficha.";
    if (!ferramenta || ferramenta.tool === "select") aviso.textContent = texto;
  }

  function ativarFerramenta(acao) {
    const v = obterViewer();
    if (!v || !cenaPronta) return;
    if (v.mode === "walk") v.setMode("top");
    acao(v);
  }

  function renderFicha() {
    const eq = store.findEquipment(ativoSelecionado);
    const wall = store.findWall(paredeSelecionada);
    const mostrarImpressora = podeMonitorar && !editando && eq?.ativo.dominio === "impressora";
    if (!mostrarImpressora) leituraSelecao = null;
    verDetalhes.hidden = !eq || editando;
    if (!eq && !wall) {
      ficha.replaceChildren(el("h3", {}, "Detalhes do equipamento"),
        el("p", {}, "Selecione um equipamento no mapa ou na lista."));
      return;
    }
    const fechar = botao("Fechar", () => {
      ativoSelecionado = paredeSelecionada = null;
      obterViewer()?.select(null, null, { silent: true });
      atualizar();
    }, { classe: "mapa-button-quiet" });
    if (wall) {
      ficha.replaceChildren(el("div", { class: "mapa-ficha-titulo" }, el("h3", {}, "Parede"), fechar),
        pares([["Altura", `${formatar(wall.height)} m`], ["Espessura", `${formatar(wall.thickness, 2)} m`]]),
        editando ? el("div", { class: "mapa-ficha-acoes" },
          botao("Editar medidas", () => configurarParede(wall)),
          botao("Remover parede", () => store.removeWall(wall.id), { classe: "mapa-button-quiet" })) : null);
      return;
    }
    const a = eq.ativo;
    const resumo = mostrarImpressora ? resumoDaImpressora(eq) : null;
    ficha.replaceChildren(el("div", { class: "mapa-ficha-titulo" }, el("h3", {}, eq.name), fechar),
      el("div", { class: "mapa-ficha-tags" }, papelTipo(a.dominio), el("span", { class: "mapa-tag" }, statusAtivo[a.status] || a.status)),
      pares([["Modelo", [a.marca, a.modelo].filter(Boolean).join(" ")], ["Hostname", a.hostname],
        ["Local", a.localizacao], ["Setor", departamento ? null : a.departamento],
        ["IP", editando ? eq.ip : null], ["Série", editando ? a.numero_serie : null],
        ["Posição", eq.pendente ? "Sem posição" : editando
          ? `X ${formatar(eq.x, 2)} · Z ${formatar(eq.z, 2)} m · ${formatar(eq.rotation, 0)}°` : "No mapa"]]),
      resumo,
      el("div", { class: "mapa-ficha-acoes" },
        editando && cenaPronta ? botao(eq.pendente ? "Posicionar" : "Mover no mapa", () => {
          ativarFerramenta(v => {
            v.setMode("top");
            v.startPlacement(eq.type, eq.id);
          });
          aviso.textContent = `Clique no piso para posicionar ${eq.name}.`;
        }, { classe: "mapa-button-primary" }) : null,
        editando ? botao("Coordenadas", () => configurarPosicao(eq)) : null,
        mostrarImpressora
          ? botao("Abrir monitoramento", () => abrirMonitoramentoImpressora(eq.id, eq.name, signal), { classe: "mapa-button-primary", icone: "printerMonitor" }) : null,
        editando && !eq.pendente ? botao("Retirar do mapa", () => {
          store.updateEquipment(eq.id, { pendente: true });
          aba = "pendentes";
          ativoSelecionado = eq.id;
          atualizar();
        }, { classe: "mapa-button-quiet" }) : null,
        !departamento && a.dominio === "ti" && state.podeModulo("ativos") ? botao("Ficha técnica", () => abrirDetalhes(a), { icone: "doc" }) : null));
  }

  function resumoDaImpressora(eq) {
    if (leituraSelecao?.id !== eq.id) {
      leituraSelecao = { id: eq.id, pedido: consultarSituacaoImpressora(eq.id) };
    }
    const estado = el("p", { role: "status", class: "muted" }, "Consultando por SNMP…");
    const dados = el("div");
    leituraSelecao.pedido.then(leitura => {
      if (!estado.isConnected || signal.aborted) return;
      const [tom, rotulo] = comunicacaoImpressora[leitura.comunicacao] || comunicacaoImpressora.falha_na_consulta;
      estado.replaceChildren(el("span", { class: "chip " + tom }, rotulo));
      dados.replaceChildren(...(leitura.suprimentos.length
        ? leitura.suprimentos.map(barraSuprimento)
        : [el("p", { class: "muted" }, "Níveis de suprimentos indisponíveis nesta leitura.")]));
    }).catch(e => {
      if (estado.isConnected && !signal.aborted) estado.textContent = e.message;
    });
    return el("section", { class: "mapa-impressora-resumo" }, el("h4", {}, "Suprimentos"), estado, dados);
  }

  function configurarPosicao(eq) {
    const x = numero(Number(eq.x.toFixed(3)), -500, 500, "any");
    const z = numero(Number(eq.z.toFixed(3)), -500, 500, "any");
    const rotacao = numero(eq.rotation, -360, 360, "any");
    abrirDialogo({
      title: `Posição de ${eq.name}`,
      body: el("div", { class: "mapa-dialogo-grid" }, campo("X (m)", x), campo("Z (m)", z), campo("Rotação (°)", rotacao)),
      actions: [{ label: "Cancelar" }, { label: "Aplicar", variant: "filled", onClick: close => {
        if (![x, z, rotacao].every(input => input.reportValidity())) return;
        aba = "mapa";
        store.updateEquipment(eq.id, { x: x.valueAsNumber, z: z.valueAsNumber, rotation: rotacao.valueAsNumber, pendente: false });
        close();
        selecionar(eq);
      } }],
    });
  }

  function configurarParede(wall) {
    const altura = numero(wall.height, 0.1, 30);
    const espessura = numero(wall.thickness, 0.05, 5);
    abrirDialogo({
      title: "Medidas da parede",
      body: el("div", { class: "mapa-dialogo-grid" }, campo("Altura (m)", altura), campo("Espessura (m)", espessura)),
      actions: [{ label: "Cancelar" }, { label: "Aplicar", variant: "filled", onClick: close => {
        if (![altura, espessura].every(input => input.reportValidity())) return;
        store.updateWall(wall.id, { height: altura.valueAsNumber, thickness: espessura.valueAsNumber });
        close();
      } }],
    });
  }

  function configurarImagem() {
    const arquivo = el("input", { type: "file", accept: "image/png,image/jpeg,image/webp", required: "" });
    const largura = numero(store.project.plan?.widthM || 30, 0.01, 1000, "any");
    const erro = el("p", { class: "mapa-erro", role: "alert" });
    const form = el("div", { class: "mapa-form" },
      campo("Arquivo PNG, JPEG ou WebP, até 12 MB", arquivo), campo("Largura real da imagem (m)", largura), erro);
    let aberto;
    const salvar = botao("Enviar planta", async () => {
      if (!arquivo.reportValidity() || !largura.reportValidity()) return;
      salvar.disabled = true;
      try {
        await store.flushSave();
        if (signal.aborted) return;
        const fd = new FormData();
        fd.append("arquivo", arquivo.files[0]);
        fd.append("largura_metros", largura.value);
        const resultado = await api.postForm(`/mapas/${store.plantaId}/imagem`, fd);
        if (signal.aborted) return;
        Object.assign(projeto, resultado);
        const url = await api.blob(`/mapas/${store.plantaId}/imagem`);
        if (signal.aborted) { URL.revokeObjectURL(url); return; }
        atualizarImagem(url);
        aberto.close();
        toast("Planta baixa atualizada");
      } catch (e) { erro.textContent = e.message; }
      finally { salvar.disabled = false; }
    }, { classe: "mapa-button-primary" });
    const remover = projeto.imagem ? botao("Retirar imagem", async () => {
      remover.disabled = true;
      try {
        await store.flushSave();
        if (signal.aborted) return;
        const resultado = await api.request("DELETE", `/mapas/${store.plantaId}/imagem`, {
          planta: store.plantaId, enfileirar: false,
        });
        if (signal.aborted) return;
        Object.assign(projeto, resultado);
        atualizarImagem(null);
        aberto.close();
        toast("Imagem retirada da planta");
      } catch (e) { erro.textContent = e.message; }
      finally { remover.disabled = false; }
    }, { classe: "mapa-button-quiet" }) : null;
    aberto = abrirDialogo({
      title: "Planta baixa",
      body: form,
      actions: [{ label: "Cancelar" }, ...(remover ? [{ elemento: remover }] : []), { elemento: salvar }],
    });
  }

  function atualizarImagem(url) {
    imagemAlterada(url);
    falhaImagem = "";
    restaurarMensagem();
    store.atualizarPlanta(projeto, url);
  }

  function calibracaoPronta(v, { worldDistance }) {
    const largura = numero(worldDistance, 0.01, 1000, "any");
    const erro = el("p", { class: "mapa-erro", role: "alert" });
    abrirDialogo({
      title: "Calibrar escala",
      body: el("div", { class: "mapa-form" }, campo("Distância real entre os pontos (m)", largura), erro),
      actions: [{ label: "Cancelar", onClick: close => { v.cancelCalibration(); close(); } },
        { label: "Aplicar escala", variant: "filled", onClick: close => {
          if (!largura.reportValidity()) return;
          try { v.applyCalibration(largura.valueAsNumber); close(); }
          catch (e) { erro.textContent = e.message; }
        } }],
    });
  }

  function ligarViewer(v) {
    cenaPronta = true;
    desinscrever.push(
      v.on("selection", ({ kind, id }) => {
        ativoSelecionado = kind === "equipment" ? id : null;
        paredeSelecionada = kind === "wall" ? id : null;
        if (ativoSelecionado) aba = "mapa";
        atualizar();
      }),
      v.on("placed", eq => { aba = "mapa"; ativoSelecionado = eq.id; atualizar(); }),
      v.on("modechange", atualizarFerramentas),
      v.on("toolchange", ({ tool }) => {
        atualizarFerramentas();
        if (tool === "measure") aviso.textContent = "Clique em dois pontos para medir a distância.";
        if (tool === "wall") aviso.textContent = "Clique nos vértices e use Concluir parede.";
        if (tool === "calibrate") aviso.textContent = "Marque dois pontos com distância real conhecida.";
      }),
      v.on("wall:point", ({ count }) => { aviso.textContent = `${count} ponto(s) marcado(s).`; }),
      v.on("wall:added", wall => { v.select("wall", wall.id); }),
      v.on("calibration:ready", dados => calibracaoPronta(v, dados)),
      v.on("measure:add", ({ distance }) => {
        aviso.textContent = `Distância medida · ${formatar(distance, 2)} m`;
        limparMedidas.hidden = false;
      }),
      v.on("pointer", ({ x, z }) => { coordenada.textContent = `X ${formatar(x, 2)}  Z ${formatar(z, 2)} m`; }),
      v.on("error", ({ message }) => { aviso.textContent = message; }),
    );
    atualizar();
  }

  atualizar();
  return { viewport, canvas, ligarViewer };
}

function pontoTipo(tipo) {
  return el("span", { class: `mapa-ponto ${tipo === "impressora" ? "impressora" : "ti"}` });
}

function papelTipo(tipo) {
  return el("span", { class: "mapa-tag" }, pontoTipo(tipo), tipoAtivo[tipo] || tipo);
}

function botaoAtivo(eq, selecionado, acao) {
  const a = eq.ativo;
  return el("button", { type: "button", class: "mapa-ativo", "aria-pressed": String(selecionado), onclick: acao },
    el("span", { class: `mapa-ativo-icone ${a.dominio === "impressora" ? "impressora" : "ti"}`,
      html: icon(a.dominio === "impressora" ? "print" : "ativos", 19) }),
    el("span", { class: "mapa-ativo-texto" }, el("strong", {}, eq.name),
      el("small", {}, a.hostname || a.modelo || a.localizacao || tipoAtivo[a.dominio])),
    el("span", { class: "mapa-ativo-seta", html: icon("chevR", 15) }));
}

function pares(campos) {
  return el("dl", { class: "mapa-pares" }, ...campos.filter(([, valor]) => valor).map(([rotulo, valor]) =>
    el("div", {}, el("dt", {}, rotulo), el("dd", {}, valor))));
}
