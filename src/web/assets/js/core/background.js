/**
 * core/background.js —— 背景装饰层
 * 在 #bg-layer 中随机生成若干模糊彩色晕点，各自缓慢游动，
 * 为页面增加生动感（纯装饰，pointer-events 关闭，不影响交互）。
 */

/** 晕点配色（取自设计主色与语义色的柔和版）。 */
const PALETTE = ["#2f6df0", "#1f8f5f", "#b7791f", "#7b5cf0", "#e06c9f"];

/** 生成并挂载背景晕点。 */
export function initBackground() {
  const layer = document.getElementById("bg-layer");
  if (!layer) return;

  const count = 6;
  for (let i = 0; i < count; i += 1) {
    const blob = document.createElement("span");
    blob.className = "blob";
    const size = 220 + Math.random() * 260;
    blob.style.width = `${size}px`;
    blob.style.height = `${size}px`;
    blob.style.left = `${Math.random() * 100}%`;
    blob.style.top = `${Math.random() * 100}%`;
    blob.style.background = PALETTE[i % PALETTE.length];
    blob.style.opacity = `${0.26 + Math.random() * 0.2}`;
    // 自定义属性驱动 keyframes 的位移方向与距离
    blob.style.setProperty("--dx", `${(Math.random() - 0.5) * 260}px`);
    blob.style.setProperty("--dy", `${(Math.random() - 0.5) * 260}px`);
    blob.style.animationDuration = `${18 + Math.random() * 16}s`;
    blob.style.animationDelay = `${-Math.random() * 12}s`;
    layer.append(blob);
  }
}
