/**
 * views/students.js —— 学生档案视图（左右分栏）
 * 布局：左侧为档案列表，选中后列表收窄向左、右侧滑出详情面板。
 * 覆盖：建档、筛选、查看详情（属性 + 公共评价标准）、删除。
 */

import { api } from "../core/api.js";
import { el, clear, placeholder } from "../core/dom.js";
import {
  DISABILITY,
  SEVERITY,
  COGNITIVE_LEVEL,
  label,
  labels,
  formatTime,
  setEvidenceSources,
} from "../core/format.js";
import { toastSuccess, toastError } from "../core/toast.js";
import {
  buildAttributesForm,
  readAttributes,
  validateAttributes,
  renderFramework,
  renderAttributes,
  ATTRIBUTE_OPTIONS,
} from "./framework.js";

/** 生成筛选下拉。 */
function filterSelect(name, options) {
  const node = el("select", { name });
  node.append(el("option", { value: "", text: "全部" }));
  for (const [value, text] of options) node.append(el("option", { value, text }));
  return node;
}

/**
 * 创建学生档案视图。
 * @param {HTMLElement} root 视图容器
 */
export function createView(root) {
  let filterDisability;
  let filterCognitive;
  let listBox;
  let layout;
  let detailBox;
  let totalBadge;
  let createForm;
  let activeId = null; // 当前选中的档案 ID

  function build() {
    clear(root);

    // ---- 工具条：筛选 ----
    filterDisability = filterSelect("disability", ATTRIBUTE_OPTIONS.disability);
    filterCognitive = filterSelect("cognitive_level", ATTRIBUTE_OPTIONS.cognitive_level);
    totalBadge = el("span", { class: "badge badge-muted", text: "共 0 人" });

    const toolbar = el("div", { class: "toolbar" }, [
      el("div", { class: "field" }, [el("label", { text: "障碍类型" }), filterDisability]),
      el("div", { class: "field" }, [el("label", { text: "认知等级" }), filterCognitive]),
      el("button", { class: "btn", type: "button", text: "筛选", on: { click: refresh } }),
      el("div", { class: "spacer" }),
      totalBadge,
    ]);

    listBox = el("div", { class: "student-list" });
    detailBox = el("div", { class: "student-detail", hidden: true });
    layout = el("div", { class: "student-layout" }, [listBox, detailBox]);

    createForm = el("div");

    const card = el("section", { class: "card" }, [
      el("div", { class: "card-header" }, [
        el("h2", { text: "学生档案" }),
        el("button", {
          class: "btn btn-primary",
          type: "button",
          text: "＋ 新建学生",
          on: { click: toggleCreate },
        }),
      ]),
      el("p", {
        class: "card-hint",
        text: "从左侧选择一名学生查看详情；建档时录入静态属性，系统据此生成公共评价标准。",
      }),
      createForm,
      toolbar,
      layout,
    ]);
    root.append(card);
  }

  /** 显示/隐藏建档表单。 */
  function toggleCreate() {
    if (createForm.childElementCount > 0) {
      clear(createForm);
      return;
    }
    buildCreateForm();
  }

  /** 构建建档表单。 */
  function buildCreateForm() {
    const nameInput = el("input", { type: "text", name: "name", required: true });
    const attrsForm = buildAttributesForm("create");
    const frameworkCheck = el("input", {
      type: "checkbox",
      name: "generate_framework",
      checked: true,
    });

    const form = el("form", { class: "create-form" }, [
      el("h3", { text: "新建学生" }),
      el("div", { class: "field" }, [el("label", { text: "学生姓名/化名" }), nameInput]),
      attrsForm,
      el("label", { class: "check" }, [frameworkCheck, "同时生成评价框架"]),
      el("div", { style: "margin-top:16px" }, [
        el("button", { class: "btn btn-primary", type: "submit", text: "建档" }),
      ]),
    ]);

    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const name = nameInput.value.trim();
      if (!name) {
        toastError("请填写学生姓名");
        return;
      }
      const attributes = readAttributes(attrsForm);
      const error = validateAttributes(attributes);
      if (error) {
        toastError(error);
        return;
      }
      try {
        const profile = await api.createStudent({
          name,
          attributes,
          generate_framework: frameworkCheck.checked,
        });
        toastSuccess(`已建档：${profile.name}`);
        clear(createForm);
        refresh();
      } catch (err) {
        toastError(err.message);
      }
    });

    createForm.append(form);
  }

  /** 关闭详情面板，恢复列表全宽。 */
  function closeDetail() {
    layout.classList.remove("narrowed");
    detailBox.hidden = true;
    clear(detailBox);
    activeId = null;
    for (const item of listBox.querySelectorAll(".student-card")) {
      item.classList.remove("active");
    }
  }

  /** 拉取并渲染学生列表（会同时收起详情面板）。 */
  async function refresh() {
    closeDetail();
    clear(listBox);
    listBox.append(placeholder("正在加载…", "loading"));
    try {
      const data = await api.listStudents({
        disability: filterDisability.value,
        cognitive_level: filterCognitive.value,
        size: 100,
      });
      totalBadge.textContent = `共 ${data.total} 人`;
      clear(listBox);
      if (data.items.length === 0) {
        listBox.append(placeholder("暂无学生档案，点击右上角新建。"));
        return;
      }
      for (const item of data.items) listBox.append(studentCard(item));
    } catch (err) {
      clear(listBox);
      listBox.append(placeholder(`加载失败：${err.message}`));
      toastError(err.message);
    }
  }

  /** 单个学生卡片。 */
  function studentCard(item) {
    const button = el(
      "button",
      {
        class: "student-card",
        type: "button",
        on: { click: () => showDetail(item.profile_id, button) },
      },
      [
        el("h4", { text: item.name }),
        el("div", { class: "badge-row" }, [
          el("span", { class: "badge badge-info", text: labels(DISABILITY, item.disabilities) }),
          el("span", { class: "badge badge-muted", text: label(SEVERITY, item.severity) }),
          el("span", {
            class: "badge badge-muted",
            text: `认知：${label(COGNITIVE_LEVEL, item.cognitive_level)}`,
          }),
        ]),
      ]
    );
    return button;
  }

  /** 展示学生详情（列表收窄、右侧滑出面板）。 */
  async function showDetail(profileId, cardEl) {
    detailBox.hidden = false;
    layout.classList.add("narrowed");
    clear(detailBox);
    detailBox.append(placeholder("正在加载详情…", "loading"));
    if (cardEl) {
      for (const node of listBox.querySelectorAll(".student-card")) {
        node.classList.remove("active");
      }
      cardEl.classList.add("active");
    }
    activeId = profileId;
    try {
      const item = await api.getStudent(profileId);
      clear(detailBox);
      detailBox.append(
        el("section", { class: "detail-body" }, [
          el("div", { class: "detail-head" }, [
            el("h3", { text: `${item.name} · 档案详情` }),
            el("div", { class: "detail-actions" }, [
              el("button", {
                class: "btn btn-sm",
                type: "button",
                text: "收起",
                on: { click: closeDetail },
              }),
              el("button", {
                class: "btn btn-danger btn-sm",
                type: "button",
                text: "删除档案",
                on: { click: () => remove(item) },
              }),
            ]),
          ]),
          el("h4", { text: "学生属性" }),
          renderAttributes(item.attributes),
          el("h4", { text: "公共评价标准" }),
          renderFramework(item.framework),
          el("p", { class: "meta", text: `更新时间：${formatTime(item.updated_at)}` }),
        ])
      );
    } catch (err) {
      clear(detailBox);
      detailBox.append(placeholder(`加载失败：${err.message}`));
      toastError(err.message);
    }
  }

  /** 删除学生档案。 */
  async function remove(item) {
    if (!window.confirm(`确认删除「${item.name}」的档案？此操作不可撤销。`)) return;
    try {
      await api.deleteStudent(item.profile_id);
      toastSuccess("已删除");
      refresh();
    } catch (err) {
      toastError(err.message);
    }
  }

  /** 加载证据来源元数据，使界面展示中文名称而非内部键。 */
  async function loadEvidenceSources() {
    try {
      const map = await api.evidenceSources();
      setEvidenceSources(map);
    } catch (err) {
      // 元数据加载失败时沿用静态兜底映射，不打断主流程
    }
  }

  build();

  return {
    /** 首次进入：加载元数据并自动筛选一次。 */
    async init() {
      await loadEvidenceSources();
      refresh();
    },
    refresh,
  };
}
