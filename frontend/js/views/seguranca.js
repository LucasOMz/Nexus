/**
 * Segurança da conta — cadastro e remoção da verificação em duas etapas.
 *
 * O ponto crítico desta tela é o **momento dos códigos de recuperação**: eles
 * aparecem UMA vez. Se a pessoa fechar sem guardar, e depois perder o celular,
 * ela perde o acesso à conta — e a saída seria pedir para um administrador
 * mexer no banco.
 *
 * Por isso a tela não deixa avançar sem uma confirmação explícita de que os
 * códigos foram guardados.
 *
 * @module views/seguranca
 */
import { api } from "../api.js";
import { state } from "../state.js";
import { ctx } from "../context.js";
import { el, icon, toast, dialog, confirmSheet, skeleton, mostrarErro } from "../ui.js";

export async function renderSeguranca(root) {
  ctx.setTitle("Segurança da conta");
  ctx.setFab(null);
  root.innerHTML = "";

  root.append(
    el("h1", { class: "page-title" }, "Segurança da conta"),
    el("p", { class: "muted", style: "margin:0 0 18px" },
      "A verificação em duas etapas protege o acesso mesmo que a senha seja descoberta."),
  );

  const caixa = el("div", {}, skeleton(3));
  root.append(caixa);
  await carregar(caixa, root);
}

async function carregar(caixa, root) {
  let d;
  try {
    d = await api.get("/mfa/situacao");
  } catch (e) {
    caixa.innerHTML = "";
    caixa.append(el("p", { class: "text-error" }, e.message));
    return;
  }

  caixa.innerHTML = "";
  caixa.append(d.ativo ? cartaoAtivo(d, root) : cartaoInativo(d, root));
}

function cartaoInativo(d, root) {
  return el("div", { class: "cartao-contagem" },
    el("div", { class: "row between wrap", style: "gap:10px" },
      el("b", { style: "font-size:15px" }, "Verificação em duas etapas"),
      el("span", { class: "chip aviso" }, "Desativada"),
    ),
    el("p", { class: "muted", style: "margin:10px 0 0" },
      "Ao entrar, além da senha, o sistema vai pedir um código de 6 dígitos "
      + "gerado por um aplicativo no seu celular."),
    d.exigido
      ? el("div", { class: "recado info", style: "margin-top:12px" },
          el("b", {}, "Recomendado para o seu perfil."),
          " Contas de administrador podem alterar permissões, apagar ativos e "
          + "restaurar backups — uma senha sozinha é pouca proteção.")
      : null,
    el("div", { class: "row", style: "margin-top:14px" },
      el("button", { class: "btn filled", onclick: () => iniciar(root),
        html: icon("check", 18) + " Ativar agora" }),
    ),
  );
}

function cartaoAtivo(d, root) {
  return el("div", { class: "cartao-contagem" },
    el("div", { class: "row between wrap", style: "gap:10px" },
      el("b", { style: "font-size:15px" }, "Verificação em duas etapas"),
      el("span", { class: "chip ok" }, "Ativada"),
    ),
    el("div", { class: "muted", style: "font-size:12.5px;margin-top:6px" },
      d.ativado_em ? `Ativada em ${new Date(d.ativado_em).toLocaleString("pt-BR")}` : ""),
    el("div", { class: "muted", style: "font-size:12.5px;margin-top:4px" },
      `${d.codigos_restantes} código(s) de recuperação não usados`),
    (d.codigos_restantes ?? 0) <= 2
      ? el("div", { class: "recado erro", style: "margin-top:12px" },
          "Restam poucos códigos de recuperação. Gere novos antes que acabem — "
          + "sem eles, perder o celular significa perder o acesso.")
      : null,
    el("div", { class: "row", style: "margin-top:14px" },
      el("button", { class: "btn text", onclick: () => desativar(root) }, "Desativar"),
    ),
  );
}

