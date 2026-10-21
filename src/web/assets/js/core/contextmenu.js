/**
 * core/contextmenu.js —— 应用内右键菜单
 * 在鼠标位置弹出自定义菜单，替代浏览器原生菜单，用于列表项的快捷操作。
 * 全局监听只绑定一次，避免重复绑定导致菜单被误关闭。
 */

import { el } from "./dom.js";

let current = null;
let bound = false;

/** 关闭已打开的菜单。 */
function closeMenu() {
  if (!current) return;
  current.remove();
  current = null;
}

/** 点击/按下菜单外部时关闭。 */
function onPointerDown(event) {
  if (current && !current.contains(event.target)) closeMenu();
}

/** Esc 关闭。 */
function onKeyDown(event) {
  if (event.key === "Escape") closeMenu();
}

/** 全局监听仅绑定一次。 */
function bindGlobal() {
  if (bound) return;
  bound = true;
  // 捕获阶段：先于其它点击处理
  document.addEventListener("mousedown", onPointerDown, true);
  document.addEventListener("keydown", onKeyDown, true);
  window.addEventListener("resize", closeMenu);
  // 只监听页面滚动，避免任务列表内思考框的自动滚动误关菜单。
  window.addEventListener("scroll", closeMenu);
}

/**
 * 在鼠标位置打开右键菜单。
 * @param {MouseEvent} event 触发事件（contextmenu）
 * @param {Array<Object|null>} items 菜单项：{ label, onSelect, danger, disabled }；null 表示分隔线
 */
export function openContextMenu(event, items) {
  event.preventDefault();
  closeMenu();
  bindGlobal();

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
  current = menu;

  // 定位并避免超出视口
  const rect = menu.getBoundingClientRect();
  const x = Math.min(event.clientX, window.innerWidth - rect.width - 8);
  const y = Math.min(event.clientY, window.innerHeight - rect.height - 8);
  menu.style.left = `${Math.max(8, x)}px`;
  menu.style.top = `${Math.max(8, y)}px`;
}
