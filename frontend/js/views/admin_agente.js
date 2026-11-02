/**
 * Administração → Sistema → Agente Nexus.
 *
 * ## O que esta tela faz
 *
 * 1. **Gera códigos de instalação** — e mostra o valor **uma única vez**.
 *    O banco guarda só o hash; se perder, gera outro.
 *
 * 2. **Lista os códigos** com usos restantes, validade e revogação.
 *
 * 3. **Fila de pendências** — máquinas que o agente encontrou e o servidor
 *    não reconheceu. É aqui que alguém escolhe o identificador.
 *
 * 4. **Máquinas registradas** — quando cada uma falou pela última vez.
 *
 * ## Por que o código aparece uma vez só
 *
 * É um segredo. Se pudesse ser relido, uma sessão de administrador
 * comprometida leria todos os códigos ativos. O mesmo tratamento da senha:
 * mostra na criação, guarda o hash, e não há "ver de novo".
 *
 * @module views/admin_agente
 */
import { api } from "../api.js";
import { el, toast, skeleton, emptyState, mostrarErro } from "../ui.js";

const DIAS = [
  { valor: 1, rotulo: "1 dia" },
  { valor: 3, rotulo: "3 dias" },
  { valor: 7, rotulo: "7 dias" },
  { valor: 30, rotulo: "30 dias" },
];

/** Data legível — "expira em 3 dias" diz mais que um timestamp. */
function quando(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  const diff = d.getTime() - Date.now();
  const dias = Math.round(diff / 86400000);
  if (diff < 0) return "expirado";
  if (dias > 1) return `em ${dias} dias`;
  const horas = Math.round(diff / 3600000);
  return horas > 1 ? `em ${horas} h` : "em menos de 1 h";
}

