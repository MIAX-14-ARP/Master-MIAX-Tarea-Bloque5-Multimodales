/* FinLens · §0 Cerebro. Red neuronal 3D de la cadena de modelos (Three.js r128) con fallback
   Canvas 2D. Etiquetas en HTML superpuesto (nítidas a cualquier zoom/DPR), controles propios
   (zoom, órbita, desplazamiento, reinicio) y re-render al cambiar devicePixelRatio.
   Los datos vienen en #fl-data (JSON). Nunca se inserta HTML con datos: solo textContent. */
(function () {
  "use strict";
  var DATA = JSON.parse(document.getElementById("fl-data").textContent);
  var root = document.getElementById("brain");
  var overlay = document.getElementById("labels");
  var hudH = document.getElementById("hud-h");
  var hudT = document.getElementById("hud-t");
  var hint = document.getElementById("hint");
  var bar = document.getElementById("bar");
  var btn = document.getElementById("replay");
  var reduced = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  hudH.textContent = DATA.headline || "";

  var COL = {
    bone: [0.95, 0.93, 0.88], brass: [0.784, 0.635, 0.29], red: [0.91, 0.44, 0.42],
    teal: [0.40, 0.74, 0.78], dim: [0.55, 0.62, 0.62]
  };

  // ---------- Geometría lógica (compartida por 3D y 2D) ----------
  var L = DATA.layers.length, GAP = 3.6, ROW = 0.82;
  var pos = {}, nodes = [];
  DATA.layers.forEach(function (layer, i) {
    var x = (i - (L - 1) / 2) * GAP, n = layer.nodes.length;
    layer.x = x;
    layer.h = Math.max(n, 3) * ROW + 0.8;
    layer.nodes.forEach(function (nd, j) {
      nd.layer = i;
      pos[nd.id] = [x, ((n - 1) / 2 - j) * ROW, 0];
      nodes.push(nd);
    });
  });
  var byId = {};
  nodes.forEach(function (n) { byId[n.id] = n; });
  var maxH = Math.max.apply(null, DATA.layers.map(function (l) { return l.h; }));
  var floorY = -maxH / 2 - 0.45;
  var edges = DATA.edges.filter(function (e) { return pos[e[0]] && pos[e[1]]; });

  // Neuronas decorativas (sin etiqueta, muy tenues): densidad visual de la referencia.
  var seed = 7;
  function rnd() { seed = (seed * 16807) % 2147483647; return seed / 2147483647; }
  var micro = [];
  DATA.layers.forEach(function (l, i) {
    for (var k = 0; k < 9; k++) micro.push({ layer: i, p: [l.x, (rnd() - 0.5) * l.h * 0.88, (rnd() - 0.5) * 1.9] });
  });
  var faint = [];
  for (var li = 0; li < L - 1; li++) {
    var a = micro.filter(function (m) { return m.layer === li; }), b = micro.filter(function (m) { return m.layer === li + 1; });
    a.forEach(function (m) { b.forEach(function (o) { if (rnd() < 0.5) faint.push([m.p, o.p]); }); });
    DATA.layers[li].nodes.forEach(function (n1) {
      DATA.layers[li + 1].nodes.forEach(function (n2) { faint.push([pos[n1.id], pos[n2.id]]); });
    });
  }
  var idlePhase = edges.map(function () { return rnd() * 4; });

  // ---------- Tiempo y estados ----------
  var REPLAY = DATA.mode === "replay";
  var DUR = DATA.duration || 7;
  var t0 = performance.now();
  var replaying = REPLAY && !reduced;
  function clock() { return (performance.now() - t0) / 1000; }
  function playT() { return REPLAY ? (replaying ? Math.min(clock(), DUR + 2) : DUR + 2) : clock(); }

  function stateAt(n, t) {
    if (n.state === "off") return "off";
    if (!REPLAY) return n.kind === "input" ? "on" : "idle";
    if (t < n.t0) return "wait";
    if (t < n.t1) return "run";
    return n.state;
  }
  function look(n, t, wall) {
    var s = stateAt(n, t), breath = 0.5 + 0.5 * Math.sin(wall * 1.3 + n.layer * 0.8);
    switch (s) {
      case "off": return { s: s, c: COL.dim, k: 0.6, a: 0.2, la: 0.45 };
      case "idle": return { s: s, c: n.mock ? COL.teal : COL.bone, k: 0.85, a: 0.5 + 0.35 * breath, la: 0.92 };
      case "wait": return { s: s, c: COL.bone, k: 0.8, a: 0.3, la: 0.55 };
      case "run": return { s: s, c: COL.brass, k: 1.9 + 0.4 * Math.sin(wall * 9), a: 1, la: 1 };
      case "fail": return { s: s, c: COL.red, k: 1.3, a: 1, la: 1 };
      case "sim": return { s: s, c: COL.teal, k: 1.05, a: 0.95, la: 1 };
      case "on": return n.kind === "output" ? { s: s, c: COL.brass, k: n.winner ? 2.2 : 1.5, a: 1, la: 1 } : { s: s, c: COL.bone, k: 1.1, a: 1, la: 1 };
      default: return { s: s, c: COL.bone, k: 1.05, a: 1, la: 1 };
    }
  }
  function focusX(t) {
    var run = nodes.filter(function (n) { return stateAt(n, t) === "run"; });
    if (!run.length) return null;
    return run.reduce(function (s, n) { return s + pos[n.id][0]; }, 0) / run.length;
  }
  function pulse(e, i, t, wall) {
    var A = byId[e[0]], B = byId[e[1]];
    if (A.state === "off" || B.state === "off") return null;
    if (!REPLAY) {
      if (reduced) return null;
      var ph = ((wall + idlePhase[i]) % 4) / 4;
      return ph < 0.55 ? [ph / 0.55, 0.35] : null;
    }
    var end = B.t0, start = Math.max(A.t1 - 0.05, end - 0.6);
    if (end - start < 0.25) start = end - 0.35;
    if (t < start || t > end) return null;
    return [(t - start) / (end - start), 1];
  }
  function edgeLevel(e, t) {
    var A = byId[e[0]], B = byId[e[1]];
    if (A.state === "off" || B.state === "off") return 0.05;
    if (!REPLAY) return 0.24;
    return t >= B.t0 ? 0.6 : 0.14;
  }

  // ---------- Etiquetas HTML (nítidas: las dibuja el navegador, no una textura) ----------
  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text) e.textContent = text;
    return e;
  }
  var labels = nodes.map(function (n) {
    var d = el("div", "lbl k-" + n.kind);
    d.appendChild(el("div", "t", n.label));
    var bajo = el("div", "row");
    if (n.value) bajo.appendChild(el("span", "v", n.value));
    if (n.sub) bajo.appendChild(el("span", "s", n.sub));
    if (n.value || n.sub) d.appendChild(bajo);
    overlay.appendChild(d);
    return { n: n, d: d, w: 0, state: "" };
  });
  var heads = DATA.layers.map(function (l) {
    var d = el("div", "hdr"), partes = l.title.split(" · ");
    d.appendChild(el("div", "ht", partes[partes.length - 1]));
    d.appendChild(el("div", "hs", l.subtitle.toLowerCase()));
    overlay.appendChild(d);
    return { l: l, d: d };
  });
  function measure() { labels.forEach(function (it) { it.w = it.d.offsetWidth; }); }

  // proyecta (x, y en píxeles CSS, escala) o null si queda detrás
  function placeLabels(project, t, wall, W, H) {
    labels.forEach(function (it) {
      var p = project(pos[it.n.id]);
      if (!p) { it.d.style.opacity = 0; return; }
      var v = look(it.n, t, wall), sc = Math.max(0.8, Math.min(W < 560 ? 0.95 : 1.15, p[2]));
      var desborda = p[0] + 14 + it.w * sc > W - 6;
      // Solo la capa de salida da la vuelta a su etiqueta; el resto se atenúa si no cabe (evita solapes).
      var izquierda = desborda && it.n.kind === "output";
      var x = izquierda ? p[0] - 12 - it.w * sc : p[0] + 12;
      var fuera = p[0] < -4 || p[0] > W + 4 || (desborda && !izquierda);
      it.d.style.transform = "translate(" + x.toFixed(1) + "px," + (p[1] - 10 * sc).toFixed(1) + "px) scale(" + sc.toFixed(3) + ")";
      it.d.style.opacity = fuera ? v.la * 0.18 : v.la;
      if (it.state !== v.s) { it.d.setAttribute("data-s", v.s); it.state = v.s; }
    });
    heads.forEach(function (h) {
      var p = project([h.l.x, h.l.h / 2 + 0.45, 0]);
      if (!p) { h.d.style.opacity = 0; return; }
      h.d.style.opacity = 1;
      if (p[0] < 24 || p[0] > W - 24) { h.d.style.opacity = 0; return; }
      var hx = Math.max(64, Math.min(W - 64, p[0]));
      h.d.style.transform = "translate(" + hx.toFixed(1) + "px," + (p[1] - 26).toFixed(1) + "px) translateX(-50%)";
    });
  }

  // ---------- Cámara: plano automático + ajustes del usuario ----------
  var span = (L - 1) * GAP;
  var user = { zoom: 1, yaw: 0, pitch: 0, pan: [0, 0, 0] };
  function shot(t, wall, aspect) {
    var far = Math.min(2.6, Math.max(1, 1.9 / aspect));
    var pos3, at;
    var fx = REPLAY && replaying && t < DUR ? focusX(t) : null;
    if (aspect < 0.9 && !reduced) {
      var x = fx !== null ? fx : tourX(wall);
      return { p: [x - 1.6, 1.3, 11.5], at: [x + 1.1, -0.25, 0] };
    }
    if (fx !== null) {
      pos3 = [fx - 4.6, 1.5, 9.2]; at = [fx + 1.4, -0.15, 0];
    } else if (!REPLAY && !reduced) {
      var d = Math.sin(wall * 0.06) * span * 0.1;
      pos3 = [d + 0.2, 3.2, 21]; at = [d * 0.5 + 1.2, 0.35, 0];
    } else {
      pos3 = [0.2, 3.3, 21.2]; at = [1.2, 0.35, 0];
    }
    for (var i = 0; i < 3; i++) pos3[i] = at[i] + (pos3[i] - at[i]) * far;
    return { p: pos3, at: at };
  }
  function tourX(wall) {
    var k = (wall / 3.4) % L, i = Math.floor(k), f = k - i, e = f < 0.6 ? 0 : (f - 0.6) / 0.4;
    e = e * e * (3 - 2 * e);
    var a = DATA.layers[i].x, b = DATA.layers[(i + 1) % L].x;
    return a + (b - a) * e;
  }
  function withUser(c) {
    // órbita (yaw/pitch) y zoom alrededor del punto mirado; desplazamiento del conjunto
    var v = [c.p[0] - c.at[0], c.p[1] - c.at[1], c.p[2] - c.at[2]];
    var cy = Math.cos(user.yaw), sy = Math.sin(user.yaw);
    v = [v[0] * cy + v[2] * sy, v[1], -v[0] * sy + v[2] * cy];
    var r = Math.hypot(v[0], v[2]), el0 = Math.atan2(v[1], r), el1 = Math.max(-0.2, Math.min(1.25, el0 + user.pitch));
    var len = Math.hypot(v[0], v[1], v[2]), hr = Math.cos(el1) * len, k = r ? hr / r : 1;
    v = [v[0] * k, Math.sin(el1) * len, v[2] * k];
    var z = 1 / user.zoom;
    var at = [c.at[0] + user.pan[0], c.at[1] + user.pan[1], c.at[2] + user.pan[2]];
    return { p: [at[0] + v[0] * z, at[1] + v[1] * z, at[2] + v[2] * z], at: at };
  }
  var cam = null;
  function smoothCam(target, dt) {
    if (!cam || reduced) { cam = { p: target.p.slice(), at: target.at.slice() }; return withUser(cam); }
    var k = 1 - Math.exp(-dt * 1.6);
    for (var i = 0; i < 3; i++) { cam.p[i] += (target.p[i] - cam.p[i]) * k; cam.at[i] += (target.at[i] - cam.at[i]) * k; }
    return withUser(cam);
  }

  // ---------- Controles propios (sin zoom de página) ----------
  var dirty = true; // para redibujar en modo estático
  function setZoom(z) { user.zoom = Math.max(0.45, Math.min(4, z)); dirty = true; }
  function reset() { user = { zoom: 1, yaw: 0, pitch: 0, pan: [0, 0, 0] }; dirty = true; }
  document.getElementById("zin").addEventListener("click", function () { setZoom(user.zoom * 1.25); });
  document.getElementById("zout").addEventListener("click", function () { setZoom(user.zoom / 1.25); });
  document.getElementById("zreset").addEventListener("click", reset);
  var active = false;
  function setActive(on) {
    active = on; root.classList.toggle("is-active", on);
    hint.textContent = on ? "rueda: zoom · arrastrar: girar · mayús+arrastrar: mover · doble clic: centrar"
                          : "clic en el lienzo para explorarlo";
  }
  setActive(false);
  var drag = null;
  root.addEventListener("pointerdown", function (ev) {
    setActive(true);
    drag = { x: ev.clientX, y: ev.clientY, pan: ev.shiftKey || ev.button === 2 };
    root.setPointerCapture(ev.pointerId);
  });
  root.addEventListener("pointermove", function (ev) {
    if (!drag) return;
    var dx = ev.clientX - drag.x, dy = ev.clientY - drag.y;
    drag.x = ev.clientX; drag.y = ev.clientY;
    if (drag.pan) {
      var s = 0.02 / user.zoom;
      user.pan[0] -= dx * s; user.pan[1] += dy * s;
    } else { user.yaw -= dx * 0.006; user.pitch += dy * 0.004; }
    dirty = true;
  });
  root.addEventListener("pointerup", function () { drag = null; });
  root.addEventListener("pointercancel", function () { drag = null; });
  root.addEventListener("contextmenu", function (ev) { ev.preventDefault(); });
  root.addEventListener("dblclick", reset);
  root.addEventListener("mouseleave", function () { if (!drag) setActive(false); });
  root.addEventListener("wheel", function (ev) {
    if (!active && !ev.ctrlKey) return; // sin activar, la rueda desplaza la página
    ev.preventDefault();
    setZoom(user.zoom * Math.exp(-ev.deltaY * 0.0015));
  }, { passive: false });
  root.addEventListener("keydown", function (ev) {
    var k = ev.key;
    if (k === "+" || k === "=") setZoom(user.zoom * 1.2);
    else if (k === "-") setZoom(user.zoom / 1.2);
    else if (k === "0" || k === "Escape") reset();
    else if (k === "ArrowLeft") { user.yaw += 0.08; dirty = true; }
    else if (k === "ArrowRight") { user.yaw -= 0.08; dirty = true; }
    else if (k === "ArrowUp") { user.pitch += 0.06; dirty = true; }
    else if (k === "ArrowDown") { user.pitch -= 0.06; dirty = true; }
    else return;
    ev.preventDefault();
  });

  function hud(t) {
    if (!REPLAY) { hudT.textContent = reduced ? "estático" : "en reposo"; return; }
    var p = Math.min(1, t / DUR);
    bar.style.width = (p * 100).toFixed(1) + "%";
    hudT.textContent = p < 1 ? "reproduciendo traza · " + Math.round(p * 100) + " %" : "traza completa";
    btn.hidden = p < 1 || reduced;
  }
  btn.addEventListener("click", function () { t0 = performance.now(); replaying = true; btn.hidden = true; });

  var visible = true;
  if ("IntersectionObserver" in window) {
    new IntersectionObserver(function (es) { visible = es[0].isIntersecting; }).observe(root);
  }
  function dpr() { return Math.min(window.devicePixelRatio || 1, 2.5); }
  // Ctrl+/Ctrl− del navegador cambia devicePixelRatio: se vuelve a dimensionar el lienzo para que no se emborrone.
  function onDprChange(cb) {
    if (!window.matchMedia) return;
    var mq = window.matchMedia("(resolution: " + (window.devicePixelRatio || 1) + "dppx)");
    var h = function () { cb(); onDprChange(cb); };
    if (mq.addEventListener) mq.addEventListener("change", h, { once: true });
  }

  // ======================= Three.js =======================
  function start3D(THREE) {
    var renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, powerPreference: "low-power" });
    if (!renderer.getContext()) throw new Error("sin WebGL");
    renderer.setPixelRatio(dpr());
    root.insertBefore(renderer.domElement, overlay);
    var scene = new THREE.Scene();
    scene.fog = new THREE.Fog(0x0c1719, 12, 38);
    var camera = new THREE.PerspectiveCamera(34, 1, 0.1, 120);
    var glowTex = (function () {
      var c = document.createElement("canvas"); c.width = c.height = 64;
      var g = c.getContext("2d"), r = g.createRadialGradient(32, 32, 0, 32, 32, 32);
      r.addColorStop(0, "rgba(255,255,255,1)"); r.addColorStop(0.25, "rgba(255,255,255,.55)"); r.addColorStop(1, "rgba(255,255,255,0)");
      g.fillStyle = r; g.fillRect(0, 0, 64, 64);
      return new THREE.CanvasTexture(c);
    })();

    DATA.layers.forEach(function (l) {
      var g = new THREE.PlaneGeometry(2.5, l.h);
      var plate = new THREE.Mesh(g, new THREE.MeshBasicMaterial({ color: 0x2b7f8c, transparent: true, opacity: 0.085,
        side: THREE.DoubleSide, depthWrite: false }));
      plate.rotation.y = Math.PI / 2; plate.position.set(l.x, 0, 0); scene.add(plate);
      var rim = new THREE.LineSegments(new THREE.EdgesGeometry(g), new THREE.LineBasicMaterial({ color: 0x66bcc6, transparent: true, opacity: 0.55 }));
      rim.rotation.y = Math.PI / 2; rim.position.set(l.x, 0, 0); scene.add(rim);
    });
    var grid = new THREE.GridHelper(70, 70, 0x2f7f8a, 0x16393f);
    grid.material.transparent = true; grid.material.opacity = 0.55; grid.position.y = floorY; scene.add(grid);

    var fp = new Float32Array(faint.length * 6);
    faint.forEach(function (e, i) { fp.set(e[0], i * 6); fp.set(e[1], i * 6 + 3); });
    var fg = new THREE.BufferGeometry(); fg.setAttribute("position", new THREE.BufferAttribute(fp, 3));
    scene.add(new THREE.LineSegments(fg, new THREE.LineBasicMaterial({ color: 0xdfeceb, transparent: true, opacity: 0.045, depthWrite: false })));
    var mp = new Float32Array(micro.length * 3);
    micro.forEach(function (m, i) { mp.set(m.p, i * 3); });
    var mg = new THREE.BufferGeometry(); mg.setAttribute("position", new THREE.BufferAttribute(mp, 3));
    scene.add(new THREE.Points(mg, new THREE.PointsMaterial({ color: 0xdfeceb, size: 0.05, transparent: true, opacity: 0.35, depthWrite: false })));

    var ep = new Float32Array(edges.length * 6), ec = new Float32Array(edges.length * 6);
    edges.forEach(function (e, i) { ep.set(pos[e[0]], i * 6); ep.set(pos[e[1]], i * 6 + 3); });
    var eg = new THREE.BufferGeometry();
    eg.setAttribute("position", new THREE.BufferAttribute(ep, 3));
    eg.setAttribute("color", new THREE.BufferAttribute(ec, 3));
    scene.add(new THREE.LineSegments(eg, new THREE.LineBasicMaterial({ vertexColors: true, transparent: true,
      blending: THREE.AdditiveBlending, depthWrite: false })));

    var pp = new Float32Array(edges.length * 3), pc = new Float32Array(edges.length * 3);
    var pg = new THREE.BufferGeometry();
    pg.setAttribute("position", new THREE.BufferAttribute(pp, 3));
    pg.setAttribute("color", new THREE.BufferAttribute(pc, 3));
    scene.add(new THREE.Points(pg, new THREE.PointsMaterial({ size: 0.42, map: glowTex, vertexColors: true, transparent: true,
      blending: THREE.AdditiveBlending, depthWrite: false })));

    var items = nodes.map(function (n) {
      var core = new THREE.Mesh(new THREE.SphereGeometry(0.075, 16, 12), new THREE.MeshBasicMaterial({ color: 0xffffff, transparent: true }));
      core.position.fromArray(pos[n.id]); scene.add(core);
      var halo = new THREE.Sprite(new THREE.SpriteMaterial({ map: glowTex, transparent: true, blending: THREE.AdditiveBlending, depthWrite: false }));
      halo.position.copy(core.position); scene.add(halo);
      return { n: n, core: core, halo: halo };
    });

    var W = 1, H = 1;
    function resize() {
      W = root.clientWidth; H = root.clientHeight;
      renderer.setPixelRatio(dpr());
      renderer.setSize(W, H, false); camera.aspect = W / H; camera.updateProjectionMatrix();
      measure(); dirty = true;
    }
    resize();
    if ("ResizeObserver" in window) new ResizeObserver(resize).observe(root);
    onDprChange(resize);

    var tmp = new THREE.Vector3();
    var F0 = 0;
    function project(p) {
      tmp.set(p[0], p[1], p[2]).applyMatrix4(camera.matrixWorldInverse);
      var depth = -tmp.z; if (depth < 0.3) return null;
      tmp.set(p[0], p[1], p[2]).project(camera);
      if (!F0) F0 = 14;
      return [(tmp.x + 1) / 2 * W, (1 - tmp.y) / 2 * H, F0 / depth];
    }
    var last = performance.now();
    function frame(now) {
      var dt = Math.min(0.1, (now - last) / 1000); last = now;
      if (visible && !document.hidden) draw(dt);
      if (!reduced) requestAnimationFrame(frame);
      else if (dirty) { draw(1); }
    }
    function draw(dt) {
      dirty = false;
      var t = playT(), wall = clock();
      items.forEach(function (it) {
        var v = look(it.n, t, wall);
        it.core.material.color.setRGB(v.c[0], v.c[1], v.c[2]); it.core.material.opacity = v.a;
        it.core.scale.setScalar(v.k);
        it.halo.material.color.setRGB(v.c[0], v.c[1], v.c[2]);
        it.halo.material.opacity = v.a * (v.k > 1.2 ? 0.9 : 0.35);
        it.halo.scale.setScalar(0.55 * v.k);
      });
      edges.forEach(function (e, i) {
        var lv = edgeLevel(e, t), c = REPLAY && t >= byId[e[1]].t0 && byId[e[1]].state !== "off" ? COL.brass : COL.bone;
        for (var k = 0; k < 2; k++) { ec[i * 6 + k * 3] = c[0] * lv; ec[i * 6 + k * 3 + 1] = c[1] * lv; ec[i * 6 + k * 3 + 2] = c[2] * lv; }
        var p = pulse(e, i, t, wall), A = pos[e[0]], B = pos[e[1]];
        if (p) {
          for (var j = 0; j < 3; j++) pp[i * 3 + j] = A[j] + (B[j] - A[j]) * p[0];
          pc[i * 3] = COL.brass[0] * p[1]; pc[i * 3 + 1] = COL.brass[1] * p[1]; pc[i * 3 + 2] = COL.brass[2] * p[1];
        } else { pc[i * 3] = pc[i * 3 + 1] = pc[i * 3 + 2] = 0; }
      });
      eg.attributes.color.needsUpdate = true; pg.attributes.position.needsUpdate = true; pg.attributes.color.needsUpdate = true;
      var c = smoothCam(shot(t, wall, camera.aspect), dt);
      camera.position.fromArray(c.p); camera.lookAt(c.at[0], c.at[1], c.at[2]);
      camera.updateMatrixWorld();
      renderer.render(scene, camera);
      placeLabels(project, t, wall, W, H);
      hud(t);
    }
    if (reduced) { draw(1); requestAnimationFrame(frame); } else { requestAnimationFrame(frame); }
  }

  // ======================= Canvas 2D (fallback) =======================
  function start2D() {
    var cv = document.createElement("canvas"); root.insertBefore(cv, overlay);
    var g = cv.getContext("2d"), W = 0, H = 0, ratio = 1, c = null;
    function resize() { W = root.clientWidth; H = root.clientHeight; ratio = dpr(); cv.width = W * ratio; cv.height = H * ratio; measure(); dirty = true; }
    resize(); window.addEventListener("resize", resize); onDprChange(resize);
    function sub(a, b) { return [a[0] - b[0], a[1] - b[1], a[2] - b[2]]; }
    function dot(a, b) { return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]; }
    function cross(a, b) { return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]; }
    function norm(a) { var l = Math.hypot(a[0], a[1], a[2]) || 1; return [a[0] / l, a[1] / l, a[2] / l]; }
    function project(p) {
      var f = norm(sub(c.at, c.p)), r = norm(cross(f, [0, 1, 0])), u = cross(r, f), v = sub(p, c.p);
      var z = dot(v, f); if (z < 0.3) return null;
      var Fp = (H / 2) / Math.tan(17 * Math.PI / 180);
      return [W / 2 + dot(v, r) / z * Fp, H / 2 - dot(v, u) / z * Fp, 14 / z];
    }
    function rgba(col, a) { return "rgba(" + Math.round(col[0] * 255) + "," + Math.round(col[1] * 255) + "," + Math.round(col[2] * 255) + "," + a + ")"; }
    function line(A, B, style, w) {
      var a = project(A), b = project(B); if (!a || !b) return;
      g.strokeStyle = style; g.lineWidth = w; g.beginPath(); g.moveTo(a[0], a[1]); g.lineTo(b[0], b[1]); g.stroke();
    }
    var last = performance.now();
    function draw(dt) {
      dirty = false;
      var t = playT(), wall = clock();
      c = smoothCam(shot(t, wall, W / H), dt);
      g.setTransform(ratio, 0, 0, ratio, 0, 0); g.clearRect(0, 0, W, H);
      for (var k = -20; k <= 20; k += 1) {
        line([k, floorY, -20], [k, floorY, 20], "rgba(47,127,138,.22)", 1);
        line([-20, floorY, k], [20, floorY, k], "rgba(47,127,138,.22)", 1);
      }
      DATA.layers.forEach(function (l) {
        var q = [[l.x, -l.h / 2, -1.25], [l.x, -l.h / 2, 1.25], [l.x, l.h / 2, 1.25], [l.x, l.h / 2, -1.25]].map(project);
        if (q.some(function (p) { return !p; })) return;
        g.beginPath(); q.forEach(function (p, j) { j ? g.lineTo(p[0], p[1]) : g.moveTo(p[0], p[1]); }); g.closePath();
        g.fillStyle = "rgba(43,127,140,.08)"; g.fill(); g.strokeStyle = "rgba(102,188,198,.55)"; g.lineWidth = 1; g.stroke();
      });
      faint.forEach(function (e) { line(e[0], e[1], "rgba(223,236,235,.05)", 1); });
      edges.forEach(function (e, i) {
        var lv = edgeLevel(e, t), col = REPLAY && t >= byId[e[1]].t0 && byId[e[1]].state !== "off" ? COL.brass : COL.bone;
        line(pos[e[0]], pos[e[1]], rgba(col, lv), 1);
        var p = pulse(e, i, t, wall);
        if (p) {
          var A = pos[e[0]], B = pos[e[1]], pt = project([A[0] + (B[0] - A[0]) * p[0], A[1] + (B[1] - A[1]) * p[0], A[2] + (B[2] - A[2]) * p[0]]);
          if (pt) { g.fillStyle = rgba(COL.brass, p[1]); g.beginPath(); g.arc(pt[0], pt[1], Math.max(2, 5 * pt[2]), 0, 7); g.fill(); }
        }
      });
      nodes.forEach(function (n) {
        var p = project(pos[n.id]); if (!p) return;
        var v = look(n, t, wall), r = Math.max(2.2, 5 * p[2] * v.k);
        g.fillStyle = rgba(v.c, v.a * 0.25); g.beginPath(); g.arc(p[0], p[1], r * 2.4, 0, 7); g.fill();
        g.fillStyle = rgba(v.c, v.a); g.beginPath(); g.arc(p[0], p[1], r, 0, 7); g.fill();
      });
      placeLabels(project, t, wall, W, H);
      hud(t);
    }
    function frame(now) {
      var dt = Math.min(0.1, (now - last) / 1000); last = now;
      if ((visible && !document.hidden && !reduced) || dirty) draw(dt);
      requestAnimationFrame(frame);
    }
    draw(1); requestAnimationFrame(frame);
  }

  // ---------- Arranque: fuentes → Three.js (con tiempo límite) → 2D si falla ----------
  var started = false;
  function go2D() { if (started) return; started = true; try { start2D(); } catch (e) { hudT.textContent = "sin lienzo"; } }
  function go3D() {
    if (started) return;
    try { started = true; start3D(window.THREE); } catch (e) {
      var cvs = root.querySelector("canvas"); if (cvs) cvs.remove(); started = false; go2D();
    }
  }
  var fontsReady = document.fonts && document.fonts.load
    ? Promise.race([document.fonts.load("600 13px 'IBM Plex Mono'"), new Promise(function (r) { setTimeout(r, 1500); })])
    : Promise.resolve();
  fontsReady.then(function () {
    measure();
    if (window.FL_FORCE_2D) return go2D();
    var s = document.createElement("script");
    s.src = window.FL_THREE_URL; s.async = true;
    var timer = setTimeout(go2D, 5000);
    s.onload = function () { clearTimeout(timer); window.THREE ? go3D() : go2D(); };
    s.onerror = function () { clearTimeout(timer); go2D(); };
    document.head.appendChild(s);
  });
})();
