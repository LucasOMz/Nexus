/**
 * Certificado de descarte — emissão e impressão.
 *
 * ## Por que esta tela existe
 *
 * Dar baixa num ativo sem registro do destino é o buraco por onde o
 * patrimônio some. O certificado fecha isso: diz **o quê**, **por quê**,
 * **para onde foi** e **quem autorizou** — e carrega um selo que denuncia
 * alteração posterior.
 *
 * ## O formulário é montado pela política
 *
 * Cada motivo exige campos diferentes: venda pede nota fiscal, sucata pede
 * licença ambiental do receptor, perda pede número de ocorrência. A tela lê
 * `GET /descarte/motivos` e mostra só o que aquele motivo exige — em vez de
 * um formulário longo onde a pessoa não sabe o que é obrigatório.
 *
 * @module views/descarte
 */
import { api } from "../api.js";
import { ctx } from "../context.js";
import { el, icon, toast, dialog, mostrarErro } from "../ui.js";

/** Rótulos dos campos. O serviço valida por NOME; a tela mostra por rótulo. */
const ROTULO = {
  destinador_nome: "Nome do destinatário",
  destinador_documento: "Documento (CPF/CNPJ)",
  destinador_cnpj: "CNPJ do receptor",
  destinador_licenca: "Licença ambiental do receptor",
  documento_fiscal: "Documento fiscal (NF-e)",
  numero_ocorrencia: "Número da ocorrência",
  quantidade: "Quantidade",
  responsavel: "Responsável pelo descarte",
  valor: "Valor (R$)",
  observacoes: "Observações",
};

/** Dica por campo — o que ajuda a preencher sem errar. */
const DICA = {
  destinador_licenca: "Número da licença do receptor (PNRS Art. 33).",
  documento_fiscal: "Saída com nota fiscal: sem ela, o documento não vale.",
  numero_ocorrencia: "Boletim de ocorrência, laudo ou registro interno do sinistro.",
};

const ativo = { atual: null };
const escolhidos = {};

