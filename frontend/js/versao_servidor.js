/**
 * Verificação de versão entre o que está no NAVEGADOR e o que o SERVIDOR roda.
 *
 * Por que isto existe: quando o servidor é iniciado antes de uma atualização,
 * ele continua servindo o código antigo. O sintoma é confuso — um recurso novo
 * responde "Method Not Allowed" (405), como se a rota não existisse, quando na
 * verdade o processo é que é velho. Aconteceu três vezes.
 *
 * Aqui comparamos a versão do frontend (`APP_VERSION`) com a que o servidor
 * informa em `/health`. Se forem diferentes, avisamos de forma clara em vez de
 * deixar o usuário procurar um bug que não existe.
 *
 * @module versao_servidor
 */
import { APP_VERSION } from "./version.js";

/** Busca a versão do servidor e avisa se estiver diferente do frontend. */
export async function conferirVersaoDoServidor() {
  let versaoServidor;
  try {
    const resp = await fetch("/health", { cache: "no-store" });
    if (!resp.ok) return;
    versaoServidor = (await resp.json()).version;
  } catch {
    return; // sem resposta agora; não vale a pena incomodar o usuário
  }
  if (!versaoServidor || versaoServidor === APP_VERSION) return;

  const aviso = document.createElement("div");
  aviso.className = "aviso-servidor";
  aviso.innerHTML = `
    <strong>Servidor desatualizado</strong>
    <span>O navegador está na versão ${APP_VERSION}, mas o servidor roda a ${versaoServidor}.
    Recursos novos podem falhar (erros como “Method Not Allowed”).</span>
    <span class="aviso-servidor-dica">Pare o servidor e rode o <code>run.bat</code> novamente.</span>
    <button type="button" title="Fechar" aria-label="Fechar">&times;</button>`;
  aviso.querySelector("button").addEventListener("click", () => aviso.remove());
  document.body.append(aviso);
}
