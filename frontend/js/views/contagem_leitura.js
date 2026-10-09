/**
 * Modo leitura da contagem — conferência física em sequência.
 *
 * É a tela que o técnico usa **de pé, com o celular na mão, andando pelo
 * setor**. Isso define cada decisão aqui:
 *
 * * o campo fica **sempre em foco** — não se toca na tela entre uma leitura e
 *   outra;
 * * leitor Bluetooth funciona sozinho, porque ele digita o código e manda
 *   **Enter**, como um teclado;
 * * o retorno é **grande e colorido**, porque o técnico olha de relance, e não
 *   parado;
 * * há **som**, porque muitas vezes ele não olha a tela;
 * * quando a rede falha, a leitura **não se perde**: entra numa fila local e
 *   pode ser reenviada.
 *
 * @module views/contagem_leitura
 */
import { api } from "../api.js";
import { el, icon, toast, confirmSheet, mostrarErro, fmtDate } from "../ui.js";

const MAX_ULTIMAS = 40;

/** Bipe curto. Grave = problema, agudo = tudo certo. */
function bipe(tom) {
  try {
    const Ctx = window.AudioContext || window.webkitAudioContext;
    if (!Ctx) return;
    const ctx = new Ctx();
    const osc = ctx.createOscillator();
    const vol = ctx.createGain();
    osc.connect(vol);
    vol.connect(ctx.destination);
    osc.frequency.value = tom === "erro" ? 220 : tom === "aviso" ? 440 : 880;
    vol.gain.setValueAtTime(0.12, ctx.currentTime);
    vol.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.16);
    osc.start();
    osc.stop(ctx.currentTime + 0.16);
    osc.onended = () => ctx.close();
  } catch {
    // Som é reforço, não requisito: sem áudio a leitura continua funcionando.
  }
}

