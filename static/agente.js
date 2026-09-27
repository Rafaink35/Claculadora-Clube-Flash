let historico = [];

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
    const res = await fetch('/api/agente', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ historico }),
    });
    const data = await res.json();
    thinkingEl.remove();
    renderMensagem('assistant', data.resposta || 'Não consegui responder agora.');
    historico.push({ role: 'assistant', text: data.resposta || '' });
  } catch (err) {
    thinkingEl.remove();
    renderMensagem('assistant', 'Erro de conexão. Tenta de novo em alguns segundos.');
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

renderMensagem('assistant', 'E aí! 🦩 Sou o Mingo, do Clube Flash. Bora ver quanto o clube economiza pra sua empresa, ou me joga qualquer dúvida/objeção que eu respondo na hora.');
