/**
 * app.js —— 前端应用入口
 * 负责：初始化显示设置与提示条、构建标签导航、按需挂载各视图。
 * 各视图相互独立，仅在切换标签时懒加载对应数据。
 */

import { qs, el, clear } from "./core/dom.js";
import { loadSettings, bindSettingsControls } from "./core/settings.js";
import { initToast, toastError } from "./core/toast.js";
import { initErrorCapture, log } from "./core/log.js";
import { initParticles } from "./core/particles.js";

import * as studentsView from "./views/students.js";
import * as frameworkView from "./views/framework.js";
import * as forgeView from "./views/forge.js";
import * as libraryView from "./views/library.js";
// tasks 视图在异步任务模块就绪后接入，缺失时自动跳过该标签
import * as tasksView from "./views/tasks.js";

/** 标签定义：id 与视图模块一一对应。 */
const TABS = [
  { id: "students", label: "学生档案", module: studentsView },
  { id: "framework", label: "评价框架", module: frameworkView },
  { id: "forge", label: "资源生成", module: forgeView },
  { id: "library", label: "资源库", module: libraryView },
  { id: "tasks", label: "任务队列", module: tasksView },
];

/** 视图控制器缓存，避免重复构建。 */
const controllers = {};
let activeTab = null;

/** 构建标签导航与视图容器。 */
function buildShell() {
  const tabbar = qs("#tabbar");
  const main = qs("#main");
  clear(tabbar);
  clear(main);

  for (const tab of TABS) {
    // 标签按钮
    const button = el("button", {
      class: "tab",
      type: "button",
      role: "tab",
      id: `tab-${tab.id}`,
      "aria-controls": `view-${tab.id}`,
      "aria-selected": "false",
      text: tab.label,
      on: { click: () => activate(tab.id) },
    });
    button.dataset.tab = tab.id;
    tabbar.append(button);

    // 视图容器
    const section = el("section", {
      class: "view",
      id: `view-${tab.id}`,
      role: "tabpanel",
      "aria-labelledby": `tab-${tab.id}`,
      hidden: true,
    });
    main.append(section);
  }
}

/** 切换到指定标签。 */
function activate(id) {
  const tab = TABS.find((item) => item.id === id);
  if (!tab || !tab.module || !tab.module.createView) {
    toastError("该功能模块尚未接入");
    return;
  }
  if (activeTab === id) return;
  // 离开旧标签时停止其后台轮询等副作用
  if (activeTab && controllers[activeTab] && controllers[activeTab].destroy) {
    controllers[activeTab].destroy();
  }
  activeTab = id;

  // 更新按钮选中态与面板可见性
  for (const item of TABS) {
    const selected = item.id === id;
    const button = qs(`#tab-${item.id}`);
    const section = qs(`#view-${item.id}`);
    if (button) button.setAttribute("aria-selected", String(selected));
    if (section) section.hidden = !selected;
  }

  // 懒构建并刷新视图
  const section = qs(`#view-${id}`);
  if (!controllers[id]) {
    controllers[id] = tab.module.createView(section, {
      // 生成完成后自动刷新资源库，保持数据联动
      onGenerated: () => {
        if (controllers.library) controllers.library.refresh();
      },
    });
    if (controllers[id].init) controllers[id].init();
  } else if (controllers[id].refresh) {
    controllers[id].refresh();
  }
}

/** 页面启动。 */
document.addEventListener("DOMContentLoaded", () => {
  initErrorCapture();
  log.info("SEN-Kaleido 前端已加载");
  initParticles(document.getElementById("particles"));
  initToast();
  loadSettings();
  bindSettingsControls(qs("#settings"));
  buildShell();
  activate("students");
});
