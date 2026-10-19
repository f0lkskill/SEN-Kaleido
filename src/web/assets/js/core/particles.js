/**
 * core/particles.js —— 科幻感粒子连线背景
 * 在固定画布上绘制少量缓慢飘动的粒子，并把相近粒子连线，营造科技感。
 * 用 canvas 绘制（不用模糊/滤镜），粒子数少、连线距离受限，开销低；
 * 页面隐藏时自动暂停，尊重 prefers-reduced-motion（此时只画静态一帧）。
 */

const COUNT = 44; // 粒子数量（保持较低以控制开销）
const LINK_DIST = 132; // 连线距离阈值（像素）
const SPEED = 0.28; // 基础漂移速度

/**
 * 初始化背景粒子。
 * @param {HTMLCanvasElement} canvas 目标画布
 */
export function initParticles(canvas) {
  if (!canvas) return;
  const ctx = canvas.getContext("2d");
  if (!ctx) return;

  const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  let width = 0;
  let height = 0;
  let particles = [];
  let rafId = null;

  function resize() {
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    width = window.innerWidth;
    height = window.innerHeight;
    canvas.width = Math.floor(width * dpr);
    canvas.height = Math.floor(height * dpr);
    canvas.style.width = `${width}px`;
    canvas.style.height = `${height}px`;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  }

  function seed() {
    particles = Array.from({ length: COUNT }, () => ({
      x: Math.random() * width,
      y: Math.random() * height,
      vx: (Math.random() - 0.5) * SPEED,
      vy: (Math.random() - 0.5) * SPEED,
    }));
  }

  /** 单帧：更新位置并绘制粒子与连线。 */
  function frame() {
    ctx.clearRect(0, 0, width, height);
    for (const p of particles) {
      p.x += p.vx;
      p.y += p.vy;
      if (p.x <= 0 || p.x >= width) p.vx *= -1;
      if (p.y <= 0 || p.y >= height) p.vy *= -1;
    }
    for (let a = 0; a < particles.length; a += 1) {
      for (let b = a + 1; b < particles.length; b += 1) {
        const dx = particles[a].x - particles[b].x;
        const dy = particles[a].y - particles[b].y;
        const dist = Math.hypot(dx, dy);
        if (dist < LINK_DIST) {
          const alpha = (1 - dist / LINK_DIST) * 0.28;
          ctx.strokeStyle = `rgba(47, 109, 240, ${alpha})`;
          ctx.lineWidth = 1;
          ctx.beginPath();
          ctx.moveTo(particles[a].x, particles[a].y);
          ctx.lineTo(particles[b].x, particles[b].y);
          ctx.stroke();
        }
      }
    }
    for (const p of particles) {
      ctx.fillStyle = "rgba(47, 109, 240, 0.5)";
      ctx.beginPath();
      ctx.arc(p.x, p.y, 1.6, 0, Math.PI * 2);
      ctx.fill();
    }
  }

  function loop() {
    frame();
    rafId = window.requestAnimationFrame(loop);
  }

  function start() {
    if (rafId === null) rafId = window.requestAnimationFrame(loop);
  }
  function stop() {
    if (rafId !== null) {
      window.cancelAnimationFrame(rafId);
      rafId = null;
    }
  }

  resize();
  seed();
  window.addEventListener("resize", () => {
    resize();
    seed();
  });
  // 页面不可见时暂停绘制，降低后台开销
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) stop();
    else if (!reduce) start();
  });

  if (reduce) frame();
  else start();
}
