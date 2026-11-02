/**
 * Administração → Sistema → Modo Manutenção.
 *
 * ## Duas funções na mesma tela
 *
 * 1. **Ligar/desligar o modo manutenção** — bloqueia o login de quem não é
 *    administrador e derruba as sessões abertas na próxima requisição.
 *
 * 2. **Ver quem está usando agora e derrubar** — a lista vem de
 *    `ultimo_acesso_em`, atualizado pelo servidor no máximo uma vez por
 *    minuto por usuário.
 *
 * ## Por que a atualização pausa com a aba oculta
 *
 * Um `setInterval` rodando numa aba em segundo plano gasta bateria e rede
 * sem ninguém olhando. O mesmo cuidado já existe no monitor de impressoras:
 * `document.hidden` desliga o ciclo, e voltar à aba recarrega na hora.
 *
 * ## O que "derrubar" faz
 *
 * Encerra **todas** as sessões daquela pessoa. Um token emitido depois volta
 * a valer — ela pode logar de novo imediatamente. Derrubar não é banir.
 *
 * @module views/admin_manutencao
 */
import { api } from "../api.js";
import { el, toast, skeleton, emptyState, mostrarErro } from "../ui.js";

const INTERVALO_MS = 15000;

let timer = null;

/** Formata "há N min" — mais legível que um horário absoluto nesta tela. */
function desde(minutos) {
  if (minutos <= 0) return "agora";
  if (minutos === 1) return "há 1 min";
  if (minutos < 60) return `há ${minutos} min`;
  const h = Math.floor(minutos / 60);
  return h === 1 ? "há 1 h" : `há ${h} h`;
}

export async function renderManutencao(root) {
  root.innerHTML = "";
  const alvo = el("div", {}, skeleton(4));
  root.append(alvo);

  const desenhar = async () => {
    let estado;
    let usuarios = [];
    try {
      [estado, usuarios] = await Promise.all([
        api.get("/admin/manutencao/status"),
        api.get("/admin/manutencao/usuarios").catch(() => []),
      ]);
    } catch (e) {
      alvo.innerHTML = "";
      alvo.append(emptyState("settings", "Não foi possível carregar", e.message));
      return;
    }

    alvo.innerHTML = "";

    // ---------------------------------------------------------------- estado
    const ativa = !!estado.ativa;
    const campo = el("textarea", {
      class: "field",
      rows: "2",
      maxlength: "500",
      placeholder: "Mensagem que os usuários verão, ex.: "
        + "Atualizando o sistema, voltamos às 22h.",
    });
    campo.value = estado.mensagem || "";

    const botao = el("button", {
      class: ativa ? "btn tonal" : "btn",
      onclick: async (ev) => {
        const bt = ev.currentTarget;
        bt.disabled = true;
        bt.textContent = ativa ? "Desativando…" : "Ativando…";
        try {
          if (ativa) {
            await api.post("/admin/manutencao/desativar", {});
            toast("Modo manutenção desligado.");
          } else {
            const r = await api.post("/admin/manutencao/ativar", {
              mensagem: campo.value.trim() || null,
            });
            toast(r.mensagem ? "Modo manutenção ativado." : "Modo ativado.");
          }
          await desenhar();
        } catch (e) {
          bt.disabled = false;
          bt.textContent = ativa ? "Desativar" : "Ativar";
          mostrarErro(e);
        }
      },
    }, ativa ? "Desativar" : "Ativar modo manutenção");

    const cartao = el("div", { class: "card", style: "margin-bottom:16px" },
      el("div", { class: "row between wrap", style: "gap:10px;align-items:center" },
        el("div", {},
          el("b", {}, "Modo manutenção"),
          el("div", { class: "muted", style: "font-size:12.5px;margin-top:2px" },
            "Bloqueia o login de técnicos e derruba as sessões abertas. "
            + "O administrador continua entrando.")),
        el("span", { class: `chip${ativa ? " danger" : ""}` },
          ativa ? "Ligado" : "Desligado")),
      ativa && estado.desde
        ? el("p", { class: "muted", style: "font-size:12.5px;margin:10px 0 0" },
            `Ligado desde ${new Date(estado.desde).toLocaleString("pt-BR")}`
            + (estado.por_nome ? ` por ${estado.por_nome}` : "") + ".")
        : null,
      el("div", { style: "margin-top:12px" }, campo),
      el("div", { class: "row", style: "margin-top:10px;gap:8px;flex-wrap:wrap" }, botao),
    );
    alvo.append(cartao);

    // ---------------------------------------------------------------- lista
    const lista = el("div", { class: "card" },
      el("div", { class: "row between wrap", style: "gap:10px;align-items:center;margin-bottom:10px" },
        el("b", {}, "Quem está usando agora"),
        el("span", { class: "muted", style: "font-size:12.5px" },
          `${usuarios.length} pessoa(s)`)));

    if (!usuarios.length) {
      lista.append(el("p", { class: "muted", style: "margin:0" },
        "Ninguém acessou nos últimos 5 minutos."));
    } else {
      for (const u of usuarios) {
        const botaoDerrubar = u.eh_admin
          ? el("span", { class: "muted", style: "font-size:12px" }, "administrador")
          : el("button", {
              class: "btn text small",
              onclick: async (ev) => {
                const bt = ev.currentTarget;
                if (!confirm(`Encerrar as sessões de ${u.nome}?`)) return;
                bt.disabled = true;
                try {
                  const r = await api.post(`/admin/manutencao/derrubar/${u.id}`, {});
                  toast(r.mensagem || "Sessões encerradas.");
                  await desenhar();
                } catch (e) {
                  bt.disabled = false;
                  mostrarErro(e);
                }
              },
            }, "Derrubar");

        lista.append(el("div", { class: "list-row" },
          el("div", { class: "list-main" },
            el("div", { class: "list-title" }, u.nome),
            el("div", { class: "list-sub" },
              [u.email, u.papel, u.planta_sigla].filter(Boolean).join(" · "))),
          el("span", { class: "muted", style: "font-size:12.5px;margin-right:10px" },
            desde(u.minutos)),
          botaoDerrubar,
        ));
      }
    }
    alvo.append(lista);
  };

  await desenhar();

  // Atualiza sozinho; pausa com a aba oculta para não gastar rede à toa.
  clearInterval(timer);
  timer = setInterval(() => { if (!document.hidden) desenhar(); }, INTERVALO_MS);

  // A tela sai ao trocar de aba — o intervalo não pode continuar rodando.
  const parar = () => clearInterval(timer);
  window.addEventListener("hashchange", parar, { once: true });
}
