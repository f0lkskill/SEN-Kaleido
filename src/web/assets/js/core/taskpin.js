/**
 * core/taskpin.js —— 任务详情钉住后的右上角缩略输出
 * 模态窗口关闭后仍保留一个小面板，便于教师继续观察最近一次任务结果。
 * 轮询更新只刷新文本，不重建 DOM，避免动画反复播放。
 */

import { el, clear } from "./dom.js";
import { TASK_STATUS, TASK_TYPE, label } from "./format.js";

let current = null;
let host = null;
let nodes = null;

/** 获取或创建固定挂载点。 */
function ensureHost() {
  if (!host || !host.isConnected) {
    host = el("div", { class: "task-pin-host", id: "task-pin-host" });
    document.body.append(host);
  }
  return host;
}

/** 构建一次缩略面板 DOM。 */
function build() {
  const box = ensureHost();
  clear(box);
  nodes = null;
  if (!current) return;

  const { task, onOpen } = current;
  const typeBadge = el("span", { class: "badge badge-muted" });
  const statusBadge = el("span", { class: "status" });
  const summary = el("p", { class: "task-pin-summary" });
  const reasoningLabel = el("span", {
    class: "task-pin-stream-label",
    text: "思考过程",
  });
  const reasoning = el("pre", { class: "task-pin-stream" });
  const reasoningBlock = el(
    "div",
    { class: "task-pin-stream-block", hidden: true },
    [reasoningLabel, reasoning]
  );
  const stream = el("pre", { class: "task-pin-stream" });
  const streamBlock = el(
    "div",
    { class: "task-pin-stream-block", hidden: true },
    [el("span", { class: "task-pin-stream-label", text: "实时输出" }), stream]
  );
  const meta = el("p", { class: "meta" });

  box.append(
    el(
      "aside",
      {
        class: "task-pin",
        role: "complementary",
        "aria-label": "钉住的任务输出",
      },
      [
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
          el("div", { class: "badge-row" }, [typeBadge, statusBadge]),
          summary,
          reasoningBlock,
          streamBlock,
          meta,
        ]),
        el("div", { class: "task-pin-actions" }, [
          el("button", {
            class: "btn btn-sm",
            type: "button",
            text: "展开详情",
            on: { click: () => onOpen && onOpen() },
          }),
        ]),
      ]
    )
  );

  nodes = {
    root: box.firstElementChild,
    typeBadge,
    statusBadge,
    summary,
    reasoningLabel,
    reasoningBlock,
    reasoning,
    streamBlock,
    stream,
    meta,
  };
  updateContent();
}

/** 只更新文本内容，不重建节点。 */
function updateContent() {
  if (!current || !nodes) return;
  const { task, summary } = current;
  const statusClass = `status-${task.status || "pending"}`;

  nodes.typeBadge.textContent = label(TASK_TYPE, task.task_type);
  nodes.statusBadge.className = `status ${statusClass}`;
  nodes.statusBadge.textContent = label(TASK_STATUS, task.status);
  nodes.summary.textContent = summary || "暂无输出摘要。";

  const reasoning = String(task.reasoning || "").trim();
  nodes.reasoningBlock.hidden = !reasoning;
  nodes.reasoningLabel.textContent =
    task.status === "running" ? "思考中…" : "思考过程";
  nodes.reasoning.textContent = reasoning.slice(-800);
  if (reasoning) nodes.reasoning.scrollTop = nodes.reasoning.scrollHeight;

  const stream = String(task.stream_content || "").trim();
  nodes.streamBlock.hidden = !stream;
  nodes.stream.textContent = stream.slice(-800);
  if (stream) nodes.stream.scrollTop = nodes.stream.scrollHeight;

  nodes.meta.textContent = task.task_id || "";
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
  build();
}

/** 刷新已钉住任务的快照（仅当任务 ID 相同），不重播入场动画。 */
export function updatePinnedTask(task, summary = "") {
  if (!current || current.task.task_id !== task.task_id) return;
  current.task = task;
  if (summary) current.summary = summary;
  if (!nodes || !nodes.root || !nodes.root.isConnected) {
    build();
    return;
  }
  updateContent();
}

/** 取消钉住并移除缩略面板。 */
export function unpin() {
  current = null;
  nodes = null;
  if (host) clear(host);
}
