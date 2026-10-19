/**
 * core/dialog.js —— 自定义确认对话框
 * 用应用内模态窗口替代浏览器原生 confirm，保持一致的视觉与无障碍体验。
 */

import { el } from "./dom.js";

/**
 * 弹出确认对话框。
 * @param {Object} options 选项：title、message、confirmText、cancelText、danger
 * @returns {Promise<boolean>} 用户是否确认
 */
export function confirmDialog({
  title = "请确认",
  message = "",
  confirmText = "确认",
  cancelText = "取消",
  danger = false,
} = {}) {
  return new Promise((resolve) => {
    const overlay = el("div", {
      class: "modal-overlay",
      role: "dialog",
      "aria-modal": "true",
      "aria-label": title,
    });
    const dialog = el("div", { class: "modal modal-sm" });
    let settled = false;

    const close = (result) => {
      if (settled) return;
      settled = true;
      document.removeEventListener("keydown", onKey);
      overlay.classList.add("leaving");
      window.setTimeout(() => overlay.remove(), 200);
      resolve(result);
    };
    const onKey = (event) => {
      if (event.key === "Escape") close(false);
    };

    const confirmBtn = el("button", {
      class: `btn ${danger ? "btn-danger" : "btn-primary"}`,
      type: "button",
      text: confirmText,
      on: { click: () => close(true) },
    });
    const cancelBtn = el("button", {
      class: "btn",
      type: "button",
      text: cancelText,
      on: { click: () => close(false) },
    });

    dialog.append(
      el("div", { class: "modal-head" }, [el("h3", { text: title })]),
      el("p", { class: "modal-text", text: message }),
      el("div", { class: "modal-actions" }, [cancelBtn, confirmBtn])
    );
    overlay.append(dialog);
    // 点击遮罩取消
    overlay.addEventListener("click", (event) => {
      if (event.target === overlay) close(false);
    });
    document.addEventListener("keydown", onKey);
    document.body.append(overlay);
    confirmBtn.focus();
  });
}
