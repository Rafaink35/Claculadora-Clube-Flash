document.getElementById('leadForm').addEventListener('submit', async (e) => {
  e.preventDefault();

  const btn = document.getElementById('leadSubmitBtn');
  const msg = document.getElementById('leadMsg');
  btn.disabled = true;
  msg.textContent = '';
  msg.className = 'lp-form-msg';

  const dados = {
    nome: document.getElementById('nome').value.trim(),
    email: document.getElementById('email').value.trim(),
    empresa: document.getElementById('empresa').value.trim(),
    cargo: document.getElementById('cargo').value.trim(),
    headcount: document.getElementById('headcount').value || null,
  };

  try {
    const res = await fetch('/api/lead', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(dados),
    });
    const data = await res.json();

    if (res.ok && data.ok) {
      msg.textContent = 'Recebido! Nosso time entra em contato em breve.';
      msg.className = 'lp-form-msg ok';
      document.getElementById('leadForm').reset();
    } else {
      msg.textContent = data.erro || 'Não foi possível enviar agora. Tenta de novo.';
      msg.className = 'lp-form-msg err';
    }
  } catch (err) {
    msg.textContent = 'Erro de conexão. Tenta de novo em alguns segundos.';
    msg.className = 'lp-form-msg err';
  }

  btn.disabled = false;
});
