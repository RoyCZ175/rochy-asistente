/*
 * Orbe estilo Siri: una "mancha líquida" de colores fluyendo dentro de un
 * círculo, hecha con WebGL (un shader real, no dibujado a mano cuadro por
 * cuadro) — es la técnica que da ese aspecto suave y orgánico en vez de
 * líneas/ondas planas. No depende de ninguna librería externa (todo el
 * código es nuestro), así que sigue funcionando sin internet.
 *
 * Uso desde index.html:
 *   const orb = SiriOrb.init(webglCanvas, particleCanvas);
 *   orb.setState('idle' | 'listening' | 'thinking' | 'speaking');
 *
 * Cómo está armado, de afuera hacia adentro:
 *   1. Un shader de fragmento calcula "ruido" (una función matemática que da
 *      valores suaves y aleatorios, como una nube) en varias capas que se
 *      mueven con el tiempo — eso es lo que da el efecto de líquido fluyendo.
 *   2. Ese ruido se colorea con el degradado de marca (azul→morado→rosa→
 *      naranja) según el ángulo, y se recorta a un círculo con borde suave.
 *   3. Encima, un segundo canvas (2D normal) dibuja partículas orbitando y
 *      ondas de "sonar" — mismo mecanismo que antes, pero ahora sobre el
 *      fondo líquido en vez de un círculo plano.
 *   4. El estado (en espera/escuchando/procesando/hablando) solo cambia qué
 *      tan turbulento y rápido se mueve el líquido — el color de marca es
 *      siempre el mismo, es la identidad visual de Rochy.
 */
(function (global) {
  const VERTEX_SRC = `
    attribute vec2 aPosition;
    void main() {
      gl_Position = vec4(aPosition, 0.0, 1.0);
    }
  `;

  // El ruido usado aquí es "simplex noise" 2D clásico (dominio público,
  // versión compacta) — un generador de manchas suaves que se puede animar
  // desplazando sus coordenadas con el tiempo.
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

    // Varias capas de ruido a distinta frecuencia/amplitud ("fractal
    // brownian motion") — da manchas suaves y orgánicas que fluyen, en vez
    // de una sola onda. Esto es lo que reemplaza el "reloj de colores por
    // ángulo" (se veía como una pizza en rebanadas) por algo líquido de verdad.
    float fbm(vec2 p) {
      float total = 0.0;
      float amp = 0.55;
      for (int i = 0; i < 4; i++) {
        total += amp * snoise(p);
        p *= 2.05;
        amp *= 0.55;
      }
      return total;
    }

    void main() {
      vec2 uv = (gl_FragCoord.xy - 0.5 * uResolution) / min(uResolution.x, uResolution.y);
      float dist = length(uv);
      float radius = 0.42;

      float t = uTime * uSpeed;
      float warpScale = 1.5 + uTurbulence * 1.3;

      // El color se deriva del propio campo de ruido (no del ángulo desde el
      // centro) — así las manchas de color fluyen y se deforman como un
      // líquido de verdad, en vez de quedar fijas como rebanadas de un reloj.
      float n1 = fbm(uv * warpScale + vec2(t * 0.16, -t * 0.11));
      float n2 = fbm(uv * warpScale * 1.8 - vec2(-t * 0.21, t * 0.15) + 6.2);
      float hue = fract(n1 * 0.5 + n2 * 0.35 + t * 0.02);
      float shade = n1;

      vec3 c0 = vec3(0.227, 0.627, 1.0);
      vec3 c1 = vec3(0.608, 0.420, 1.0);
      vec3 c2 = vec3(1.0, 0.361, 0.659);
      vec3 c3 = vec3(1.0, 0.647, 0.239);

      vec3 color;
      float seg = hue * 4.0;
      if (seg < 1.0) color = mix(c0, c1, smoothstep(0.0, 1.0, seg));
      else if (seg < 2.0) color = mix(c1, c2, smoothstep(0.0, 1.0, seg - 1.0));
      else if (seg < 3.0) color = mix(c2, c3, smoothstep(0.0, 1.0, seg - 2.0));
      else color = mix(c3, c0, smoothstep(0.0, 1.0, seg - 3.0));

      color *= 0.72 + 0.55 * shade;

      float edge = smoothstep(radius, radius - 0.035, dist);
      float glow = smoothstep(radius * 2.3, radius, dist) * 0.32;

      vec3 bg = vec3(0.02, 0.024, 0.043);
      vec3 finalColor = mix(bg, color, edge);
      finalColor += color * glow * (1.0 - edge);

      gl_FragColor = vec4(finalColor, 1.0);
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
    idle:      { turbulence: 0.15, speed: 0.35 },
    listening: { turbulence: 0.55, speed: 0.65 },
    thinking:  { turbulence: 0.78, speed: 1.15 },
    speaking:  { turbulence: 0.95, speed: 1.45 },
  };

  const RIPPLE_INTERVAL = { listening: 1000, speaking: 650 };
  const RIPPLE_LIFE_MS = 1200;

  function init(glCanvas, particleCanvas) {
    const gl = glCanvas.getContext('webgl') || glCanvas.getContext('experimental-webgl');
    let program = null;
    let uniforms = {};

    if (gl) {
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
      // Un solo triángulo que cubre toda la pantalla (más simple que un
      // rectángulo con dos triángulos, técnica estándar en WebGL).
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

    const PARTICLES = Array.from({ length: 18 }, (_, i) => ({
      angle: (i / 18) * Math.PI * 2,
      radius: 0.5 + Math.random() * 0.18,
      speed: 0.15 + Math.random() * 0.25,
      size: 1.2 + Math.random() * 1.8,
      hue: ['#3aa0ff', '#9b6bff', '#ff5ca8', '#ffa53d'][i % 4],
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
        gl.uniform2f(uniforms.resolution, glCanvas.width, glCanvas.height);
        gl.uniform1f(uniforms.time, now / 1000);
        gl.uniform1f(uniforms.turbulence, current.turbulence);
        gl.uniform1f(uniforms.speed, current.speed);
        gl.drawArrays(gl.TRIANGLES, 0, 3);
      }

      // Capa 2D encima: partículas + ondas de sonar (mismo mecanismo que la
      // versión anterior, ahora sobre el fondo líquido).
      const w = particleCanvas.width, h = particleCanvas.height;
      const cx = w / 2, cy = h / 2;
      const R = Math.min(w, h) * 0.42;
      pctx.clearRect(0, 0, w, h);

      const rippleGap = RIPPLE_INTERVAL[activeState];
      if (rippleGap && now - lastRippleAt > rippleGap) {
        ripples.push(now);
        lastRippleAt = now;
      }
      ripples = ripples.filter((born) => now - born < RIPPLE_LIFE_MS);
      for (const born of ripples) {
        const t = (now - born) / RIPPLE_LIFE_MS;
        const rad = R + t * (R * 0.5);
        pctx.beginPath();
        pctx.arc(cx, cy, rad, 0, Math.PI * 2);
        pctx.strokeStyle = `rgba(255,255,255,${(1 - t) * 0.25})`;
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
