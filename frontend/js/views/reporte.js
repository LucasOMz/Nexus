/**
 * Reporte de Erro.
 *
 * Qualquer usuário pode descrever o problema e anexar um print. A lista do que
 * foi reportado aparece **somente para o administrador**.
 *
 * Recurso temporário: se o servidor responder `ativo: false`, a tela avisa em
 * vez de mostrar o formulário.
 *
 * @module views/reporte
 */
import { api } from "../api.js";
import { state } from "../state.js";
import { el, icon, toast, dialog, fmtDate, emptyState, mostrarErro } from "../ui.js";

const STATUS_ROTULO = { aberto: "Aberto", em_analise: "Em análise", resolvido: "Resolvido", descartado: "Descartado" };
// Cor da etiqueta conforme a situação definida pelo administrador.
const STATUS_CLASSE = { aberto: "aviso", em_analise: "aviso", resolvido: "ok", descartado: "" };

/** Explicação curta de cada situação, para o autor entender o andamento. */
const STATUS_DICA = {
  aberto: "Recebido. A equipe de TI ainda não analisou.",
  em_analise: "A equipe de TI está verificando o problema.",
  resolvido: "O problema foi corrigido.",
  descartado: "Não foi considerado um problema (ou não pôde ser reproduzido).",
};

/** Formulário de envio — visível para todos. */
function abaFormulario(root) {
  const titulo = el("input", { placeholder: "Resuma o problema em uma linha", maxlength: "200" });
  const tela = el("input", { placeholder: "Em qual tela aconteceu? (ex.: Ativos, Leitura)" });
  const descricao = el("textarea", {
    placeholder: "Descreva o que você fez, o que esperava e o que aconteceu.",
    rows: "6",
  });
  const arquivo = el("input", { type: "file", accept: "image/*" });
  const previa = el("div", { class: "reporte-previa hidden" });

  arquivo.addEventListener("change", () => {
    previa.innerHTML = "";
    const f = arquivo.files && arquivo.files[0];
    if (!f) { previa.classList.add("hidden"); return; }
    const url = URL.createObjectURL(f);
    previa.append(el("img", { src: url, alt: "Print do erro" }));
    previa.append(el("span", { class: "muted" }, `${f.name} — ${(f.size / 1024).toFixed(0)} KB`));
    previa.classList.remove("hidden");
  });

  const botao = el("button", {
    class: "btn filled",
    disabled: true,
    onclick: async () => {
      const dados = new FormData();
      dados.append("titulo", titulo.value.trim());
      dados.append("descricao", descricao.value.trim());
      if (tela.value.trim()) dados.append("tela", tela.value.trim());
      const f = arquivo.files && arquivo.files[0];
      if (f) dados.append("arquivo", f);

      botao.disabled = true;
      try {
        await api.postForm("/reportes", dados);
        toast("Reporte enviado. Obrigado por avisar!");
        root.querySelector("#reporte-corpo").innerHTML = "";
        root.querySelector("#reporte-corpo").append(cartaoEnviado(root));
      } catch (e) {
        mostrarErro(e, "enviar o reporte");
        botao.disabled = false;
      }
    },
  }, "Enviar reporte");

  const validar = () => {
    botao.disabled = titulo.value.trim().length < 3 || descricao.value.trim().length < 5;
  };
  titulo.addEventListener("input", validar);
  descricao.addEventListener("input", validar);

  return el("div", { class: "card" },
    el("h3", { style: "margin:0 0 4px;font-size:16px" }, "Reportar um erro"),
    el("p", { class: "muted", style: "margin:0 0 16px;font-size:13px" },
      "Encontrou algo errado? Descreva abaixo e, se puder, anexe um print da tela. "
      + "Isso ajuda muito a identificar o problema."),
    el("div", { class: "field" }, el("label", {}, "Resumo *"), titulo),
    el("div", { class: "field" }, el("label", {}, "Tela"), tela),
    el("div", { class: "field" }, el("label", {}, "Descrição *"), descricao),
    el("div", { class: "field" }, el("label", {}, "Print da tela (opcional)"), arquivo, previa),
    el("div", { class: "row", style: "justify-content:flex-end;margin-top:14px" }, botao),
  );
}

