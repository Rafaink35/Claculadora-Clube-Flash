let historico = [];

if ('serviceWorker' in navigator) {
  navigator.serviceWorker.register('/static/sw.js').catch(() => {});
}

const chatMessages = document.getElementById('chatMessages');
const chatForm = document.getElementById('chatForm');
const chatInput = document.getElementById('chatInput');
const sendBtn = document.getElementById('sendBtn');
const suggestions = document.getElementById('suggestions');

function renderMensagem(role, texto, thinking = false){
  const div = document.createElement('div');
  div.className = `msg ${role}` + (thinking ? ' thinking' : '');
  div.textContent = texto;
  chatMessages.appendChild(div);
  chatMessages.scrollTop = chatMessages.scrollHeight;
  return div;
}

function escapeHtml(texto){
  const div = document.createElement('div');
  div.textContent = String(texto ?? '');
  return div.innerHTML;
}

function renderCtaComercial(motivo){
  const wrapper = document.createElement('div');
  wrapper.className = 'msg assistant cta-comercial';
  const btn = document.createElement('button');
  btn.type = 'button';
  btn.className = 'cta-comercial-btn';
  btn.textContent = '📞 Falar com um comercial';
  wrapper.appendChild(btn);
  chatMessages.appendChild(wrapper);
  chatMessages.scrollTop = chatMessages.scrollHeight;

  btn.addEventListener('click', () => {
    btn.disabled = true;
    wrapper.remove();
    enviarMensagem(`Quero falar com um comercial sobre ${motivo}`);
  });
}

function renderFormularioContato(motivo){
  const wrapper = document.createElement('div');
  wrapper.className = 'msg assistant form-contato';
  wrapper.innerHTML = `
    <div class="form-contato-titulo">Deixa seus dados que o comercial te procura:</div>
    <label class="form-contato-label">Produto de interesse</label>
    <input type="text" class="fc-produto" value="${escapeHtml(motivo)}" placeholder="Produto de interesse">
    <input type="text" class="fc-nome" placeholder="Seu nome">
    <input type="email" class="fc-email" placeholder="Seu e-mail">
    <input type="text" class="fc-empresa" placeholder="Empresa (opcional)">
    <input type="tel" class="fc-telefone" placeholder="Telefone (opcional)">
    <input type="number" min="1" class="fc-colaboradores" placeholder="Número de colaboradores (opcional)">
    <button type="button" class="fc-enviar">Enviar</button>
    <div class="fc-status"></div>
  `;
  chatMessages.appendChild(wrapper);
  chatMessages.scrollTop = chatMessages.scrollHeight;

  wrapper.querySelector('.fc-enviar').addEventListener('click', async () => {
    const produto = wrapper.querySelector('.fc-produto').value.trim() || motivo;
    const nome = wrapper.querySelector('.fc-nome').value.trim();
    const email = wrapper.querySelector('.fc-email').value.trim();
    const empresa = wrapper.querySelector('.fc-empresa').value.trim();
    const telefone = wrapper.querySelector('.fc-telefone').value.trim();
    const colaboradores = wrapper.querySelector('.fc-colaboradores').value.trim();
    const status = wrapper.querySelector('.fc-status');
    const btn = wrapper.querySelector('.fc-enviar');

    if (!nome || !email){
      status.textContent = 'Preenche nome e e-mail pelo menos :)';
      return;
    }

    btn.disabled = true;
    status.textContent = 'Enviando...';
    try {
      const res = await fetch('/api/lead-comercial', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ nome, email, empresa, telefone, colaboradores, motivo: produto }),
      });
      const data = await res.json();
      if (res.ok && data.ok){
        status.textContent = 'Recebido! Nosso comercial vai te procurar em breve.';
        wrapper.querySelectorAll('input, button').forEach(el => el.disabled = true);
      } else {
        status.textContent = 'Não consegui enviar agora, tenta de novo.';
        btn.disabled = false;
      }
    } catch (err) {
      status.textContent = 'Erro de conexão. Tenta de novo.';
      btn.disabled = false;
    }
  });
}

const MAX_TENTATIVAS_AUTOMATICAS = 3;
const esperar = (ms) => new Promise((r) => setTimeout(r, ms));

