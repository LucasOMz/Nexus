/* =====================================================================
   Service Worker — PWA offline-first
   Versao: v3

   IMPORTANTE: sempre que o frontend mudar, AUMENTE este numero.
   Ao mudar a versao, o SW novo assume o controle, apaga os caches
   antigos e a pagina se recarrega sozinha (ver app.js).

   Estrategia: NETWORK-FIRST para tudo que e same-origin.
   Assim o usuario sempre recebe a versao nova quando esta online, e o
   cache continua servindo como reserva quando esta offline.
   (cache-first causava o site ficar preso em uma versao antiga)
   ===================================================================== */
const VERSION = "v123";
const CACHE = `patrimonio-${VERSION}`;
const CORE = ["/", "/index.html", "/styles.css", "/app.js", "/manifest.json"];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE)
      .then((cache) => cache.addAll(CORE).catch(() => undefined))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

/** Permite que a pagina peca a ativacao imediata de um SW novo. */
self.addEventListener("message", (event) => {
  if (event.data === "skip-waiting") self.skipWaiting();
});

self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.method !== "GET" || !request.url.startsWith("http")) return;

  const url = new URL(request.url);
  // Nao intercepta o proprio SW nem origens externas.
  if (url.origin !== self.location.origin || url.pathname === "/sw.js") return;

  const isApi = url.pathname.startsWith("/api/");
  const isNavegacao = request.mode === "navigate";

  event.respondWith(
    fetch(request)
      .then((res) => {
        // Guarda copia para uso offline (exceto respostas de erro).
        //
        // NUNCA guardamos /api/: a resposta e especifica do usuario (leva o token
        // no cabecalho) e muda o tempo todo. Cachear aqui fazia a tela exibir
        // dado velho de outra sessao. API e sempre rede; sem rede, avisa.
        if (!isApi && res && res.ok) {
          const copy = res.clone();
          caches.open(CACHE).then((cache) => cache.put(request, copy)).catch(() => undefined);
        }
        return res;
      })
      .catch(async () => {
        // A API nunca vem do cache: devolve erro claro para a tela avisar.
        if (isApi) {
          return new Response(JSON.stringify({ detail: "Sem conexao com o servidor" }), {
            status: 503,
            headers: { "Content-Type": "application/json" },
          });
        }
        const cached = await caches.match(request);
        if (cached) return cached;
        // Navegacao offline sem cache: devolve a pagina principal.
        if (isNavegacao) {
          const raiz = await caches.match("/");
          if (raiz) return raiz;
        }
        return new Response("Offline", { status: 503, headers: { "Content-Type": "text/plain" } });
      })
  );
});