function cartaoEnviado(root) {
  return el("div", { class: "card", style: "text-align:center" },
    el("div", { class: "kpi-icon", style: "margin:0 auto 10px", html: icon("check", 32) }),
    el("h3", { style: "margin:0 0 6px;font-size:17px" }, "Reporte enviado"),
    el("p", { class: "muted", style: "margin:0 auto 16px;max-width:420px" },
      "Obrigado! O administrador vai receber o seu relato e o print, se você anexou."),
    el("button", {
      class: "btn tonal small",
      onclick: () => {
        const corpo = root.querySelector("#reporte-corpo");
        corpo.innerHTML = "";
        corpo.append(abaFormulario(root));
      },
    }, "Enviar outro"),
  );
}

/** Os reportes do próprio usuário, com a situação definida pelo administrador. */
function abaMeus(root, irParaEnviar) {
  const caixa = el("div", {});
  const resumo = el("span", { class: "muted", style: "font-size:13px" });

  async function carregar() {
    caixa.innerHTML = "";
    try {
      const dados = await api.get("/reportes/meus");
      resumo.textContent = dados.total
        ? `${dados.total} reporte(s) enviado(s)`
          + Object.entries(dados.por_status || {}).filter(([, n]) => n)
              .map(([k, n]) => ` · ${STATUS_ROTULO[k] || k}: ${n}`).join("")
        : "";

      if (!dados.itens.length) {
        caixa.append(el("div", { class: "card", style: "text-align:center" },
          el("p", { class: "muted", style: "margin:0 0 14px" },
            "Você ainda não enviou nenhum reporte."),
          el("button", { class: "btn tonal small", onclick: irParaEnviar }, "Reportar um erro"),
        ));
        return;
      }

      dados.itens.forEach((r) => {
        caixa.append(el("div", { class: "card reporte-item" },
          el("div", { class: "row between", style: "flex-wrap:wrap;gap:8px" },
            el("div", {},
              el("strong", {}, r.titulo),
              el("div", { class: "muted", style: "font-size:12.5px" },
                `${fmtDate(r.criado_em, true)}${r.tela ? ` · tela: ${r.tela}` : ""}`),
            ),
            el("span", { class: `badge ${STATUS_CLASSE[r.status] || ""}` }, r.status_rotulo),
          ),
          el("p", { style: "margin:8px 0 0;font-size:13px" }, STATUS_DICA[r.status] || ""),
          el("p", { class: "muted", style: "white-space:pre-wrap;margin:10px 0 0;font-size:13px" },
            r.descricao),
          r.tem_imagem
            ? el("div", { style: "margin-top:10px" },
                el("button", {
                  class: "btn outlined small",
                  onclick: () => abrirPrint(r),
                  html: icon("image", 16) + " Ver o print que enviei",
                }))
            : null,
        ));
      });
    } catch (e) {
      mostrarErro(e, "carregar os seus reportes");
    }
  }

  carregar();

  return el("div", {},
    el("div", { class: "card" },
      el("h3", { style: "margin:0 0 4px;font-size:16px" }, "Meus reports"),
      el("p", { class: "muted", style: "margin:0 0 6px;font-size:13px" },
        "Acompanhe aqui a situação de cada problema que você reportou. "
        + "A situação é atualizada pela equipe de TI."),
      resumo,
    ),
    caixa,
  );
}

