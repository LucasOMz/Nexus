import { api } from "../api.js";
import { state } from "../state.js";
import { el, toast } from "../ui.js";

const rota = "/admin/termo-entrega";
const tipos = { leitura: "Aceite de leitura", texto: "Texto livre", matricula: "Matrícula",
  nome: "Nome do colaborador", patrimonio: "Patrimônio do equipamento", data: "Data", assinatura: "Assinatura" };

function input(rotulo, atributos, ...extras) {
  const campo = el("input", atributos);
  return [el("label", { class: "field" }, rotulo, campo, ...extras), campo];
}

export async function renderTermoEntrega(root) {
  root.replaceChildren(el("p", { role: "status" }, "Carregando termo de entrega…"));
  let config;
  try {
    ({ modelo: config } = await api.get(rota));
  } catch (erro) {
    root.replaceChildren(el("p", { role: "alert" }, erro.message),
      el("button", { class: "btn tonal", onclick: () => renderTermoEntrega(root) }, "Tentar novamente"));
    return;
  }
  const campos = (config?.campos || []).map(campo => ({ ...campo }));
  let pagina = 1, total = config?.paginas.length || 0, selecionado = null;
  let arquivo = null, src = "", revisao = 0;
  const [campoNome, nome] = input("Nome do modelo", { value: config?.nome || "Termo de entrega", required: true, maxlength: 120 });
  const [campoUrl, url] = input("Endereço HTTPS do Nexus", { type: "url", value: config?.url_publica || "", required: true,
    placeholder: "https://nexus.empresa.com" }, el("small", { class: "muted" }, "É o endereço que o colaborador receberá por e-mail."));
  const [campoPrazo, prazo] = input("Validade do link em horas", { type: "number", min: 1, max: 720, step: 1,
    value: config?.prazo_horas || 72, required: true });
  const [campoArquivo, arquivoInput] = input("PDF do termo", { type: "file", accept: "application/pdf,.pdf" });
  const exigir = el("input", { type: "checkbox", checked: config?.exigir_agente ?? false });
  const ret = el("p", { role: "status", class: "muted" });
  const imagem = el("img", { alt: "Prévia da página do termo" });
  const marcadores = el("div", { class: "termo-marcadores" });
  const folha = el("div", { class: "termo-folha", hidden: true }, imagem, marcadores);
  const legenda = el("span", { role: "status" });
  const anterior = el("button", { type: "button", class: "btn text", onclick: () => visualizar(pagina - 1) }, "Anterior");
  const proxima = el("button", { type: "button", class: "btn text", onclick: () => visualizar(pagina + 1) }, "Próxima");
  const lista = el("select", { "aria-label": "Campos desta página" });
  const tipo = el("select", { "aria-label": "Tipo do campo" },
    ...Object.entries(tipos).map(([valor, rotulo]) => el("option", { value: valor }, rotulo)));
  const editar = el("div");
  const adicionar = el("button", { type: "button", class: "btn tonal" }, "Adicionar campo");
  const guardar = el("button", { type: "submit", class: "btn filled" }, "Salvar modelo");

  function desenharMarcadores() {
    marcadores.replaceChildren(...campos.filter(c => c.pagina === pagina).map(c =>
      el("button", { type: "button", class: "termo-marca" + (c.id === selecionado ? " ativa" : ""),
        style: `left:${c.x}%;top:${c.y}%;width:${c.largura}%;height:${c.altura}%`,
        title: c.rotulo, onclick: (evento) => { evento.stopPropagation(); selecionado = c.id; desenhar(); } }, c.rotulo)));
  }

  function desenhar() {
    const naPagina = campos.filter(c => c.pagina === pagina);
    const atual = naPagina.find(c => c.id === selecionado);
    legenda.textContent = total ? `Página ${pagina} de ${total}` : "Importe o PDF para posicionar os campos.";
    anterior.disabled = pagina <= 1;
    proxima.disabled = pagina >= total;
    adicionar.disabled = !total;
    lista.replaceChildren(el("option", { value: "" }, "Selecione um campo"),
      ...naPagina.map(c => el("option", { value: c.id }, c.rotulo)));
    lista.value = atual?.id || "";
    lista.disabled = !naPagina.length;
    desenharMarcadores();
    editar.replaceChildren();
    if (!atual) return;
    const [campoRotulo, rotulo] = input("Rótulo do campo", { value: atual.rotulo, maxlength: 85 });
    rotulo.onchange = () => { atual.rotulo = rotulo.value.trim() || tipos[atual.tipo]; desenhar(); };
    const posicoes = [["x", "Distância da esquerda (%)"], ["y", "Distância do topo (%)"],
      ["largura", "Largura (%)"], ["altura", "Altura (%)"]].map(([chave, label]) => {
      const [campo, numero] = input(label, { type: "number", min: 0, max: 100, step: 0.1, value: atual[chave] });
      numero.onchange = () => {
        if (!Number.isFinite(numero.valueAsNumber)) return;
        const valor = numero.valueAsNumber;
        const fim = { x: 100 - atual.largura, y: 100 - atual.altura, largura: 100 - atual.x, altura: 100 - atual.y };
        atual[chave] = Math.max(chave === "largura" || chave === "altura" ? 1 : 0, Math.min(fim[chave], valor));
        numero.value = atual[chave];
        desenharMarcadores();
      };
      return campo;
    });
    const obrigatorio = el("input", { type: "checkbox", checked: atual.obrigatorio,
      onchange: e => { atual.obrigatorio = e.target.checked; } });
    editar.append(campoRotulo, el("div", { class: "termo-coordenadas" }, ...posicoes),
      el("label", { class: "row termo-opcao" }, obrigatorio, "Campo obrigatório"),
      el("button", { type: "button", class: "btn text", onclick: () => {
        campos.splice(campos.indexOf(atual), 1); selecionado = null; desenhar();
      } }, "Remover campo"));
  }

  async function visualizar(novaPagina) {
    if (!arquivo && !total) { desenhar(); return; }
    const pedido = ++revisao;
    ret.textContent = "Carregando página…";
    folha.hidden = true;
    adicionar.disabled = true;
    try {
      let urlImagem, paginas = total;
      if (arquivo) {
        const dados = new FormData();
        dados.append("arquivo", arquivo);
        const res = await fetch(`${api.base}${rota}/previa?pagina=${novaPagina}`, {
          method: "POST", headers: { Authorization: "Bearer " + state.access }, body: dados,
        });
        if (!res.ok) throw new Error((await res.json().catch(() => null))?.detail || "Não foi possível abrir o PDF.");
        paginas = Number(res.headers.get("X-Total-Paginas"));
        urlImagem = URL.createObjectURL(await res.blob());
      } else {
        urlImagem = await api.blob(`${rota}/pagina/${novaPagina}`);
      }
      if (pedido !== revisao || !root.isConnected) { URL.revokeObjectURL(urlImagem); return; }
      const anteriorSrc = src;
      src = urlImagem;
      imagem.src = urlImagem;
      if (anteriorSrc) URL.revokeObjectURL(anteriorSrc);
      total = paginas;
      pagina = novaPagina;
      selecionado = null;
      folha.hidden = false;
      ret.textContent = "";
    } catch (erro) {
      if (pedido === revisao) ret.textContent = erro.message;
    } finally {
      if (pedido === revisao) desenhar();
    }
  }

  lista.onchange = () => { selecionado = lista.value; desenhar(); };
  arquivoInput.onchange = () => {
    arquivo = arquivoInput.files[0] || null;
    total = config?.paginas.length || 0;
    visualizar(1);
  };
  adicionar.onclick = () => {
    if (campos.length >= 80) { ret.textContent = "O modelo aceita até 80 campos."; return; }
    const id = "campo-" + Date.now() + "-" + campos.length;
    campos.push({ id, tipo: tipo.value, rotulo: tipos[tipo.value], pagina, x: 12, y: 12, largura: 28, altura: 5, obrigatorio: true });
    selecionado = id;
    desenhar();
  };
  folha.onclick = (evento) => {
    const atual = campos.find(c => c.id === selecionado);
    if (!atual) return;
    const rect = folha.getBoundingClientRect();
    atual.x = Math.max(0, Math.min(100 - atual.largura, Math.round(1000 * (evento.clientX - rect.left) / rect.width) / 10));
    atual.y = Math.max(0, Math.min(100 - atual.altura, Math.round(1000 * (evento.clientY - rect.top) / rect.height) / 10));
    desenhar();
  };
  const form = el("form", { class: "termo-editor" },
    el("section", { class: "card" }, el("h2", { class: "section-title" }, "Modelo do termo"), campoNome, campoUrl,
      campoPrazo, campoArquivo, el("label", { class: "row termo-opcao" }, exigir, "Exigir confirmação pelo Agente Nexus"), guardar, ret),
    el("section", { class: "card" }, el("h2", { class: "section-title" }, "Campos e posição"),
      el("p", { class: "muted" }, "Adicione um campo, selecione-o e clique no PDF para posicionar."),
      el("div", { class: "row wrap termo-adicionar" }, tipo, adicionar), el("div", { class: "field" }, lista),
      el("div", { class: "row wrap" }, anterior, legenda, proxima), folha, editar));
  form.onsubmit = async (evento) => {
    evento.preventDefault();
    if (guardar.disabled) return;
    guardar.disabled = true;
    ret.textContent = "Salvando modelo…";
    const dados = new FormData();
    dados.append("modelo_base", String(config?.id || 0));
    dados.append("configuracao", JSON.stringify({ nome: nome.value, url_publica: url.value, prazo_horas: prazo.valueAsNumber,
      exigir_agente: exigir.checked, campos }));
    if (arquivo) dados.append("arquivo", arquivo);
    try {
      config = await api.form("PUT", rota, dados);
      arquivo = null;
      arquivoInput.value = "";
      toast("Modelo de termo salvo");
      ret.textContent = "Modelo salvo. Novos envios usarão esta versão.";
    } catch (erro) {
      ret.textContent = erro.message;
    } finally {
      guardar.disabled = false;
    }
  };
  root.replaceChildren(form);
  await visualizar(1);
}
