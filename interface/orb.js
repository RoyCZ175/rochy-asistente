/*
 * Orbe "cerebro geométrico": una esfera hecha de puntos conectados entre sí
 * (como una red neuronal / constelación 3D) que gira sola y además sigue el
 * mouse con una leve inclinación — nada de líquidos ni texturas, formas
 * geométricas limpias con los mismos colores que el resto de la interfaz
 * (los del borde de las tarjetas). Todo con canvas 2D normal, sin WebGL ni
 * librerías externas — más simple y confiable, y sigue funcionando offline.
 *
 * Uso desde index.html:
 *   const orb = SiriOrb.init(glowCanvas, netCanvas);
 *   orb.setState('idle' | 'listening' | 'thinking' | 'speaking');
 *
 * Cómo está armado:
 *   1. fibonacciSphere() reparte N puntos de forma pareja sobre una esfera
 *      (sin amontonarlos en los polos, la técnica clásica para esto).
 *   2. buildEdges() conecta cada punto con sus K vecinos más cercanos — se
 *      calcula UNA sola vez al iniciar (la forma no cambia, solo gira).
 *   3. Cada cuadro: se rota el conjunto de puntos (giro automático + una
 *      inclinación extra según dónde esté el mouse), se proyectan a 2D con
 *      perspectiva simple, y se dibujan líneas + puntos — más grandes y
 *      brillantes los que están "de frente", más tenues los de atrás.
 */
