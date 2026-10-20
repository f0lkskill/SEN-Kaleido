/**
 * views/tasks.js —— 异步任务队列视图
 * 支持提交任务（尤其是 forge.generate 批量生成）、查看状态、取消任务，
 * 并在存在未完成任务时自动轮询刷新。
 */

import { api } from "../core/api.js";
import { el, clear, placeholder, enhanceDisclosure, panel } from "../core/dom.js";
import {
  TASK_STATUS,
  TASK_STATUS_CLASS,
  label,
  formatTime,
} from "../core/format.js";
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
};

// 未完成任务状态，用于决定是否继续轮询
const ACTIVE_STATUS = ["pending", "running"];

/**
 * 创建任务队列视图。
 * @param {HTMLElement} root 视图容器
 */
export function createView(root) {
  let typeSelect;
  let payloadInput;
  let priorityInput;
  let attemptsInput;
  let deferCheck;
  let filterStatus;
  let filterType;
  let listBox;
  let counter;
  let timer = null;

  function build() {
    clear(root);

    typeSelect = el("select", { name: "task_type" });
    payloadInput = el("textarea", { name: "payload" });
    priorityInput = el("input", { type: "number", name: "priority", value: "0" });
    attemptsInput = el("input", { type: "number", name: "max_attempts", value: "1", min: "1" });
    deferCheck = el("input", { type: "checkbox", name: "defer_off_peak" });

    typeSelect.addEventListener("change", fillTemplate);

    // ---- 提交表单 ----
    const submitCard = el("section", { class: "card" }, [
      panel("任务设置", [
        el("div", { class: "field" }, [
          el("label", { text: "任务类型" }),
          typeSelect,
        ]),
        el("div", { class: "field" }, [
          el("label", { text: "任务参数（JSON）" }),
          payloadInput,
        ]),
        el("div", { class: "field-row" }, [
          el("div", { class: "field" }, [
            el("label", { text: "优先级", title: "数值越大越先执行" }),
            priorityInput,
          ]),
          el("div", { class: "field" }, [
            el("label", { text: "最大尝试次数" }),
            attemptsInput,
          ]),
        ]),
        el("label", { class: "check" }, [deferCheck, "仅在闲时执行"]),
      ]),
      el("div", { class: "form-actions" }, [
        el("button", {
          class: "btn btn-primary",
          type: "button",
          text: "提交任务",
          on: { click: doSubmit },
        }),
      ]),
    ]);

    // ---- 列表 ----
    filterStatus = el("select", { name: "status" });
    filterStatus.append(el("option", { value: "", text: "全部状态" }));
    for (const [value, text] of Object.entries(TASK_STATUS)) {
      filterStatus.append(el("option", { value, text }));
    }
    filterType = el("select", { name: "type" });
    filterType.append(el("option", { value: "", text: "全部类型" }));
    counter = el("span", { class: "badge badge-muted", text: "共 0 条" });
    listBox = el("div", { class: "list" });

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

    // 筛选改动即时刷新
    filterStatus.addEventListener("change", refresh);
    filterType.addEventListener("change", refresh);

    const listCard = el("section", { class: "card" }, [toolbar, listBox]);

    // 左：任务列表；右：提交表单（左右分栏）
    root.append(
      el("div", { class: "split split-narrow-right" }, [
        el("div", {}, [listCard]),
        el("div", { class: "split-aside" }, [submitCard]),
      ])
    );
  }

  /** 按任务类型填充 payload 模板。 */
  function fillTemplate() {
    const type = typeSelect.value;
    if (PAYLOAD_TEMPLATES[type]) {
      payloadInput.value = JSON.stringify(PAYLOAD_TEMPLATES[type], null, 2);
    } else {
      payloadInput.value = "{}";
    }
  }

  /** 加载任务类型选项。 */
  async function loadTypes() {
    try {
      // 任务类型来自 tasks 接口
      const typesData = await api.taskTypes();
      clear(typeSelect);
      for (const type of typesData.task_types) {
        typeSelect.append(el("option", { value: type, text: type }));
      }
      clear(filterType);
      filterType.append(el("option", { value: "", text: "全部类型" }));
      for (const type of typesData.task_types) {
        filterType.append(el("option", { value: type, text: type }));
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

  /** 拉取任务列表。 */
  async function refresh() {
    clear(listBox);
    listBox.append(placeholder("正在加载…", "loading"));
    try {
      const data = await api.listTasks({
        status: filterStatus.value,
        task_type: filterType.value,
        size: 100,
      });
      counter.textContent = `共 ${data.total} 条`;
      clear(listBox);
      if (data.items.length === 0) {
        listBox.append(placeholder("暂无任务。"));
      } else {
        for (const item of data.items) listBox.append(taskItem(item));
      }
      // 有未完成任务时安排下一轮自动刷新
      schedulePolling(data.items);
    } catch (err) {
      clear(listBox);
      listBox.append(placeholder(`加载失败：${err.message}`));
      toastError(err.message);
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

  /** 单条任务。 */
  function taskItem(item) {
    const statusClass = TASK_STATUS_CLASS[item.status] || "";
    const canCancel = ACTIVE_STATUS.includes(item.status);

    const header = el("summary", {}, [
      `${item.task_id} `,
      el("span", { class: "badge badge-muted", text: item.task_type }),
      " ",
      el("span", { class: `status ${statusClass}`, text: label(TASK_STATUS, item.status) }),
    ]);

    const body = el("div", {}, [
      el("p", {
        class: "meta",
        text: `尝试 ${item.attempts}/${item.max_attempts} · 创建 ${formatTime(item.created_at)} · 更新 ${formatTime(item.updated_at)}`,
      }),
      enhanceDisclosure(
        el("details", { class: "disclosure" }, [
          el("summary", { text: "任务参数" }),
          el("pre", { class: "output", text: JSON.stringify(item.payload, null, 2) }),
        ])
      ),
    ]);

    if (item.result) {
      body.append(
        enhanceDisclosure(
          el("details", { class: "disclosure" }, [
            el("summary", { text: "执行结果" }),
            el("pre", { class: "output", text: JSON.stringify(item.result, null, 2) }),
          ])
        )
      );
    }
    if (item.error) {
      body.append(el("p", { class: "meta", text: `错误：${item.error}` }));
    }
    if (canCancel) {
      body.append(
        el("button", {
          class: "btn btn-danger btn-sm",
          type: "button",
          text: "取消任务",
          on: { click: () => doCancel(item.task_id) },
        })
      );
    }

    return enhanceDisclosure(el("details", { class: "list-item disclosure" }, [header, body]));
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
