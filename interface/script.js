// El orbe en sí (el shader líquido tipo Siri) vive en orb.js, en su propio
// archivo — aquí solo lo inicializamos y le avisamos de los cambios de
// estado. El color de marca es siempre el mismo; el estado solo cambia qué
// tan turbulento/rápido se mueve, y los textos de la píldora de estado.
const orb = SiriOrb.init(document.getElementById('orbGl'), document.getElementById('orbParticles'));

const STATE_LABELS = {
  idle:      { label: 'En línea',   sub: 'Siempre listo para ayudarte' },
  listening: { label: 'Escuchando', sub: 'Di tu mensaje cuando quieras' },
  thinking:  { label: 'Procesando', sub: 'Dame un momento…' },
  speaking:  { label: 'Hablando',   sub: 'Escuchando la respuesta' },
};

function setState(name) {
  if (!STATE_LABELS[name]) return;
  orb.setState(name);
  if (name === 'thinking') {
    showTypingIndicator();
  } else {
    hideTypingIndicator();
  }
  if (name === 'idle') {
    // "En línea" a secas estaba mal aquí: pisaba el texto correcto (modo
    // local, o la materia de estudio activa) cada vez que volvía a idle,
    // aunque el puntito de color sí quedaba bien — quedaba diciendo "En
    // línea" con el punto en naranja de modo local al mismo tiempo.
    updateStatusBar();
  } else if (!studySubjectActive) {
    document.getElementById('statusText').textContent = STATE_LABELS[name].label;
    document.getElementById('statusSub').textContent = STATE_LABELS[name].sub;
  }
  document.getElementById('statusDot').classList.toggle('local', currentAiMode === 'local' && name === 'idle');
}

// --- Transcript ---
const log = document.getElementById('log');

// Burbuja de "escribiendo…" (tres puntos animados) mientras Rochy procesa —
// así se ve de inmediato que algo está pasando, en vez de quedar el chat
// quieto hasta que la respuesta ya está lista.
let typingBubbleEl = null;
function showTypingIndicator() {
  if (typingBubbleEl) return;
  typingBubbleEl = document.createElement('div');
  typingBubbleEl.className = 'bubble assistant typing';
  typingBubbleEl.innerHTML = '<span></span><span></span><span></span>';
  log.appendChild(typingBubbleEl);
  log.scrollTop = log.scrollHeight;
}
function hideTypingIndicator() {
  if (!typingBubbleEl) return;
  typingBubbleEl.remove();
  typingBubbleEl = null;
}

function addBubble(role, text) {
  hideTypingIndicator();
  const div = document.createElement('div');
  div.className = 'bubble ' + (role === 'user' ? 'user' : 'assistant');
  div.textContent = text;
  log.appendChild(div);
  log.scrollTop = log.scrollHeight;
  // En cuanto hay conversación de verdad, el encabezado/tarjetas se
  // achican para darle casi todo el espacio al chat — la pantalla de
  // bienvenida ya cumplió su función de mostrar las opciones disponibles.
  // La esfera y el estado "En línea" NO se ven afectados por esto.
  document.getElementById('main').classList.add('chatting');
}

// --- Estado actual conocido por la interfaz ---
let currentAiMode = 'online';
let currentStudySubject = null;
let studySubjectActive = false;

function updateStatusBar() {
  studySubjectActive = !!currentStudySubject;
  const dot = document.getElementById('statusDot');
  dot.classList.toggle('local', currentAiMode === 'local');
  // Fondo de "nubes" de color (ver #modeGlow en style.css) — mismo cambio
  // que el puntito de estado, pero de un vistazo en toda la pantalla.
  document.body.classList.toggle('mode-local', currentAiMode === 'local');

  if (studySubjectActive) {
    document.getElementById('statusText').textContent = 'Estudiando: ' + currentStudySubject;
    document.getElementById('statusSub').textContent = currentAiMode === 'local' ? 'Modo local (ahorro)' : 'Modo en línea';
  } else {
    document.getElementById('statusText').textContent = currentAiMode === 'local' ? 'Modo local' : 'En línea';
    document.getElementById('statusSub').textContent = currentAiMode === 'local' ? 'Ahorrando datos, sin internet' : 'Siempre listo para ayudarte';
  }

  document.getElementById('uploadBtn').disabled = !currentStudySubject;
}
updateStatusBar();

