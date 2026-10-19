/**
 * core/contextmenu.js —— 应用内右键菜单
 * 在鼠标位置弹出自定义菜单，替代浏览器原生菜单，用于列表项的快捷操作。
 */

import { el } from "./dom.js";

let current = null;

/** 关闭已打开的菜单。 */
function closeMenu() {
  if (!current) return;
  current.remove();
  current = null;
}

/**
 * 在鼠标位置打开右键菜单。
 * @param {MouseEvent} event 触发事件（contextmenu）
 * @param {Array<Object|null>} items 菜单项：{ label, onSelect, danger, disabled }；null 表示分隔线
 */
export function openContextMenu(event, items) {
  event.preventDefault();
  closeMenu();

  const menu = el("div", { class: "context-menu", role: "menu" });
  for (const item of items) {
    if (!item) {
      menu.append(el("div", { class: "context-menu-sep" }));
      continue;
    }
    menu.append(
      el("button", {
        class: `context-menu-item${item.danger ? " is-danger" : ""}`,
        type: "button",
        role: "menuitem",
        text: item.label,
        disabled: item.disabled,
        on: {
          click: () => {
            closeMenu();
            if (item.onSelect) item.onSelect();
          },
        },
      })
    );
  }

  document.body.append(menu);
  // 定位并避免超出视口
  const rect = menu.getBoundingClientRect();
  const x = Math.min(event.clientX, window.innerWidth - rect.width - 8);
  const y = Math.min(event.clientY, window.innerHeight - rect.height - 8);
  menu.style.left = `${Math.max(8, x)}px`;
  menu.style.top = `${Math.max(8, y)}px`;

  // 延迟绑定，避免本次 contextmenu 事件立即关闭菜单
  window.setTimeout(() => {
    document.addEventListener("click", closeMenu, { once: true });
    document.addEventListener("contextmenu", closeMenu, { once: true });
    document.addEventListener(
      "keydown",
      (keyEvent) => {
        if (keyEvent.key === "Escape") closeMenu();
      },
      { once: true }
    );
  }, 0);
}
