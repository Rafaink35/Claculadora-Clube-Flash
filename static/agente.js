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

    if (data.fonte === 'gemini'){
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

renderMensagem('assistant', 'E aí! 🦩 Sou o Mingo, do Clube Flash. Bora ver quanto o clube economiza pra sua empresa, ou me joga qualquer dúvida/objeção que eu respondo na hora.');
