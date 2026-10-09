/**
 * Administração → OCS Inventory.
 *
 * Integração com o OCS para trazer o parque de máquinas automaticamente.
 * O token é gravado cifrado no servidor e nunca volta em claro para cá.
 *
 * @module views/admin_ocs
 */
import { api } from "../api.js";
import { el, icon, toast, dialog, emptyState, fmtDate, mostrarErro, skeleton } from "../ui.js";

/** Opção de ligar/desligar, com título e explicação (mesmo padrão do AD). */
function opcao(nome, titulo, dica, marcado) {
  return `
    <label class="opcao">
      <input type="checkbox" name="${nome}" ${marcado ? "checked" : ""}>
      <span class="opcao-texto">
        <span class="opcao-titulo">${titulo}</span>
        ${dica ? `<span class="opcao-dica">${dica}</span>` : ""}
      </span>
    </label>`;
}

const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

export async function renderOCS(root) {
  const cfg = await api.get("/ocs/config").catch((e) => { mostrarErro(e); return {}; });
  const plantas = await api.get("/plantas/opcoes").catch(() => []);

  root.innerHTML = "";

  // ---------------------------------------------------------------- cabeçalho
  root.append(el("div", { class: "card" },
    el("div", { class: "section-title", style: "margin:0" }, "Integração com o OCS Inventory"),
    el("div", { class: "muted", style: "font-size:13px" },
      "O OCS descobre as máquinas da rede e este sistema importa o parque para o "
      + "inventário de ativos. Os dados técnicos (SO, memória, processador, número "
      + "de série) vêm do OCS — enquanto planta, responsável, garantia e patrimônio "
      + "continuam sendo seus, e não são sobrescritos."),
  ));

  const form = el("form", {});
  form.innerHTML = `
    <div class="form-section">
      <div class="row between" style="flex-wrap:wrap;gap:10px;margin-bottom:4px">
        <h4 style="margin:0">Situação</h4>
        <span class="badge ${cfg.ativo ? "ok" : "aviso"}" id="ocs-situacao">${cfg.ativo ? "Ativada" : "Desativada"}</span>
      </div>
      <p class="muted" style="margin:0 0 12px;font-size:13px">
        Enquanto estiver desativada, nenhuma consulta é feita ao OCS.
      </p>
      <div class="opcoes">
        ${opcao("ativo", "Ativar a integração com o OCS",
          "Ligue depois de preencher o endereço e o token, e o teste de conexão passar.",
          cfg.ativo)}
      </div>
    </div>

    <div class="form-section"><h4>Conexão com o servidor do OCS</h4>
      <div class="form-grid">
        <div class="field span-2"><label>Endereço do servidor *</label>
          <input name="servidor" value="${esc(cfg.servidor)}" placeholder="http://ocs-server/ocsinventory">
          <span class="hint">Endereço completo, incluindo a pasta do OCS Inventory.</span></div>
        <div class="field span-2"><label>Token da API</label>
          <input type="password" name="token" placeholder="${cfg.token_definido ? "(definido — deixe vazio para manter)" : "cole aqui o API_TOKEN do servidor OCS"}">
          <span class="hint">${cfg.token_definido
            ? (cfg.token_cifrado ? "Guardado cifrado no banco." : "Atenção: guardado sem cifra.")
            : "Ainda não definido. Fica no arquivo de configuração do servidor OCS."}</span></div>
        <div class="field"><label>Tempo limite (segundos)</label>
          <input type="number" name="timeout_s" value="${cfg.timeout_s ?? 30}" min="5" max="300"></div>
      </div>
      <h5 class="sub-titulo">Segurança da conexão</h5>
      <div class="opcoes">
        ${opcao("verificar_ssl", "Validar o certificado do servidor",
          "Desligue <b>apenas</b> se o OCS usar certificado próprio e a validação impedir a conexão.",
          cfg.verificar_ssl !== false)}
      </div>
    </div>

    <div class="form-section"><h4>Sincronização automática</h4>
      <p class="muted" style="margin:0 0 12px;font-size:13px">
        Com a sincronização ligada, o sistema consulta o OCS sozinho no intervalo
        escolhido — sem ninguém precisar clicar.
      </p>
      <div class="opcoes">
        ${opcao("sync_automatica", "Sincronizar automaticamente",
          "A primeira execução acontece assim que o intervalo for atingido, contando a partir da última sincronização.",
          cfg.sync_automatica)}
      </div>
      <div class="form-grid" style="margin-top:14px">
        <div class="field"><label>De quanto em quanto tempo</label>
          <select name="sync_intervalo" id="ocs-intervalo">
            ${[[15, "A cada 15 minutos"], [30, "A cada 30 minutos"], [60, "A cada 1 hora"],
               [120, "A cada 2 horas"], [240, "A cada 4 horas"], [480, "A cada 8 horas"],
               [720, "A cada 12 horas"], [1440, "Uma vez por dia"]]
              .map(([v, r]) => `<option value="${v}" ${Number(cfg.sync_intervalo_minutos) === v ? "selected" : ""}>${r}</option>`).join("")}
            <option value="personalizado" ${![15, 30, 60, 120, 240, 480, 720, 1440].includes(Number(cfg.sync_intervalo_minutos)) ? "selected" : ""}>Personalizado…</option>
          </select></div>
      </div>
      <div class="form-grid hidden" id="ocs-intervalo-custom" style="margin-top:10px">
        <div class="field"><label>Intervalo personalizado</label>
          <div class="row" style="gap:8px;align-items:flex-start">
            <input type="number" name="sync_custom_valor" min="1" style="max-width:120px"
                   value="${![15, 30, 60, 120, 240, 480, 720, 1440].includes(Number(cfg.sync_intervalo_minutos)) ? Math.max(1, Math.round(Number(cfg.sync_intervalo_minutos) / 60) || 1) : ""}">
            <select name="sync_custom_unidade" style="max-width:150px">
              <option value="minutos">minutos</option>
              <option value="horas">horas</option>
            </select>
          </div>
          <span class="hint">Mínimo de 5 minutos; máximo de 7 dias (10.080 minutos).</span></div>
      </div>
    </div>

    <div class="form-section"><h4>O que fazer ao importar</h4>
      <div class="form-grid">
        <div class="field"><label>Inventário de destino</label>
          <select name="dominio_padrao">
            <option value="ti" ${cfg.dominio_padrao === "ti" ? "selected" : ""}>Ativos de TI</option>
            <option value="impressora" ${cfg.dominio_padrao === "impressora" ? "selected" : ""}>Impressoras</option>
          </select></div>
        <div class="field"><label>Situação inicial dos novos ativos</label>
          <select name="status_padrao">
            ${["estoque", "em_uso", "manutencao", "emprestado", "baixado"]
              .map((s) => `<option value="${s}" ${cfg.status_padrao === s ? "selected" : ""}>${s.replace("_", " ")}</option>`).join("")}
          </select></div>
        <div class="field span-2"><label>Filtrar por hostname (opcional)</label>
          <input name="filtrar_hostname" value="${esc(cfg.filtrar_hostname)}" placeholder="ex.: ^(PC|NB)-">
          <span class="hint">Expressão regular. Em branco importa todas as máquinas do OCS.</span></div>
      </div>
      <h5 class="sub-titulo">Comportamento</h5>
      <div class="opcoes">
        ${opcao("criar_novos", "Cadastrar máquinas que ainda não existem",
          "Desligado, a sincronização só completa dados de ativos já cadastrados.",
          cfg.criar_novos !== false)}
        ${opcao("atualizar_existentes", "Atualizar os dados técnicos dos que já existem",
          "Mexe apenas em SO, memória, processador e rede. Planta, responsável e garantia não são tocados.",
          cfg.atualizar_existentes !== false)}
        ${opcao("ignorar_sem_serial", "Ignorar máquinas sem número de série utilizável",
          "Recomendado. Máquinas virtuais e placas genéricas repetem o mesmo serial falso, "
          + "o que faria várias caírem num cadastro só.",
          cfg.ignorar_sem_serial !== false)}
      </div>
    </div>

    <div class="form-section"><h4>Planta pela rede</h4>
      <p class="muted" style="margin:0 0 6px;font-size:13px">
        O OCS não sabe o que é uma planta. Estas regras descobrem a planta pela
        <b>forma do hostname</b> da máquina. O que não casar com nenhuma regra entra
        <b>sem planta</b>, para você revisar — melhor revisar do que ficar na planta errada.
      </p>
      <p class="muted" style="margin:0 0 12px;font-size:12.5px">
        A <b>primeira regra que casar decide</b>, então a ordem importa.
        Para hostnames como <code>DTAT0001</code> (D = desktop, TAT = planta, 0001 = número),
        use <b>contém</b> com o padrão <code>TAT</code>.
      </p>
      <div id="ocs-regras"></div>
      <button type="button" class="btn tonal small mt" id="ocs-add-regra"
              style="margin-top:10px">+ Adicionar regra</button>
      <div id="ocs-previa" style="margin-top:12px"></div>
    </div>`;

  const resultadoBox = el("div");

  // O distintivo acompanha o interruptor enquanto se edita.
  const interruptor = form.querySelector('[name="ativo"]');
  const distintivo = form.querySelector("#ocs-situacao");
  interruptor?.addEventListener("change", () => {
    const ligado = interruptor.checked;
    distintivo.textContent = ligado ? "Ativada" : "Desativada";
    distintivo.className = `badge ${ligado ? "ok" : "aviso"}`;
  });

  // Intervalo: o seletor traz os múltiplos prontos e uma opção personalizada.
  const campoIntervalo = form.querySelector("#ocs-intervalo");
  const campoCustom = form.querySelector("#ocs-intervalo-custom");
  function alternarCustom() {
    campoCustom.classList.toggle("hidden", campoIntervalo.value !== "personalizado");
  }
  campoIntervalo?.addEventListener("change", alternarCustom);
  alternarCustom();

  /** Intervalo final em MINUTOS — o sistema guarda sempre nesta unidade. */
  function intervaloEmMinutos(fd) {
    if (campoIntervalo.value !== "personalizado") return Number(campoIntervalo.value) || 60;
    const valor = Number(fd.get("sync_custom_valor")) || 1;
    const minutos = fd.get("sync_custom_unidade") === "horas" ? valor * 60 : valor;
    // O servidor recusa fora de 5 min – 7 dias; aqui já avisamos antes.
    return Math.min(10080, Math.max(5, Math.round(minutos)));
  }

  // ------------------------------------------------------------ regras de planta
  const caixaRegras = form.querySelector("#ocs-regras");
  let regras = Array.isArray(cfg.regras_planta) ? [...cfg.regras_planta] : [];

  function desenharRegras() {
    caixaRegras.innerHTML = "";
    if (!regras.length) {
      caixaRegras.append(el("p", { class: "muted", style: "font-size:13px;margin:0" },
        "Nenhuma regra. Todas as máquinas entrarão sem planta."));
      return;
    }
    regras.forEach((r, i) => {
      const tipo = el("select", { class: "regra-tipo" },
        ...[["comeca_com", "hostname começa com"], ["contem", "hostname contém"], ["regex", "hostname casa a expressão"]]
          .map(([v, rot]) => el("option", { value: v, ...((r.tipo || "comeca_com") === v ? { selected: "" } : {}) }, rot)));
      const prefixo = el("input", {
        value: r.prefixo || "",
        placeholder: (r.tipo === "contem") ? "ex.: TAT" : (r.tipo === "regex" ? "^[DNR]TAT\\d+$" : "ex.: PC-BNT-"),
      });
      const planta = el("select", {},
        el("option", { value: "" }, "— escolha —"),
        ...plantas.map((p) => el("option", { value: p.id, ...(Number(r.planta_id) === p.id ? { selected: "" } : {}) },
          `${p.sigla} — ${p.nome}`)));

      prefixo.addEventListener("input", () => { regras[i].prefixo = prefixo.value; });
      planta.addEventListener("change", () => { regras[i].planta_id = Number(planta.value) || null; });
      tipo.addEventListener("change", () => {
        regras[i].tipo = tipo.value;
        // O exemplo muda junto com o tipo escolhido.
        prefixo.placeholder = tipo.value === "contem" ? "ex.: TAT"
          : tipo.value === "regex" ? "^[DNR]TAT\\d+$" : "ex.: PC-BNT-";
      });

      caixaRegras.append(el("div", { class: "regra-linha" },
        tipo,
        prefixo,
        el("span", { class: "muted", style: "font-size:12.5px" }, "→ planta"),
        planta,
        el("button", { class: "iconbtn", type: "button", title: "Remover",
          onclick: () => { regras.splice(i, 1); desenharRegras(); },
          html: icon("trash", 18) }),
      ));
    });
  }
  form.querySelector("#ocs-add-regra").addEventListener("click", () => {
    regras.push({ prefixo: "", planta_id: null });
    desenharRegras();
  });
  desenharRegras();

  // ------------------------------------------------------------------- salvar
  function payload() {
    const fd = new FormData(form);
    const dados = {
      ativo: Boolean(fd.get("ativo")),
      servidor: fd.get("servidor") || null,
      verificar_ssl: Boolean(fd.get("verificar_ssl")),
      timeout_s: Number(fd.get("timeout_s")) || 30,
      sync_automatica: Boolean(fd.get("sync_automatica")),
      sync_intervalo_minutos: intervaloEmMinutos(fd),
      criar_novos: Boolean(fd.get("criar_novos")),
      atualizar_existentes: Boolean(fd.get("atualizar_existentes")),
      ignorar_sem_serial: Boolean(fd.get("ignorar_sem_serial")),
      dominio_padrao: fd.get("dominio_padrao") || "ti",
      status_padrao: fd.get("status_padrao") || "estoque",
      filtrar_hostname: fd.get("filtrar_hostname") || null,
      regras_planta: regras.filter((r) => (r.prefixo || "").trim() && r.planta_id),
    };
    const token = fd.get("token");
    if (token) dados.token = token;
    return dados;
  }

  async function salvar() {
    await api.put("/ocs/config", payload());
    toast("Configuração salva");
  }

  function mostrarResultado(r) {
    resultadoBox.innerHTML = "";
    const cor = r.sucesso === false || r.ok === false ? "var(--md-sys-color-error)" : "var(--cor-ok)";
    resultadoBox.append(el("p", { style: `font-weight:600;color:${cor};margin:12px 0 6px` },
      (r.sucesso === false || r.ok === false ? "✗ " : "✓ ") + (r.mensagem || "")));

    if (r.novas !== undefined) {
      resultadoBox.append(el("div", { class: "row", style: "gap:8px;flex-wrap:wrap" },
        ...[["Novas", r.novas], ["Atualizadas", r.atualizadas], ["Ignoradas", r.ignoradas],
            ["Sem planta", r.sem_planta], ["Erros", r.erros]]
          .map(([k, v]) => el("span", { class: "chip" }, `${k}: ${v}`))));
    }
    (r.avisos || []).forEach((a) => resultadoBox.append(el("p", { class: "muted", style: "font-size:12.5px" }, `⚠ ${a}`)));

    if ((r.detalhes || []).length) {
      const linhas = r.detalhes.slice(0, 60).map((d) =>
        el("div", { class: "row between", style: "border-bottom:1px solid var(--md-sys-color-outline-variant);padding:6px 0;font-size:12.5px" },
          el("span", {}, d.hostname || "—"),
          el("span", { class: "muted" },
            d.acao + (d.motivo ? ` (${d.motivo})` : "") + (d.sem_planta ? " · sem planta" : ""))));
      resultadoBox.append(el("details", { style: "margin-top:10px" },
        el("summary", { class: "muted" }, `${r.detalhes.length} máquina(s) no detalhe`),
        el("div", { style: "margin-top:8px" }, ...linhas)));
    }
  }

  async function acao(rotulo, fn) {
    const botaoOriginal = resultadoBox.querySelector("button");
    try {
      botaoOriginal && (botaoOriginal.disabled = true);
      mostrarResultado(await fn());
    } catch (e) {
      mostrarErro(e, rotulo);
    }
  }

  root.append(el("div", { class: "card" }, form,
    el("div", { class: "row", style: "gap:10px;margin-top:8px;flex-wrap:wrap" },
      el("button", { class: "btn filled", type: "button", onclick: async () => {
        try { await salvar(); } catch (e) { mostrarErro(e); }
      }, html: icon("check", 18) + " Salvar" }),
      el("button", { class: "btn outlined", type: "button", onclick: async () => {
        try { await salvar(); mostrarResultado(await api.post("/ocs/testar")); } catch (e) { mostrarErro(e); }
      }, html: icon("server", 18) + " Testar conexão" }),
      el("button", { class: "btn tonal", type: "button", onclick: async () => {
        try { await salvar(); mostrarResultado(await api.post("/ocs/simular")); } catch (e) { mostrarErro(e); }
      }, html: icon("search", 18) + " Simular" }),
      el("button", { class: "btn tonal", type: "button", onclick: async () => {
        const ok = confirm("Sincronizar agora? Os ativos serão criados e atualizados.");
        if (!ok) return;
        try { await salvar(); mostrarResultado(await api.post("/ocs/sincronizar")); } catch (e) { mostrarErro(e); }
      }, html: icon("refresh", 18) + " Sincronizar agora" }),
    ),
    resultadoBox,
  ));

  // -------------------------------------------------------------- prévia regras
  const caixaPrevia = form.querySelector("#ocs-previa");
  root.append(el("div", { class: "card" },
    el("div", { class: "row between", style: "flex-wrap:wrap;gap:10px" },
      el("div", {},
        el("div", { class: "section-title", style: "margin:0" }, "Conferir as regras"),
        el("div", { class: "muted", style: "font-size:13px" },
          "Mostra quantas máquinas do OCS casariam com cada regra — antes de sincronizar.")),
      el("button", { class: "btn outlined small", type: "button", onclick: async (ev) => {
        caixaPrevia.innerHTML = "";
        caixaPrevia.append(skeleton(2));
        try {
          const r = await api.get("/ocs/previa-regras");
          caixaPrevia.innerHTML = "";
          caixaPrevia.append(el("p", { class: "muted", style: "font-size:13px" },
            `${r.total_ocs} máquina(s) no OCS.`));
          (r.por_regra || []).forEach((x) => caixaPrevia.append(
            el("div", { class: "row between", style: "border-bottom:1px solid var(--md-sys-color-outline-variant);padding:8px 0" },
              el("span", {}, `${x.prefixo} → ${x.planta_sigla || "?"}`),
              el("span", { class: "badge ok" }, `${x.maquinas}`))));
          if (r.sem_regra) {
            caixaPrevia.append(el("p", { style: "margin:10px 0 0;font-size:13px" },
              `${r.sem_regra} máquina(s) não casam com nenhuma regra e entrarão sem planta.`));
            if ((r.exemplos_sem_regra || []).length) {
              caixaPrevia.append(el("p", { class: "muted", style: "font-size:12.5px" },
                `Exemplos: ${r.exemplos_sem_regra.join(", ")}`));
            }
          }
        } catch (e) { caixaPrevia.innerHTML = ""; mostrarErro(e, "consultar a prévia"); }
      }, html: icon("search", 16) + " Conferir agora" }),
    ),
    caixaPrevia,
  ));

  // ------------------------------------------------------------------ histórico
  const hist = el("div", {});
  root.append(el("div", { class: "card" },
    el("div", { class: "section-title", style: "margin:0 0 10px" }, "Histórico de sincronizações"),
    hist,
  ));

  try {
    const h = await api.get("/ocs/historico", { limite: 20 });
    if (!h.itens.length) {
      hist.append(el("p", { class: "muted", style: "font-size:13px" }, "Nenhuma sincronização registrada ainda."));
    } else {
      h.itens.forEach((i) => hist.append(
        el("div", { class: "row between", style: "border-bottom:1px solid var(--md-sys-color-outline-variant);padding:9px 0;font-size:13px" },
          el("div", {},
            el("div", {}, `${fmtDate(i.criado_em, true)} · ${i.origem}`),
            el("div", { class: "muted", style: "font-size:12px" },
              `${i.novas} nova(s) · ${i.atualizadas} atualizada(s) · ${i.ignoradas} ignorada(s)`
              + (i.sem_planta ? ` · ${i.sem_planta} sem planta` : "")
              + (i.erros ? ` · ${i.erros} erro(s)` : "")
              + ` · ${i.duracao_ms} ms`)),
          el("span", { class: `badge ${i.sucesso ? "ok" : ""}` }, i.sucesso ? "ok" : "falha"))));
    }
  } catch (e) {
    hist.append(el("p", { class: "text-error" }, e.message));
  }

  // Diagnóstico rápido quando nada foi configurado ainda.
  if (!cfg.ultimo_teste_msg && !cfg.servidor) {
    root.append(el("div", { class: "card" },
      el("p", { class: "muted", style: "margin:0;font-size:13px" },
        "Comece preenchendo o endereço do servidor e o token da API, clique em "
        + "Salvar e depois em Testar conexão. Só então ligue a integração.")));
  }
}
