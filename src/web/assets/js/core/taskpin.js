/**
 * core/taskpin.js —— 任务详情钉住后的右上角缩略输出
 * 模态窗口关闭后仍保留一个小面板，便于教师继续观察最近一次任务结果。
 * 轮询更新只刷新文本，不重建 DOM，避免动画反复播放。
 */

import { api } from "./api.js";
import { el, clear } from "./dom.js";
import { TASK_STATUS, TASK_TYPE, label } from "./format.js";

const ACTIVE_STATUS = ["pending", "running"];
const POLL_INTERVAL = 800;

let current = null;
let host = null;
let nodes = null;
let pollTimer = null;
let closing = false;

/** 获取或创建固定挂载点。 */
function ensureHost() {
  if (!host || !host.isConnected) {
    host = el("div", { class: "task-pin-host", id: "task-pin-host" });
    document.body.append(host);
  }
  return host;
}

/** 生成比任务 ID 更易读的标题。 */
function taskTitle(task) {
  const payload = task.payload || {};
  const type = label(TASK_TYPE, task.task_type) || task.task_type || "任务";
  if (task.task_type === "forge.generate") {
    return payload.topic ? `${payload.topic} · ${type}` : type;
  }
  if (task.task_type === "facet.evaluate") {
    return payload.resource_id ? `资源 ${payload.resource_id} · ${type}` : type;
  }
  if (task.task_type === "forge.portrait") {
    return payload.profile_id ? `学生 ${payload.profile_id} · ${type}` : type;
  }
  if (task.task_type === "loop.evaluate") {
    return payload.student_id ? `学生 ${payload.student_id} · ${type}` : type;
  }
  return type;
}

/** 构建一次缩略面板 DOM。 */
function build() {
  const box = ensureHost();
  clear(box);
  nodes = null;
  closing = false;
  if (!current) return;

  const { task, onOpen } = current;
  const title = el("span", {
    class: "task-pin-title",
    text: taskTitle(task),
    title: task.task_id || "",
  });
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
  const minimizeButton = el("button", {
    class: "task-pin-minimize",
    type: "button",
    title: "最小化",
    "aria-label": "最小化钉住面板",
    "aria-expanded": "true",
    text: "−",
    on: { click: () => toggleMinimize() },
  });

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
          title,
          el("div", { class: "task-pin-head-actions" }, [
            minimizeButton,
            el("button", {
              class: "task-pin-close",
              type: "button",
              title: "取消钉住",
              "aria-label": "取消钉住",
              text: "×",
              on: { click: () => unpin() },
            }),
          ]),
        ]),
        el("div", { class: "task-pin-collapsible" }, [
          el("div", { class: "task-pin-collapsible-inner" }, [
            el("div", { class: "task-pin-body" }, [
              el("div", { class: "badge-row" }, [typeBadge, statusBadge]),
              summary,
              reasoningBlock,
            ]),
            onOpen
              ? el("div", { class: "task-pin-actions" }, [
                  el("button", {
                    class: "btn btn-sm",
                    type: "button",
                    text: "展开详情",
                    on: { click: () => onOpen() },
                  }),
                ])
              : null,
          ]),
        ]),
      ]
    )
  );

  nodes = {
    root: box.firstElementChild,
    title,
    typeBadge,
    statusBadge,
    summary,
    reasoningLabel,
    reasoningBlock,
    reasoning,
    minimizeButton,
  };
  updateContent();
}

/** 折叠/展开面板主体。 */
function toggleMinimize() {
  if (!nodes || !nodes.root) return;
  const minimized = nodes.root.classList.toggle("is-minimized");
  nodes.minimizeButton.textContent = minimized ? "+" : "−";
  nodes.minimizeButton.title = minimized ? "展开" : "最小化";
  nodes.minimizeButton.setAttribute(
    "aria-label",
    minimized ? "展开钉住面板" : "最小化钉住面板"
  );
  nodes.minimizeButton.setAttribute("aria-expanded", String(!minimized));
}

/** 只更新文本内容，不重建节点。 */
function updateContent() {
  if (!current || !nodes) return;
  const { task, summary } = current;
  const statusClass = `status-${task.status || "pending"}`;

  nodes.root.dataset.status = task.status || "pending";
  nodes.title.textContent = taskTitle(task);
  nodes.title.title = task.task_id || "";
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
}

/** 钉住期间独立轮询，离开任务队列页后仍能刷新思考流。 */
function schedulePoll() {
  clearTimeout(pollTimer);
  pollTimer = null;
  if (!current || !ACTIVE_STATUS.includes(current.task.status)) return;
  pollTimer = setTimeout(pollPinned, POLL_INTERVAL);
}

async function pollPinned() {
  pollTimer = null;
  if (!current) return;
  const taskId = current.task.task_id;
  try {
    const task = await api.getTask(taskId);
    if (!current || current.task.task_id !== taskId) return;
    current.task = task;
    if (current.summarize) current.summary = current.summarize(task);
    if (!nodes || !nodes.root || !nodes.root.isConnected) build();
    else updateContent();
  } catch (err) {
    // 轮询失败不打断面板，下一次继续尝试。
  }
  if (current && current.task.task_id === taskId) schedulePoll();
}

/** 当前任务是否已钉住。 */
export function isPinned(taskId) {
  return Boolean(current && current.task.task_id === taskId);
}

/**
 * 钉住任务并显示右上角缩略输出。
 * @param {Object} task 任务对象
 * @param {Object} options summary（摘要文本）、onOpen（重新打开详情）与 summarize（摘要生成函数）
 */
export function pinTask(
  task,
  { summary = "", onOpen = null, summarize = null } = {}
) {
  current = { task, summary, onOpen, summarize };
  build();
  schedulePoll();
}

/** 刷新已钉住任务的快照（仅当任务 ID 相同），不重播入场动画。 */
export function updatePinnedTask(task, summary = "") {
  if (!current || current.task.task_id !== task.task_id) return;
  current.task = task;
  if (summary) current.summary = summary;
  if (!nodes || !nodes.root || !nodes.root.isConnected) {
    build();
    if (!pollTimer) schedulePoll();
    return;
  }
  updateContent();
  if (!pollTimer) schedulePoll();
}

/** 取消钉住：先播放退出动画，再移除缩略面板。 */
export function unpin() {
  current = null;
  clearTimeout(pollTimer);
  pollTimer = null;

  const root = nodes && nodes.root;
  if (!root || !root.isConnected || closing) {
    if (host) clear(host);
    nodes = null;
    return;
  }

  closing = true;
  root.classList.add("is-closing");
  let finished = false;
  const finish = () => {
    if (finished) return;
    finished = true;
    // 动画期间若已钉住新任务，不要清掉新面板
    if (nodes && nodes.root === root) {
      nodes = null;
      if (host) clear(host);
    }
    closing = false;
  };
  root.addEventListener("animationend", finish, { once: true });
  window.setTimeout(finish, 260);
}
