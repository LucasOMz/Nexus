/**
 * Reordenação por "clique e segure".
 *
 * Segurar um item por um instante o levanta como uma **janelinha flutuante**
 * que acompanha o dedo (ou o mouse). Arrastar para cima e para baixo
 * reposiciona a lista; soltar grava a nova ordem.
 *
 * Duas decisões que fazem a diferença na prática:
 *
 * 1. Os eventos de movimento e soltura são ouvidos no **documento**, não na
 *    lista. Presos à lista, o arraste "morria" assim que o dedo saía dela —
 *    era o que deixava a reação travada.
 * 2. O item segue o dedo **sem esperar pelo próximo quadro**: a posição é
 *    escrita direto no `pointermove`.
 *
 * @module ordenar
 */

/** Quanto tempo segurar antes de "levantar" o item (ms). */
const SEGURAR_MS = 260;
/** Movimento que cancela a espera: se mexeu, era rolagem ou clique. */
const TOLERANCIA_PX = 10;

/**
 * Torna uma lista reordenável por clique e segure.
 *
 * @param {HTMLElement} container lista que contém os itens
 * @param {string} seletorItem seletor dos itens que podem ser arrastados
 * @param {(ordem: string[]) => void} aoSoltar recebe a ordem final (pelas chaves)
 * @param {(el: HTMLElement) => string} chaveDe extrai a chave de um item
 */
export function permitirReordenar(container, seletorItem, aoSoltar, chaveDe) {
  let timer = null;
  let origem = null;        // elemento pressionado
  let clone = null;         // janelinha flutuante
  let deslocamentoY = 0;    // onde, dentro do item, o dedo tocou
  let arrastando = false;
  let inicio = null;
  let pointerId = null;

  const itens = () => [...container.querySelectorAll(seletorItem)];

  function removerOuvintes() {
    document.removeEventListener("pointermove", aoMover, true);
    document.removeEventListener("pointerup", finalizar, true);
    document.removeEventListener("pointercancel", limpar, true);
  }

  function limpar() {
    clearTimeout(timer);
    timer = null;
    if (clone) { clone.remove(); clone = null; }
    origem?.classList.remove("arrastando");
    container.classList.remove("reordenando");
    document.body.classList.remove("arrastando-item");
    removerOuvintes();
    origem = null;
    inicio = null;
    pointerId = null;
    arrastando = false;
  }

  /** Cria a janelinha flutuante que segue o ponteiro. */
  function levantar(item, x, y) {
    const caixa = item.getBoundingClientRect();
    deslocamentoY = y - caixa.top;

    clone = item.cloneNode(true);
    clone.classList.add("item-flutuante");
    clone.classList.remove("arrastando");
    Object.assign(clone.style, {
      position: "fixed",
      left: `${caixa.left}px`,
      top: `${caixa.top}px`,
      width: `${caixa.width}px`,
      height: `${caixa.height}px`,
      pointerEvents: "none",
      zIndex: "3000",
      margin: "0",
    });
    document.body.append(clone);

    item.classList.add("arrastando");
    container.classList.add("reordenando");
    // Enquanto arrasta, o texto não fica selecionado sem querer.
    document.body.classList.add("arrastando-item");
    arrastando = true;
  }

  /** Move o item de lugar conforme o ponteiro passa por cima dos outros. */
  function reposicionar(y) {
    if (!clone || !origem) return;
    clone.style.top = `${y - deslocamentoY}px`;

    const outros = itens().filter((i) => i !== origem);
    for (const outro of outros) {
      const c = outro.getBoundingClientRect();
      if (y < c.top + c.height / 2) {
        // O dedo passou do meio deste item: sobe para antes dele.
        if (outro.previousElementSibling !== origem) container.insertBefore(origem, outro);
        return;
      }
    }
    const ultimo = outros[outros.length - 1];
    if (ultimo && ultimo.nextElementSibling !== origem) {
      container.insertBefore(origem, ultimo.nextElementSibling);
    }
  }

  function aoMover(ev) {
    if (!origem) return;

    if (!arrastando) {
      // Mexeu antes de segurar o tempo: era rolagem/clique, não arraste.
      if (Math.abs(ev.clientX - inicio.x) > TOLERANCIA_PX
        || Math.abs(ev.clientY - inicio.y) > TOLERANCIA_PX) {
        clearTimeout(timer);
        timer = null;
        origem = null;
        removerOuvintes();
      }
      return;
    }

    // Segura a rolagem da página enquanto o item está na mão.
    ev.preventDefault();
    reposicionar(ev.clientY);
  }

  /**
   * Solta o item e entrega a ordem final.
   *
   * ATENÇÃO ao nome: esta função NÃO pode se chamar `aoSoltar`. Ela já se
   * chamou assim — igual ao parâmetro — e em JavaScript a declaração de função
   * sobrescreve o parâmetro de mesmo nome. O resultado era uma chamada
   * recursiva que retornava na hora: o arraste funcionava na tela e a ordem
   * nunca era gravada, **sem erro nenhum aparecer**.
   */
  function finalizar() {
    if (!arrastando) { limpar(); return; }
    const ordem = itens().map((el) => chaveDe(el)).filter(Boolean);
    limpar();
    aoSoltar(ordem);
  }

  container.addEventListener("pointerdown", (ev) => {
    if (ev.button !== undefined && ev.button !== 0) return;   // só botão principal
    const item = ev.target.closest?.(seletorItem);
    if (!item || !container.contains(item)) return;
    // A estrela segue o caminho normal: quem clica nela quer favoritar.
    if (ev.target.closest("button.favorito")) return;

    origem = item;
    inicio = { x: ev.clientX, y: ev.clientY };
    pointerId = ev.pointerId;

    // Os ouvintes vão para o documento: presos à lista, o arraste morria ao
    // sair dela.
    document.addEventListener("pointermove", aoMover, true);
    document.addEventListener("pointerup", finalizar, true);
    document.addEventListener("pointercancel", limpar, true);

    timer = setTimeout(() => {
      timer = null;
      if (!origem) return;
      try { item.setPointerCapture?.(pointerId); } catch { /* opcional */ }
      levantar(item, inicio.x, inicio.y);
      // Vibração curta no celular: confirma que o item foi pego.
      navigator.vibrate?.(15);
    }, SEGURAR_MS);
  });

  // O item na mão não pode ser "clicado" ao soltar: sem isto, soltar sobre a
  // própria linha navegaria para o módulo.
  container.addEventListener("click", (ev) => {
    if (ev.target.closest?.(".drawer-linha.arrastando")) {
      ev.preventDefault();
      ev.stopPropagation();
    }
  }, true);
}
