/**
 * Notificações por e-mail — configuração e preferências.
 *
 * ## A tela inteira é de administrador
 *
 * Servidor (SMTP), modelos, prévia, histórico **e as preferências de cada
 * técnico**. O administrador escolhe de quem são as preferências, em vez de
 * cada um entrar na Administração — que é área restrita e não deveria ser o
 * caminho para uma configuração pessoal.
 *
 * Isso foi decidido de propósito: hoje o dono da configuração é o
 * administrador. Uma tela de autoatendimento para o técnico fica para quando
 * houver necessidade real.
 *
 * ## Por que as quatro seções ficam juntas
 *
 * Quem liga o SMTP é a mesma pessoa que vai querer conferir a prévia e o
 * histórico. Separar em três telas obrigaria a navegar entre elas para
 * responder "está funcionando?" — a pergunta real depois de configurar.
 *
 * @module views/admin_notificacoes
 */
import { api } from "../api.js";
import { el, toast, skeleton, emptyState, mostrarErro } from "../ui.js";

const ABA_SERVIDOR = "servidor";
const ABA_MODELOS = "modelos";
const ABA_PREFERENCIAS = "preferencias";
const ABA_HISTORICO = "historico";

const ABAS = [
  [ABA_SERVIDOR, "Servidor (SMTP)"],
  [ABA_MODELOS, "Modelos de mensagem"],
  [ABA_PREFERENCIAS, "Preferências por técnico"],
  [ABA_HISTORICO, "Enviados"],
];

const DIAS = [
  [1, "Seg"], [2, "Ter"], [3, "Qua"], [4, "Qui"], [5, "Sex"], [6, "Sáb"], [7, "Dom"],
];

/**
 * A tela de administração das notificações.
 *
 * @param {HTMLElement} root
 * @param {{aba?: string}} [opcoes] aba inicial — permite abrir direto
 */
export async function renderNotificacoes(root, opcoes = {}) {
  let ativa = opcoes.aba && ABAS.some(([c]) => c === opcoes.aba) ? opcoes.aba : ABAS[0][0];

  root.innerHTML = "";

  const barra = el("div", { class: "row wrap", style: "gap:8px;margin-bottom:16px" });
  const alvo = el("div", {}, skeleton(4));

  function pintar() {
    barra.innerHTML = "";
    for (const [chave, rotulo] of ABAS) {
      barra.append(el("button", {
        class: `chip${ativa === chave ? " selected" : ""}`,
        onclick: () => { ativa = chave; pintar(); despachar(); },
      }, rotulo));
    }
  }

  async function despachar() {
    alvo.innerHTML = "";
    alvo.append(skeleton(3));
    try {
      if (ativa === ABA_SERVIDOR) await secaoServidor(alvo);
      else if (ativa === ABA_MODELOS) await secaoModelos(alvo);
      else if (ativa === ABA_PREFERENCIAS) await secaoPreferencias(alvo);
      else if (ativa === ABA_HISTORICO) await secaoHistorico(alvo);
    } catch (e) {
      alvo.innerHTML = "";
      alvo.append(el("p", { class: "text-error" }, e.message));
    }
  }

  root.append(barra, alvo);
  pintar();
  await despachar();
}

