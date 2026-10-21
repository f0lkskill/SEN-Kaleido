/**
 * views/tasks.js —— 任务队列视图
 * 左侧任务列表（右键菜单 / 详情模态框 / 钉住右上角缩略输出），
 * 右侧触发任务面板。存在未完成任务时自动轮询刷新。
 */

import { api } from "../core/api.js";
import { el, clear, placeholder, panel } from "../core/dom.js";
import { renderMarkdown } from "../core/markdown.js";
import { openContextMenu } from "../core/contextmenu.js";
import {
  TASK_STATUS,
  TASK_STATUS_CLASS,
  TASK_TYPE,
  TASK_TYPE_HINT,
  FACET_VERDICT,
  DIMENSION,
  label,
  formatTime,
} from "../core/format.js";
import {
  isPinned,
  pinTask,
  unpin,
  updatePinnedTask,
} from "../core/taskpin.js";
import { toastSuccess, toastError } from "../core/toast.js";

// 各任务类型的 payload 模板，便于快速提交
const PAYLOAD_TEMPLATES = {
  "forge.generate": {
    resource_type: "courseware",
    topic: "认识四季",
    profile_id: "",
    extra: {},
  },
  "forge.portrait": {
    profile_id: "",
  },
  "facet.evaluate": {
    resource_id: "",
    use_llm: true,
  },
  "loop.evaluate": {
    student_id: "",
    period: "",
  },
};

// 未完成任务状态，用于决定是否继续轮询
const ACTIVE_STATUS = ["pending", "running"];

const STAT_ITEMS = [
  ["pending", "排队中"],
  ["running", "执行中"],
  ["succeeded", "已完成"],
  ["failed", "失败"],
];

/** 任务触发来源的中文说明。 */
const TRIGGER_LABEL = {
  manual: "手动触发",
  evidence_verified: "证据审核后自动",
};

/**
 * 创建任务队列视图。
 * @param {HTMLElement} root 视图容器
 */