export function abrirLeitura(contagem) {
  const pendentes = [];   // leituras que a rede recusou, aguardando reenvio
  const ultimas = [];

  const overlay = el("div", { class: "tela-cheia leitura" });
  const entrada = el("input", {
    class: "leitura-campo",
    placeholder: "Escaneie o código…",
    autocomplete: "off",
    autocorrect: "off",
    spellcheck: "false",
    inputmode: "text",
  });
  const contador = el("div", { class: "leitura-contador" }, "0");
  const veredito = el("div", { class: "leitura-veredito" });
  const lista = el("div", { class: "leitura-ultimas" });
  const statusRede = el("div", { class: "leitura-rede oculto" });

  const fechar = () => {
    pararCamera();
    overlay.remove();
    document.removeEventListener("keydown", esc);
  };
  const esc = (e) => {
    if (e.key === "Escape" && document.activeElement !== entrada) fechar();
  };
  document.addEventListener("keydown", esc);

  // Um toque em qualquer lugar devolve o foco ao campo: no corredor ninguém
  // vai acertar o campo com o dedo.
  overlay.addEventListener("click", (e) => {
    if (!e.target.closest("button")) entrada.focus();
  });

  // -------------------------------------------------------------------------
  function mostrarVeredito(tipo, titulo, detalhe) {
    veredito.className = `leitura-veredito ${tipo} visivel`;
    veredito.innerHTML = "";
    veredito.append(
      el("span", { class: "leitura-icone", html: icon(tipo === "erro" ? "close" : tipo === "aviso" ? "historico" : "check", 34) }),
      el("span", {},
        el("b", {}, titulo),
        detalhe ? el("span", { class: "leitura-detalhe" }, detalhe) : null,
      ),
    );
    // Volta ao neutro sozinho, para a tela não ficar "presa" no último item.
    clearTimeout(mostrarVeredito._t);
    mostrarVeredito._t = setTimeout(() => veredito.classList.remove("visivel"), 2200);
  }

  async function enviar(codigo) {
    try {
      const r = await api.post(`/contagens/${contagem.id}/ler`, { codigo });
      contador.textContent = String(r.total_lidos ?? ultimas.length + 1);

      const tipo = r.repetido ? "aviso" : r.item.resultado === "nao_cadastrado" ? "aviso" : "ok";
      bipe(tipo);
      mostrarVeredito(tipo, r.mensagem, r.item.codigo_lido);

      ultimas.unshift({
        codigo: r.item.codigo_lido,
        resultado: r.item.resultado,
        repetido: r.repetido,
        patrimonio: r.item.ativo_patrimonio,
        hora: new Date().toISOString(),
      });
      desenharUltimas();
    } catch (e) {
      // A leitura não se perde: entra na fila local.
      pendentes.push(codigo);
      bipe("erro");
      mostrarVeredito("erro", "Sem conexão — leitura guardada", `${pendentes.length} para reenviar`);
      atualizarStatusRede();
      desenharUltimas();
      // Um erro de validação (código vazio, contagem fechada) não é fila:
      // nesse caso avisar é mais útil que silenciar.
      if (e?.status && e.status < 500 && e.status !== 0) {
        pendentes.pop();
        mostrarErro(e);
      }
    }
  }

  async function reenviarPendentes() {
    if (!pendentes.length) return;
    toast(`Reenviando ${pendentes.length} leitura(s)…`);
    let ok = 0;
    while (pendentes.length) {
      const codigo = pendentes[0];
      try {
        const r = await api.post(`/contagens/${contagem.id}/ler`, { codigo });
        contador.textContent = String(r.total_lidos ?? "");
        pendentes.shift();
        ok++;
      } catch {
        break; // continua sem rede: para e tenta de novo depois
      }
    }
    atualizarStatusRede();
    desenharUltimas();
    if (ok) toast(`${ok} leitura(s) reenviada(s)`);
  }

  function atualizarStatusRede() {
    if (!pendentes.length) {
      statusRede.classList.add("oculto");
      return;
    }
    statusRede.classList.remove("oculto");
    statusRede.innerHTML = "";
    statusRede.append(
      el("span", {}, `${pendentes.length} leitura(s) aguardando conexão`),
      el("button", { class: "btn tonal", onclick: reenviarPendentes }, "Reenviar agora"),
    );
  }

  function desenharUltimas() {
    lista.innerHTML = "";
    if (!ultimas.length && !pendentes.length) {
      lista.append(el("p", { class: "muted", style: "margin:0;text-align:center" },
        "As leituras aparecem aqui."));
      return;
    }
    // Pendentes primeiro: o técnico precisa ver o que ainda não subiu.
    for (const codigo of pendentes) {
      lista.append(linha("aviso", "aguardando envio", codigo));
    }
    for (const u of ultimas.slice(0, MAX_ULTIMAS)) {
      const tipo = u.repetido ? "aviso" : u.resultado === "nao_cadastrado" ? "aviso" : "ok";
      const rotulo = u.repetido ? "já lido" : u.resultado === "nao_cadastrado" ? "não cadastrado" : "conforme";
      lista.append(linha(tipo, rotulo, u.patrimonio || u.codigo, u.hora));
    }
  }

  function linha(tipo, rotulo, texto, hora) {
    return el("div", { class: `leitura-linha ${tipo}` },
      el("span", { class: "leitura-linha-icone", html: icon(tipo === "ok" ? "check" : "historico", 16) }),
      el("b", {}, texto),
      el("span", { class: "leitura-linha-rotulo" }, rotulo),
      hora ? el("span", { class: "muted leitura-hora" }, fmtDate(hora, true)) : null,
    );
  }

  // -------------------------------------------------------------------------
  // Câmera (alternativa ao leitor Bluetooth)
  let cameraAtiva = false;
  let stream = null;

  function pararCamera() {
    if (stream) { stream.getTracks().forEach((t) => t.stop()); stream = null; }
    cameraAtiva = false;
  }

  async function abrirCamera() {
    dataUpload.classList.add("oculto");
    camera.classList.remove("oculto");
    try {
      stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "environment" } });
      video.srcObject = stream;
      await video.play();
      cameraAtiva = true;
      if ("BarcodeDetector" in window) {
        const detector = new window.BarcodeDetector({ formats: ["qr_code", "code_128", "ean_13"] });
        const varrer = async () => {
          if (!cameraAtiva) return;
          try {
            const codigos = await detector.detect(video);
            if (codigos.length) {
              entrada.value = codigos[0].rawValue;
              await processar();
            }
          } catch { /* quadro sem leitura: segue */ }
          if (cameraAtiva) requestAnimationFrame(varrer);
        };
        requestAnimationFrame(varrer);
      } else {
        toast("Este navegador não lê código pela câmera. Use o leitor ou digite.");
      }
    } catch {
      toast("Não foi possível abrir a câmera");
      fechaCamera();
    }
  }

  function fechaCamera() {
    pararCamera();
    camera.classList.add("oculto");
    dataUpload.classList.remove("oculto");
    entrada.focus();
  }

  async function processar() {
    const codigo = entrada.value.trim();
    entrada.value = "";
    if (!codigo) return;
    await enviar(codigo);
    entrada.focus();
  }

  entrada.addEventListener("keydown", (e) => {
    // Leitor Bluetooth manda Enter ao final do código.
    if (e.key === "Enter") { e.preventDefault(); processar(); }
  });
  // Se o leitor "colar" o código sem Enter, um pequeno silêncio fecha a leitura.
  let tCola = null;
  entrada.addEventListener("input", () => {
    clearTimeout(tCola);
    if (!entrada.value.trim()) return;
    tCola = setTimeout(() => { if (entrada.value.trim().length >= 6) processar(); }, 350);
  });

  const video = el("video", { class: "leitura-video", playsinline: true, muted: true });
  const camera = el("div", { class: "leitura-camera oculto" }, video);
  const dataUpload = el("div", { class: "leitura-data" });

  overlay.append(
    el("header", { class: "tela-cheia-topo" },
      el("button", { class: "iconbtn", onclick: fechar, html: icon("close", 22), title: "Sair da leitura" }),
      el("b", {}, contagem.nome),
      el("div", { class: "spacer" }),
      el("button", { class: "btn tonal", onclick: () => (cameraAtiva ? fechaCamera() : abrirCamera()),
        html: icon("scanner", 18) + " Câmera" }),
    ),

    el("div", { class: "leitura-corpo" },
      el("div", { class: "leitura-progresso" },
        contador,
        el("span", { class: "leitura-progresso-rotulo" },
          contagem.esperados ? `de ${contagem.esperados} esperados` : "lidos"),
      ),

      statusRede,
      camera,
      dataUpload,
      veredito,

      el("div", { class: "leitura-lista" }, lista),
    ),
  );

  document.body.append(overlay);
  entrada.focus();

  // Contagem inicial, caso a sessão já tenha leituras.
  api.get(`/contagens/${contagem.id}`)
    .then((c) => { contador.textContent = String(c.lidos ?? 0); })
    .catch(() => {});

  desenharUltimas();
}