// ===========================================================================
// Seção: servidor SMTP
// ===========================================================================
async function secaoServidor(alvo) {
  const cfg = await api.get("/notificacoes-email/smtp");

  const campo = (rotulo, entrada, ajuda) => el("div", { class: "field" },
    el("label", {}, rotulo),
    entrada,
    ajuda ? el("p", { class: "dica", style: "margin:4px 0 0" }, ajuda) : null,
  );

  const ativo = el("input", { type: "checkbox" });
  ativo.checked = !!cfg.ativo;

  const host = el("input", { placeholder: "smtp.empresa.com", value: cfg.host || "" });
  const porta = el("input", { type: "number", value: String(cfg.porta || 587), style: "max-width:120px" });
  const seguranca = el("select", {},
    ...[["tls", "STARTTLS (587)"], ["ssl", "SSL/TLS (465)"], ["nenhuma", "Sem cifra (25)"]]
      .map(([v, r]) => {
        const o = el("option", { value: v }, r);
        if (cfg.seguranca === v) o.selected = true;
        return o;
      }));
  const usuario = el("input", { placeholder: "notificacoes@empresa.com", value: cfg.usuario || "" });
  const senha = el("input", {
    type: "password",
    placeholder: cfg.tem_senha ? "•••••••• (guardada — deixe vazio para manter)" : "senha ou senha de aplicativo",
    autocomplete: "new-password",
  });
  const remetenteEmail = el("input", { placeholder: "notificacoes@empresa.com", value: cfg.remetente_email || "" });
  const remetenteNome = el("input", { placeholder: "Nexus", value: cfg.remetente_nome || "Nexus" });
  const responder = el("input", { placeholder: "ti@empresa.com", value: cfg.responder_para || "" });
  const prefixo = el("input", { placeholder: "[Nexus]", value: cfg.assunto_prefixo || "" });
  const hInicio = el("input", { type: "number", min: "0", max: "23", value: String(cfg.hora_inicio ?? 7), style: "max-width:90px" });
  const hFim = el("input", { type: "number", min: "0", max: "23", value: String(cfg.hora_fim ?? 19), style: "max-width:90px" });

  const estado = el("p", {
    class: cfg.pronto ? "text-ok" : "muted",
    style: "margin:0 0 12px",
  }, cfg.pronto ? "Envio configurado e ligado." : `Não está pronto: ${cfg.motivo || "configure os campos."}`);

  // Começa vazio de propósito: o e-mail do remetente costuma ser um endereço
  // de serviço (notificacoes@...), e pré-preencher com ele faria o teste ir
  // para uma caixa que ninguém abre. Quem testa digita o próprio endereço.
  const destinatarioTeste = el("input", {
    type: "email",
    placeholder: "seu@empresa.com",
    style: "max-width:280px",
  });

  let salvando = false;
  async function salvar() {
    if (salvando) return;
    salvando = true;
    try {
      const corpo = {
        ativo: ativo.checked,
        host: host.value.trim() || null,
        porta: Number(porta.value) || 587,
        seguranca: seguranca.value,
        usuario: usuario.value.trim() || null,
        remetente_email: remetenteEmail.value.trim() || null,
        remetente_nome: remetenteNome.value.trim() || "Nexus",
        responder_para: responder.value.trim() || null,
        assunto_prefixo: prefixo.value,
        hora_inicio: Number(hInicio.value) || 0,
        hora_fim: Number(hFim.value) || 23,
      };
      // Só envia a senha quando foi digitada — vazio significa "manter".
      // Sem isto, abrir a tela e salvar apagaria a credencial, porque ela
      // nunca volta para o navegador.
      if (senha.value !== "") corpo.senha = senha.value;

      await api.request("PUT", "/notificacoes-email/smtp", { body: corpo });
      toast("Configuração salva");
      await secaoServidor(alvo);
    } catch (e) {
      mostrarErro(e, "salvar a configuração de e-mail");
    } finally {
      salvando = false;
    }
  }

  async function testar() {
    const destino = destinatarioTeste.value.trim();
    if (!destino) { mostrarErro(new Error("Informe o e-mail que vai receber o teste.")); return; }
    try {
      const r = await api.request("POST", "/notificacoes-email/smtp/testar", { body: { destinatario: destino } });
      toast(r.mensagem || "Teste enviado");
    } catch (e) {
      mostrarErro(e, "enviar o teste");
    }
  }

  alvo.append(
    el("div", { class: "card" },
      el("h2", { style: "margin:0 0 4px;font-size:16px" }, "Servidor de e-mail"),
      el("p", { class: "muted", style: "margin:0 0 16px;font-size:13px" },
        "Usado para todos os avisos do sistema. Sem esta configuração, nenhum e-mail sai."),
      estado,

      el("label", { class: "row", style: "gap:8px;align-items:center;margin-bottom:16px" },
        ativo, el("span", {}, "Enviar e-mails (ligar/desligar)")),

      el("div", { class: "grid-2" },
        campo("Servidor (host)", host, "Endereço do SMTP. Ex.: smtp.office365.com"),
        campo("Porta", porta, "587 com STARTTLS · 465 com SSL · 25 sem cifra"),
      ),
      el("div", { class: "grid-2" },
        campo("Segurança", seguranca),
        campo("Usuário", usuario, "Muitas vezes é o e-mail completo."),
      ),
      campo("Senha", senha,
        cfg.tem_senha
          ? "Já existe uma senha guardada. Deixe em branco para manter."
          : "Guardada cifrada. Gmail e Outlook exigem senha de aplicativo."),

      el("div", { class: "grid-2" },
        campo("E-mail do remetente", remetenteEmail, "Precisa ser aceito pelo servidor — em geral o mesmo do usuário."),
        campo("Nome do remetente", remetenteNome),
      ),
      el("div", { class: "grid-2" },
        campo("Responder para", responder, "Opcional. Para onde vão as respostas."),
        campo("Prefixo do assunto", prefixo, "Ajuda a criar regra na caixa de entrada."),
      ),

      el("h3", { class: "secao-titulo", style: "margin-top:20px" }, "Janela de envio"),
      el("p", { class: "muted", style: "margin:0 0 10px;font-size:13px" },
        "Fora deste intervalo, os avisos esperam o próximo ciclo. E-mail às 3h não é lido."),
      el("div", { class: "row wrap", style: "gap:8px;align-items:center" },
        el("span", {}, "Das"), hInicio, el("span", {}, "às"), hFim, el("span", { class: "muted" }, "horas"),
      ),

      el("div", { class: "row wrap", style: "gap:8px;margin-top:20px" },
        el("button", { class: "btn filled", onclick: salvar }, "Salvar"),
      ),
    ),

    el("div", { class: "card", style: "margin-top:16px" },
      el("h2", { style: "margin:0 0 4px;font-size:16px" }, "Testar envio"),
      el("p", { class: "muted", style: "margin:0 0 12px;font-size:13px" },
        "Envia uma mensagem curta de teste. Faça isto depois de salvar."),
      el("div", { class: "row wrap", style: "gap:8px;align-items:center" },
        destinatarioTeste,
        el("button", { class: "btn tonal", onclick: testar }, "Enviar teste"),
      ),
    ),
  );
}