async function pedirRespostaAoAgente(thinkingEl){
  // Se a cota da IA estiver cheia, o servidor devolve fonte "rate_limit" com um
  // tempo sugerido de espera. Em vez de mostrar erro pro cliente, esperamos e
  // tentamos de novo sozinhos — ele só vê o "pensando..." um pouco mais longo.
  for (let tentativa = 1; tentativa <= MAX_TENTATIVAS_AUTOMATICAS; tentativa++){
    const res = await fetch('/api/agente', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ historico }),
    });
    const data = await res.json();

    if (data.fonte !== 'rate_limit') return data;

    if (tentativa < MAX_TENTATIVAS_AUTOMATICAS){
      thinkingEl.textContent = 'Tá bombando por aqui, já te respondo...';
      await esperar((data.retry_after || 15) * 1000);
    }
  }
  return {
    fonte: 'erro',
    resposta: 'Estou com muita procura agora. Manda a mensagem de novo em alguns segundinhos?',
  };
}

async function enviarMensagem(texto){
  if (!texto.trim()) return;

  suggestions.style.display = 'none';
  renderMensagem('user', texto);
  historico.push({ role: 'user', text: texto });

  chatInput.value = '';
  chatInput.disabled = true;
  sendBtn.disabled = true;

  const thinkingEl = renderMensagem('assistant', 'Pensando...', true);

  try {
    const data = await pedirRespostaAoAgente(thinkingEl);
    thinkingEl.remove();
    renderMensagem('assistant', data.resposta || 'Não consegui responder agora.');

    if (data.mostrar_formulario){
      renderFormularioContato(data.motivo_formulario || 'Falar com o comercial');
    } else if (data.mostrar_cta){
      renderCtaComercial(data.motivo_cta || 'Falar com o comercial');
    }

    if (data.fonte === 'gemini' || data.fonte === 'base_conhecimento'){
      historico.push({ role: 'assistant', text: data.resposta });
    } else {
      // Mensagem de erro não entra no histórico (o modelo leria como fala dele),
      // e a pergunta sem resposta sai também, pra o cliente poder reenviar limpo.
      historico.pop();
    }
  } catch (err) {
    thinkingEl.remove();
    renderMensagem('assistant', 'Erro de conexão. Tenta de novo em alguns segundos.');
    historico.pop();
  }

  chatInput.disabled = false;
  sendBtn.disabled = false;
  chatInput.focus();
}

chatForm.addEventListener('submit', (e) => {
  e.preventDefault();
  enviarMensagem(chatInput.value);
});

suggestions.querySelectorAll('.suggestion-chip').forEach(chip => {
  chip.addEventListener('click', () => enviarMensagem(chip.dataset.msg));
});

// Se o app da Flash (WebView) passar ?nome=...&empresa=... na URL, a gente já
// sabe quem é a pessoa e pula a pergunta do nome, personalizando a saudação.
const paramsUrl = new URLSearchParams(window.location.search);
const nomeUrl = (paramsUrl.get('nome') || '').trim();
const empresaUrl = (paramsUrl.get('empresa') || '').trim();

let saudacaoInicial;
if (nomeUrl && empresaUrl) {
  saudacaoInicial = `Oi, ${nomeUrl}! 🦩 Eu sou o Mingo, do Clube Flash. Bora ver como o clube pode ajudar você aí na ${empresaUrl}?`;
} else if (nomeUrl) {
  saudacaoInicial = `Oi, ${nomeUrl}! 🦩 Eu sou o Mingo, do Clube Flash. Bora ver como o clube pode te ajudar?`;
} else {
  saudacaoInicial = 'Oi! 🦩 Eu sou o Mingo, do Clube Flash. Tudo bem com você? Antes da gente continuar, qual é o seu nome?';
}

renderMensagem('assistant', saudacaoInicial);
if (nomeUrl) {
  // Entra no histórico como fala do próprio Mingo, pra ele "lembrar" o nome
  // (e a empresa, se veio) nas respostas seguintes, sem soar forçado.
  historico.push({ role: 'assistant', text: saudacaoInicial });
}
