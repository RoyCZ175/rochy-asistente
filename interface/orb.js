/*
 * Orbe estilo Siri: varios "blobs" de luz de colores que flotan y se
 * superponen dentro de un círculo, mezclándose de forma ADITIVA (como luces
 * de colores, no pintura) — así las zonas donde se cruzan brillan más, que
 * es justo lo que da esa sensación de "hecho de luz" en vez de una textura
 * plana. Hecho con WebGL (shader real), sin ninguna librería externa, así
 * que sigue funcionando sin internet.
 *
 * Uso desde index.html:
 *   const orb = SiriOrb.init(webglCanvas, particleCanvas);
 *   orb.setState('idle' | 'listening' | 'thinking' | 'speaking');
 *
 * Puntos clave de esta versión (corrige los problemas de la anterior):
 *   - El canvas es transparente de verdad (alpha real por píxel) — antes se
 *     pintaba un color de fondo "a mano" que no coincidía con el fondo real
 *     de la página, y se veía como un cuadrado oscuro alrededor del orbe.
 *   - El color ya NO sale de una textura de ruido (se veía como una célula
 *     bajo microscopio) — ahora son manchas de luz que orbitan y se
 *     combinan sumando brillo donde se cruzan, con una curva de tono suave
 *     para que no se "queme" a blanco duro.
 *   - Paleta de 6 colores (antes 4) para más variedad.
 */