export async function renderAgente(root) {
  root.innerHTML = "";
  const alvo = el("div", {}, skeleton(4));
  root.append(alvo);

  const desenhar = async () => {
    let codigos = [];
    let pendentes = [];
    let tokens = [];
    try {
      [codigos, pendentes, tokens] = await Promise.all([
        api.get("/admin/agentes/codigos").catch(() => []),
        api.get("/admin/agentes/pendentes").catch(() => []),
        api.get("/admin/agentes/tokens").catch(() => []),
      ]);
    } catch (e) {
      alvo.innerHTML = "";
      alvo.append(emptyState("settings", "Não foi possível carregar", e.message));
      return;
    }

    alvo.innerHTML = "";

    // ------------------------------------------------------------ gerar
    const campoRotulo = el("input", {
      class: "field", placeholder: "Ex.: lote-novembro",
      style: "margin-bottom:8px",
    });
    const selectDias = el("select", { class: "field", style: "margin-bottom:8px" },
      ...DIAS.map((d) => el("option", { value: String(d.valor) }, d.rotulo)));
    selectDias.value = "7";
    const campoUsos = el("input", {
      class: "field", type: "number", min: "1", value: "1",
      style: "margin-bottom:8px",
    });

    // Onde o código gerado aparece — uma vez só.
    const areaCodigo = el("div", {});

    const botaoGerar = el("button", {
      class: "btn",
      onclick: async (ev) => {
        const bt = ev.currentTarget;
        bt.disabled = true;
        bt.textContent = "Gerando…";
        try {
          const r = await api.post("/admin/agentes/codigos", {
            rotulo: campoRotulo.value.trim() || null,
            dias: Number(selectDias.value),
            usos_max: Number(campoUsos.value) || 1,
          });
          areaCodigo.innerHTML = "";
          areaCodigo.append(
            el("div", {
              class: "card",
              style: "margin-top:12px;border:1px solid var(--md-sys-color-primary, #6750a4)",
            },
              el("p", { class: "muted", style: "margin:0 0 6px;font-size:12.5px" },
                "Este código aparece uma única vez. Copie agora."),
              el("div", {
                style: "font-family:monospace;font-size:22px;letter-spacing:1px;"
                  + "margin:6px 0 10px;user-select:all",
              }, r.codigo),
              el("div", { class: "row", style: "gap:8px;flex-wrap:wrap" },
                el("button", {
                  class: "btn tonal small",
                  onclick: async () => {
                    try {
                      await navigator.clipboard.writeText(r.codigo);
                      toast("Código copiado.");
                    } catch {
                      toast("Selecione e copie manualmente.");
                    }
                  },
                }, "Copiar código"),
                el("button", {
                  class: "btn text small",
                  onclick: () => {
                    const cmd = `msiexec /i nexus-agente.msi /qn`
                      + ` SERVER=${location.origin} CODIGO=${r.codigo}`;
                    navigator.clipboard?.writeText(cmd);
                    toast("Comando de instalação copiado.");
                  },
                }, "Copiar comando")),
            ),
          );
          await desenhar();
        } catch (e) {
          mostrarErro(e);
        } finally {
          bt.disabled = false;
          bt.textContent = "Gerar código";
        }
      },
    }, "Gerar código");

    alvo.append(el("div", { class: "card", style: "margin-bottom:16px" },
      el("b", {}, "Novo código de instalação"),
      el("p", { class: "muted", style: "font-size:12.5px;margin:4px 0 12px" },
        "O agente usa este código uma vez para se registrar e recebe, em troca, "
        + "um token próprio. O código nunca fica guardado na máquina."),
      campoRotulo, selectDias, campoUsos, botaoGerar,
      areaCodigo,
    ));

    // ------------------------------------------------------------ codigos
    const cartaoCodigos = el("div", { class: "card", style: "margin-bottom:16px" },
      el("b", {}, "Códigos gerados"));

    if (!codigos.length) {
      cartaoCodigos.append(el("p", { class: "muted", style: "margin:8px 0 0" },
        "Nenhum código gerado ainda."));
    } else {
      for (const c of codigos) {
        const restantes = Math.max(0, (c.usos_max || 0) - (c.usos_feitos || 0));
        cartaoCodigos.append(el("div", { class: "list-row" },
          el("div", { class: "list-main" },
            el("div", { class: "list-title" },
              `${c.prefixo}…${c.rotulo ? " · " + c.rotulo : ""}`),
            el("div", { class: "list-sub" },
              `${c.usos_feitos}/${c.usos_max} usados · ${restantes} restantes · `
              + `expira ${quando(c.expira_em)}`)),
          c.util
            ? el("button", {
                class: "btn text small",
                onclick: async () => {
                  if (!confirm(`Revogar o código ${c.prefixo}?`)) return;
                  try {
                    await api.del(`/admin/agentes/codigos/${c.id}`);
                    toast("Código revogado.");
                    await desenhar();
                  } catch (e) { mostrarErro(e); }
                },
              }, "Revogar")
            : el("span", { class: "chip" }, c.revogado ? "revogado" : "inativo"),
        ));
      }
    }
    alvo.append(cartaoCodigos);

    // ------------------------------------------------------------ pendentes
    const cartaoPend = el("div", { class: "card", style: "margin-bottom:16px" },
      el("div", { class: "row between wrap", style: "gap:10px;align-items:center" },
        el("b", {}, "Aguardando cadastro"),
        el("span", { class: "chip" + (pendentes.length ? " aviso" : "") },
          String(pendentes.length))));

    if (!pendentes.length) {
      cartaoPend.append(el("p", { class: "muted", style: "margin:8px 0 0" },
        "Nenhuma máquina aguardando. Toda máquina que o agente encontrou já "
        + "tem ativo correspondente."));
    } else {
      cartaoPend.append(el("p", { class: "muted", style: "font-size:12.5px;margin:4px 0 10px" },
        "Máquinas que apareceram e não foram reconhecidas — normalmente por não "
        + "terem serial de fábrica. Escolha o identificador de cada uma."));
      for (const p of pendentes) {
        const campo = el("input", {
          class: "field", placeholder: "Patrimônio ou serial correto",
          style: "margin-bottom:8px",
        });
        const motivo = p.motivo === "sem_serial"
          ? "sem serial de fábrica"
          : "serial não cadastrado";
        cartaoPend.append(el("div", {
          class: "card", style: "margin-top:8px;background:transparent",
        },
          el("div", { class: "list-title" }, p.hostname || "(sem hostname)"),
          el("div", { class: "list-sub" },
            [motivo, p.serial_bruto, p.mac, p.ip].filter(Boolean).join(" · ")),
          el("div", { class: "list-sub", style: "margin-top:4px" },
            [p.basico?.fabricante, p.basico?.modelo, p.basico?.cpu]
              .filter(Boolean).join(" · ")),
          el("div", { style: "margin-top:10px" }, campo),
          el("div", { class: "row", style: "gap:8px;flex-wrap:wrap" },
            el("button", {
              class: "btn small",
              onclick: async (ev) => {
                const valor = campo.value.trim();
                if (!valor) { toast("Informe o identificador."); return; }
                ev.currentTarget.disabled = true;
                try {
                  await api.post(`/admin/agentes/pendentes/${p.id}`, {
                    patrimonio: valor,
                    numero_serie: valor,
                  });
                  toast("Ativo criado.");
                  await desenhar();
                } catch (e) {
                  ev.currentTarget.disabled = false;
                  mostrarErro(e);
                }
              },
            }, "Cadastrar"),
            el("button", {
              class: "btn text small",
              onclick: async () => {
                try {
                  await api.post(`/admin/agentes/pendentes/${p.id}`, { ignorar: true });
                  toast("Pendência ignorada.");
                  await desenhar();
                } catch (e) { mostrarErro(e); }
              },
            }, "Ignorar")),
        ));
      }
    }
    alvo.append(cartaoPend);

    // ------------------------------------------------------------ tokens
    const cartaoTokens = el("div", { class: "card" },
      el("div", { class: "row between wrap", style: "gap:10px;align-items:center" },
        el("b", {}, "Máquinas registradas"),
        el("span", { class: "muted", style: "font-size:12.5px" },
          `${tokens.length}`)));

    if (!tokens.length) {
      cartaoTokens.append(el("p", { class: "muted", style: "margin:8px 0 0" },
        "Nenhum agente registrado ainda."));
    } else {
      for (const t of tokens.slice(0, 50)) {
        cartaoTokens.append(el("div", { class: "list-row" },
          el("div", { class: "list-main" },
            el("div", { class: "list-title" },
              t.patrimonio || t.hostname || `ativo ${t.ativo_id}`),
            el("div", { class: "list-sub" },
              [t.hostname, t.serial, t.ultimo_ip].filter(Boolean).join(" · "))),
          el("span", { class: "muted", style: "font-size:12.5px;margin-right:10px" },
            t.ultimo_uso_em ? quando(t.ultimo_uso_em).replace("em ", "há ") : "nunca"),
          t.revogado
            ? el("span", { class: "chip" }, "revogado")
            : el("button", {
                class: "btn text small",
                onclick: async () => {
                  if (!confirm("Revogar o token desta máquina?")) return;
                  try {
                    await api.del(`/admin/agentes/tokens/${t.id}`);
                    toast("Token revogado.");
                    await desenhar();
                  } catch (e) { mostrarErro(e); }
                },
              }, "Revogar"),
        ));
      }
    }
    alvo.append(cartaoTokens);
  };

  await desenhar();
}