// ===========================================================================
// Seção: modelos de mensagem
// ===========================================================================
async function secaoModelos(alvo) {
  const dados = await api.get("/notificacoes-email/templates");

  alvo.append(el("p", { class: "muted", style: "margin:0 0 14px" },
    "O texto de cada aviso. Use as variáveis entre chaves — elas são trocadas "
    + "pelos dados do ativo, do usuário e da data."));

  for (const t of dados.itens) {
    const assunto = el("input", { value: t.assunto || "", style: "width:100%" });
    const corpo = el("textarea", { rows: "6", style: "width:100%;font-family:monospace" });
    corpo.value = t.corpo || "";

    const variaveis = el("p", { class: "muted", style: "margin:6px 0 0;font-size:12px" },
      "Variáveis: " + t.variaveis.map((v) => `{{${v}}}`).join(" · "));

    const card = el("div", { class: "card", style: "margin-bottom:12px" },
      el("div", { class: "row", style: "justify-content:space-between;align-items:baseline" },
        el("h3", { style: "margin:0 0 6px;font-size:15px" }, t.nome),
        t.personalizado
          ? el("span", { class: "chip info" }, "personalizado")
          : el("span", { class: "chip" }, "padrão"),
      ),
      el("div", { class: "field" }, el("label", {}, "Assunto"), assunto),
      el("div", { class: "field" }, el("label", {}, "Mensagem"), corpo),
      variaveis,
      el("div", { class: "row wrap", style: "gap:8px;margin-top:10px" },
        el("button", {
          class: "btn filled small",
          onclick: async () => {
            try {
              await api.request("PUT", `/notificacoes-email/templates/${t.chave}`, {
                body: { assunto: assunto.value, corpo: corpo.value },
              });
              toast(`Modelo de "${t.nome}" salvo`);
              await secaoModelos(alvo);
            } catch (e) { mostrarErro(e, "salvar o modelo"); }
          },
        }, "Salvar"),
        t.personalizado
          ? el("button", {
              class: "btn text small",
              onclick: async () => {
                try {
                  await api.request("PUT", `/notificacoes-email/templates/${t.chave}`, { body: {} });
                  toast("Modelo padrão restaurado");
                  await secaoModelos(alvo);
                } catch (e) { mostrarErro(e, "restaurar o padrão"); }
              },
            }, "Voltar ao padrão")
          : null,
      ),
    );
    alvo.append(card);
  }
}

