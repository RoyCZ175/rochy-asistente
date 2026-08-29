// Service worker mínimo — solo existe para que el navegador considere esta
// página "instalable" (requisito técnico de Chrome/Android para el ícono de
// pantalla de inicio). No cachea nada a propósito: el micrófono remoto
// siempre debe hablar con Rochy en vivo, nunca con una versión vieja guardada.
self.addEventListener("install", (event) => {
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  event.respondWith(fetch(event.request));
});