(function (global) {
  const VERTEX_SRC = `
    attribute vec2 aPosition;
    void main() {
      gl_Position = vec4(aPosition, 0.0, 1.0);
    }
  `;

  const FRAGMENT_SRC = `
    precision highp float;
    uniform vec2 uResolution;
    uniform float uTime;
    uniform float uTurbulence;
    uniform float uSpeed;

    vec3 mod289(vec3 x) { return x - floor(x * (1.0 / 289.0)) * 289.0; }
    vec2 mod289(vec2 x) { return x - floor(x * (1.0 / 289.0)) * 289.0; }
    vec3 permute(vec3 x) { return mod289(((x * 34.0) + 1.0) * x); }

    float snoise(vec2 v) {
      const vec4 C = vec4(0.211324865405187, 0.366025403784439,
                          -0.577350269189626, 0.024390243902439);
      vec2 i  = floor(v + dot(v, C.yy));
      vec2 x0 = v - i + dot(i, C.xx);
      vec2 i1 = (x0.x > x0.y) ? vec2(1.0, 0.0) : vec2(0.0, 1.0);
      vec4 x12 = x0.xyxy + C.xxzz;
      x12.xy -= i1;
      i = mod289(i);
      vec3 p = permute(permute(i.y + vec3(0.0, i1.y, 1.0))
              + i.x + vec3(0.0, i1.x, 1.0));
      vec3 m = max(0.5 - vec3(dot(x0, x0), dot(x12.xy, x12.xy), dot(x12.zw, x12.zw)), 0.0);
      m = m * m; m = m * m;
      vec3 x = 2.0 * fract(p * C.www) - 1.0;
      vec3 h = abs(x) - 0.5;
      vec3 ox = floor(x + 0.5);
      vec3 a0 = x - ox;
      m *= 1.79284291400159 - 0.85373472095314 * (a0 * a0 + h * h);
      vec3 g;
      g.x = a0.x * x0.x + h.x * x0.y;
      g.yz = a0.yz * x12.xz + h.yz * x12.yw;
      return 130.0 * dot(m, g);
    }

    // Paleta de marca con 6 colores (antes 4), recorrida en ciclo continuo.
    vec3 palette(float t) {
      vec3 c0 = vec3(0.227, 0.627, 1.0);   // azul
      vec3 c1 = vec3(0.420, 0.470, 1.0);   // índigo
      vec3 c2 = vec3(0.608, 0.420, 1.0);   // morado
      vec3 c3 = vec3(1.0, 0.361, 0.659);   // rosa
      vec3 c4 = vec3(1.0, 0.647, 0.239);   // naranja
      vec3 c5 = vec3(0.30, 0.85, 0.95);    // celeste
      float seg = fract(t) * 6.0;
      if (seg < 1.0) return mix(c0, c1, smoothstep(0.0, 1.0, seg));
      if (seg < 2.0) return mix(c1, c2, smoothstep(0.0, 1.0, seg - 1.0));
      if (seg < 3.0) return mix(c2, c3, smoothstep(0.0, 1.0, seg - 2.0));
      if (seg < 4.0) return mix(c3, c4, smoothstep(0.0, 1.0, seg - 3.0));
      if (seg < 5.0) return mix(c4, c5, smoothstep(0.0, 1.0, seg - 4.0));
      return mix(c5, c0, smoothstep(0.0, 1.0, seg - 5.0));
    }

    void main() {
      vec2 uv = (gl_FragCoord.xy - 0.5 * uResolution) / min(uResolution.x, uResolution.y);
      float dist = length(uv);
      float radius = 0.40;

      float t = uTime * uSpeed;

      // Deforma el espacio suavemente (un solo ruido, escala grande) para
      // que las manchas de luz no floten en círculos perfectos y se sientan
      // más orgánicas — sin pasarse de "textura", por eso una sola capa.
      vec2 warp = vec2(
        snoise(uv * 1.0 + vec2(t * 0.06, 0.0)),
        snoise(uv * 1.0 + vec2(0.0, -t * 0.05) + 9.0)
      ) * 0.05 * (0.6 + uTurbulence);
      vec2 p = uv + warp;

      // Un solo tono domina en cada momento (recorre la paleta lento, nunca
      // salta) — evita el problema de sumar 5 colores de toda la rueda de
      // color, que en las zonas donde se cruzan se cancelan hacia blanco/
      // gris (es básico de teoría del color: mezclar todo el arcoíris da
      // blanco). Las manchas de abajo solo aportan BRILLO y un ligero
      // corrimiento hacia el tono VECINO en la paleta (nunca el opuesto),
      // así siempre se ve saturado y de un color reconocible.
      vec3 baseHue = palette(t * 0.025);
      vec3 neighborHue = palette(t * 0.025 + 0.16);

      float glow = 0.0;
      const int BLOBS = 4;
      for (int i = 0; i < BLOBS; i++) {
        float fi = float(i);
        float speed = 0.3 + 0.09 * fi;
        float ang = t * speed * (0.5 + uTurbulence * 0.7) + fi * 2.1;
        float orbitR = 0.14 + 0.11 * sin(fi * 2.3 + t * 0.12);
        vec2 pos = vec2(cos(ang), sin(ang * 1.2)) * orbitR;
        float d = length(p - pos);
        glow += pow(smoothstep(0.40, 0.0, d), 1.3);
      }
      glow = clamp(glow, 0.0, 2.2);

      // Mezcla también según la posición (no solo el brillo), para que en
      // un mismo instante se vean los dos tonos vecinos a la vez (uno hacia
      // arriba, el otro hacia abajo) en vez de un solo color plano.
      float posMix = smoothstep(-radius * 0.9, radius * 0.9, p.y + warp.x * 0.6);
      vec3 baseColor = mix(baseHue, neighborHue, clamp(posMix * 0.7 + glow * 0.25, 0.0, 1.0));
      vec3 col = baseColor * (0.5 + glow * 0.5);

      // Curva de tono suave (evita que se "queme" a blanco duro donde se
      // superponen varias manchas) — da el aspecto de luz real, no de pintura.
      col = 1.0 - exp(-col * 1.4);

      // El borde NO es un círculo perfecto: se deforma según el ángulo con
      // dos capas de ruido (una más gruesa, una más fina) que además se
      // mueven despacio con el tiempo — da un contorno orgánico, como una
      // gota, en vez de un aro geométrico exacto.
      float angle = atan(uv.y, uv.x);
      vec2 edgeSample = vec2(cos(angle), sin(angle));
      float edgeWobble = snoise(edgeSample * 1.1 + t * 0.1) * 0.022
                        + snoise(edgeSample * 2.0 - t * 0.08 + 3.0) * 0.010;
      float effRadius = radius + edgeWobble;

      // Máscara: opaco bien adentro del contorno (ya deformado), con un halo
      // suave que se desvanece hacia afuera — fuera de un radio, alpha llega
      // a 0 de verdad (canvas transparente), nunca un cuadrado de fondo.
      float inner = smoothstep(effRadius, effRadius - 0.09, dist);
      float haloStrength = clamp(length(col) * 0.5, 0.0, 1.0);
      float halo = smoothstep(effRadius * 2.6, effRadius * 0.5, dist) * 0.5 * haloStrength;
      float alpha = clamp(max(inner, halo), 0.0, 1.0);

      gl_FragColor = vec4(col, alpha);
    }
  `;

  function compileShader(gl, type, src) {
    const shader = gl.createShader(type);
    gl.shaderSource(shader, src);
    gl.compileShader(shader);
    if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
      console.error('[orb] error compilando shader:', gl.getShaderInfoLog(shader));
      gl.deleteShader(shader);
      return null;
    }
    return shader;
  }

  const STATE_PARAMS = {
    idle:      { turbulence: 0.12, speed: 0.35 },
    listening: { turbulence: 0.5,  speed: 0.65 },
    thinking:  { turbulence: 0.78, speed: 1.15 },
    speaking:  { turbulence: 0.95, speed: 1.45 },
  };

  const RIPPLE_INTERVAL = { listening: 1000, speaking: 650 };
  const RIPPLE_LIFE_MS = 1200;

  // Dibuja un contorno cerrado con curvas suaves y bultos irregulares —
  // nunca un círculo perfecto. Se generan pocos puntos de control (9) con un
  // radio que varía según el ángulo (dos ondas sinusoidales combinadas) y se
  // conectan con curvas cuadráticas a través de los puntos medios, la
  // técnica clásica para contornos de "gota" suaves y orgánicos.
  function drawWobblyPath(ctx, cx, cy, baseRadius, phase, amount) {
    const N = 9;
    const pts = [];
    for (let i = 0; i < N; i++) {
      const a = (i / N) * Math.PI * 2;
      const wobble = 1 + amount * (Math.sin(a * 3 + phase) * 0.6 + Math.sin(a * 5 - phase * 1.4) * 0.4);
      const r = baseRadius * wobble;
      pts.push([cx + Math.cos(a) * r, cy + Math.sin(a) * r]);
    }
    ctx.beginPath();
    const startMid = [(pts[0][0] + pts[N - 1][0]) / 2, (pts[0][1] + pts[N - 1][1]) / 2];
    ctx.moveTo(startMid[0], startMid[1]);
    for (let i = 0; i < N; i++) {
      const curr = pts[i];
      const next = pts[(i + 1) % N];
      const midX = (curr[0] + next[0]) / 2;
      const midY = (curr[1] + next[1]) / 2;
      ctx.quadraticCurveTo(curr[0], curr[1], midX, midY);
    }
    ctx.closePath();
  }

  function init(glCanvas, particleCanvas) {
    // alpha:true + premultipliedAlpha:false es la combinación que evita el
    // "cuadrado oscuro": sin esto, el navegador puede mezclar mal el canvas
    // con la página de fondo y dejar un borde/relleno visible.
    const gl =
      glCanvas.getContext('webgl', { alpha: true, premultipliedAlpha: false }) ||
      glCanvas.getContext('experimental-webgl', { alpha: true, premultipliedAlpha: false });
    let program = null;
    let uniforms = {};

    if (gl) {
      gl.enable(gl.BLEND);
      gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);
      gl.clearColor(0, 0, 0, 0);

      const vs = compileShader(gl, gl.VERTEX_SHADER, VERTEX_SRC);
      const fs = compileShader(gl, gl.FRAGMENT_SHADER, FRAGMENT_SRC);
      if (vs && fs) {
        program = gl.createProgram();
        gl.attachShader(program, vs);
        gl.attachShader(program, fs);
        gl.linkProgram(program);
        if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
          console.error('[orb] error enlazando programa:', gl.getProgramInfoLog(program));
          program = null;
        }
      }
    }

    if (program) {
      gl.useProgram(program);
      const buffer = gl.createBuffer();
      gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
      gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW);
      const posLoc = gl.getAttribLocation(program, 'aPosition');
      gl.enableVertexAttribArray(posLoc);
      gl.vertexAttribPointer(posLoc, 2, gl.FLOAT, false, 0, 0);

      uniforms.resolution = gl.getUniformLocation(program, 'uResolution');
      uniforms.time = gl.getUniformLocation(program, 'uTime');
      uniforms.turbulence = gl.getUniformLocation(program, 'uTurbulence');
      uniforms.speed = gl.getUniformLocation(program, 'uSpeed');
    }

    const pctx = particleCanvas.getContext('2d');

    function resize() {
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      for (const c of [glCanvas, particleCanvas]) {
        const w = c.clientWidth, h = c.clientHeight;
        if (c.width !== Math.round(w * dpr) || c.height !== Math.round(h * dpr)) {
          c.width = Math.round(w * dpr);
          c.height = Math.round(h * dpr);
        }
      }
      if (gl) gl.viewport(0, 0, glCanvas.width, glCanvas.height);
    }
    resize();
    window.addEventListener('resize', resize);

    let current = { ...STATE_PARAMS.idle };
    let target = { ...STATE_PARAMS.idle };
    let activeState = 'idle';
    let lastRippleAt = 0;
    let ripples = [];

    const PARTICLES = Array.from({ length: 16 }, (_, i) => ({
      angle: (i / 16) * Math.PI * 2,
      radius: 0.48 + Math.random() * 0.16,
      speed: 0.15 + Math.random() * 0.25,
      size: 1.2 + Math.random() * 1.8,
      hue: ['#3aa0ff', '#9b6bff', '#ff5ca8', '#ffa53d', '#4dd8ef'][i % 5],
    }));

    function lerp(a, b, t) { return a + (b - a) * t; }

    function setState(name) {
      if (!STATE_PARAMS[name]) return;
      target = { ...STATE_PARAMS[name] };
      activeState = name;
    }

    function frame(now) {
      resize();
      current.turbulence = lerp(current.turbulence, target.turbulence, 0.04);
      current.speed = lerp(current.speed, target.speed, 0.04);

      if (gl && program) {
        gl.useProgram(program);
        gl.clear(gl.COLOR_BUFFER_BIT);
        gl.uniform2f(uniforms.resolution, glCanvas.width, glCanvas.height);
        gl.uniform1f(uniforms.time, now / 1000);
        gl.uniform1f(uniforms.turbulence, current.turbulence);
        gl.uniform1f(uniforms.speed, current.speed);
        gl.drawArrays(gl.TRIANGLES, 0, 3);
      }

      const w = particleCanvas.width, h = particleCanvas.height;
      const cx = w / 2, cy = h / 2;
      const R = Math.min(w, h) * 0.40;
      pctx.clearRect(0, 0, w, h);

      const rippleGap = RIPPLE_INTERVAL[activeState];
      if (rippleGap && now - lastRippleAt > rippleGap) {
        // Cada onda tiene su propia "personalidad" de bultos (fase al azar),
        // fija desde que nace — así se ve orgánica en vez de temblar cada
        // cuadro. No es un círculo perfecto, tiene curvas irregulares.
        ripples.push({ born: now, phase: Math.random() * Math.PI * 2 });
        lastRippleAt = now;
      }
      ripples = ripples.filter((r) => now - r.born < RIPPLE_LIFE_MS);
      for (const r of ripples) {
        const t = (now - r.born) / RIPPLE_LIFE_MS;
        const rad = R + t * (R * 0.55);
        drawWobblyPath(pctx, cx, cy, rad, r.phase, 0.07);
        pctx.strokeStyle = `rgba(255,255,255,${(1 - t) * 0.28})`;
        pctx.lineWidth = 1.5;
        pctx.stroke();
      }

      for (const p of PARTICLES) {
        p.angle += 0.004 * p.speed * (1 + current.turbulence);
        const rad = (p.radius + Math.sin(now / 600 + p.angle) * 0.02) * Math.min(w, h);
        const x = cx + Math.cos(p.angle) * rad;
        const y = cy + Math.sin(p.angle) * rad;
        pctx.beginPath();
        pctx.arc(x, y, p.size * (w / 260), 0, Math.PI * 2);
        pctx.fillStyle = p.hue;
        pctx.globalAlpha = 0.55;
        pctx.fill();
        pctx.globalAlpha = 1;
      }

      requestAnimationFrame(frame);
    }
    requestAnimationFrame(frame);

    return { setState };
  }

  global.SiriOrb = { init };
})(window);
