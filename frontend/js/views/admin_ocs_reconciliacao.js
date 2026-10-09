/**
 * Reconciliação com o OCS — aba de Administração.
 *
 * Mostra a diferença entre o que a rede tem e o que o inventário registra.
 * **Só leitura**: aponta, não altera. Criar ativos sozinho a partir da rede
 * transformaria um relatório de conferência numa fonte de surpresas.
 *
 * @module views/admin_ocs_reconciliacao
 */
import { api } from "../api.js";
import { state } from "../state.js";
import { el, icon, toast, fmtDate, skeleton, mostrarErro } from "../ui.js";

let dias = 30;

export async function renderReconciliacao(root) {
  root.innerHTML = "";
  root.append(
    el("div", { class: "row between wrap", style: "gap:10px" },
      el("h2", { style: "margin:0" }, "Reconciliação com o OCS"),
      el("div", { class: "row", style: "gap:8px;align-items:center" },
        el("label", { class: "muted", for: "rec-dias" }, "Dias sem contato"),
        el("input", {
          id: "rec-dias", type: "number", min: 1, max: 365, value: dias,
          style: "width:90px",
          onchange: (e) => { dias = Number(e.target.value) || 30; conferir(caixa, botao); },
        }),
        el("button", { id: "rec-conferir", class: "btn filled",
          html: icon("relatorios", 16) + " Conferir" }),
      ),
    ),
    el("p", { class: "muted", style: "margin:8px 0 18px" },
      "O OCS diz o que existe na rede agora; o inventário diz o que deveria existir. "
      + "A diferença entre os dois é o que aparece abaixo."),
  );

  const caixa = el("div", {}, skeleton(4));
  root.append(caixa);
  const botao = root.querySelector("#rec-conferir");
  botao.addEventListener("click", () => conferir(caixa, botao));
  conferir(caixa, botao);
}

async function conferir(caixa, botao) {
  botao.disabled = true;
  caixa.innerHTML = "";
  caixa.append(skeleton(4));

  let d;
  try {
    d = await api.get("/admin/ocs/reconciliacao", { dias });
  } catch (e) {
    caixa.innerHTML = "";
    caixa.append(el("p", { class: "text-error" }, e.message));
    botao.disabled = false;
    return;
  }
  botao.disabled = false;

  caixa.innerHTML = "";
  const r = d.resumo || {};

  if (d.aviso) {
    caixa.append(el("div", { class: "recado info", style: "margin-bottom:16px" }, d.aviso));
  }

  caixa.append(
    el("div", { class: "resumo-numeros" },
      numero(r.na_rede ?? 0, "Na rede"),
      numero(r.no_inventario ?? 0, "No inventário"),
      numero(r.fantasmas ?? 0, "Fantasmas", r.fantasmas ? "erro" : ""),
      numero(r.perdidos ?? 0, "Perdidos", r.perdidos ? "aviso" : ""),
      numero(r.divergencias ?? 0, "Divergências", r.divergencias ? "aviso" : ""),
    ),
    el("p", { class: "muted", style: "font-size:12.5px;margin:14px 0 20px" },
      `Conferido em ${d.conferido_em ? fmtDate(d.conferido_em, true) : "—"}`
      + ` · limite de ${d.dias_sem_contato} dias sem contato`),
  );

  // --- Fantasmas ---------------------------------------------------------
  caixa.append(secao(
    "Fantasmas",
    "Estão na rede e não estão no inventário — candidatos a cadastro.",
    d.fantasmas, (f) => [
      el("b", {}, f.hostname || "(sem hostname)"),
      f.ip ? el("span", { class: "muted" }, f.ip) : null,
      f.mac_address ? el("span", { class: "muted" }, f.mac_address) : null,
      f.numero_serie ? el("span", { class: "muted" }, `série ${f.numero_serie}`) : null,
      f.so ? el("span", { class: "muted" }, f.so) : null,
      f.hostname
        ? el("button", {
            class: "btn text", style: "margin-left:auto",
            onclick: () => {
              navigator.clipboard?.writeText(f.hostname);
              toast("Hostname copiado — cadastre em Ativos");
            },
          }, "Copiar hostname")
        : null,
    ], "erro",
  ));

  // --- Perdidos ----------------------------------------------------------
  caixa.append(secao(
    "Perdidos",
    `No inventário, sem contato com o OCS há mais de ${dias} dias.`,
    d.perdidos, (p) => [
      el("b", {}, p.patrimonio || "(sem patrimônio)"),
      p.hostname ? el("span", { class: "muted" }, p.hostname) : null,
      el("span", { class: p.motivo === "nunca visto" ? "chip aviso" : "chip", style: "margin-left:auto" },
        p.motivo),
    ], "aviso",
  ));

  // --- Divergências ------------------------------------------------------
  caixa.append(secao(
    "Divergências",
    "Estão nos dois lados, mas com dados diferentes. O inventário pode estar desatualizado.",
    d.divergencias, (x) => [
      el("b", {}, x.patrimonio || `ativo #${x.ativo_id}`),
      el("span", { class: "chip neutro" }, x.rotulo),
      el("span", { class: "div-lado" },
        el("span", { class: "muted" }, "no inventário: "), el("code", {}, String(x.no_inventario ?? "—"))),
      el("span", { class: "div-seta" }, "→"),
      el("span", { class: "div-lado" },
        el("span", { class: "muted" }, "na rede: "), el("code", {}, String(x.na_rede ?? "—"))),
    ], "aviso",
  ));
}

function numero(valor, rotulo, tom = "") {
  return el("div", { class: `numero ${tom}` },
    el("span", { class: "numero-valor" }, String(valor)),
    el("span", { class: "numero-rotulo" }, rotulo),
  );
}

function secao(titulo, descricao, itens, render, tom) {
  const lista = itens || [];
  return el("section", { class: "secao-divergencia" },
    el("div", { class: `secao-topo ${tom}` },
      el("b", {}, `${titulo} (${lista.length})`),
      el("p", { class: "muted", style: "margin:4px 0 0" }, descricao),
    ),
    lista.length
      ? el("div", { class: "lista-divergencia" },
          ...lista.map((x) => el("div", { class: "linha-divergencia" },
            ...render(x).filter(Boolean))))
      : el("p", { class: "muted", style: "padding:14px" },
          tom === "erro" ? "Nenhuma máquina fora do inventário. 👍"
                         : "Nada aqui. 👍"),
  );
}