// ===========================================================================
// Seção: preferências por técnico
// ===========================================================================
async function secaoPreferencias(alvo, escolhido = null) {
  // A lista de técnicos vem do cadastro. Só usuários com e-mail fazem sentido
  // aqui — sem endereço, nenhuma preferência tem efeito.
  const usuarios = await api.get("/cadastros/usuarios").catch(() => []);
  const comEmail = (usuarios || []).filter((u) => u.email);

  if (!comEmail.length) {
    alvo.append(el("div", { class: "card" },
      el("p", { class: "muted", style: "margin:0" },
        "Nenhum usuário tem e-mail cadastrado. Sem endereço, nenhum aviso pode ser enviado — "
        + "preencha em Usuários & Permissões.")));
    return;
  }

  const alvoId = escolhido ?? comEmail[0].id;

  const [dados, catalogo] = await Promise.all([
    api.get("/notificacoes-email/preferencias", { usuario_id: alvoId }),
    api.get("/notificacoes-email/catalogo"),
  ]);

  const frequencias = catalogo.frequencias || [];

  // Seletor do técnico: a tela é do administrador, e ele configura para
  // outra pessoa. Sem isto, só as próprias preferências seriam alcançáveis.
  const seletor = el("select", {},
    ...comEmail.map((u) => {
      const o = el("option", { value: String(u.id) }, `${u.nome} — ${u.email}`);
      if (u.id === alvoId) o.selected = true;
      return o;
    }));
  seletor.addEventListener("change", async () => {
    alvo.innerHTML = "";
    alvo.append(skeleton(3));
    await secaoPreferencias(alvo, Number(seletor.value));
  });

  const lista = el("div", {});

  for (const item of dados.itens) {
    estados[item.chave] = {
      ativo: item.ativo,
      frequencia: item.frequencia,
      hora: item.hora,
      dias_semana: item.dias_semana,
    };

    const ligado = el("input", { type: "checkbox" });
    ligado.checked = !!item.ativo;

    const selFreq = el("select", {}, ...frequencias.map((f) => {
      const o = el("option", { value: f.valor, title: f.ajuda }, f.rotulo);
      if (item.frequencia === f.valor) o.selected = true;
      return o;
    }));

    const hora = el("input", { type: "number", min: "0", max: "23", value: String(item.hora ?? 8), style: "max-width:74px" });
    const blocoHora = el("span", { class: "row", style: "gap:4px;align-items:center" }, el("span", { class: "muted", style: "font-size:12px" }, "às"), hora, el("span", { class: "muted", style: "font-size:12px" }, "h"));

    // Dias da semana só fazem sentido no semanal.
    const diasCaixa = el("span", { class: "row wrap", style: "gap:4px;margin-left:8px" });
    const marcados = new Set((item.dias_semana || "").split(",").filter(Boolean).map(Number));
    for (const [iso, rotulo] of DIAS) {
      const cb = el("input", { type: "checkbox", style: "margin:0" });
      cb.checked = marcados.has(iso);
      cb.dataset.dia = String(iso);
      diasCaixa.append(el("label", { class: "chip", style: "cursor:pointer;gap:4px" }, cb, el("span", {}, rotulo)));
    }

    const blocoDias = el("span", { style: "margin-left:8px" }, diasCaixa);

    function sincronizar() {
      const freq = selFreq.value;
      blocoHora.style.display = freq === "imediata" || freq === "desligada" ? "none" : "inline-flex";
      blocoDias.style.display = freq === "semanal" ? "inline" : "none";
      lista.querySelectorAll(`[data-chave="${item.chave}"]`).forEach((n) => {
        n.style.opacity = ligado.checked ? "1" : "0.45";
      });
    }

    ligado.addEventListener("change", sincronizar);
    selFreq.addEventListener("change", sincronizar);

    const linha = el("div", {
      class: "card",
      style: "margin-bottom:10px",
      "data-chave": item.chave,
    },
      el("div", { class: "row wrap", style: "justify-content:space-between;gap:12px;align-items:flex-start" },
        el("div", { style: "flex:1;min-width:220px" },
          el("label", { class: "row", style: "gap:8px;align-items:center;cursor:pointer" },
            ligado, el("b", {}, item.nome)),
          el("p", { class: "muted", style: "margin:4px 0 0;font-size:12.5px" }, item.descricao),
        ),
        el("div", { class: "row wrap", style: "gap:6px;align-items:center" },
          selFreq, blocoHora, blocoDias,
        ),
      ),
    );

    linhas.push(linha);
    lista.append(linha);
    setTimeout(sincronizar, 0);
  }

  async function salvar() {
    const itens = dados.itens.map((item) => {
      const linha = lista.querySelector(`[data-chave="${item.chave}"]`);
      const ligado = linha.querySelector('input[type="checkbox"]');
      const freq = linha.querySelector("select").value;
      const num = linha.querySelector('input[type="number"]');
      const dias = [...linha.querySelectorAll('input[data-dia]')]
        .filter((cb) => cb.checked)
        .map((cb) => cb.dataset.dia)
        .join(",");

      return {
        chave: item.chave,
        ativo: ligado.checked,
        frequencia: freq,
        hora: Number(num?.value) || 8,
        dias_semana: freq === "semanal" ? (dias || null) : null,
      };
    });

    try {
      // O `usuario_id` diz de quem são as preferências. O servidor só aceita
      // configurar outro usuário quando quem chama é administrador.
      await api.request("PUT", "/notificacoes-email/preferencias", {
        body: { itens, usuario_id: alvoId },
      });
      toast(`Preferências de ${dados.usuario_nome || "técnico"} salvas`);
    } catch (e) {
      mostrarErro(e, "salvar as preferências");
    }
  }

  alvo.append(
    el("div", { class: "card", style: "margin-bottom:14px" },
      el("h2", { style: "margin:0 0 4px;font-size:16px" }, "O que este técnico recebe"),
      el("p", { class: "muted", style: "margin:0 0 12px;font-size:13px" },
        "As preferências valem para o endereço abaixo. Aviso sem preferência "
        + "registrada usa o padrão do catálogo — a coluna mostra o que o envio fará."),
      el("div", { class: "field" },
        el("label", {}, "Técnico"),
        seletor,
        el("p", { class: "dica", style: "margin:6px 0 0" },
          `Avisos irão para ${dados.email || "— (sem e-mail)"}.`),
      ),
    ),
    lista,
    el("div", { class: "row", style: "margin-top:8px" },
      el("button", { class: "btn filled", onclick: salvar }, "Salvar preferências"),
    ),
  );
}

