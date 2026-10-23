/**
 * Importação de ativos por CSV — as três etapas.
 *
 * ## Por que três, e não um botão de "enviar"
 *
 * Importação é a operação mais destrutiva do sistema: um arquivo com 500
 * linhas erradas cria 500 ativos errados de uma vez, e desfazer à mão é pior
 * que não ter feito.
 *
 * ```
 * 1. MODELO      as colunas, o que é obrigatório, e o arquivo para baixar
 * 2. PRÉVIA      o que será importado — com foto, e o que será criado
 * 3. CONFIRMAÇÃO o número final, e a lembrança de que haverá backup
 * ```
 *
 * A etapa 2 é a que importa: ela deixa a decisão ser tomada **olhando o
 * resultado**, e não imaginando. Quem vê "348 válidas, 4 inválidas, 3
 * categorias serão criadas" decide diferente de quem só vê um botão.
 *
 * ## A prévia não grava
 *
 * O backend lê e valida sem tocar no banco. Só a etapa 3 grava — e grava com
 * backup automático antes.
 *
 * @module views/importar_ativos
 */
import { api } from "../api.js";
import { state } from "../state.js";
import { el, icon, toast, dialog, mostrarErro } from "../ui.js";
import { fotoUrl } from "./ativos.js";

/**
 * Abre o assistente. Chamado pelo botão da tela de ativos, visível apenas
 * para administrador.
 */
export async function importarAtivos(aoTerminar) {
  const caixa = el("div", {});
  const estado = { arquivo: null, analise: null };

  const dlg = dialog({
    title: "Importar ativos por CSV",
    wide: true,
    body: caixa,
    actions: [],
  });

  const desenhar = () => {
    caixa.innerHTML = "";
    if (estado.analise) {
      caixa.append(previa(estado.analise, estado.arquivo, voltar, confirmar));
    } else {
      caixa.append(etapaModelo(escolher));
    }
  };

  const voltar = () => { estado.analise = null; desenhar(); };

  function escolher(arquivo) {
    estado.arquivo = arquivo;
    analisar(arquivo).then((a) => { estado.analise = a; desenhar(); });
  }

  async function analisar(arquivo) {
    const corpo = new FormData();
    corpo.append("arquivo", arquivo);
    return api.postForm("/ativos/importar/analisar", corpo);
  }

  async function confirmar() {
    const corpo = new FormData();
    corpo.append("arquivo", estado.arquivo);
    try {
      const r = await api.postForm("/ativos/importar/confirmar", corpo);
      toast(r.mensagem || `${r.criados} ativo(s) importado(s)`);
      if (dlg?.close) dlg.close();
      if (aoTerminar) aoTerminar();
    } catch (e) {
      // 409 traz a razão em `detail` — geralmente "nada válido" ou "sem
      // backup". Mostrar isso é melhor que um "erro" genérico.
      mostrarErro(e);
    }
  }

  desenhar();
}

