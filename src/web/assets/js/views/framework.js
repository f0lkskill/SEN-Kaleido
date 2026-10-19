/**
 * views/framework.js —— 评价框架视图与共用渲染
 * 提供三处能力：
 * 1. buildAttributesForm / readAttributes：属性录入表单（支持多障碍）；
 * 2. renderAttributes / renderFramework：把规范化属性与评价框架渲染为
 *    直观的可视化结构（分组标签、权重进度条、评分等级卡片）；
 * 3. createView：独立的"评价框架预览"页，输入临时属性即时预览，不落库。
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
  METHOD,
  FREQUENCY,
  label,
  labels,
  evidenceLabels,
} from "../core/format.js";
import { toastError } from "../core/toast.js";

/** 枚举选项定义（与后端 attributes.yaml 保持一致）。 */
export const ATTRIBUTE_OPTIONS = {
  disability: Object.entries(DISABILITY),
  disabilities: Object.entries(DISABILITY),
  severity: Object.entries(SEVERITY),
  cognitive_level: Object.entries(COGNITIVE_LEVEL),
  sensory_preference: Object.entries(SENSORY),
  learning_pace: Object.entries(LEARNING_PACE),
  rehab_goals: Object.entries(REHAB_GOAL),
};

/** 生成一个单选下拉，包含给定选项。 */
function select(name, options, { required = false, includeBlank = false } = {}) {
  const node = el("select", { name, id: name });
  if (includeBlank) node.append(el("option", { value: "", text: "（不指定）" }));
  for (const [value, text] of options) {
    node.append(el("option", { value, text }));
  }
  if (required) node.setAttribute("required", "required");
  return node;
}

/** 把 0~1 的权重渲染为进度条。 */
function meter(value) {
  const percent = Math.round(Number(value || 0) * 100);
  return el("div", { class: "meter", role: "img", "aria-label": `权重 ${percent}%` }, [
    el("div", { class: "meter-fill", style: `width:${percent}%` }),
  ]);
}

/**
 * 渲染评价框架（可视化结构）。
 * @param {Object} framework 框架对象
 * @returns {HTMLElement}
 */
export function renderFramework(framework) {
  const wrap = el("div", { class: "framework" });

  // ---- 维度权重（进度条，直观展示各维度占比） ----
  const weights = framework.weights || {};
  const weightBox = el("div", { class: "weight-list" });
  const entries = Object.entries(weights);
  if (entries.length === 0) {
    weightBox.append(el("p", { class: "meta", text: "无" }));
  } else {
    for (const [key, value] of entries) {
      weightBox.append(
        el("div", { class: "weight-item" }, [
          el("span", { class: "weight-name", text: label(DIMENSION, key) }),
          meter(value),
          el("span", { class: "weight-value", text: `${Math.round(Number(value) * 100)}%` }),
        ])
      );
    }
  }
  wrap.append(
    el("h3", { text: "评价维度与权重" }),
    el("p", { class: "card-hint", text: "权重越高，该维度在综合评价中占比越大。" }),
    weightBox
  );

  // ---- 指标与观测点（分组卡片 + 评分等级展示） ----
  wrap.append(el("h3", { text: "评价标准与观测点" }));
  const indicators = framework.indicators || [];
  if (indicators.length === 0) {
    wrap.append(placeholder("该框架未包含指标"));
    return wrap;
  }

  for (const indicator of indicators) {
    const indicatorCard = el("div", { class: "indicator" }, [
      el("div", { class: "indicator-head" }, [
        el("h4", { text: indicator.name }),
        el("span", { class: "badge", text: label(DIMENSION, indicator.dimension) }),
      ]),
    ]);

    for (const obs of indicator.observations || []) {
      const obsCard = el("div", { class: "observation" }, [
        el("div", { class: "obs-head" }, [
          el("span", { class: "obs-name", text: obs.name }),
          el("span", { class: "badge badge-muted", text: label(METHOD, obs.method) }),
          el("span", { class: "badge badge-muted", text: label(FREQUENCY, obs.frequency) }),
        ]),
      ]);

      // 证据来源：把后端键转成中文名称
      const sources = (obs.evidence_sources || []).map((key) =>
        el("span", { class: "badge badge-info", text: evidenceLabels([key]) })
      );
      if (sources.length) {
        obsCard.append(
          el("div", { class: "obs-sources" }, [
            el("span", { class: "meta", text: "证据来源：" }),
            ...sources,
          ])
        );
      }

      // 评分标准：以等级卡片直观呈现"达到什么程度算几级"
      const rubrics = obs.rubrics || [];
      if (rubrics.length) {
        const rubricList = el("div", { class: "rubric-list" });
        for (const level of rubrics) {
          rubricList.append(
            el("div", { class: "rubric-item" }, [
              el("span", { class: "rubric-level", text: `${level.level} 级` }),
              el("div", { class: "rubric-body" }, [
                el("strong", { text: level.label }),
                el("p", { class: "rubric-desc", text: level.description }),
                el("p", { class: "meta", text: `证据要求：${level.evidence}` }),
              ]),
            ])
          );
        }
        obsCard.append(el("div", { class: "rubric-box" }, [
          el("p", { class: "meta", text: "评分标准：" }),
          rubricList,
        ]));
      }

      indicatorCard.append(obsCard);
    }
    wrap.append(indicatorCard);
  }
  return wrap;
}

