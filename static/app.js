let categories = [];
let months = 12;
let ultimoCalculo = {};

const rampColors = ['#A60058','#E6007C','#FE2B8F','#FF6D94','#FF9ABD','#FFC2D0','#FFB3C7','#FFD6E1','#FFECF2'];

function escapeHtml(texto){
  const div = document.createElement('div');
  div.textContent = String(texto ?? '');
  return div.innerHTML;
}

function fmtBRL(v){
  return v.toLocaleString('pt-BR', {style:'currency', currency:'BRL'});
}

function buildTable(){
  const tbody = document.getElementById('catTableBody');
  tbody.innerHTML = '';
  categories.forEach(cat => {
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td>
        <span class="cat-name">${escapeHtml(cat.nome)}</span>
        <span class="cat-partners">${cat.parceiros} parceiros ativos · ${escapeHtml(cat.fonte_uso || 'estimativa')}</span>
      </td>
      <td class="fixed-pct">${cat.desconto.toFixed(1).replace('.', ',')}%</td>
      <td><input type="number" min="0" step="0.5" value="${cat.freq}" data-id="${cat.id}" data-field="freq"></td>
      <td><input type="number" min="0" step="1" value="${cat.ticket}" data-id="${cat.id}" data-field="ticket"></td>
      <td class="cat-econ" id="econ-${cat.id}">—</td>
    `;
    tbody.appendChild(tr);
  });
  tbody.querySelectorAll('input').forEach(inp => {
    inp.addEventListener('input', (e) => {
      const cat = categories.find(c => c.id === e.target.dataset.id);
      const field = e.target.dataset.field;
      const val = parseFloat(e.target.value);
      cat[field] = isNaN(val) ? 0 : val;
      recalc();
    });
  });
}

function recalc(){
  const headcount = Math.max(1, parseInt(document.getElementById('headcount').value) || 1);
  const salario = Math.max(1, parseFloat(document.getElementById('salario').value) || 1);
  const companyName = document.getElementById('companyName').value.trim() || 'sua empresa';

  let totalMes = 0;
  const perCat = categories.map(cat => {
    const econMes = cat.freq * cat.ticket * (cat.desconto / 100);
    totalMes += econMes;
    return {...cat, econMes};
  });

  perCat.forEach(cat => {
    const el = document.getElementById('econ-' + cat.id);
    if (el) el.textContent = fmtBRL(cat.econMes);
  });

  const individualPeriodo = totalMes * months;
  const agregadoPeriodo = individualPeriodo * headcount;

  document.getElementById('heroLabel').textContent =
    `Economia agregada devolvida à empresa em ${months} ${months === 1 ? 'mês' : 'meses'}`;
  document.getElementById('heroNumber').textContent = fmtBRL(agregadoPeriodo);
  document.getElementById('heroSub').innerHTML =
    `Isso equivale a <strong>${fmtBRL(individualPeriodo)}</strong> por colaborador no período, considerando o padrão de uso projetado ao lado.`;

  const pctSalario = (totalMes / salario) * 100;
  document.getElementById('heroImpact').textContent =
    `Equivale a ${pctSalario.toFixed(1).replace('.', ',')}% do salário médio mensal do colaborador, todo mês`;

  const sorted = [...perCat].sort((a,b) => b.econMes - a.econMes);
  const max = sorted.length ? sorted[0].econMes : 1;
  const barsContainer = document.getElementById('barsContainer');
  barsContainer.innerHTML = '';
  sorted.forEach((cat, i) => {
    const pct = totalMes > 0 ? (cat.econMes / totalMes * 100) : 0;
    const width = max > 0 ? (cat.econMes / max * 100) : 0;
    const row = document.createElement('div');
    row.className = 'bar-row';
    row.innerHTML = `
      <div class="bar-labels">
        <span class="name">${escapeHtml(cat.nome)}</span>
        <span class="val">${fmtBRL(cat.econMes)}/mês · ${pct.toFixed(0)}%</span>
      </div>
      <div class="bar-track">
        <div class="bar-fill" style="width:${width}%; background:${rampColors[i % rampColors.length]};"></div>
      </div>
    `;
    barsContainer.appendChild(row);
  });

  const top = sorted[0];
  const topPct = totalMes > 0 ? Number((top.econMes / totalMes * 100).toFixed(0)) : 0;
  const narrative =
    `Cada colaborador de <b>${escapeHtml(companyName)}</b> economizou em média ${fmtBRL(totalMes)} por mês usando o Clube Flash. ` +
    `Ao longo de ${months} ${months === 1 ? 'mês' : 'meses'}, isso soma ${fmtBRL(individualPeriodo)} por colaborador — e ${fmtBRL(agregadoPeriodo)} devolvidos ao total de ${headcount.toLocaleString('pt-BR')} colaboradores da empresa. ` +
    `A categoria que mais gerou economia foi ${top.nome}, respondendo por ${topPct}% do valor total — o equivalente a ${pctSalario.toFixed(1).replace('.', ',')}% do salário médio mensal, todo mês.`;
  document.getElementById('narrativeText').innerHTML = narrative;
  document.getElementById('narrativeFonte').textContent = '';

  ultimoCalculo = {
    empresa: companyName,
    headcount: headcount,
    meses: months,
    totalMes: totalMes,
    individualPeriodo: individualPeriodo,
    agregadoPeriodo: agregadoPeriodo,
    categoriaTop: top.nome,
    topPct: topPct,
    pctSalario: pctSalario,
  };
}

async function init(){
  const res = await fetch('/api/categorias');
  categories = await res.json();

  buildTable();
  recalc();

  document.getElementById('periodPills').addEventListener('click', (e) => {
    if (e.target.classList.contains('pill')){
      document.querySelectorAll('.pill').forEach(p => p.classList.remove('active'));
      e.target.classList.add('active');
      months = parseInt(e.target.dataset.months);
      recalc();
    }
  });

  document.getElementById('headcount').addEventListener('input', recalc);
  document.getElementById('companyName').addEventListener('input', recalc);
  document.getElementById('salario').addEventListener('input', recalc);

  document.getElementById('copyBtn').addEventListener('click', async () => {
    const text = document.getElementById('narrativeText').innerText;
    const btn = document.getElementById('copyBtn');
    try {
      await navigator.clipboard.writeText(text);
      btn.textContent = 'Copiado!';
      btn.classList.add('copied');
    } catch(err){
      const ta = document.createElement('textarea');
      ta.value = text;
      document.body.appendChild(ta);
      ta.select();
      try { document.execCommand('copy'); btn.textContent = 'Copiado!'; btn.classList.add('copied'); }
      catch(e2){ btn.textContent = 'Não foi possível copiar'; }
      document.body.removeChild(ta);
    }
    setTimeout(() => { btn.textContent = 'Copiar narrativa'; btn.classList.remove('copied'); }, 1800);
  });

  document.getElementById('aiBtn').addEventListener('click', async () => {
    const btn = document.getElementById('aiBtn');
    const textoOriginal = btn.textContent;
    btn.disabled = true;
    btn.textContent = 'Gerando...';
    try {
      const res = await fetch('/api/gerar-narrativa', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(ultimoCalculo),
      });
      const data = await res.json();
      if (data.narrativa) {
        document.getElementById('narrativeText').textContent = data.narrativa;
        document.getElementById('narrativeFonte').textContent =
          data.fonte === 'gemini'
            ? '✨ Gerado por IA (Gemini)'
            : 'IA indisponível no momento — usando texto padrão';
      }
    } catch (err) {
      document.getElementById('narrativeFonte').textContent =
        'Não foi possível gerar com IA agora — tente novamente';
    }
    btn.disabled = false;
    btn.textContent = textoOriginal;
  });
}

init();