// ---------------------------------------------------------------------------
// Etapa 1 — as colunas e o modelo
// ---------------------------------------------------------------------------
function etapaModelo(aoEscolher) {
  const lista = el("div", { class: "imp-colunas" },
    el("p", { class: "muted" }, "Carregando as colunas…"));

  // O inventário vai junto: as fichas técnicas de TI e de impressora são
  // diferentes, e mostrar as duas famílias de colunas na mesma tela dava a
  // impressão de que o inventário era um só.
  api.get("/ativos/importar/colunas", { dominio: state.dominio }).then((d) => {
    lista.innerHTML = "";
    lista.append(
      el("p", { class: "muted", style: "margin:0 0 10px" },
        "A planilha precisa ter uma linha de cabeçalho com estes nomes. "
        + "A ordem não importa; colunas a mais são ignoradas."),
      el("div", { class: "imp-tabela" },
        el("div", { class: "imp-linha imp-cabecalho" },
          el("span", {}, "Coluna"),
          el("span", {}, "Obrigatória"),
          el("span", {}, "O que preencher")),
        ...d.colunas.map((c) => el("div", { class: "imp-linha" },
          el("code", {}, c.nome),
          el("span", { class: c.obrigatoria ? "chip erro" : "chip" },
            c.obrigatoria ? "sim" : "opcional"),
          el("span", { class: "muted" }, c.descricao)))),
    );
  }).catch((e) => {
    lista.innerHTML = "";
    lista.append(el("p", { class: "text-error" }, e.message));
  });

  // --- anexo ------------------------------------------------------------
  const entrada = el("input", { type: "file", accept: ".csv,text/csv", style: "display:none" });
  entrada.addEventListener("change", () => {
    const f = entrada.files?.[0];
    if (f) aoEscolher(f);
  });

  const soltar = el("div", { class: "imp-soltar" },
    el("div", { html: icon("download", 30) }),
    el("b", {}, "Arraste o CSV aqui"),
    el("div", { class: "muted", style: "font-size:12.5px" },
      "ou clique para escolher o arquivo"),
    el("div", { class: "muted", style: "font-size:12px;margin-top:6px" },
      "No Excel: Salvar como → CSV UTF-8 (delimitado por vírgulas)."));
  soltar.addEventListener("click", () => entrada.click());
  soltar.addEventListener("dragover", (e) => { e.preventDefault(); soltar.classList.add("sobre"); });
  soltar.addEventListener("dragleave", () => soltar.classList.remove("sobre"));
  soltar.addEventListener("drop", (e) => {
    e.preventDefault();
    soltar.classList.remove("sobre");
    const f = e.dataTransfer?.files?.[0];
    if (f) aoEscolher(f);
  });

  return el("div", {},
    el("div", { class: "row between wrap", style: "gap:10px;align-items:center" },
      el("b", {}, "1. Como preencher a planilha"),
      el("button", { class: "btn tonal small", onclick: () => baixarModelo(),
        html: icon("download", 15) + " Baixar modelo" })),
    el("div", { style: "margin-top:10px" }, lista),
    el("div", { style: "margin-top:18px" },
      el("b", {}, "2. Anexe o arquivo"),
      el("div", { style: "margin-top:8px" }, soltar, entrada)),
  );
}