export async function renderDescarte(root) {
  ctx.setTitle("Certificado de descarte");
  ctx.setFab(null);
  root.innerHTML = "";

  let politica;
  try {
    politica = await api.get("/descarte/motivos");
  } catch (e) {
    root.append(el("p", { class: "text-error" }, e.message));
    return;
  }

  const busca = el("input", { placeholder: "Patrimônio, hostname, série, modelo…", autocomplete: "off" });
  const resultados = el("div", { class: "vinculo-lista", style: "display:none" });
  const resumoAtivo = el("div", { class: "ativo-escolhido oculto" });
  const campos = el("div", { class: "grade", style: "margin-top:14px" });
  const botao = el("button", { class: "btn filled", type: "button", disabled: "disabled" }, "Emitir certificado");

  const selMotivo = el("select", {},
    el("option", { value: "" }, "Escolha o motivo…"),
    ...politica.motivos.map((m) => el("option", { value: m.valor }, m.rotulo)));

  // --- Busca de ativo ---------------------------------------------------
  let timer = null;
  let geracao = 0;

  busca.addEventListener("input", () => {
    clearTimeout(timer);
    timer = setTimeout(async () => {
      const termo = busca.value.trim();
      if (termo.length < 2) { resultados.style.display = "none"; return; }
      const meu = ++geracao;
      try {
        const r = await api.get(`/ativos?search=${encodeURIComponent(termo)}&size=20`);
        if (meu !== geracao) return;
        pintarResultados(r.items || []);
      } catch { /* busca auxiliar */ }
    }, 220);
  });

  function pintarResultados(itens) {
    resultados.innerHTML = "";
    if (!itens.length) {
      resultados.append(el("p", { class: "muted" }, "Nada encontrado."));
    } else {
      for (const a of itens) {
        const b = el("button", { type: "button", class: "busca-item",
          onclick: () => escolherAtivo(a) },
          el("b", {}, a.patrimonio),
          el("span", { class: "busca-modelo" },
            [a.hostname, a.modelo, a.marca].filter(Boolean).join(" · ") || ""));
        resultados.append(b);
      }
    }
    resultados.style.display = "";
  }

  function escolherAtivo(a) {
    ativo.atual = a;
    resultados.style.display = "none";
    busca.value = a.patrimonio;
    resumoAtivo.classList.remove("oculto");
    resumoAtivo.innerHTML = "";
    resumoAtivo.append(
      el("b", {}, a.patrimonio),
      el("div", { class: "muted", style: "font-size:12.5px" },
        [a.hostname, a.modelo, a.marca, a.planta_sigla].filter(Boolean).join(" · ")),
    );
    atualizarBotao();
  }

  // --- Formulário por motivo --------------------------------------------
  selMotivo.addEventListener("change", montarCampos);

  function montarCampos() {
    const m = politica.motivos.find((x) => x.valor === selMotivo.value);
    campos.innerHTML = "";
    if (!m) { atualizarBotao(); return; }

    // Só os campos que ESTE motivo exige. Um formulário com tudo deixaria a
    // pessoa sem saber o que é obrigatório — e o servidor recusaria depois.
    for (const campo of m.exige) {
      campos.append(campoDe(campo, true));
    }
    // Os opcionais ficam à parte, para não competir com o obrigatório.
    if (m.valor === "venda" || m.valor === "doacao") campos.append(campoDe("valor", false));
    campos.append(campoDe("observacoes", false));

    campos.append(el("div", { class: "recado info", style: "grid-column:1/-1;margin:0" },
      el("b", {}, m.rotulo), ` — ${m.fundamento}.`));
    atualizarBotao();
  }

  function campoDe(chave, obrigatorio) {
    const entrada = chave === "observacoes"
      ? el("textarea", { rows: "2" })
      : el("input", { type: chave === "quantidade" ? "number" : "text" });
    entrada.addEventListener("input", () => { escolhidos[chave] = entrada.value; });
    escolhidos[chave] = chave === "quantidade" ? "1" : "";
    if (chave === "quantidade") entrada.value = "1";

    return el("div", { class: "field" },
      el("label", {}, ROTULO[chave] || chave, obrigatorio ? " *" : ""),
      entrada,
      DICA[chave] ? el("span", { class: "dica" }, DICA[chave]) : null);
  }

  function atualizarBotao() {
    botao.disabled = !(ativo.atual && selMotivo.value);
  }
  botao.addEventListener("click", emitir);

  async function emitir() {
    botao.disabled = true;
    botao.textContent = "Emitindo…";
    const corpo = { ativo_id: ativo.atual.id, motivo: selMotivo.value };
    for (const [k, v] of Object.entries(escolhidos)) {
      if (v !== "" && v !== undefined && v !== null) corpo[k] = v;
    }
    try {
      const r = await api.post("/descarte", corpo);
      mostrarCertificado(r);
    } catch (e) {
      // O servidor devolve TODAS as pendências de uma vez — mostrar só a
      // primeira obrigaria a descobrir o formulário errando.
      const detalhe = e.detalhe || e.detail;
      const pendencias = detalhe?.pendencias;
      if (pendencias?.length) {
        mostrarErro(new Error(
          `Faltam dados: ${pendencias.map((p) => ROTULO[p] || p).join(", ")}.`));
      } else {
        mostrarErro(e);
      }
    }
    botao.disabled = false;
    botao.textContent = "Emitir certificado";
  }

  root.append(
    el("h1", { class: "page-title" }, "Certificado de descarte"),
    el("p", { class: "muted", style: "margin:0 0 16px" },
      "Registra a baixa de um ativo com destino, fundamento e responsável. "
      + "O certificado carrega um selo que denuncia alteração posterior."),
    el("div", { class: "card" },
      el("div", { class: "field" }, el("label", {}, "Ativo *"), busca),
      resultados,
      resumoAtivo,
      el("div", { class: "field", style: "margin-top:14px" },
        el("label", {}, "Motivo *"), selMotivo),
      campos,
      el("div", { class: "row", style: "margin-top:16px" }, botao),
    ),
  );
}

/** O certificado emitido, com o texto pronto para imprimir. */
function mostrarCertificado(r) {
  const cert = r.certificado || {};
  dialog({
    title: `Certificado ${cert.numero || ""}`,
    wide: true,
    body: el("div", {},
      el("div", { class: r.conferido ? "recado ok" : "recado erro" },
        r.conferido
          ? "Selo conferido: o documento corresponde ao que o sistema registrou."
          : "ATENÇÃO: o selo não conferiu."),
      el("pre", { class: "certificado-texto" }, r.texto || ""),
    ),
    actions: [
      { label: "Fechar", variant: "text" },
      { label: "Imprimir", variant: "filled", onClick: () => imprimir(r.texto, cert.numero) },
    ],
  });
}

/**
 * Impressão em janela própria.
 *
 * Não usa `window.print()` na página: a tela tem barra lateral, cabeçalho e
 * botões — e o documento sairia com tudo isso. Uma janela só com o texto
 * imprime o certificado e mais nada.
 */
function imprimir(texto, numero) {
  const janela = window.open("", "_blank", "width=820,height=900");
  if (!janela) { toast("Permita janelas pop-up para imprimir"); return; }

  janela.document.write(`<!DOCTYPE html><html lang="pt-BR"><head>
    <meta charset="utf-8"><title>Certificado ${numero || ""}</title>
    <style>
      body { font-family: ui-monospace, "Courier New", monospace; font-size: 12px;
             line-height: 1.55; padding: 32px; white-space: pre-wrap; color: #111; }
      @media print { body { padding: 0; } }
    </style></head><body>${escapar(texto || "")}</body></html>`);
  janela.document.close();
  janela.focus();
  janela.print();
}

function escapar(s) {
  return String(s).replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));
}
