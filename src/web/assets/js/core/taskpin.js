/**
 * core/taskpin.js —— 任务详情钉住后的右上角缩略输出
 * 模态窗口关闭后仍保留一个小面板，便于教师继续观察最近一次任务结果。
 */

import { el, clear } from "./dom.js";
import { TASK_STATUS, TASK_TYPE, label } from "./format.js";

let current = null;
let host = null;

/** 获取或创建固定挂载点。 */
function ensureHost() {
  if (!host || !host.isConnected) {
    host = el("div", { class: "task-pin-host", id: "task-pin-host" });
    document.body.append(host);
  }
  return host;
}

/** 重新渲染缩略面板。 */
function render() {
  const box = ensureHost();
  clear(box);
  if (!current) return;

  const { task, summary, onOpen } = current;
  const statusClass = `status-${task.status || "pending"}`;
  box.append(
    el("aside", { class: "task-pin", role: "complementary", "aria-label": "钉住的任务输出" }, [
      el("div", { class: "task-pin-head" }, [
        el("span", { class: "task-pin-title", text: "钉住输出" }),
        el("button", {
          class: "task-pin-close",
          type: "button",
          title: "取消钉住",
          "aria-label": "取消钉住",
          text: "×",
          on: { click: () => unpin() },
        }),
      ]),
      el("div", { class: "task-pin-body" }, [
        el("div", { class: "badge-row" }, [
          el("span", { class: "badge badge-muted", text: label(TASK_TYPE, task.task_type) }),
          el("span", { class: `status ${statusClass}`, text: label(TASK_STATUS, task.status) }),
        ]),
        el("p", { class: "task-pin-summary", text: summary || "暂无输出摘要。" }),
        el("p", { class: "meta", text: task.task_id || "" }),
      ]),
      el("div", { class: "task-pin-actions" }, [
        el("button", {
          class: "btn btn-sm",
          type: "button",
          text: "展开详情",
          on: { click: () => onOpen && onOpen() },
        }),
      ]),
    ])
  );
}

/** 当前任务是否已钉住。 */
export function isPinned(taskId) {
  return Boolean(current && current.task.task_id === taskId);
}

/**
 * 钉住任务并显示右上角缩略输出。
 * @param {Object} task 任务对象
 * @param {Object} options summary（摘要文本）与 onOpen（重新打开详情）
 */
export function pinTask(task, { summary = "", onOpen = null } = {}) {
  current = { task, summary, onOpen };
  render();
}

/** 刷新已钉住任务的快照（仅当任务 ID 相同）。 */
export function updatePinnedTask(task, summary = "") {
  if (!current || current.task.task_id !== task.task_id) return;
  current.task = task;
  if (summary) current.summary = summary;
  render();
}

/** 取消钉住并移除缩略面板。 */
export function unpin() {
  current = null;
  if (host) clear(host);
}
