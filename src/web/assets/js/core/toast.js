/**
 * core/toast.js —— 全局提示条
 * 用于反馈操作成功/失败，作为无障碍的 live region 播报给屏幕阅读器。
 */

let toastEl = null;
let timer = null;

/** 载入页面时缓存提示条节点。 */
export function initToast() {
  toastEl = document.getElementById("toast");
}

/**
 * 显示提示。
 * @param {string} message 文本
 * @param {"info"|"success"|"error"} [kind] 类型
 */
export function toast(message, kind = "info") {
  if (!toastEl) return;
  toastEl.textContent = message;
  toastEl.className = `toast show ${kind}`;
  clearTimeout(timer);
  timer = setTimeout(() => {
    toastEl.className = "toast";
  }, 3600);
}

/** 便捷：成功提示。 */
export function toastSuccess(message) {
  toast(message, "success");
}

/** 便捷：错误提示。 */
export function toastError(message) {
  toast(message, "error");
}