/** Lista dos reportes — somente administrador. */
function abaRecebidos(root) {
  const caixa = el("div", {});
  const filtro = el("select", { class: "chip" },
    el("option", { value: "" }, "Todos"),
    ...Object.entries(STATUS_ROTULO).map(([v, l]) => el("option", { value: v }, l)),
  );
  const resumo = el("span", { class: "muted", style: "font-size:13px" });

  async function carregar() {
    caixa.innerHTML = "";
    try {
      const dados = await api.get("/reportes", filtro.value ? { status: filtro.value } : {});
      resumo.textContent = `${dados.total} reporte(s)`
        + Object.entries(dados.por_status || {}).filter(([, n]) => n).map(([k, n]) => ` · ${STATUS_ROTULO[k] || k}: ${n}`).join("");
      if (!dados.itens.length) {
        caixa.append(emptyState("check", "Nada por aqui", "Nenhum reporte com esse filtro."));
        return;
      }
      dados.itens.forEach((r) => caixa.append(linhaReporte(r, carregar)));
    } catch (e) {
      mostrarErro(e, "carregar os reportes");
    }
  }

  filtro.addEventListener("change", carregar);
  carregar();

  return el("div", {},
    el("div", { class: "card" },
      el("div", { class: "row between", style: "flex-wrap:wrap;gap:10px" },
        el("div", {},
          el("h3", { style: "margin:0 0 4px;font-size:16px" }, "Reportes recebidos"),
          resumo,
        ),
        el("div", { class: "row", style: "gap:8px" }, el("span", { class: "muted", style: "font-size:12.5px" }, "Situação:"), filtro),
      ),
    ),
    caixa,
  );
}

function linhaReporte(r, recarregar) {
  const classe = r.status === "aberto" ? "aviso" : r.status === "resolvido" ? "ok" : "";
  const cartao = el("div", { class: "card reporte-item" },
    el("div", { class: "row between", style: "flex-wrap:wrap;gap:8px" },
      el("div", {},
        el("strong", {}, r.titulo),
        el("div", { class: "muted", style: "font-size:12.5px" },
          // O `+` precisa ficar DENTRO do el(): fora dele, concatenaria o
          // próprio elemento DOM e a tela mostraria "[object HTMLDivElement]".
          `${r.usuario_nome || "—"}${r.usuario_email ? ` (${r.usuario_email})` : ""}`
          + `${r.planta_sigla ? ` · ${r.planta_sigla}` : ""}`
          + ` · ${fmtDate(r.criado_em, true)}`
          + `${r.tela ? ` · tela: ${r.tela}` : ""}`),
      ),
      el("span", { class: `badge ${classe}` }, r.status_rotulo),
    ),
    el("p", { style: "white-space:pre-wrap;margin:10px 0 0;font-size:13.5px" }, r.descricao),
    r.observacao_admin
      ? el("p", { class: "muted", style: "margin:10px 0 0;font-size:13px;border-left:3px solid var(--md-sys-color-outline-variant);padding-left:10px" },
          `Anotação: ${r.observacao_admin}`)
      : null,
    el("div", { class: "row", style: "gap:8px;margin-top:12px" },
      r.tem_imagem
        ? el("button", {
            class: "btn outlined small",
            onclick: () => abrirPrint(r),
            html: icon("image", 16) + " Ver print",
          })
        : el("span", { class: "muted", style: "font-size:12.5px" }, "Sem print"),
      el("span", { class: "spacer" }),
      el("button", { class: "btn text small", onclick: () => anotar(r, recarregar) }, "Anotar"),
      el("button", {
        class: "btn text small",
        onclick: async () => {
          if (!confirm(`Excluir o reporte "${r.titulo}"?`)) return;
          try { await api.del(`/reportes/${r.id}`); toast("Reporte excluído"); recarregar(); }
          catch (e) { mostrarErro(e, "excluir o reporte"); }
        },
        html: icon("trash", 16),
      }),
    ),
  );
  return cartao;
}

/**
 * Abre o print do reporte.
 *
 * A imagem é buscada COM o token e vira uma URL local — usar o endereço da API
 * direto no `<img>` daria 401, porque o navegador não manda o cabeçalho de
 * autorização nesse tipo de requisição.
 */