export function createView(root) {
  let typeSelect;
  let typeHint;
  let payloadInput;
  let priorityInput;
  let attemptsInput;
  let deferCheck;
  let filterStatus;
  let filterType;
  let listBox;
  let statsBox;
  let counter;
  let timer = null;
  let latestItems = new Map();
  let taskNodes = new Map();
  let taskSignatures = new Map();

  function build() {
    clear(root);

    typeSelect = el("select", { name: "task_type" });
    typeHint = el("p", { class: "meta task-type-hint" });
    payloadInput = el("textarea", {
      name: "payload",
      class: "json-editor",
      rows: 11,
      spellcheck: false,
    });
    priorityInput = el("input", { type: "number", name: "priority", value: "0" });
    attemptsInput = el("input", {
      type: "number",
      name: "max_attempts",
      value: "1",
      min: "1",
    });
    deferCheck = el("input", { type: "checkbox", name: "defer_off_peak" });

    typeSelect.addEventListener("change", fillTemplate);

    // ---- 触发任务面板 ----
    const submitCard = el("section", { class: "card task-submit-card" }, [
      el("div", { class: "card-header" }, [
        el("div", {}, [
          el("h2", { text: "触发任务" }),
          el("p", {
            class: "card-hint",
            text: "提交耗时任务，或让证据审核通过后自动触发学情评价。",
          }),
        ]),
      ]),
      panel(null, [
        el("div", { class: "field" }, [el("label", { text: "任务类型" }), typeSelect]),
        typeHint,
        el("div", { class: "field" }, [
          el("label", { text: "任务参数（JSON）" }),
          payloadInput,
        ]),
        el("details", { class: "disclosure task-advanced" }, [
          el("summary", { text: "调度选项" }),
          el("div", { class: "field-row" }, [
            el("div", { class: "field" }, [
              el("label", { text: "优先级", title: "数值越大越先执行" }),
              priorityInput,
            ]),
            el("div", { class: "field" }, [
              el("label", { text: "最大尝试" }),
              attemptsInput,
            ]),
          ]),
          el("label", { class: "check" }, [deferCheck, "仅在闲时执行（夜间/周末/节假日）"]),
        ]),
      ]),
      el("div", { class: "form-actions" }, [
        el("button", {
          class: "btn btn-primary task-submit-btn",
          type: "button",
          text: "提交任务",
          on: { click: doSubmit },
        }),
        el("button", {
          class: "btn task-reset-btn",
          type: "button",
          text: "恢复模板",
          on: { click: fillTemplate },
        }),
      ]),
    ]);

    // ---- 任务列表 ----
    filterStatus = el("select", { name: "status" });
    filterStatus.append(el("option", { value: "", text: "全部状态" }));
    for (const [value, text] of Object.entries(TASK_STATUS)) {
      filterStatus.append(el("option", { value, text }));
    }
    filterType = el("select", { name: "type" });
    filterType.append(el("option", { value: "", text: "全部类型" }));
    counter = el("span", { class: "badge badge-muted", text: "共 0 条" });
    statsBox = el("div", { class: "task-stats" });
    listBox = el("div", { class: "task-list" });

    const toolbar = el("div", { class: "toolbar" }, [
      el("div", { class: "field" }, [el("label", { text: "状态" }), filterStatus]),
      el("div", { class: "field" }, [el("label", { text: "类型" }), filterType]),
      el("button", {
        class: "btn",
        type: "button",
        text: "刷新",
        on: { click: refresh },
      }),
      el("div", { class: "spacer" }),
      counter,
    ]);

    filterStatus.addEventListener("change", refresh);
    filterType.addEventListener("change", refresh);

    const listCard = el("section", { class: "card task-list-card" }, [
      el("div", { class: "card-header" }, [
        el("div", {}, [
          el("h2", { text: "任务列表" }),
          el("p", {
            class: "card-hint",
            text: "点击任务查看详细输出，右键可快速操作。",
          }),
        ]),
      ]),
      statsBox,
      toolbar,
      listBox,
    ]);

    root.append(
      el("div", { class: "split split-narrow-right task-layout" }, [
        el("div", {}, [listCard]),
        el("div", { class: "split-aside" }, [submitCard]),
      ])
    );
  }

  /** 按任务类型填充 payload 模板，并更新触发时机说明。 */
  function fillTemplate() {
    const type = typeSelect.value;
    payloadInput.value = JSON.stringify(PAYLOAD_TEMPLATES[type] || {}, null, 2);
    typeHint.textContent = TASK_TYPE_HINT[type] || "该任务由后台队列执行。";
  }

  /** 加载任务类型选项。 */
  async function loadTypes() {
    try {
      const typesData = await api.taskTypes();
      clear(typeSelect);
      for (const type of typesData.task_types) {
        typeSelect.append(
          el("option", { value: type, text: label(TASK_TYPE, type) })
        );
      }
      clear(filterType);
      filterType.append(el("option", { value: "", text: "全部类型" }));
      for (const type of typesData.task_types) {
        filterType.append(
          el("option", { value: type, text: label(TASK_TYPE, type) })
        );
      }
      fillTemplate();
    } catch (err) {
      toastError(`加载任务类型失败：${err.message}`);
    }
  }

  /** 提交任务。 */
  async function doSubmit() {
    let payload;
    try {
      payload = JSON.parse(payloadInput.value || "{}");
    } catch (err) {
      toastError("任务参数不是合法 JSON");
      return;
    }
    const body = {
      task_type: typeSelect.value,
      payload,
      priority: Number(priorityInput.value) || 0,
      max_attempts: Number(attemptsInput.value) || 1,
      defer_off_peak: deferCheck.checked,
    };
    try {
      const task = await api.createTask(body);
      toastSuccess(`已提交任务：${task.task_id}`);
      refresh();
    } catch (err) {
      toastError(err.message);
    }
  }

  /** 拉取任务列表；轮询时增量更新，避免整表重建、滚动回顶与动画重播。 */
  async function refresh() {
    if (listBox.dataset.rendered !== "1") {
      clear(listBox);
      listBox.append(placeholder("正在加载…", "loading"));
    }
    try {
      const data = await api.listTasks({
        status: filterStatus.value,
        task_type: filterType.value,
        size: 100,
      });
      counter.textContent = `共 ${data.total} 条`;
      latestItems = new Map(data.items.map((item) => [item.task_id, item]));
      renderStats(data.items);

      if (data.items.length === 0) {
        clear(listBox);
        listBox.append(placeholder("暂无任务。"));
        taskNodes.clear();
        taskSignatures.clear();
      } else {
        if (taskNodes.size === 0) clear(listBox);
        const nextNodes = new Map();
        const nextSignatures = new Map();
        let reference = listBox.firstElementChild;
        for (const item of data.items) {
          const signature = taskSignature(item);
          let node = taskNodes.get(item.task_id);
          if (!node || taskSignatures.get(item.task_id) !== signature) {
            const fresh = taskItem(item, { animate: !node });
            if (node) {
              // 节点即将被替换：若它正是插入参照点，先让参照点后移，
              // 避免 insertBefore 使用已被替换出 DOM 的旧节点。
              if (reference === node) reference = node.nextElementSibling;
              node.replaceWith(fresh);
            }
            node = fresh;
          }
          nextNodes.set(item.task_id, node);
          nextSignatures.set(item.task_id, signature);
          if (reference && reference.parentNode !== listBox) reference = null;
          if (node === reference) {
            reference = reference.nextElementSibling;
          } else {
            listBox.insertBefore(node, reference);
          }
        }
        for (const [taskId, node] of taskNodes) {
          if (!nextNodes.has(taskId)) node.remove();
        }
        taskNodes = nextNodes;
        taskSignatures = nextSignatures;
        // 思考内容自动滚动到最新位置
        for (const pre of listBox.querySelectorAll(".task-reasoning-text")) {
          pre.scrollTop = pre.scrollHeight;
        }
      }
      listBox.dataset.rendered = "1";

      const pinned = data.items.find((item) => isPinned(item.task_id));
      if (pinned) updatePinnedTask(pinned, taskSummary(pinned));
      schedulePolling(data.items);
    } catch (err) {
      clear(listBox);
      listBox.dataset.rendered = "";
      listBox.append(placeholder(`加载失败：${err.message}`));
      taskNodes.clear();
      taskSignatures.clear();
      toastError(err.message);
    }
  }

  /** 用于判断任务卡片是否需要重建的轻量签名。 */
  function taskSignature(item) {
    return [
      item.updated_at || "",
      item.status || "",
      item.attempts ?? "",
      String(item.reasoning || "").length,
      item.error || "",
    ].join("|");
  }

  /** 汇总当前筛选范围内的状态数量。 */
  function renderStats(items) {
    clear(statsBox);
    const counts = {};
    for (const item of items) counts[item.status] = (counts[item.status] || 0) + 1;
    for (const [status, text] of STAT_ITEMS) {
      statsBox.append(
        el("div", { class: `task-stat task-stat-${status}` }, [
          el("span", { class: "task-stat-value", text: String(counts[status] || 0) }),
          el("span", { class: "task-stat-label", text }),
        ])
      );
    }
  }

  /** 安排轮询：仅当存在 pending/running 任务时启用。 */
  function schedulePolling(items) {
    clearTimeout(timer);
    const active = (items || []).some((item) => ACTIVE_STATUS.includes(item.status));
    if (active) {
      timer = setTimeout(refresh, 2000);
    }
  }

  /** 触发来源文字。 */
  function triggerText(item) {
    return TRIGGER_LABEL[(item.payload || {}).trigger] || "";
  }

  /** 从任务结果提炼一行摘要。 */
  function taskSummary(item) {
    if (item.error) return `失败：${item.error}`;
    const result = item.result || {};
    if (result.verdict) {
      return `质量校验：${label(FACET_VERDICT, result.verdict)}${
        result.score === undefined ? "" : ` · ${result.score} 分`
      }`;
    }
    const dimensions = result.dimension_scores || {};
    if (Object.keys(dimensions).length > 0) {
      const coverage = Math.round(Number(result.coverage || 0) * 100);
      const text = Object.entries(dimensions)
        .map(([key, value]) => `${label(DIMENSION, key)} ${value}`)
        .join(" · ");
      return `覆盖率 ${coverage}% · ${text}`;
    }
    const content = String(result.content || "").trim();
    if (content) {
      const flat = content.replace(/\s+/g, " ");
      return flat.length > 110 ? `${flat.slice(0, 110)}…` : flat;
    }
    if (result.resource_id) return `资源 ${result.resource_id}`;
    if (result.profile_id) return `学生 ${result.profile_id}`;
    if (result.snapshot_id) return `快照 ${result.snapshot_id}`;
    return result.keys ? `结果字段：${result.keys.join("、")}` : "暂无输出摘要。";
  }

  /** 单条任务卡片；仅首次出现或新增任务播放渐入动画。 */
  function taskItem(item, { animate = false } = {}) {
    const statusClass = TASK_STATUS_CLASS[item.status] || "";
    const canCancel = ACTIVE_STATUS.includes(item.status);
    const card = el(
      "article",
      {
        class: `task-item task-item-${item.status}`,
        tabindex: "0",
        role: "button",
        "aria-label": `查看任务 ${item.task_id}`,
        on: {
          click: () => openTaskModal(item),
          contextmenu: (event) => openContextMenu(event, taskMenu(item)),
          keydown: (event) => {
            if (event.key === "Enter" || event.key === " ") {
              event.preventDefault();
              openTaskModal(item);
            }
          },
        },
      },
      [
        el("div", { class: "task-item-main" }, [
          el("div", { class: "task-item-top" }, [
            el("span", { class: `task-dot ${statusClass}`, "aria-hidden": "true" }),
            el("strong", { text: label(TASK_TYPE, item.task_type) }),
            el("span", { class: "badge badge-muted", text: item.task_id }),
            triggerText(item)
              ? el("span", { class: "badge badge-info", text: triggerText(item) })
              : null,
            el("span", { class: `status ${statusClass}`, text: label(TASK_STATUS, item.status) }),
          ]),
          el("p", { class: "task-item-summary", text: taskSummary(item) }),
          item.reasoning
            ? el("div", { class: "task-reasoning" }, [
                el("span", {
                  class: "task-reasoning-label",
                  text: item.status === "running" ? "思考中…" : "思考过程",
                }),
                el("pre", {
                  class: "task-reasoning-text",
                  text: String(item.reasoning).slice(-1200),
                }),
              ])
            : null,
          el("p", {
            class: "meta",
            text: `尝试 ${item.attempts}/${item.max_attempts} · 创建 ${formatTime(
              item.created_at
            )} · 更新 ${formatTime(item.updated_at)}`,
          }),
        ]),
        el("div", { class: "task-item-actions" }, [
          el("button", {
            class: "btn btn-sm",
            type: "button",
            text: "查看输出",
            on: {
              click: (event) => {
                event.stopPropagation();
                openTaskModal(item);
              },
            },
          }),
          canCancel
            ? el("button", {
                class: "btn btn-danger btn-sm",
                type: "button",
                text: "取消",
                on: {
                  click: (event) => {
                    event.stopPropagation();
                    doCancel(item.task_id);
                  },
                },
              })
            : null,
        ]),
      ]
    );
    if (animate) {
      card.classList.add("is-new");
      card.addEventListener(
        "animationend",
        () => card.classList.remove("is-new"),
        { once: true }
      );
    }
    return card;
  }

  /** 任务右键菜单。 */
  function taskMenu(item) {
    const canCancel = ACTIVE_STATUS.includes(item.status);
    return [
      { label: "查看详细输出", onSelect: () => openTaskModal(item) },
      {
        label: "钉住到右上角",
        onSelect: () => {
          pinTask(item, {
            summary: taskSummary(item),
            summarize: taskSummary,
            onOpen: () => openTaskModalById(item.task_id),
          });
          toastSuccess("已钉住任务输出");
        },
      },
      {
        label: "复制任务 ID",
        onSelect: () => copyText(item.task_id),
      },
      {
        label: "复制执行结果",
        disabled: !item.result,
        onSelect: () => copyText(JSON.stringify(item.result, null, 2)),
      },
      null,
      {
        label: "取消任务",
        danger: true,
        disabled: !canCancel,
        onSelect: () => doCancel(item.task_id),
      },
    ];
  }

  /** 根据 ID 打开最新任务详情；缓存中没有时向后台读取。 */
  async function openTaskModalById(taskId) {
    let task = latestItems.get(taskId);
    if (!task) {
      try {
        task = await api.getTask(taskId);
      } catch (err) {
        toastError(err.message);
        return;
      }
    }
    openTaskModal(task);
  }

  /** 打开任务详情模态框。 */
  function openTaskModal(task) {
    const overlay = el("div", {
      class: "modal-overlay",
      role: "dialog",
      "aria-modal": "true",
      "aria-label": `任务详情 ${task.task_id}`,
    });
    const dialog = el("div", { class: "modal task-detail-modal" });
    let settled = false;

    const close = () => {
      if (settled) return;
      settled = true;
      document.removeEventListener("keydown", onKey);
      overlay.classList.add("leaving");
      window.setTimeout(() => overlay.remove(), 200);
    };
    const onKey = (event) => {
      if (event.key === "Escape") close();
    };

    const pinButton = el("button", {
      class: `btn btn-sm task-pin-btn${isPinned(task.task_id) ? " is-pinned" : ""}`,
      type: "button",
      "aria-pressed": String(isPinned(task.task_id)),
      text: isPinned(task.task_id) ? "已钉住" : "钉住",
    });
    pinButton.addEventListener("click", () => {
      if (isPinned(task.task_id)) {
        unpin();
        pinButton.classList.remove("is-pinned");
        pinButton.setAttribute("aria-pressed", "false");
        pinButton.textContent = "钉住";
        toastSuccess("已取消钉住");
        return;
      }
      pinTask(task, {
        summary: taskSummary(task),
        summarize: taskSummary,
        onOpen: () => openTaskModalById(task.task_id),
      });
      pinButton.classList.add("is-pinned");
      pinButton.setAttribute("aria-pressed", "true");
      pinButton.textContent = "已钉住";
      toastSuccess("已钉住，关闭后仍显示在右上角");
    });

    const body = el("div", { class: "task-detail" }, [
      el("div", { class: "badge-row" }, [
        el("span", { class: "badge badge-muted", text: label(TASK_TYPE, task.task_type) }),
        el("span", {
          class: `status ${TASK_STATUS_CLASS[task.status] || ""}`,
          text: label(TASK_STATUS, task.status),
        }),
        triggerText(task)
          ? el("span", { class: "badge badge-info", text: triggerText(task) })
          : null,
        el("span", { class: "badge badge-muted", text: `尝试 ${task.attempts}/${task.max_attempts}` }),
      ]),
      el("p", {
        class: "meta",
        text:
          `创建 ${formatTime(task.created_at)} · 开始 ${formatTime(task.started_at)} · ` +
          `结束 ${formatTime(task.finished_at)}`,
      }),
    ]);

    if (task.error) {
      body.append(
        el("div", { class: "task-error" }, [
          el("strong", { text: "执行错误" }),
          el("p", { text: task.error }),
        ])
      );
    }

    if (String(task.reasoning || "").trim()) {
      body.append(
        panel("思考过程", [
          el("pre", { class: "output reasoning", text: task.reasoning }),
        ])
      );
    }
    const result = task.result || {};
    if (String(result.content || "").trim()) {
      const output = el("div", { class: "md task-output" });
      output.innerHTML = renderMarkdown(result.content);
      body.append(
        panel("输出内容", [
          result.content_truncated
            ? el("p", { class: "meta", text: "输出较长，任务面板仅保留前 12000 字。" })
            : null,
          output,
        ])
      );
    } else if (Object.keys(result).length > 0) {
      body.append(
        panel("执行结果", [
          el("pre", { class: "output", text: JSON.stringify(result, null, 2) }),
        ])
      );
    } else {
      body.append(placeholder("任务尚未产生输出。"));
    }

    body.append(
      el("details", { class: "disclosure" }, [
        el("summary", { text: "任务参数" }),
        el("pre", { class: "output", text: JSON.stringify(task.payload || {}, null, 2) }),
      ])
    );

    const closeBtn = closeButton(close);
    dialog.append(
      el("div", { class: "modal-head" }, [
        el("h3", { text: `任务详情 · ${task.task_id}` }),
        el("div", { class: "task-detail-head-actions" }, [pinButton, closeBtn]),
      ]),
      body
    );
    overlay.append(dialog);
    overlay.addEventListener("click", (event) => {
      if (event.target === overlay) close();
    });
    document.addEventListener("keydown", onKey);
    document.body.append(overlay);
    closeBtn.focus();
  }

  /** 生成关闭按钮。 */
  function closeButton(onClick) {
    return el("button", {
      class: "btn btn-sm",
      type: "button",
      text: "关闭",
      on: { click: onClick },
    });
  }

  /** 取消任务。 */
  async function doCancel(taskId) {
    try {
      await api.cancelTask(taskId);
      toastSuccess("任务已取消");
      refresh();
    } catch (err) {
      toastError(err.message);
    }
  }

  /** 复制文本到剪贴板。 */
  async function copyText(text) {
    try {
      await navigator.clipboard.writeText(String(text));
      toastSuccess("已复制到剪贴板");
    } catch (err) {
      toastError("复制失败，请手动复制");
    }
  }

  build();

  return {
    init() {
      loadTypes().then(refresh);
    },
    refresh() {
      refresh();
    },
    /** 离开视图时停止轮询。 */
    destroy() {
      clearTimeout(timer);
    },
  };
}