function baixarModelo() {
  // O download precisa do token, então não dá para usar um `<a href>` direto:
  // a rota exige administrador. Busca e entrega ao navegador.
  //
  // `api.blob` **já devolve a URL** do objeto criado — e não o `Blob`. Chamar
  // `URL.createObjectURL` de novo em cima dela falha com
  // "Overload resolution failed", porque uma string não é `Blob`.
  //
  // Os outros quatro lugares que usam `api.blob` já tratavam como URL
  // (`const url = await api.blob(...)`). Era só aqui que não.
  api.blob("/ativos/importar/modelo").then((url) => {
    const a = el("a", { href: url, download: "modelo-ativos.csv" });
    document.body.append(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  }).catch(mostrarErro);
}

// ---------------------------------------------------------------------------
// Etapa 2 — a prévia
// ---------------------------------------------------------------------------
function previa(a, arquivo, aoVoltar, aoConfirmar) {
  if (a.erro_geral) {
    return el("div", {},
      el("div", { class: "recado erro" },
        el("b", {}, "O arquivo não pôde ser lido"),
        el("div", { style: "margin-top:6px" }, a.erro_geral)),
      el("div", { class: "row", style: "gap:8px;margin-top:16px" },
        el("button", { class: "btn tonal", onclick: aoVoltar }, "Escolher outro arquivo")));
  }

  const validas = a.linhas.filter((l) => l.ok);
  const invalidas = a.linhas.filter((l) => !l.ok);
  const bloqueado = validas.length === 0;

  return el("div", {},
    el("div", { class: "row between wrap", style: "gap:10px;align-items:center" },
      el("div", {},
        el("b", {}, "Prévia do que será importado"),
        el("div", { class: "muted", style: "font-size:12.5px" }, arquivo?.name || "")),
      el("button", { class: "btn text small", onclick: aoVoltar }, "Trocar arquivo")),

    // --- números ---------------------------------------------------------
    el("div", { class: "resumo-numeros", style: "margin:14px 0" },
      numero(a.validas, "Serão importadas", a.validas > 0 ? "ok" : ""),
      numero(a.invalidas, "Com erro", a.invalidas > 0 ? "erro" : ""),
      numero(a.total, "Linhas no arquivo")),

    // --- o que será CRIADO -----------------------------------------------
    //
    // O aviso mais importante da tela: sem ele, quem importa descobre depois
    // que "Notbook" e "Notebook" viraram duas categorias.
    a.a_criar?.length
      ? el("div", { class: "recado info", style: "margin-bottom:14px" },
          el("b", {}, `${a.a_criar.length} cadastro(s) que ainda não existem serão criados:`),
          el("div", { style: "margin-top:6px" }, a.a_criar.join(" · ")),
          el("div", { class: "muted", style: "font-size:12px;margin-top:6px" },
            `Confira se não é erro de digitação — "Notbook" e "Notebook" virariam dois cadastros diferentes.`))
      : null,

    a.colunas_desconhecidas?.length
      ? el("p", { class: "muted", style: "font-size:12.5px;margin:0 0 10px" },
          `Colunas ignoradas por não serem reconhecidas: ${a.colunas_desconhecidas.join(", ")}`)
      : null,

    // --- linhas ----------------------------------------------------------
    el("div", { class: "imp-previas" },
      ...validas.slice(0, 100).map(cartaoPrevia),
      validas.length > 100
        ? el("p", { class: "muted", style: "margin:8px 0" },
            `… e mais ${validas.length - 100} linha(s) válida(s) não mostradas.`)
        : null),

    invalidas.length
      ? el("div", { style: "margin-top:14px" },
          el("b", { class: "text-error" }, `${invalidas.length} linha(s) NÃO serão importadas`),
          el("div", { class: "imp-previas", style: "margin-top:8px" },
            ...invalidas.slice(0, 50).map((l) => el("div", { class: "imp-previa imp-erro" },
              el("b", {}, `Linha ${l.numero}`),
              el("div", { class: "muted", style: "font-size:12.5px" },
                l.erros.join(" · "))))))
      : null,

    // --- confirmação -----------------------------------------------------
    el("div", { class: "recado aviso", style: "margin-top:18px" },
      el("b", {}, "3. Confirmar"),
      el("div", { style: "margin-top:6px" },
        "Um backup do banco é criado automaticamente antes de gravar. "
        + "Se algo sair errado, é por ele que se volta atrás.")),

    el("div", { class: "row", style: "gap:8px;margin-top:12px" },
      el("button", {
        class: "btn filled", disabled: bloqueado,
        onclick: () => {
          if (!window.confirm(
            `Importar ${a.validas} ativo(s)?\n\n`
            + "Um backup será criado antes. As linhas com erro serão ignoradas."
          )) return;
          aoConfirmar();
        },
      }, bloqueado ? "Nada válido para importar" : `Importar ${a.validas} ativo(s)`),
      el("button", { class: "btn text", onclick: aoVoltar }, "Cancelar")),
  );
}

function cartaoPrevia(l) {
  const foto = l.foto_id
    ? el("img", { class: "imp-foto", src: fotoUrl(l.foto_id), loading: "lazy",
        alt: `Foto ${l.foto_id}` })
    : el("div", { class: "imp-foto imp-sem-foto", html: icon("image", 18) });

  return el("div", { class: "imp-previa" },
    el("div", { class: "imp-previa-linha1" },
      el("span", { class: "chip" }, l.dominio || "—"),
      el("b", {}, l.patrimonio || "—"),
      el("span", { class: "muted", style: "font-size:12px" }, `linha ${l.numero}`)),
    el("div", { class: "imp-previa-corpo" },
      foto,
      el("div", { class: "muted", style: "font-size:12.5px;min-width:0" },
        [l.marca, l.modelo].filter(Boolean).join(" ") || "sem marca/modelo",
        l.valor ? el("div", {}, `R$ ${l.valor}`) : null,
        l.criar?.length
          ? el("div", { class: "text-aviso" }, `cria: ${l.criar.join(", ")}`)
          : null,
        l.avisos?.length
          ? el("div", { class: "muted" }, l.avisos.join(" · "))
          : null)),
  );
}

function numero(valor, rotulo, tom = "") {
  return el("div", { class: `numero ${tom}` },
    el("span", { class: "numero-valor" }, String(valor ?? 0)),
    el("span", { class: "numero-rotulo" }, rotulo));
}