async function abrirPrint(r) {
  const caixa = el("div", { style: "text-align:center" }, el("p", { class: "muted" }, "Carregando o print…"));
  let urlBlob = null;

  dialog({
    title: r.titulo,
    wide: true,
    body: caixa,
    actions: [
      { label: "Fechar", variant: "text" },
      { label: "Abrir em nova aba", variant: "outlined", onClick: () => {
        if (!urlBlob) { toast("O print ainda está carregando"); return; }
        window.open(urlBlob, "_blank");
      } },
    ],
  });

  try {
    urlBlob = await api.blob(`/reportes/${r.id}/imagem`);
    caixa.innerHTML = "";
    caixa.append(el("img", {
      src: urlBlob, alt: "Print do erro",
      style: "width:100%;border-radius:8px;border:1px solid var(--md-sys-color-outline-variant)",
    }));
  } catch (e) {
    caixa.innerHTML = "";
    caixa.append(el("p", { class: "text-error" }, `Não foi possível abrir o print: ${e.message}`));
  }
}

function anotar(r, recarregar) {
  const situacao = el("select", {},
    ...Object.entries(STATUS_ROTULO).map(([v, l]) => el("option", { value: v, ...(r.status === v ? { selected: "" } : {}) }, l)));
  const obs = el("textarea", { rows: "3", placeholder: "O que foi feito / o que falta" , value: r.observacao_admin || "" });

  dialog({
    title: `Reporte #${r.id}`,
    body: el("div", {},
      el("div", { class: "field" }, el("label", {}, "Situação"), situacao),
      el("div", { class: "field" }, el("label", {}, "Anotação interna"), obs),
    ),
    actions: [
      { label: "Cancelar", variant: "text" },
      { label: "Salvar", variant: "filled", onClick: async (close) => {
        try {
          const dados = new FormData();
          dados.append("status", situacao.value);
          dados.append("observacao_admin", obs.value);
          await api.patchForm(`/reportes/${r.id}`, dados);
          close();
          toast("Reporte atualizado");
          recarregar();
        } catch (e) { mostrarErro(e, "salvar o reporte"); }
      } },
    ],
  });
}

export async function renderReporte(root) {
  root.innerHTML = "";

  const disp = await api.get("/reportes/disponivel").catch(() => ({ ativo: false }));
  if (!disp.ativo) {
    root.append(el("div", { class: "card" },
      el("h1", { class: "page-title", style: "font-size:20px" }, "Reporte de Erro"),
      el("p", { class: "muted" },
        "Este canal foi desativado. Se precisar reportar algo, fale com a equipe de TI."),
    ));
    return;
  }

  const abas = [
    { chave: "enviar", rotulo: "Enviar reporte" },
    // Qualquer usuário acompanha o que ele mesmo reportou.
    { chave: "meus", rotulo: "Meus reports" },
  ];
  if (state.isAdmin) abas.push({ chave: "recebidos", rotulo: "Reportes recebidos" });

  const corpo = el("div", { id: "reporte-corpo" });
  const barra = el("div", { class: "row", style: "gap:6px;margin-bottom:14px" });
  let ativa = "enviar";

  function trocar(chave) {
    ativa = chave;
    [...barra.children].forEach((b) => b.classList.toggle("selected", b.dataset.chave === chave));
    corpo.innerHTML = "";
    if (chave === "recebidos") corpo.append(abaRecebidos(root));
    else if (chave === "meus") corpo.append(abaMeus(root, () => trocar("enviar")));
    else corpo.append(abaFormulario(root));
  }

  abas.forEach((a) => {
    const b = el("button", {
      class: "chip" + (a.chave === ativa ? " selected" : ""),
      onclick: () => trocar(a.chave),
    }, a.rotulo);
    b.dataset.chave = a.chave;
    barra.append(b);
  });

  root.append(
    el("h1", { class: "page-title" }, "Reporte de Erro"),
    barra,
    corpo,
  );
  trocar("enviar");
}
