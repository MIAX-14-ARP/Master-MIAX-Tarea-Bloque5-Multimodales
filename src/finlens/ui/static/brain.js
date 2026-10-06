/* FinLens · §0 Cerebro. Red neuronal 3D de la cadena de modelos (Three.js r128) con
   fallback Canvas 2D. Los datos vienen en #fl-data (JSON). Nunca se inserta HTML con datos:
   el texto va a canvas (fillText) o a textContent. */
(function () {
  "use strict";
  var DATA = JSON.parse(document.getElementById("fl-data").textContent);
  var root = document.getElementById("brain");
  var hudH = document.getElementById("hud-h");
  var hudT = document.getElementById("hud-t");
  var bar = document.getElementById("bar");
  var btn = document.getElementById("replay");
  var reduced = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  hudH.textContent = DATA.headline || "";

  var COL = {
    bone: [0.93, 0.90, 0.84], brass: [0.784, 0.635, 0.29], red: [0.91, 0.44, 0.42],
    teal: [0.345, 0.682, 0.725], dim: [0.55, 0.62, 0.62]
  };
  var CSS = { bone: "#ede6d6", dim: "#9fb3b3", brass: "#c8a24a", red: "#e8716a", teal: "#58aeb9", sub: "#8fa7a9" };

  // ---------- Geometría lógica (compartida por 3D y 2D) ----------
  var L = DATA.layers.length, GAP = 3.2, ROW = 0.64;
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
  var faint = []; // pares de puntos
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
    // color, tamaño relativo y opacidad de la neurona y su etiqueta
    var s = stateAt(n, t), breath = 0.5 + 0.5 * Math.sin(wall * 1.3 + n.layer * 0.8);
    switch (s) {
      case "off": return { c: COL.dim, k: 0.6, a: 0.18, la: 0.28 };
      case "idle": return { c: n.mock ? COL.teal : COL.bone, k: 0.85, a: 0.45 + 0.35 * breath, la: 0.78 };
      case "wait": return { c: COL.bone, k: 0.8, a: 0.3, la: 0.45 };
      case "run": return { c: COL.brass, k: 1.9 + 0.4 * Math.sin(wall * 9), a: 1, la: 1 };
      case "fail": return { c: COL.red, k: 1.3, a: 1, la: 1 };
      case "sim": return { c: COL.teal, k: 1.05, a: 0.95, la: 0.95 };
      case "on": return n.kind === "output" ? { c: COL.brass, k: n.winner ? 2.2 : 1.5, a: 1, la: 1 } : { c: COL.bone, k: 1.1, a: 1, la: 1 };
      default: return { c: COL.bone, k: 1.05, a: 1, la: 1 };
    }
  }
  function focusX(t) {
    var run = nodes.filter(function (n) { return stateAt(n, t) === "run"; });
    if (!run.length) return null;
    return run.reduce(function (s, n) { return s + pos[n.id][0]; }, 0) / run.length;
  }
  // Pulso de una arista: [progreso 0..1, intensidad] o null.
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
    if (!REPLAY) return 0.22;
    return t >= B.t0 ? 0.6 : 0.14;
  }

  // ---------- Texto en canvas (etiquetas) ----------
  function labelCanvas(lines, opt) {
    var scale = 2, pad = 6, c = document.createElement("canvas"), x = c.getContext("2d");
    var fonts = lines.map(function (l) { return (l.w || 500) + " " + l.size * scale + "px 'IBM Plex Mono', Consolas, monospace"; });
    var w = 0;
    lines.forEach(function (l, i) {
      x.font = fonts[i];
      var tw = x.measureText(l.text).width + (l.value ? x.measureText("  " + l.value).width : 0);
      w = Math.max(w, tw);
    });
    var h = lines.reduce(function (s, l) { return s + l.size * scale * 1.35; }, 0);
    c.width = Math.ceil(w + pad * 2 * scale); c.height = Math.ceil(h + pad * scale);
    var y = pad * scale / 2;
    lines.forEach(function (l, i) {
      x.font = fonts[i]; x.textBaseline = "top"; x.fillStyle = l.color;
      if (opt && opt.shadow) { x.shadowColor = "rgba(0,0,0,.75)"; x.shadowBlur = 6; }
      x.fillText(l.text, pad * scale, y);
      if (l.value) { var tw = x.measureText(l.text + "  ").width; x.fillStyle = l.vcolor; x.fillText(l.value, pad * scale + tw, y); }
      y += l.size * scale * 1.35;
    });
    return c;
  }
  var compact = function () { return root.clientWidth < 560; };
  function nodeLines(n) {
    var produced = n.kind === "output" && n.state === "on";
    var lines = [{ text: n.label, size: 13, w: 600, color: produced ? CSS.brass : CSS.bone,
      value: n.value, vcolor: produced ? CSS.brass : (n.state === "fail" ? CSS.red : CSS.dim) }];
    if (n.sub && !compact()) lines.push({ text: n.sub.length > 34 ? n.sub.slice(0, 33) + "…" : n.sub, size: 10, w: 400, color: CSS.sub });
    return lines;
  }
  function headerLines(l) {
    return [{ text: l.title.toUpperCase(), size: 11, w: 600, color: CSS.teal },
            { text: l.subtitle, size: 10, w: 400, color: CSS.sub }];
  }

  // ---------- Cámara (misma para 3D y 2D) ----------
  var span = (L - 1) * GAP;
  function shot(t, wall, aspect) {
    var far = Math.min(2.6, Math.max(1, 1.9 / aspect));
    var pos3, at;
    var fx = REPLAY && replaying && t < DUR ? focusX(t) : null;
    if (aspect < 0.9 && !reduced) {
      // Vertical (móvil): travelling continuo capa a capa, como la cámara del reel.
      var x = fx !== null ? fx : tourX(wall);
      return { p: [x - 1.6, 1.3, 11.5], at: [x + 1.1, -0.25, 0] };
    }
    if (fx !== null) {
      pos3 = [fx - 4.6, 1.5, 8.6]; at = [fx + 1.4, -0.15, 0];
    } else if (!REPLAY && !reduced) {
      var d = Math.sin(wall * 0.06) * span * 0.12;
      pos3 = [d - 2.2, 2.2, 15.4]; at = [d * 0.5 - 0.15, -0.35, 0];
    } else {
      pos3 = [-2.2, 2.3, 15.6]; at = [-0.15, -0.35, 0];
    }
    for (var i = 0; i < 3; i++) pos3[i] = at[i] + (pos3[i] - at[i]) * far;
    return { p: pos3, at: at };
  }
  function tourX(wall) {
    var k = (wall / 3.4) % L, i = Math.floor(k), f = k - i, e = f < 0.6 ? 0 : (f - 0.6) / 0.4;
    e = e * e * (3 - 2 * e);
    var a = DATA.layers[i].x, b = DATA.layers[(i + 1) % L].x;
    return i === L - 1 ? a + (b - a) * e : a + (b - a) * e;
  }
  var cam = null;
  function smoothCam(target, dt) {
    if (!cam || reduced) { cam = { p: target.p.slice(), at: target.at.slice() }; return cam; }
    var k = 1 - Math.exp(-dt * 1.6);
    for (var i = 0; i < 3; i++) { cam.p[i] += (target.p[i] - cam.p[i]) * k; cam.at[i] += (target.at[i] - cam.at[i]) * k; }
    return cam;
  }

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

  // ======================= Three.js =======================
  function start3D(THREE) {
    var renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, powerPreference: "low-power" });
    if (!renderer.getContext()) throw new Error("sin WebGL");
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.75));
    root.appendChild(renderer.domElement);
    var scene = new THREE.Scene();
    scene.fog = new THREE.Fog(0x0c1719, 11, 34);
    var camera = new THREE.PerspectiveCamera(34, 1, 0.1, 120);

    function sprite(canvas, height) {
      var tex = new THREE.CanvasTexture(canvas);
      tex.minFilter = THREE.LinearFilter;
      var m = new THREE.SpriteMaterial({ map: tex, transparent: true, depthWrite: false, fog: false });
      var s = new THREE.Sprite(m);
      s.scale.set(height * canvas.width / canvas.height, height, 1);
      return s;
    }
    var glowTex = (function () {
      var c = document.createElement("canvas"); c.width = c.height = 64;
      var g = c.getContext("2d"), r = g.createRadialGradient(32, 32, 0, 32, 32, 32);
      r.addColorStop(0, "rgba(255,255,255,1)"); r.addColorStop(0.25, "rgba(255,255,255,.55)"); r.addColorStop(1, "rgba(255,255,255,0)");
      g.fillStyle = r; g.fillRect(0, 0, 64, 64);
      return new THREE.CanvasTexture(c);
    })();

    // Placas de cristal por capa + cabecera mono
    DATA.layers.forEach(function (l) {
      var g = new THREE.PlaneGeometry(2.5, l.h);
      var plate = new THREE.Mesh(g, new THREE.MeshBasicMaterial({ color: 0x2b7f8c, transparent: true, opacity: 0.085,
        side: THREE.DoubleSide, depthWrite: false }));
      plate.rotation.y = Math.PI / 2; plate.position.set(l.x, 0, 0); scene.add(plate);
      var rim = new THREE.LineSegments(new THREE.EdgesGeometry(g), new THREE.LineBasicMaterial({ color: 0x58aeb9, transparent: true, opacity: 0.5 }));
      rim.rotation.y = Math.PI / 2; rim.position.set(l.x, 0, 0); scene.add(rim);
      var hdr = sprite(labelCanvas(headerLines(l)), 0.5);
      hdr.position.set(l.x, l.h / 2 + 0.38, 0); scene.add(hdr);
    });

    // Suelo con rejilla en perspectiva
    var grid = new THREE.GridHelper(70, 70, 0x2f7f8a, 0x16393f);
    grid.material.transparent = true; grid.material.opacity = 0.55; grid.position.y = floorY; scene.add(grid);

    // Aristas decorativas tenues
    var fp = new Float32Array(faint.length * 6);
    faint.forEach(function (e, i) { fp.set(e[0], i * 6); fp.set(e[1], i * 6 + 3); });
    var fg = new THREE.BufferGeometry(); fg.setAttribute("position", new THREE.BufferAttribute(fp, 3));
    scene.add(new THREE.LineSegments(fg, new THREE.LineBasicMaterial({ color: 0xdfeceb, transparent: true, opacity: 0.045, depthWrite: false })));
    var mp = new Float32Array(micro.length * 3);
    micro.forEach(function (m, i) { mp.set(m.p, i * 3); });
    var mg = new THREE.BufferGeometry(); mg.setAttribute("position", new THREE.BufferAttribute(mp, 3));
    scene.add(new THREE.Points(mg, new THREE.PointsMaterial({ color: 0xdfeceb, size: 0.05, transparent: true, opacity: 0.35, depthWrite: false })));

    // Aristas semánticas (color por vértice, se actualiza cada fotograma)
    var ep = new Float32Array(edges.length * 6), ec = new Float32Array(edges.length * 6);
    edges.forEach(function (e, i) { ep.set(pos[e[0]], i * 6); ep.set(pos[e[1]], i * 6 + 3); });
    var eg = new THREE.BufferGeometry();
    eg.setAttribute("position", new THREE.BufferAttribute(ep, 3));
    eg.setAttribute("color", new THREE.BufferAttribute(ec, 3));
    scene.add(new THREE.LineSegments(eg, new THREE.LineBasicMaterial({ vertexColors: true, transparent: true,
      blending: THREE.AdditiveBlending, depthWrite: false })));

    // Pulsos
    var pp = new Float32Array(edges.length * 3), pc = new Float32Array(edges.length * 3);
    var pg = new THREE.BufferGeometry();
    pg.setAttribute("position", new THREE.BufferAttribute(pp, 3));
    pg.setAttribute("color", new THREE.BufferAttribute(pc, 3));
    scene.add(new THREE.Points(pg, new THREE.PointsMaterial({ size: 0.42, map: glowTex, vertexColors: true, transparent: true,
      blending: THREE.AdditiveBlending, depthWrite: false })));

    // Neuronas etiquetadas
    var items = nodes.map(function (n) {
      var core = new THREE.Mesh(new THREE.SphereGeometry(0.075, 16, 12), new THREE.MeshBasicMaterial({ color: 0xffffff, transparent: true }));
      core.position.fromArray(pos[n.id]); scene.add(core);
      var halo = new THREE.Sprite(new THREE.SpriteMaterial({ map: glowTex, transparent: true, blending: THREE.AdditiveBlending, depthWrite: false }));
      halo.position.copy(core.position); scene.add(halo);
      var lab = sprite(labelCanvas(nodeLines(n), { shadow: true }), compact() ? 0.3 : 0.42);
      lab.center.set(-0.08, 0.5);
      lab.position.copy(core.position); scene.add(lab);
      return { n: n, core: core, halo: halo, lab: lab };
    });

    function resize() {
      var w = root.clientWidth, h = root.clientHeight;
      renderer.setSize(w, h, false); camera.aspect = w / h; camera.updateProjectionMatrix();
    }
    resize();
    if ("ResizeObserver" in window) new ResizeObserver(resize).observe(root);

    var last = performance.now();
    function frame(now) {
      var dt = Math.min(0.1, (now - last) / 1000); last = now;
      if (visible && !document.hidden) draw(dt);
      if (!reduced) requestAnimationFrame(frame);
    }
    function draw(dt) {
      var t = playT(), wall = clock();
      items.forEach(function (it) {
        var v = look(it.n, t, wall);
        it.core.material.color.setRGB(v.c[0], v.c[1], v.c[2]); it.core.material.opacity = v.a;
        it.core.scale.setScalar(v.k);
        it.halo.material.color.setRGB(v.c[0], v.c[1], v.c[2]);
        it.halo.material.opacity = v.a * (v.k > 1.2 ? 0.9 : 0.35);
        it.halo.scale.setScalar(0.55 * v.k);
        it.lab.material.opacity = v.la;
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
      renderer.render(scene, camera);
      hud(t);
    }
    if (reduced) { draw(1); } else { requestAnimationFrame(frame); }
  }

  // ======================= Canvas 2D (fallback) =======================
  function start2D() {
    var cv = document.createElement("canvas"); root.appendChild(cv);
    var g = cv.getContext("2d"), W = 0, H = 0, dpr = Math.min(window.devicePixelRatio || 1, 2);
    var labels = {};
    nodes.forEach(function (n) { labels[n.id] = labelCanvas(nodeLines(n), { shadow: true }); });
    var heads = DATA.layers.map(function (l) { return labelCanvas(headerLines(l)); });
    function resize() { W = root.clientWidth; H = root.clientHeight; cv.width = W * dpr; cv.height = H * dpr; }
    resize(); window.addEventListener("resize", resize);
    function proj(c, p) {
      var f = norm(sub(c.at, c.p)), r = norm(cross(f, [0, 1, 0])), u = cross(r, f), v = sub(p, c.p);
      var z = dot(v, f); if (z < 0.2) return null;
      var F = (H / 2) / Math.tan(17 * Math.PI / 180);
      return [W / 2 + dot(v, r) / z * F, H / 2 - dot(v, u) / z * F, F / z];
    }
    function sub(a, b) { return [a[0] - b[0], a[1] - b[1], a[2] - b[2]]; }
    function dot(a, b) { return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]; }
    function cross(a, b) { return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]; }
    function norm(a) { var l = Math.hypot(a[0], a[1], a[2]) || 1; return [a[0] / l, a[1] / l, a[2] / l]; }
    function rgba(c, a) { return "rgba(" + Math.round(c[0] * 255) + "," + Math.round(c[1] * 255) + "," + Math.round(c[2] * 255) + "," + a + ")"; }
    function line(c, A, B, style, w) {
      var a = proj(c, A), b = proj(c, B); if (!a || !b) return;
      g.strokeStyle = style; g.lineWidth = w; g.beginPath(); g.moveTo(a[0], a[1]); g.lineTo(b[0], b[1]); g.stroke();
    }
    var last = performance.now();
    function draw(dt) {
      var t = playT(), wall = clock(), c = smoothCam(shot(t, wall, W / H), dt);
      g.setTransform(dpr, 0, 0, dpr, 0, 0); g.clearRect(0, 0, W, H);
      for (var k = -20; k <= 20; k += 1) {
        line(c, [k, floorY, -20], [k, floorY, 20], "rgba(47,127,138,.22)", 1);
        line(c, [-20, floorY, k], [20, floorY, k], "rgba(47,127,138,.22)", 1);
      }
      DATA.layers.forEach(function (l, i) {
        var q = [[l.x, -l.h / 2, -1.25], [l.x, -l.h / 2, 1.25], [l.x, l.h / 2, 1.25], [l.x, l.h / 2, -1.25]].map(function (p) { return proj(c, p); });
        if (q.some(function (p) { return !p; })) return;
        g.beginPath(); q.forEach(function (p, j) { j ? g.lineTo(p[0], p[1]) : g.moveTo(p[0], p[1]); }); g.closePath();
        g.fillStyle = "rgba(43,127,140,.08)"; g.fill(); g.strokeStyle = "rgba(88,174,185,.5)"; g.lineWidth = 1; g.stroke();
        var hp = proj(c, [l.x, l.h / 2 + 0.38, 0]);
        if (hp) { var hh = 0.42 * hp[2], hw = hh * heads[i].width / heads[i].height; g.drawImage(heads[i], hp[0] - hw / 2, hp[1] - hh / 2, hw, hh); }
      });
      faint.forEach(function (e) { line(c, e[0], e[1], "rgba(223,236,235,.05)", 1); });
      edges.forEach(function (e, i) {
        var lv = edgeLevel(e, t), col = REPLAY && t >= byId[e[1]].t0 && byId[e[1]].state !== "off" ? COL.brass : COL.bone;
        line(c, pos[e[0]], pos[e[1]], rgba(col, lv), 1);
        var p = pulse(e, i, t, wall);
        if (p) {
          var A = pos[e[0]], B = pos[e[1]], pt = proj(c, [A[0] + (B[0] - A[0]) * p[0], A[1] + (B[1] - A[1]) * p[0], A[2] + (B[2] - A[2]) * p[0]]);
          if (pt) { g.fillStyle = rgba(COL.brass, p[1]); g.beginPath(); g.arc(pt[0], pt[1], Math.max(2, 0.07 * pt[2]), 0, 7); g.fill(); }
        }
      });
      nodes.forEach(function (n) {
        var p = proj(c, pos[n.id]); if (!p) return;
        var v = look(n, t, wall), r = Math.max(2, 0.075 * p[2] * v.k);
        g.fillStyle = rgba(v.c, v.a * 0.25); g.beginPath(); g.arc(p[0], p[1], r * 2.4, 0, 7); g.fill();
        g.fillStyle = rgba(v.c, v.a); g.beginPath(); g.arc(p[0], p[1], r, 0, 7); g.fill();
        var lc = labels[n.id], lh = (compact() ? 0.3 : 0.42) * p[2], lw = lh * lc.width / lc.height;
        g.globalAlpha = v.la; g.drawImage(lc, p[0] + lw * 0.08, p[1] - lh / 2, lw, lh); g.globalAlpha = 1;
      });
      hud(t);
    }
    function frame(now) {
      var dt = Math.min(0.1, (now - last) / 1000); last = now;
      if (visible && !document.hidden) draw(dt);
      if (!reduced) requestAnimationFrame(frame);
    }
    if (reduced) draw(1); else requestAnimationFrame(frame);
  }

  // ---------- Arranque: fuentes → Three.js (con tiempo límite) → 2D si falla ----------
  var started = false;
  function go2D() { if (started) return; started = true; try { start2D(); } catch (e) { hudT.textContent = "sin lienzo"; } }
  function go3D() {
    if (started) return;
    try { started = true; start3D(window.THREE); } catch (e) { root.innerHTML = ""; started = false; go2D(); }
  }
  var fontsReady = document.fonts && document.fonts.load
    ? Promise.race([document.fonts.load("600 26px 'IBM Plex Mono'"), new Promise(function (r) { setTimeout(r, 1500); })])
    : Promise.resolve();
  fontsReady.then(function () {
    if (window.FL_FORCE_2D) return go2D();
    var s = document.createElement("script");
    s.src = window.FL_THREE_URL; s.async = true;
    var timer = setTimeout(go2D, 5000);
    s.onload = function () { clearTimeout(timer); window.THREE ? go3D() : go2D(); };
    s.onerror = function () { clearTimeout(timer); go2D(); };
    document.head.appendChild(s);
  });
})();
