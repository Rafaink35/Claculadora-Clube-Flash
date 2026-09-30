// Service worker mínimo — só existe pra habilitar "instalar app" no Android/Chrome.
// Não faz cache agressivo de propósito: o Mingo sempre busca resposta nova.
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (event) => event.waitUntil(self.clients.claim()));
self.addEventListener('fetch', () => {}); // necessário existir, mesmo vazio
