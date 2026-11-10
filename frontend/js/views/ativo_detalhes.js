/**
 * "Detalhes Completos" de um ativo — o que o agente coletou.
 *
 * ## Por que uma tela separada do formulário
 *
 * A janelinha do ativo é **editável**: hostname, MAC, SO, CPU, RAM. Quem
 * digita ali está corrigindo o cadastro.
 *
 * Aqui é **somente leitura**, e por um motivo: este dado veio da máquina, não
 * de uma pessoa. Se fosse editável, o próximo agente sobrescreveria a
 * edição sem aviso — e o técnico não entenderia por que o dado "voltou".
 *
 * ## O que a tela responde, em ordem
 *
 * 1. **Quando foi a última coleta** — é o que diz se o agente está vivo.
 * 2. **O que mudou, e quando** — o histórico com diff.
 * 3. **O hardware completo** — o que não cabe num formulário.
 *
 * @module views/ativo_detalhes
 */
import { api } from "../api.js";
import { el, dialog, skeleton, emptyState, toast } from "../ui.js";

/** Formata uma data como "há 3 dias", que é o que importa aqui. */
function desde(iso) {
  if (!iso) return "nunca";
  const d = new Date(iso);
  const min = Math.round((Date.now() - d.getTime()) / 60000);
  if (min < 1) return "agora";
  if (min < 60) return `há ${min} min`;
  const h = Math.round(min / 60);
  if (h < 24) return `há ${h} h`;
  const dias = Math.round(h / 24);
  return dias === 1 ? "há 1 dia" : `há ${dias} dias`;
}

function dataHora(iso) {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString("pt-BR");
  } catch {
    return String(iso);
  }
}

/** Um par rótulo/valor, ignorando vazios. */
function linha(rotulo, valor) {
  if (valor === null || valor === undefined || valor === "") return null;
  return el("div", { class: "list-row" },
    el("div", { class: "list-main" },
      el("div", { class: "list-sub" }, rotulo),
      el("div", { class: "list-title" }, String(valor))));
}

function secao(titulo, ...filhos) {
  const uteis = filhos.filter(Boolean);
  if (!uteis.length) return null;
  return el("div", { style: "margin-bottom:18px" },
    el("h3", { class: "secao-titulo", style: "margin:0 0 8px" }, titulo),
    ...uteis);
}

/**
 * Abre o painel de detalhes de um ativo.
 *
 * @param {object} ativo — o registro da lista (precisa de `id` e `dominio`)
 */

/**
 * Janela com os programas instalados nesta máquina.
 *
 * ## Por que janela própria
 *
 * A lista tem ~150 linhas. Dentro de "Detalhes" ela empurrava o hardware, os
 * usuários e o histórico para baixo — informação que se consulta sempre ficava
 * escondida atrás de informação que se consulta às vezes.
 *
 * Aqui ela aparece sozinha, e quem abre já sabe o que veio ver.
 */
export function abrirSoftwares(ativo) {
  const corpo = el("div", {});
  corpo.append(skeleton(4));

  const janela = dialog({
    title: `Softwares — ${ativo.patrimonio || ativo.numero_serie || "ativo"}`,
    body: corpo,
    wide: true,
    actions: [{ label: "Fechar", variant: "tonal", onClick: (fechar) => fechar() }],
  });

  // Classe própria para esta janela: a lista tem três colunas com nomes
  // longos ("Microsoft Visual C++ 2015-2022 Redistributable (x64)"), e na
  // largura padrão do diálogo sobra rolagem horizontal.
  janela.dlg.classList.add("dialog-software");

  api.get(`/ativos/${ativo.id}/software`).then((dados) => {
    corpo.innerHTML = "";

    const linhas = dados?.softwares || [];

    if (!linhas.length) {
      corpo.append(el("div", { class: "card" },
        el("p", { style: "margin:0 0 6px;font-weight:500" }, "Nenhum programa reportado"),
        el("p", { class: "muted", style: "margin:0;font-size:13px" },
          "O agente envia a lista junto com o inventário — use \"Atualizar agora\" "
          + "no agente para não esperar o ciclo diário.")));
      return;
    }

    const quando = dados.coletado_em
      ? new Date(dados.coletado_em).toLocaleString("pt-BR")
      : null;

    corpo.append(el("p", { class: "muted", style: "margin:0 0 10px;font-size:12.5px" },
      `${linhas.length} programa(s)`
      + (quando ? ` · última coleta em ${quando}` : "")));

    const tabela = el("table", { class: "data" },
      el("thead", {}, el("tr", {},
        el("th", {}, "Programa"),
        // Larguras no CSS (.dialog-software). Inline aqui venceria a media
        // query de tela estreita e voltaria a cortar o texto.
        el("th", {}, "Versão"),
        el("th", {}, "Fabricante"))));

    const tbody = el("tbody", {});
    for (const s of linhas) {
      tbody.append(el("tr", {},
        el("td", {}, s.nome),
        el("td", { class: "muted" }, s.versao || "—"),
        el("td", { class: "muted" }, s.fabricante || "—")));
    }

    tabela.append(tbody);
    corpo.append(tabela);
  }).catch((e) => {
    corpo.innerHTML = "";
    corpo.append(el("div", { class: "card" },
      el("p", { class: "text-error", style: "margin:0" }, e.message)));
  });
}

