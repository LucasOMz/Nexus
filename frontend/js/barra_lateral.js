/**
 * Barra lateral: favoritos e ordem.
 *
 * São **duas preferências separadas**, e é isso que faz a tela se comportar
 * como o usuário espera:
 *
 * * `barra_favoritos` — **quais** módulos aparecem na barra lateral rápida.
 * * `barra_ordem` — a ordem da **lista inteira** da gaveta.
 *
 * A ordem da barra lateral é derivada: é a ordem da gaveta filtrada pelos
 * favoritos. Assim, reordenar um item que **não** é favorito também é
 * respeitado — e a barra continua coerente com o que se vê na gaveta.
 *
 * Guardar as duas num campo só (como estava) fazia a posição dos itens não
 * favoritados se perder a cada reabertura.
 *
 * Tudo é gravado **no banco**, junto do usuário: entrando de outro computador,
 * a barra vem do jeito que ele deixou.
 *
 * @module barra_lateral
 */
import { api } from "./api.js";
import { state } from "./state.js";

/** Módulos favoritos do usuário logado. */
export function favoritos() {
  const lista = state.user?.barra_favoritos;
  return Array.isArray(lista) ? lista : [];
}

/** Ordem completa da gaveta escolhida pelo usuário. */
export function ordem() {
  const lista = state.user?.barra_ordem;
  return Array.isArray(lista) ? lista : [];
}

/** Este módulo está favoritado? */
export function ehFavorito(chave) {
  return favoritos().includes(chave);
}

/**
 * Aplica a ordem escolhida a uma lista de módulos.
 *
 * Módulos que ainda não estão na ordem salva (uma aba recém-criada, por
 * exemplo) vão para o fim, sem bagunçar o que já estava organizado.
 */
export function ordenarModulos(chaves) {
  const salva = ordem();
  if (!salva.length) return chaves;
  const conhecidos = salva.filter((c) => chaves.includes(c));
  const novos = chaves.filter((c) => !conhecidos.includes(c));
  return [...conhecidos, ...novos];
}

/** Os favoritos, na ordem da gaveta. É o que a barra lateral mostra. */
export function favoritosOrdenados(disponiveis) {
  return ordenarModulos(disponiveis).filter((c) => ehFavorito(c));
}

/** Marca/desmarca um módulo. */
export async function alternar(chave) {
  const atuais = favoritos();
  const novo = atuais.includes(chave)
    ? atuais.filter((c) => c !== chave)
    : [...atuais, chave];
  await gravar({ barra_favoritos: novo });
  return novo.includes(chave);
}

/** Grava a ordem da lista inteira da gaveta. */
export async function definirOrdem(lista) {
  const limpa = lista.filter((c) => typeof c === "string" && c);
  await gravar({ barra_ordem: limpa });
}

/**
 * Envia as preferências ao servidor.
 *
 * Atualiza a tela **na hora** e grava em segundo plano: esperar a rede para
 * pintar a estrela deixaria o clique com cara de travado. Se a gravação
 * falhar, o estado local volta ao que era — a tela não mente sobre o que foi
 * salvo.
 */
async function gravar(mudancas) {
  const antes = {
    barra_favoritos: state.user?.barra_favoritos,
    barra_ordem: state.user?.barra_ordem,
  };

  if (state.user) {
    for (const [campo, valor] of Object.entries(mudancas)) state.user[campo] = valor;
  }

  try {
    const r = await api.put("/auth/preferencias", mudancas);
    if (state.user && r) {
      if (Array.isArray(r.barra_favoritos)) state.user.barra_favoritos = r.barra_favoritos;
      if (Array.isArray(r.barra_ordem)) state.user.barra_ordem = r.barra_ordem;
    }
  } catch (e) {
    if (state.user) Object.assign(state.user, antes);
    throw e;
  }
}