// --- WebSocket ---
let ws;
function connect() {
  const conn = document.getElementById('connLabel');
  try {
    ws = new WebSocket('ws://localhost:8765');
  } catch (e) {
    setTimeout(connect, 2000);
    return;
  }
  ws.onopen = () => { conn.textContent = 'conectado'; };
  ws.onclose = () => { conn.textContent = 'reconectando…'; setTimeout(connect, 2000); };
  ws.onerror = () => ws.close();
  ws.onmessage = (event) => {
    let data;
    try { data = JSON.parse(event.data); } catch (e) { return; }

    if (data.type === 'state' && data.state) {
      setState(data.state);
    } else if (data.type === 'transcript' && data.text) {
      addBubble(data.role, data.text);
    } else if (data.type === 'mode_update') {
      currentAiMode = data.ai_mode || 'online';
      currentStudySubject = data.study_subject || null;
      updateStatusBar();
    } else if (data.type === 'open_file_picker' && data.subject) {
      openFilePicker(data.subject);
    } else if (data.type === 'voice_envelope') {
      // Volumen real de la voz que está a punto de sonar (ver tts.py) — el
      // orbe lo usa para crecer/encoger siguiendo los altos y bajos de
      // verdad mientras habla.
      orb.setVoiceEnvelope(data.envelope, data.step_ms);
    }
  };
}
connect();

// --- Selector nativo de archivos (modo estudio) ---
function openFilePicker(subject) {
  if (!window.pywebview || !window.pywebview.api) {
    setTimeout(() => openFilePicker(subject), 300);
    return;
  }
  window.pywebview.api.pick_and_copy(subject).then(() => {});
}

// --- Entrada de texto ---
const input = document.getElementById('textInput');
const sendBtn = document.getElementById('sendBtn');

function sendText() {
  const text = input.value.trim();
  if (!text || !ws || ws.readyState !== WebSocket.OPEN) return;
  ws.send(JSON.stringify({ type: 'text_command', text }));
  input.value = '';
}

sendBtn.addEventListener('click', sendText);
input.addEventListener('keydown', (e) => {
  if (e.key === 'Enter') sendText();
});

function sendControl(text) {
  if (!ws || ws.readyState !== WebSocket.OPEN) return;
  ws.send(JSON.stringify({ type: 'text_command', text }));
}

document.getElementById('pauseBtn').addEventListener('click', () => sendControl('descansa'));
document.getElementById('powerBtn').addEventListener('click', () => sendControl('apágate'));
document.getElementById('brandBtn').addEventListener('click', () => sendControl('reinicia la conversación'));

document.getElementById('modeBtn').addEventListener('click', () => {
  sendControl(currentAiMode === 'local' ? 'modo online' : 'modo local');
});

document.getElementById('uploadBtn').addEventListener('click', () => {
  if (currentStudySubject) openFilePicker(currentStudySubject);
});

// --- Ventana flotante (modal) ---
// Reemplaza alert()/prompt() nativos (se veían genéricos y feos, sin
// nuestro estilo) y el panel de ayuda inline. "Ayuda" y "Estudiar" abren
// esta misma ventana con contenido distinto — nunca aparece nada de esto
// como mensajes en el chat.
const modalOverlay = document.getElementById('modalOverlay');
const modalTitleEl = document.getElementById('modalTitle');
const modalBodyEl = document.getElementById('modalBody');

function openModal(title, bodyHTML) {
  modalTitleEl.textContent = title;
  modalBodyEl.innerHTML = bodyHTML;
  modalOverlay.classList.add('open');
}
function closeModal() {
  modalOverlay.classList.remove('open');
}
document.getElementById('modalClose').addEventListener('click', closeModal);
modalOverlay.addEventListener('click', (e) => {
  if (e.target === modalOverlay) closeModal();
});

const HELP_HTML = `
  <div class="helpSection">
    <h4>Hablar con Rochy</h4>
    <p>Dile "rochy" en voz alta y espera a que responda "Dime", o escribe tu mensaje abajo y presiona Enter. No hace falta decir nada especial para charlar o pedir tareas normales.</p>
  </div>
  <div class="helpSection">
    <h4>Modo local vs. modo en línea</h4>
    <p><b>En línea</b> usa internet y da las respuestas más completas. <b>Local</b> usa la IA de tu propia PC, no gasta datos.</p>
    <p>Di <code>modo local</code> o <code>modo online</code>, o usa la tarjeta "Cambiar modo".</p>
  </div>
  <div class="helpSection">
    <h4>Modo estudio</h4>
    <p>Rochy responde usando tus propios apuntes (PDF, Word o texto). Usa la tarjeta "Estudiar" para elegir una materia existente o crear una nueva.</p>
    <p>Di <code>sal del modo estudio</code> para salir, o <code>olvida el estudio de [materia]</code> para que olvide lo aprendido (sin borrar tus archivos).</p>
  </div>
  <div class="helpSection">
    <h4>Si Rochy se equivoca o tarda</h4>
    <p>Di <code>olvídalo</code> o <code>cancela</code> en cualquier momento.</p>
  </div>
  <div class="helpSection">
    <h4>Pausar o cerrar</h4>
    <p>"Pausar" deja de escuchar activamente. "Apagar" cierra la aplicación. También puedes decir "descansa" o "apágate".</p>
  </div>
`;

