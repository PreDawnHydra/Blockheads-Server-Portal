// The main menu's background, as MainMenuUI -render:projectionMatrix: draws it:
//  - mainMenuBackground.png on a square 3·max(halfW, halfH) wide, centred, turning at 0.15 rad/s;
//  - the game's 2048 stars (direction + brightness w) on a sphere around the camera, additive, point size and
//    brightness v = (w·scale/4)², slowly drifting on three angles;
//  - five clocks (clockFace / clockHand), very faint, at setClockPositions' places, hands wandering at random
//    speeds (value += dt·speed·0.5, speed eases toward a random goal re-rolled every few seconds).
// Without the assets it draws a plain blue gradient and the stars.
(() => {
  const canvas = document.getElementById("bg");
  const ctx = canvas.getContext("2d");
  const img = (src) => { const i = new Image(); i.src = src; return i; };
  const background = img("/game/GameResources/mainMenuBackground.png");
  const face = img("/game/GameResources/clockFace.png");
  const hand = img("/game/GameResources/clockHand.png");
  let stars = [];
  fetch("/theme/stars.json").then((r) => r.json()).then((s) => (stars = s)).catch(() => {});

  const rand = (a, b) => a + Math.random() * (b - a);
  // Clock i: centre and half-size as fractions of the half screen (y up), and its scroll factor k_i.
  const clocks = [
    [-0.5, -0.83, 0.42, "w"], [-0.86, 0.76, 0.39, "h"], [0.92, -0.12, 0.31, "h"],
    [0.23, -0.45, 0.23, "h"], [0.64, 0.64, 0.4, "w"],
  ].map(([x, y, s, by]) => ({ x, y, s, by, value: rand(-1, 1), speed: rand(-1, 1), goal: rand(-1, 1), timer: rand(0, 1) }));
  const drift = [0, 1, 2].map(() => ({ a: rand(0, 1), speed: rand(-1, 1), goal: rand(-1, 1), timer: rand(0, 1) }));

  let w = 0, h = 0, dpr = 1, angle = 0, last = performance.now();
  function resize() {
    dpr = Math.min(window.devicePixelRatio || 1, 2);
    w = window.innerWidth; h = window.innerHeight;
    canvas.width = Math.round(w * dpr); canvas.height = Math.round(h * dpr);
  }
  window.addEventListener("resize", resize);
  resize();

  function wander(o, dt, rate) {
    o.speed = (1 - dt) * o.speed + dt * o.goal;
    o.timer -= rate * dt;
    if (o.timer <= 0) { o.goal = rand(-1, 1); o.timer = rand(0, 1); }
  }

  function rotate(v, axis, t) {
    const c = Math.cos(t), s = Math.sin(t);
    const [x, y, z] = v;
    if (axis === 0) return [x, y * c - z * s, y * s + z * c];
    if (axis === 1) return [x * c + z * s, y, -x * s + z * c];
    return [x * c - y * s, x * s + y * c, z];
  }

  function frame(now) {
    const dt = Math.min((now - last) / 1000, 0.1);
    last = now;
    angle += 0.15 * dt;
    const halfW = w / 2, halfH = h / 2;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.globalCompositeOperation = "source-over";
    ctx.globalAlpha = 1;
    if (background.complete && background.naturalWidth) {
      const side = 3 * Math.max(halfW, halfH);
      ctx.save();
      ctx.translate(halfW, halfH);
      ctx.rotate(-angle);
      ctx.imageSmoothingEnabled = true;
      ctx.drawImage(background, -side / 2, -side / 2, side, side);
      ctx.restore();
    } else {
      const g = ctx.createLinearGradient(0, 0, w, h);
      g.addColorStop(0, "#1c1f6b"); g.addColorStop(1, "#2a73c9");
      ctx.fillStyle = g; ctx.fillRect(0, 0, w, h);
    }

    // Stars: perspective with a 60° vertical field (narrowed by h/w in landscape), camera at the sphere's centre.
    for (const d of drift) { d.a += dt * d.speed * 0.01; wander(d, dt, 0.05); }
    const fov = (Math.PI / 3) * (h < w ? h / w : 1);
    const f = 1 / Math.tan(fov / 2), aspect = w / h;
    ctx.globalCompositeOperation = "lighter";
    ctx.fillStyle = "#fff";
    for (const s of stars) {
      let v = [s[0], s[1], s[2]];
      v = rotate(v, 0, 2 * Math.PI * drift[0].a);
      v = rotate(v, 1, 2 * Math.PI * drift[1].a);
      v = rotate(v, 2, 2 * Math.PI * drift[2].a);
      if (v[2] >= -0.01) continue;
      const x = (f / aspect) * v[0] / -v[2], y = f * v[1] / -v[2];
      if (x < -1 || x > 1 || y < -1 || y > 1) continue;
      const size = Math.pow((s[3] * dpr) / 4, 2);
      ctx.globalAlpha = Math.min(size, 1);
      const px = Math.max(size, 1) / dpr;
      ctx.fillRect(halfW + x * halfW - px / 2, halfH - y * halfH - px / 2, px, px);
    }

    // Clocks: faces at ~6 % light, hands at 12 %.
    if (face.complete && face.naturalWidth) {
      ctx.imageSmoothingEnabled = true;
      for (const [i, c] of clocks.entries()) {
        c.value += dt * c.speed * 0.5;
        wander(c, dt, 0.2);
        const cx = halfW + c.x * halfW, cy = halfH - c.y * halfH;
        const s = c.s * (c.by === "w" ? halfW : halfH);
        ctx.globalCompositeOperation = "lighter";
        ctx.globalAlpha = 0.06;
        ctx.drawImage(face, cx - s, cy - s, 2 * s, 2 * s);
        if (!hand.complete || !hand.naturalWidth) continue;
        ctx.globalCompositeOperation = "source-over";
        ctx.globalAlpha = 0.12;
        const minute = 5 * c.value, hour = minute / 12;
        for (const [a, len] of [[minute, (2 * s) / 3], [hour, (5 * s) / 12]]) {
          ctx.save();
          ctx.translate(cx, cy);
          ctx.rotate(-a);
          ctx.drawImage(hand, -s / 12, -len, s / 6, len + s / 12);
          ctx.restore();
        }
      }
    }
    ctx.globalAlpha = 1;
    ctx.globalCompositeOperation = "source-over";
    requestAnimationFrame(frame);
  }
  requestAnimationFrame(frame);
})();
