/**
 * views/framework.js —— 评价框架视图
 * 提供两处能力：
 * 1. renderFramework：把框架对象渲染为可读的四级结构（维度→指标→观测点→评分标准）；
 * 2. createView：独立的"评价框架预览"页，输入临时属性即时预览，不落库。
 */

import { api } from "../core/api.js";
import { el, clear, placeholder } from "../core/dom.js";
import {
  DISABILITY,
  SEVERITY,
  COGNITIVE_LEVEL,
  SENSORY,
  REHAB_GOAL,
  LEARNING_PACE,
  DIMENSION,
  label,
  labels,
} from "../core/format.js";
import { toastError } from "../core/toast.js";

/** 枚举选项定义（与后端 attributes.yaml 保持一致）。 */
export const ATTRIBUTE_OPTIONS = {
  disability: Object.entries(DISABILITY),
  severity: Object.entries(SEVERITY),
  cognitive_level: Object.entries(COGNITIVE_LEVEL),
  sensory_preference: Object.entries(SENSORY),
  learning_pace: Object.entries(LEARNING_PACE),
  rehab_goals: Object.entries(REHAB_GOAL),
};

/** 生成一个 <select>，包含给定选项。 */
function select(name, options, { required = false, includeBlank = false } = {}) {
  const node = el("select", { name, id: name });
  if (includeBlank) node.append(el("option", { value: "", text: "（不指定）" }));
  for (const [value, text] of options) {
    node.append(el("option", { value, text }));
  }
  if (required) node.setAttribute("required", "required");
  return node;
}

/**
 * 渲染评价框架（四级结构）。
 * @param {Object} framework 框架对象
 * @returns {HTMLElement}
 */
export function renderFramework(framework) {
  const wrap = el("div", { class: "framework" });

  // ---- 维度权重 ----
  const weights = framework.weights || {};
  const weightItems = Object.entries(weights).map(([key, value]) =>
    el("div", { class: "badge" }, [
      `${label(DIMENSION, key)} ${Math.round(Number(value) * 100)}%`,
    ])
  );
  wrap.append(
    el("h3", { text: "评价维度与权重" }),
    el("div", { class: "badge-row" }, weightItems.length ? weightItems : [el("span", { class: "meta", text: "无" })])
  );

  if (framework.prompt_template_key) {
    wrap.append(
      el("p", { class: "meta" }, [`Prompt 模板：${framework.prompt_template_key}`])
    );
  }

  // ---- 指标与观测点 ----
  wrap.append(el("h3", { text: "指标与观测点" }));
  const indicators = framework.indicators || [];
  if (indicators.length === 0) {
    wrap.append(placeholder("该框架未包含指标"));
    return wrap;
  }

  const list = el("div", { class: "list" });
  for (const indicator of indicators) {
    const observations = el("div", { class: "table-wrap" });
    const table = el("table", { class: "data" });
    table.append(
      el("thead", {}, [
        el("tr", {}, [
          el("th", { text: "观测点" }),
          el("th", { text: "方式" }),
          el("th", { text: "频率" }),
          el("th", { text: "证据来源" }),
          el("th", { text: "评分等级" }),
        ]),
      ])
    );
    const tbody = el("tbody");
    for (const obs of indicator.observations || []) {
      tbody.append(
        el("tr", {}, [
          el("td", { text: obs.name }),
          el("td", { text: obs.method === "quantitative" ? "量化" : "质性" }),
          el("td", { text: label(FREQUENCY, obs.frequency) }),
          el("td", { text: labels({}, obs.evidence_sources) }),
          el("td", { text: `${(obs.rubrics || []).length} 级` }),
        ])
      );
    }
    table.append(tbody);
    observations.append(table);

    list.append(
      el("div", { class: "list-item" }, [
        el("h4", {}, [
          indicator.name,
          " ",
          el("span", { class: "badge", text: label(DIMENSION, indicator.dimension) }),
        ]),
        observations,
      ])
    );
  }
  wrap.append(list);
  return wrap;
}

/** 观测频率标签。 */
const FREQUENCY = {
  per_lesson: "每课",
  weekly: "每周",
  phase: "阶段性",
};