// ===========================================================================
// Seção: enviados (histórico + prévia)
// ===========================================================================
async function secaoHistorico(alvo) {
  const [hist, previa] = await Promise.all([
    api.get("/notificacoes-email/historico", { limite: 50 }).catch(() => ({ itens: [] })),
    api.get("/notificacoes-email/previa", { limite: 15 }).catch(() => ({ itens: [], total: 0 })),
  ]);

  const listaPrevia = el("div", {});
  if (!previa.itens?.length) {
    listaPrevia.append(el("p", { class: "muted" }, "Nenhum aviso pendente agora."));
  } else {
    for (const p of previa.itens) {
      listaPrevia.append(el("div", { class: "card", style: "margin-bottom:8px" },
        el("div", { class: "row", style: "justify-content:space-between" },
          el("b", { style: "font-size:13.5px" }, p.assunto),
          el("span", { class: "muted", style: "font-size:12px" }, p.destinatario),
        ),
        el("pre", { style: "white-space:pre-wrap;margin:8px 0 0;font-size:12px;font-family:inherit" }, p.corpo),
      ));
    }
  }

  const listaHist = el("div", {});
  if (!hist.itens?.length) {
    listaHist.append(el("p", { class: "muted" }, "Nada enviado ainda."));
  } else {
    for (const h of hist.itens) {
      listaHist.append(el("div", { class: "list-row" },
        el("div", { class: "list-main" },
          el("div", { class: "list-title" }, h.assunto),
          el("div", { class: "list-sub" },
            `${h.destinatario} · ${h.chave}${h.resumo ? ` · ${h.resumo}` : ""}`
            + (h.erro ? ` · ${h.erro}` : "")),
        ),
        el("span", { class: h.ok ? "chip ok" : "chip danger" }, h.ok ? "enviado" : "falhou"),
      ));
    }
  }

  alvo.append(
    el("div", { class: "card", style: "margin-bottom:14px" },
      el("div", { class: "row", style: "justify-content:space-between;align-items:baseline;margin-bottom:8px" },
        el("h2", { style: "margin:0;font-size:16px" }, "O que sairia agora"),
        el("button", {
          class: "btn tonal small",
          onclick: async () => {
            try {
              const r = await api.request("POST", "/notificacoes-email/enviar-agora", { body: {} });
              toast(`Enviados: ${r.enviados} · Falhas: ${r.falhas} · Pulados: ${r.pulados}`);
              await secaoHistorico(alvo);
            } catch (e) { mostrarErro(e, "enviar agora"); }
          },
        }, "Enviar agora"),
      ),
      el("p", { class: "muted", style: "margin:0 0 10px;font-size:13px" },
        "A prévia não envia nada. Confira o texto antes de ligar o envio."),
      listaPrevia,
    ),

    el("div", { class: "card" },
      el("h2", { style: "margin:0 0 10px;font-size:16px" }, "Últimos envios"),
      listaHist,
    ),
  );
}
