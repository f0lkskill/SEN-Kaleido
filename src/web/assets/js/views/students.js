/**
 * views/students.js —— 学生档案视图
 * 覆盖建档、列表筛选、查看详情（属性 + 评价框架）、删除。
 */

import { api } from "../core/api.js";
import { el, clear, placeholder } from "../core/dom.js";
import { DISABILITY, COGNITIVE_LEVEL, label, formatTime } from "../core/format.js";
import { toastSuccess, toastError } from "../core/toast.js";
import {
  buildAttributesForm,
  readAttributes,
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
  let grid;
  let totalBadge;
  let detail;
  let createForm;

  function build() {
    clear(root);

    // ---- 工具条：筛选 ----
    filterDisability = filterSelect("disability", ATTRIBUTE_OPTIONS.disability);
    filterCognitive = filterSelect("cognitive_level", ATTRIBUTE_OPTIONS.cognitive_level);
    totalBadge = el("span", { class: "badge badge-muted", text: "共 0 人" });

    const toolbar = el("div", { class: "toolbar" }, [
      el("div", { class: "field" }, [
        el("label", { text: "障碍类型" }),
        filterDisability,
      ]),
      el("div", { class: "field" }, [
        el("label", { text: "认知等级" }),
        filterCognitive,
      ]),
      el("button", {
        class: "btn",
        type: "button",
        text: "筛选",
        on: { click: refresh },
      }),
      el("div", { class: "spacer" }),
      totalBadge,
    ]);

    grid = el("div", { class: "grid grid-students" });
    detail = el("div", { class: "detail-panel" });

    // ---- 建档表单（默认折叠） ----
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
        text: "建档时录入静态属性，系统据此生成个性化评价框架。",
      }),
      createForm,
      toolbar,
      el("div", { class: "list" }, [grid]),
      detail,
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
      el("div", { class: "field" }, [
        el("label", { text: "学生姓名/化名" }),
        nameInput,
      ]),
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
      const payload = {
        name,
        attributes: readAttributes(attrsForm),
        generate_framework: frameworkCheck.checked,
      };
      try {
        const profile = await api.createStudent(payload);
        toastSuccess(`已建档：${profile.name}`);
        clear(createForm);
        refresh();
      } catch (err) {
        toastError(err.message);
      }
    });

    createForm.append(form);
  }

  /** 拉取并渲染学生列表。 */
  async function refresh() {
    clear(grid);
    grid.append(placeholder("正在加载…", "loading"));
    try {
      const data = await api.listStudents({
        disability: filterDisability.value,
        cognitive_level: filterCognitive.value,
        size: 100,
      });
      totalBadge.textContent = `共 ${data.total} 人`;
      clear(grid);
      if (data.items.length === 0) {
        grid.append(placeholder("暂无学生档案，点击右上角新建。"));
        return;
      }
      for (const item of data.items) grid.append(studentCard(item));
    } catch (err) {
      clear(grid);
      grid.append(placeholder(`加载失败：${err.message}`));
      toastError(err.message);
    }
  }

  /** 单个学生卡片。 */
  function studentCard(item) {
    const attrs = item.attributes || {};
    return el("button", {
      class: "list-item",
      type: "button",
      style: "text-align:left; cursor:pointer;",
      on: { click: () => showDetail(item.profile_id) },
    }, [
      el("h4", { text: item.name }),
      el("div", { class: "badge-row" }, [
        el("span", { class: "badge", text: label(DISABILITY, attrs.disability) }),
        el("span", { class: "badge badge-muted", text: `认知：${label(COGNITIVE_LEVEL, attrs.cognitive_level)}` }),
      ]),
      el("p", { class: "meta", text: `建档：${formatTime(item.created_at)}` }),
    ]);
  }

  /** 展示学生详情。 */
  async function showDetail(profileId) {
    clear(detail);
    detail.append(placeholder("正在加载详情…", "loading"));
    try {
      const item = await api.getStudent(profileId);
      clear(detail);
      detail.append(
        el("section", { class: "card" }, [
          el("div", { class: "card-header" }, [
            el("h3", { text: `${item.name} · 档案详情` }),
            el("button", {
              class: "btn btn-danger btn-sm",
              type: "button",
              text: "删除档案",
              on: { click: () => remove(item) },
            }),
          ]),
          renderAttributes(item.attributes),
          el("p", { class: "meta", text: `更新时间：${formatTime(item.updated_at)}` }),
          renderFramework(item.framework),
        ])
      );
    } catch (err) {
      clear(detail);
      detail.append(placeholder(`加载失败：${err.message}`));
      toastError(err.message);
    }
  }

  /** 删除学生档案。 */
  async function remove(item) {
    if (!window.confirm(`确认删除「${item.name}」的档案？此操作不可撤销。`)) return;
    try {
      await api.deleteStudent(item.profile_id);
      toastSuccess("已删除");
      clear(detail);
      refresh();
    } catch (err) {
      toastError(err.message);
    }
  }

  build();

  return { refresh };
}