export async function abrirDetalhes(ativo) {
  const corpo = el("div", {}, skeleton(4));

  dialog({
    title: `Detalhes — ${ativo.patrimonio || ativo.numero_serie || "ativo"}`,
    body: corpo,
    wide: true,
    // `onClick` recebe a função de fechar, não o objeto do diálogo —
    // `f.close()` estourava e o botão não fazia nada.
    actions: [{ label: "Fechar", variant: "tonal", onClick: (fechar) => fechar() }],
  });

  // O detalhe completo vem de duas fontes: a ficha do ativo e o histórico.
  // O histórico pode falhar sem derrubar a tela — é acessório.
  let ficha = null;
  let historico = [];
  let usuarios = [];
  let softwares = null;
  try {
    const dados = await api.get(`/ativos/${ativo.id}`);
    ficha = dados.ti || dados.impressora || null;
    historico = await api.get(`/admin/agentes/historico/${ativo.id}`).catch(() => []);
    // Lista corrente de quem já logou nesta máquina. Quem não aparece há 30
    // dias já foi removido pelo servidor.
    usuarios = await api.get(`/admin/agentes/usuarios-do-ativo/${ativo.id}`)
      .catch(() => []);
    // Lista de programas da ultima coleta. `null` = falhou (mostra o aviso);
    // `[]` = coletou e nao achou nada.
    softwares = await api.get(`/ativos/${ativo.id}/software`).catch(() => null);
  } catch (e) {
    corpo.innerHTML = "";
    corpo.append(emptyState("ativos", "Não foi possível carregar", e.message));
    return;
  }

  corpo.innerHTML = "";

  if (!ficha) {
    corpo.append(emptyState("ativos", "Sem detalhes coletados",
      "Este ativo ainda não recebeu inventário de um agente."));
    return;
  }

  // --- 1. quando foi a última coleta ------------------------------------
  const coletado = ficha.inventario_em;
  const velho = coletado
    ? (Date.now() - new Date(coletado).getTime()) > 7 * 86400000
    : true;

  corpo.append(el("div", {
    class: "card",
    style: "margin-bottom:16px" + (velho ? ";border:1px solid var(--md-sys-color-error, #b3261e)" : ""),
  },
    el("div", { class: "row between wrap", style: "gap:10px;align-items:center" },
      el("div", {},
        el("b", {}, "Última coleta"),
        el("div", { class: "muted", style: "font-size:12.5px;margin-top:2px" },
          coletado
            ? `${desde(coletado)} · ${dataHora(coletado)}`
            : "Nenhum agente enviou inventário para este ativo.")),
      el("span", { class: `chip${velho ? " danger" : ""}` },
        coletado ? (velho ? "desatualizado" : "em dia") : "sem coleta")),
    velho && coletado
      ? el("p", { class: "muted", style: "font-size:12.5px;margin:10px 0 0" },
          "Se o equipamento está em uso, o agente pode estar parado ou a máquina "
          + "sem rede. Peça para ligar o computador e verificar o serviço.")
      : null,
  ));

  // --- 2. hardware ------------------------------------------------------
  let detalhes = {};
  try {
    detalhes = JSON.parse(ficha.inventario_json || "{}");
  } catch {
    detalhes = {};
  }

  const hardware = el("div", {},
    linha("Hostname", ficha.hostname),
    linha("Sistema operacional", ficha.so),
    linha("Processador", ficha.cpu),
    linha("Memória RAM", ficha.ram_gb ? `${ficha.ram_gb} GB` : null),
    linha("Armazenamento", ficha.armazenamento_gb ? `${ficha.armazenamento_gb} GB` : null),
    linha("Domínio", ficha.dominio_ad),
    linha("MAC", ficha.mac_address),
    linha("IP", ficha.ip),
    linha("BIOS", detalhes.bios_versao),
    linha("Placa-mãe", [detalhes.placa_mae_fabricante, detalhes.placa_mae]
      .filter(Boolean).join(" ") || null),
    linha("GPU", detalhes.gpu),
    linha("Uptime", detalhes.uptime_horas != null
      ? `${detalhes.uptime_horas} horas` : null),
    linha("Usuário logado", detalhes.usuario_logado),
  );

  // Discos, rede e monitores são listas — viram linhas próprias.
  if (Array.isArray(detalhes.discos) && detalhes.discos.length) {
    hardware.append(el("h3", { class: "secao-titulo", style: "margin:14px 0 6px" },
      `Discos (${detalhes.discos.length})`));
    for (const d of detalhes.discos) {
      hardware.append(linha(
        [d.modelo, d.tipo].filter(Boolean).join(" · ") || "disco",
        [d.gb ? `${d.gb} GB` : null, d.serial].filter(Boolean).join(" · ")));
    }
  }

  if (Array.isArray(detalhes.monitores) && detalhes.monitores.length) {
    hardware.append(el("h3", { class: "secao-titulo", style: "margin:14px 0 6px" },
      `Monitores (${detalhes.monitores.length})`));
    for (const m of detalhes.monitores) {
      hardware.append(linha(
        [m.fabricante, m.modelo].filter(Boolean).join(" ") || "monitor",
        m.serial));
    }
  }

  if (Array.isArray(detalhes.rede) && detalhes.rede.length) {
    hardware.append(el("h3", { class: "secao-titulo", style: "margin:14px 0 6px" },
      `Rede (${detalhes.rede.length})`));
    for (const r of detalhes.rede) {
      hardware.append(linha(
        r.adaptador || "adaptador",
        [r.mac, (r.ips || []).join(", ")].filter(Boolean).join(" · ")));
    }
  }

  corpo.append(secao("Hardware", hardware) || el("div", {}));

  // --- 2b. quem já usou -------------------------------------------------
  //
  // Máquina compartilhada tem mais de uma pessoa. A lista guarda todo mundo
  // que já se logou, com a data do último acesso — nada expira.
  if (usuarios.length) {
    const lista = el("div", {});
    for (const u of usuarios) {
      lista.append(el("div", { class: "list-row" },
        el("div", { class: "list-main" },
          el("div", { class: "list-title" }, u.nome),
          el("div", { class: "list-sub" },
            "último acesso em " + dataHora(u.ultimo_login))),
        u.nome === (ficha.usuario_logado || "")
          ? el("span", { class: "chip" }, "atual")
          : el("span", {}, "")));
    }
    corpo.append(secao("Usuários desta máquina", lista) || el("div", {}));
  }


  // --- 3. histórico -----------------------------------------------------
  if (!historico.length) {
    corpo.append(el("div", { class: "card" },
      el("p", { class: "muted", style: "margin:0" },
        "Sem histórico ainda. A primeira coleta registra a linha de base; "
        + "as próximas só geram linha quando o hardware mudar.")));
  } else {
    corpo.append(el("h3", { class: "secao-titulo", style: "margin:18px 0 8px" },
      "Histórico de alterações"));

    for (const h of historico) {
      if (h.linha_de_base) {
        corpo.append(el("div", { class: "list-row" },
          el("div", { class: "list-main" },
            el("div", { class: "list-title" }, "Primeira coleta"),
            el("div", { class: "list-sub" }, dataHora(h.quando))),
          el("span", { class: "chip" }, "base")));
        continue;
      }
      corpo.append(el("div", { class: "card", style: "margin-bottom:8px" },
        el("div", { class: "muted", style: "font-size:12.5px;margin-bottom:6px" },
          dataHora(h.quando)),
        ...(h.mudancas || []).map((m) => el("div", { class: "list-row" },
          el("div", { class: "list-main" },
            el("div", { class: "list-sub" }, m.rotulo || m.campo),
            el("div", { class: "list-title" },
              `${m.de ?? "—"}  →  ${m.para ?? "—"}`)),
          el("span", { class: "chip" }, "alterado"))),
      ));
    }
  }
}