(function (global) {
  // Misma paleta "gamer" que el borde de las tarjetas (--blue/--purple/
  // --pink/--orange/--green en index.html), para que todo se vea como una
  // sola identidad de color.
  const PALETTE = ['#00d9ff', '#b347ff', '#ff2f9e', '#ff9900', '#3dffa0'];

  function hexToRgb(hex) {
    const n = parseInt(hex.slice(1), 16);
    return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
  }
  const PALETTE_RGB = PALETTE.map(hexToRgb);

  const STATE_PARAMS = {
    idle:      { spin: 0.15, pulse: 0.4 },
    listening: { spin: 0.35, pulse: 0.8 },
    thinking:  { spin: 0.95, pulse: 1.0 },
    speaking:  { spin: 0.6,  pulse: 1.2 },
  };

  const RIPPLE_INTERVAL = { listening: 1000, speaking: 650 };
  const RIPPLE_LIFE_MS = 1200;

  function fibonacciSphere(n) {
    const pts = [];
    const goldenAngle = Math.PI * (3 - Math.sqrt(5));
    for (let i = 0; i < n; i++) {
      const y = 1 - (i / (n - 1)) * 2;
      const r = Math.sqrt(Math.max(0, 1 - y * y));
      const theta = goldenAngle * i;
      pts.push({ x: Math.cos(theta) * r, y, z: Math.sin(theta) * r });
    }
    return pts;
  }

  function buildEdges(points, k) {
    const edges = [];
    const seen = new Set();
    for (let i = 0; i < points.length; i++) {
      const dists = [];
      for (let j = 0; j < points.length; j++) {
        if (i === j) continue;
        const dx = points[i].x - points[j].x;
        const dy = points[i].y - points[j].y;
        const dz = points[i].z - points[j].z;
        dists.push([j, dx * dx + dy * dy + dz * dz]);
      }
      dists.sort((a, b) => a[1] - b[1]);
      for (let n = 0; n < k; n++) {
        const j = dists[n][0];
        const key = i < j ? `${i}_${j}` : `${j}_${i}`;
        if (!seen.has(key)) {
          seen.add(key);
          edges.push([i, j]);
        }
      }
    }
    return edges;
  }

  function init(glowCanvas, netCanvas) {
    const gctx = glowCanvas.getContext('2d');
    const ctx = netCanvas.getContext('2d');

    const POINTS = fibonacciSphere(64);
    const EDGES = buildEdges(POINTS, 3);

    function resize() {
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      for (const c of [glowCanvas, netCanvas]) {
        const w = c.clientWidth, h = c.clientHeight;
        if (c.width !== Math.round(w * dpr) || c.height !== Math.round(h * dpr)) {
          c.width = Math.round(w * dpr);
          c.height = Math.round(h * dpr);
        }
      }
    }
    resize();
    window.addEventListener('resize', resize);

    let current = { ...STATE_PARAMS.idle };
    let target = { ...STATE_PARAMS.idle };
    let activeState = 'idle';
    function setState(name) {
      if (!STATE_PARAMS[name]) return;
      target = { ...STATE_PARAMS[name] };
      activeState = name;
    }
    function lerp(a, b, t) { return a + (b - a) * t; }

    // Sigue el mouse: una inclinación suave hacia donde esté el cursor
    // (relativo al centro del orbe) — no es un giro loco, solo "mirar hacia".
    let mouseTX = 0, mouseTY = 0;
    let mouseX = 0, mouseY = 0;
    window.addEventListener('mousemove', (e) => {
      const rect = netCanvas.getBoundingClientRect();
      const cx = rect.left + rect.width / 2;
      const cy = rect.top + rect.height / 2;
      const dx = (e.clientX - cx) / (rect.width / 2 || 1);
      const dy = (e.clientY - cy) / (rect.height / 2 || 1);
      mouseTX = Math.max(-1, Math.min(1, dx));
      mouseTY = Math.max(-1, Math.min(1, dy));
    });

    let rotY = 0;
    const baseTiltX = 0.15;
    let ripples = [];
    let lastRippleAt = 0;

    // Volumen real de la voz mientras habla (ver tts.py: se calcula del
    // audio de verdad, no es un adorno) — el orbe crece/encoge siguiendo
    // estos valores en vez de solo pulsar de forma genérica.
    let voiceEnvelope = [];
    let voiceStepMs = 60;
    let voiceStartedAt = 0;
    let voiceLevel = 0;
    function setVoiceEnvelope(envelope, stepMs) {
      voiceEnvelope = envelope || [];
      voiceStepMs = stepMs || 60;
      voiceStartedAt = performance.now();
    }
    function currentVoiceLevel(now) {
      if (!voiceEnvelope.length) return 0;
      const elapsed = now - voiceStartedAt;
      const idx = elapsed / voiceStepMs;
      const i0 = Math.floor(idx);
      if (i0 >= voiceEnvelope.length) return 0;
      const i1 = Math.min(i0 + 1, voiceEnvelope.length - 1);
      const frac = idx - i0;
      return lerp(voiceEnvelope[i0], voiceEnvelope[i1], frac);
    }

    function frame(now) {
      resize();
      current.spin = lerp(current.spin, target.spin, 0.03);
      current.pulse = lerp(current.pulse, target.pulse, 0.03);
      mouseX = lerp(mouseX, mouseTX, 0.06);
      mouseY = lerp(mouseY, mouseTY, 0.06);

      rotY += 0.004 * current.spin;
      const tiltX = baseTiltX + mouseY * 0.35;
      const tiltZ = mouseX * 0.5;

      // Volumen real de la voz mientras habla — crece/encoge el orbe
      // siguiendo los altos y bajos de verdad, suavizado para que no salte
      // de golpe entre un valor y el siguiente.
      const targetVoice = activeState === 'speaking' ? currentVoiceLevel(now) : 0;
      voiceLevel = lerp(voiceLevel, targetVoice, 0.35);

      // Respiración lenta entre colores vivos y más oscuros/apagados —
      // independiente del estado, le da rango de vida a la esfera incluso
      // en reposo, no se queda siempre en el mismo brillo.
      const darkBreath = 0.62 + Math.sin(now / 4200) * 0.38;

      const w = netCanvas.width, h = netCanvas.height;
      const cx = w / 2, cy = h / 2;
      const R = Math.min(w, h) * 0.34 * (1 + voiceLevel * 0.4);

      ctx.clearRect(0, 0, w, h);
      gctx.clearRect(0, 0, glowCanvas.width, glowCanvas.height);

      // Resplandor suave detrás, respira con el estado (más fuerte
      // pensando/hablando que en espera) y con la voz real al hablar.
      const glowR = R * (1.7 + Math.sin(now / 900) * 0.08 * current.pulse + voiceLevel * 0.25);
      const [pr, pg, pb] = PALETTE_RGB[1];
      const glowGrad = gctx.createRadialGradient(cx, cy, 0, cx, cy, Math.max(glowR, 1));
      glowGrad.addColorStop(0, `rgba(${pr},${pg},${pb},${0.16 * current.pulse * darkBreath + voiceLevel * 0.12})`);
      glowGrad.addColorStop(1, 'rgba(5,6,11,0)');
      gctx.fillStyle = glowGrad;
      gctx.beginPath();
      gctx.arc(cx, cy, Math.max(glowR, 1), 0, Math.PI * 2);
      gctx.fill();

      const cosY = Math.cos(rotY), sinY = Math.sin(rotY);
      const cosX = Math.cos(tiltX), sinX = Math.sin(tiltX);
      const cosZ = Math.cos(tiltZ), sinZ = Math.sin(tiltZ);

      const projected = POINTS.map((p) => {
        const x1 = p.x * cosY - p.z * sinY;
        const z1 = p.x * sinY + p.z * cosY;
        const y1 = p.y;

        const y2 = y1 * cosX - z1 * sinX;
        const z2 = y1 * sinX + z1 * cosX;

        const x2 = x1 * cosZ - y2 * sinZ;
        const y3 = x1 * sinZ + y2 * cosZ;

        const scale = 1 / (1.6 - z2 * 0.5);
        return { x: cx + x2 * R * scale, y: cy + y3 * R * scale, depth: z2 };
      });

      // Ondas de sonar al escuchar/hablar (mismo mecanismo que antes).
      const rippleGap = RIPPLE_INTERVAL[activeState];
      if (rippleGap && now - lastRippleAt > rippleGap) {
        ripples.push(now);
        lastRippleAt = now;
      }
      ripples = ripples.filter((born) => now - born < RIPPLE_LIFE_MS);
      for (const born of ripples) {
        const t = (now - born) / RIPPLE_LIFE_MS;
        ctx.beginPath();
        ctx.arc(cx, cy, R + t * (R * 0.6), 0, Math.PI * 2);
        ctx.strokeStyle = `rgba(255,255,255,${(1 - t) * 0.2})`;
        ctx.lineWidth = 1;
        ctx.stroke();
      }

      // Conexiones: más tenues las que quedan "de espaldas" a la cámara, y
      // todas un poco más tenues durante los momentos "oscuros" de la
      // respiración de color.
      for (const [i, j] of EDGES) {
        const a = projected[i], b = projected[j];
        const depthAvg = (a.depth + b.depth) / 2;
        const alpha = (0.1 + Math.max(0, depthAvg) * 0.35) * darkBreath;
        const [r, g, b2] = PALETTE_RGB[(i + j) % PALETTE_RGB.length];
        ctx.beginPath();
        ctx.moveTo(a.x, a.y);
        ctx.lineTo(b.x, b.y);
        ctx.strokeStyle = `rgba(${r},${g},${b2},${alpha})`;
        ctx.lineWidth = 1;
        ctx.stroke();
      }

      // Nodos: más grandes y brillantes los que están "de frente".
      projected.forEach((p, idx) => {
        const front = (p.depth + 1) / 2;
        const size = 1.1 + front * 2.3;
        const [r, g, b2] = PALETTE_RGB[idx % PALETTE_RGB.length];
        ctx.beginPath();
        ctx.arc(p.x, p.y, size, 0, Math.PI * 2);
        ctx.fillStyle = `rgba(${r},${g},${b2},${(0.35 + front * 0.6) * darkBreath})`;
        ctx.shadowBlur = 6 * front * darkBreath;
        ctx.shadowColor = `rgb(${r},${g},${b2})`;
        ctx.fill();
        ctx.shadowBlur = 0;
      });

      requestAnimationFrame(frame);
    }
    requestAnimationFrame(frame);

    return { setState, setVoiceEnvelope };
  }

  global.SiriOrb = { init };
})(window);