/** 渲染已规范化的属性概览（分组卡片，值用中文标签）。 */
export function renderAttributes(attributes) {
  const rows = [
    ["障碍类型", labels(DISABILITY, attributes.disabilities), true],
    ["障碍程度", label(SEVERITY, attributes.severity)],
    ["认知等级", label(COGNITIVE_LEVEL, attributes.cognitive_level)],
    ["感官偏好", label(SENSORY, attributes.sensory_preference)],
    ["康复目标", labels(REHAB_GOAL, attributes.rehab_goals)],
    ["学习节奏", label(LEARNING_PACE, attributes.learning_pace)],
  ];
  const wrap = el("div", { class: "attr-grid" });
  for (const [name, value] of rows) {
    wrap.append(
      el("div", { class: "attr-item" }, [
        el("span", { class: "attr-name", text: name }),
        el("span", { class: "attr-value", text: value }),
      ])
    );
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
  const disabilities = data.getAll("disabilities").map(String);
  const attributes = {
    disabilities,
    severity: String(data.get("severity") || ""),
    cognitive_level: String(data.get("cognitive_level") || ""),
    learning_pace: String(data.get("learning_pace") || ""),
    rehab_goals: goals,
  };
  const sensory = String(data.get("sensory_preference") || "");
  if (sensory) attributes.sensory_preference = sensory;
  return attributes;
}

/** 校验录入属性，返回错误信息或 null。 */
export function validateAttributes(attributes) {
  if (!attributes.disabilities || attributes.disabilities.length === 0) {
    return "请至少选择一种障碍类型";
  }
  return null;
}

/** 构建属性录入表单（供预览页、学生建档与资源生成共用）。 */
export function buildAttributesForm(prefix) {
  const form = el("form", { class: "attributes-form" });

  // 障碍类型：多选（一个学生可同时具备多种障碍）
  const disabilityField = el("div", { class: "field" }, [
    el("label", { text: "障碍类型（可多选，至少一项）" }),
    el(
      "div",
      { class: "checks" },
      ATTRIBUTE_OPTIONS.disabilities.map(([value, text]) =>
        el("label", { class: "check" }, [
          el("input", { type: "checkbox", name: "disabilities", value }),
          text,
        ])
      )
    ),
  ]);

  const row1 = el("div", { class: "field-row" }, [
    el("div", { class: "field" }, [
      el("label", { for: `${prefix}-severity`, text: "障碍程度" }),
      select("severity", ATTRIBUTE_OPTIONS.severity, { required: true }),
    ]),
    el("div", { class: "field" }, [
      el("label", { for: `${prefix}-cognitive`, text: "认知等级" }),
      select("cognitive_level", ATTRIBUTE_OPTIONS.cognitive_level, { required: true }),
    ]),
  ]);

  const row2 = el("div", { class: "field-row" }, [
    el("div", { class: "field" }, [
      el("label", { for: `${prefix}-pace`, text: "学习节奏" }),
      select("learning_pace", ATTRIBUTE_OPTIONS.learning_pace, { required: true }),
    ]),
    el("div", { class: "field" }, [
      el("label", { for: `${prefix}-sensory`, text: "感官偏好（留空则按主障碍推导）" }),
      select("sensory_preference", ATTRIBUTE_OPTIONS.sensory_preference, {
        includeBlank: true,
      }),
    ]),
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

  form.append(disabilityField, row1, row2, goalField);
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
        text: "当前阶段所有学生共用公共标准（上课参与度、练习完成质量）；输入临时属性可即时预览，不写入档案。",
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
    const attributes = readAttributes(form);
    const error = validateAttributes(attributes);
    if (error) {
      toastError(error);
      return;
    }
    clear(output);
    output.append(placeholder("正在生成预览…", "loading"));
    try {
      const data = await api.previewFramework(attributes);
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