function showHelp() {
  openModal('Ayuda', HELP_HTML);
}

const SUBJECT_ICON = '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"><path d="M4 5.5C4 4.7 4.7 4 5.5 4H12v16H5.5C4.7 20 4 19.3 4 18.5V5.5Z"/><path d="M20 5.5C20 4.7 19.3 4 18.5 4H12v16h6.5c.8 0 1.5-.7 1.5-1.5V5.5Z"/></svg>';

async function showStudyPicker() {
  openModal('Modo estudio', '<p style="opacity:.7">Cargando tus materias…</p>');

  let subjects = [];
  try {
    if (window.pywebview && window.pywebview.api) {
      subjects = await window.pywebview.api.list_subjects();
    }
  } catch (e) {
    subjects = [];
  }

  const rowsHtml = subjects.length
    ? subjects.map((s) => `
        <div class="subjectRow" data-subject="${s}">
          <span class="subjectIcon">${SUBJECT_ICON}</span>
          <span class="subjectName">${s.replace(/_/g, ' ')}</span>
        </div>
      `).join('')
    : '<p style="opacity:.7">Todavía no tienes ninguna materia — crea la primera abajo.</p>';

  modalBodyEl.innerHTML = `
    <p style="margin:0 0 10px 0; opacity:.75;">Elige una materia para seguir estudiando:</p>
    ${rowsHtml}
    <div id="newSubjectRow">
      <input id="newSubjectInput" type="text" placeholder="Nueva materia…">
      <button id="newSubjectBtn">Crear</button>
    </div>
  `;

  modalBodyEl.querySelectorAll('.subjectRow').forEach((row) => {
    row.addEventListener('click', async () => {
      const subject = row.dataset.subject;
      closeModal();
      if (window.pywebview && window.pywebview.api) {
        await window.pywebview.api.activate_subject(subject);
      }
    });
  });

  const newInput = document.getElementById('newSubjectInput');
  const createNew = () => {
    const name = newInput.value.trim();
    if (!name) return;
    closeModal();
    openFilePicker(name); // crea la carpeta, abre el selector, copia e indexa
  };
  document.getElementById('newSubjectBtn').addEventListener('click', createNew);
  newInput.addEventListener('keydown', (e) => { if (e.key === 'Enter') createNew(); });
}

document.getElementById('helpBtn').addEventListener('click', showHelp);
document.getElementById('studyBtn').addEventListener('click', showStudyPicker);

// --- Barra lateral como cajón en pantallas chicas ---
const sidebarEl = document.getElementById('sidebar');
const sidebarBackdrop = document.getElementById('sidebarBackdrop');
function openSidebar() {
  sidebarEl.classList.add('open');
  sidebarBackdrop.classList.add('open');
}
function closeSidebar() {
  sidebarEl.classList.remove('open');
  sidebarBackdrop.classList.remove('open');
}
document.getElementById('hamburgerBtn').addEventListener('click', openSidebar);
sidebarBackdrop.addEventListener('click', closeSidebar);
// Elegir cualquier ícono de la barra la cierra sola (si estaba abierta como cajón).
sidebarEl.querySelectorAll('button').forEach((btn) => {
  btn.addEventListener('click', closeSidebar);
});

// --- Barra lateral: accesos rápidos a las mismas acciones que las tarjetas ---
document.getElementById('navChat').addEventListener('click', () => {
  setActiveNav('navChat');
  input.focus();
});
document.getElementById('navMode').addEventListener('click', () => {
  document.getElementById('modeBtn').click();
});
document.getElementById('navStudy').addEventListener('click', () => {
  setActiveNav('navStudy');
  showStudyPicker();
});
document.getElementById('navFiles').addEventListener('click', () => {
  setActiveNav('navFiles');
  document.getElementById('uploadBtn').click();
});
document.getElementById('navHelp').addEventListener('click', () => {
  setActiveNav('navHelp');
  showHelp();
});
function setActiveNav(id) {
  for (const btn of document.querySelectorAll('.navBtn')) {
    btn.classList.toggle('active', btn.id === id);
  }
}