/** 渲染已规范化的属性概览。 */
export function renderAttributes(attributes) {
  const rows = [
    ["障碍类型", label(DISABILITY, attributes.disability)],
    ["障碍程度", label(SEVERITY, attributes.severity)],
    ["认知等级", label(COGNITIVE_LEVEL, attributes.cognitive_level)],
    ["感官偏好", label(SENSORY, attributes.sensory_preference)],
    ["康复目标", labels(REHAB_GOAL, attributes.rehab_goals)],
    ["学习节奏", label(LEARNING_PACE, attributes.learning_pace)],
  ];
  const wrap = el("div", { class: "badge-row" });
  for (const [name, value] of rows) {
    wrap.append(el("span", { class: "badge badge-muted", text: `${name}：${value}` }));
  }
  return wrap;
}

/**
 * 采集属性表单的值。
 * @param {HTMLFormElement} form 表单
 * @returns {Object} 属性输入对象
 */
export function readAttributes(form) {
  const data = new FormData(form);
  const goals = data.getAll("rehab_goals").map(String);
  const attributes = {
    disability: String(data.get("disability") || ""),
    severity: String(data.get("severity") || ""),
    cognitive_level: String(data.get("cognitive_level") || ""),
    learning_pace: String(data.get("learning_pace") || ""),
    rehab_goals: goals,
  };
  const sensory = String(data.get("sensory_preference") || "");
  if (sensory) attributes.sensory_preference = sensory;
  return attributes;
}

/** 构建属性录入表单（供预览页与学生建档共用）。 */
export function buildAttributesForm(prefix) {
  const form = el("form", { class: "attributes-form" });
  const row1 = el("div", { class: "field-row" });
  row1.append(
    el("div", { class: "field" }, [
      el("label", { for: `${prefix}-disability`, text: "障碍类型" }),
      select("disability", ATTRIBUTE_OPTIONS.disability, { required: true }),
    ]),
    el("div", { class: "field" }, [
      el("label", { for: `${prefix}-severity`, text: "障碍程度" }),
      select("severity", ATTRIBUTE_OPTIONS.severity, { required: true }),
    ])
  );

  const row2 = el("div", { class: "field-row" });
  row2.append(
    el("div", { class: "field" }, [
      el("label", { for: `${prefix}-cognitive`, text: "认知等级" }),
      select("cognitive_level", ATTRIBUTE_OPTIONS.cognitive_level, { required: true }),
    ]),
    el("div", { class: "field" }, [
      el("label", { for: `${prefix}-pace`, text: "学习节奏" }),
      select("learning_pace", ATTRIBUTE_OPTIONS.learning_pace, { required: true }),
    ])
  );

  const sensoryField = el("div", { class: "field" }, [
    el("label", { for: `${prefix}-sensory`, text: "感官偏好（留空则按类型推导）" }),
    select("sensory_preference", ATTRIBUTE_OPTIONS.sensory_preference, {
      includeBlank: true,
    }),
  ]);

  const goalField = el("div", { class: "field" }, [
    el("label", { text: "康复目标（可多选）" }),
    el(
      "div",
      { class: "checks" },
      ATTRIBUTE_OPTIONS.rehab_goals.map(([value, text]) =>
        el("label", { class: "check" }, [
          el("input", { type: "checkbox", name: "rehab_goals", value }),
          text,
        ])
      )
    ),
  ]);

  form.append(row1, row2, sensoryField, goalField);
  return form;
}

/**
 * 创建"评价框架预览"视图。
 * @param {HTMLElement} root 视图容器
 */
export function createView(root) {
  let form;
  let output;

  function build() {
    clear(root);
    form = buildAttributesForm("preview");
    output = el("div");

    const card = el("section", { class: "card" }, [
      el("div", { class: "card-header" }, [el("h2", { text: "评价框架预览" })]),
      el("p", {
        class: "card-hint",
        text: "输入临时属性，即时查看规范化属性与个性化评价框架，不写入档案。",
      }),
      form,
      el("button", {
        class: "btn btn-primary",
        type: "button",
        text: "预览",
        on: { click: preview },
      }),
      el("div", { style: "margin-top:16px" }, [output]),
    ]);
    root.append(card);
  }

  async function preview() {
    clear(output);
    output.append(placeholder("正在生成预览…", "loading"));
    try {
      const data = await api.previewFramework(readAttributes(form));
      clear(output);
      output.append(
        el("h3", { text: "规范化属性" }),
        renderAttributes(data.attributes),
        renderFramework(data.framework)
      );
    } catch (err) {
      clear(output);
      output.append(placeholder(`预览失败：${err.message}`));
      toastError(err.message);
    }
  }

  build();

  return {
    /** 切换到此标签时调用（重绘表单，保持简单）。 */
    refresh() {
      build();
    },
  };
}