// ---------------------------------------------------------------------------
async function iniciar(root) {
  let dados;
  try {
    dados = await api.post("/mfa/iniciar", {});
  } catch (e) {
    return mostrarErro(e);
  }

  // O QR vem como imagem protegida: `<img src>` não manda o token, então
  // buscamos como blob — o mesmo tratamento já usado nos anexos.
  let urlQr = null;
  try {
    urlQr = await api.blob("/mfa/qrcode");
  } catch { /* sem QR ainda dá para digitar o segredo */ }

  const codigo = el("input", {
    inputmode: "numeric", autocomplete: "one-time-code",
    placeholder: "000000", maxlength: "6",
    style: "font-size:22px;letter-spacing:6px;text-align:center",
  });
  const erro = el("div", { class: "recado erro oculto" });

  dialog({
    title: "Ativar verificação em duas etapas",
    wide: true,
    body: el("div", {},
      el("p", { class: "muted", style: "margin:0 0 14px" },
        "Instale um aplicativo autenticador (Google Authenticator, Microsoft "
        + "Authenticator, Authy) e aponte a câmera para o código abaixo."),

      el("div", { style: "text-align:center;margin-bottom:16px" },
        urlQr
          ? el("img", { src: urlQr, alt: "QR Code para o aplicativo autenticador",
                        style: "width:200px;height:200px;border-radius:12px;background:#fff;padding:8px" })
          : el("div", { class: "recado info" },
              "Não foi possível gerar o QR Code. Use o código abaixo no aplicativo."),
      ),

      el("div", { class: "field" },
        el("label", {}, "Ou digite este código no aplicativo"),
        el("input", { value: dados.segredo, readonly: "readonly",
                      style: "font-family:ui-monospace,monospace;font-size:13px",
                      onclick: (e) => e.target.select() }),
        el("span", { class: "dica" }, "Toque para selecionar, se precisar copiar."),
      ),

      el("div", { class: "field" },
        el("label", {}, "Código de 6 dígitos que o aplicativo mostra"),
        codigo,
      ),
      erro,
    ),
    actions: [
      { label: "Cancelar", variant: "text" },
      { label: "Confirmar", variant: "filled", onClick: async (close) => {
        const valor = codigo.value.trim();
        if (!valor) { codigo.focus(); return; }
        try {
          const r = await api.post("/mfa/confirmar", { codigo: valor });
          close();
          if (urlQr) URL.revokeObjectURL(urlQr);
          mostrarCodigos(r.codigos_recuperacao, root);
        } catch (e) {
          erro.classList.remove("oculto");
          erro.textContent = e.message;
          codigo.value = "";
          codigo.focus();
        }
      } },
    ],
  });
  setTimeout(() => codigo.focus(), 100);
}

/**
 * Os códigos de recuperação — mostrados UMA vez.
 *
 * A tela não fecha sem a confirmação explícita de que foram guardados. É a
 * única saída se o celular for perdido, e depois desta janela eles não podem
 * ser recuperados: o servidor guarda só o hash.
 */
function mostrarCodigos(codigos, root) {
  if (!codigos?.length) { toast("Ativado"); return carregar(document.getElementById("view"), root); }

  const guardei = el("input", { type: "checkbox" });

  dialog({
    title: "Guarde os códigos de recuperação",
    wide: true,
    closeOnBackdrop: false,
    body: el("div", {},
      el("div", { class: "recado erro" },
        el("b", {}, "Esta é a única vez que eles aparecem."),
        " O sistema guarda apenas um código embaralhado — nem nós podemos "
        + "mostrá-los de novo."),

      el("p", { class: "muted", style: "margin:14px 0 8px" },
        "Cada código serve UMA vez e substitui o aplicativo caso você perca o "
        + "celular. Imprima, ou guarde num gerenciador de senhas."),

      el("div", { style: "display:grid;grid-template-columns:repeat(auto-fill,minmax(130px,1fr));gap:8px" },
        ...codigos.map((c) => el("code", {
          style: "padding:10px;border-radius:8px;text-align:center;font-size:15px;"
               + "background:var(--md-sys-color-surface-container-high);letter-spacing:1px",
        }, c))),

      el("div", { class: "row", style: "gap:8px;margin-top:14px" },
        el("button", { class: "btn tonal", onclick: () => {
          navigator.clipboard?.writeText(codigos.join("\n"));
          toast("Códigos copiados");
        }, html: icon("download", 16) + " Copiar todos" }),
        el("button", { class: "btn text", onclick: () => window.print() }, "Imprimir"),
      ),

      el("label", { class: "opcao", style: "margin-top:16px" }, guardei,
        el("span", { class: "opcao-texto" },
          el("span", { class: "opcao-titulo" }, "Guardei os códigos em lugar seguro"),
          el("span", { class: "opcao-dica" },
            "Marque para concluir. Sem eles, perder o celular significa perder o acesso."))),
    ),
    actions: [
      { label: "Concluir", variant: "filled", onClick: async (close) => {
        if (!guardei.checked) {
          mostrarErro(new Error("Marque que guardou os códigos antes de concluir."));
          return;
        }
        close();
        toast("Verificação em duas etapas ativada");
        await carregar(document.getElementById("view"), root);
      } },
    ],
  });
}

async function desativar(root) {
  if (!(await confirmSheet("Desativar verificação",
      "Sua conta volta a depender só da senha. Continuar?"))) return;

  const codigo = el("input", {
    inputmode: "numeric", placeholder: "Código do aplicativo ou de recuperação",
  });

  dialog({
    title: "Desativar verificação",
    body: el("div", {},
      el("p", { class: "muted", style: "margin:0 0 12px" },
        "Informe um código válido para confirmar. A senha sozinha não desativa "
        + "a proteção — isso evita que uma máquina destravada a desligue."),
      el("div", { class: "field" }, el("label", {}, "Código"), codigo),
    ),
    actions: [
      { label: "Cancelar", variant: "text" },
      { label: "Desativar", variant: "filled", onClick: async (close) => {
        try {
          await api.post("/mfa/desativar", { codigo: codigo.value.trim() });
          close();
          toast("Verificação desativada");
          await carregar(document.getElementById("view"), root);
        } catch (e) { mostrarErro(e); }
      } },
    ],
  });
  setTimeout(() => codigo.focus(), 100);
}
