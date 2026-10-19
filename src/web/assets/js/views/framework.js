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

/**
 * 渲染评价标准（指标 → 观测点 → 评分等级）。
 * 不展示维度权重占比，聚焦"达到什么程度算几级"。
 * @param {Object} framework 框架对象
 * @returns {HTMLElement}
 */
export function renderFramework(framework) {
  const wrap = el("div", { class: "framework" });
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

      // 评分等级：直观呈现"达到什么程度算几级"
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
          el("p", { class: "meta", text: "评分等级：" }),
          rubricList,
        ]));
      }

      indicatorCard.append(obsCard);
    }
    wrap.append(indicatorCard);
  }
  return wrap;
}

/** 学习节奏的展示文案（节奏值 → 名称 + 教学提示）。 */
const PACE_INFO = {
  fast: { name: "较快", desc: "可适当加快推进速度，增加拓展与挑战性练习。" },
  medium: { name: "适中", desc: "按常规节奏推进，兼顾理解与练习。" },
  slow: { name: "较慢", desc: "放慢节奏，增加重复、分解步骤与即时提示。" },
};

/** 指数取值（0~1）映射为颜色：低→红，中→黄，高→绿。 */
function indexColor(value) {
  const ratio = Math.max(0, Math.min(1, Number(value) || 0));
  const hue = Math.round(ratio * 120); // 0=红, 60=黄, 120=绿
  return `hsl(${hue}, 68%, 42%)`;
}

/** 依据维度指数与框架评分等级，推断当前达到的等级名称。 */
function dimLevel(framework, dim, value) {
  const indicators = (framework && framework.indicators) || [];
  const indicator = indicators.find((item) => item.dimension === dim);
  const observation = indicator && (indicator.observations || [])[0];
  const rubrics = (observation && observation.rubrics) || [];
  if (!rubrics.length) return "";
  const levels = [...rubrics].sort((a, b) => a.level - b.level);
  const ratio = Math.max(0, Math.min(1, Number(value) || 0));
  const index = Math.round(ratio * (levels.length - 1));
  return levels[index].label || "";
}

/** 构造带指数气泡的节点属性。 */
function indexNodeAttrs(baseClass, value, tip) {
  return {
    class: `${baseClass} index-node`,
    "data-tip": `${tip} ${Number(value).toFixed(2)}`,
    style: `--index-color:${indexColor(value)}`,
  };
}

/**
 * 渲染学习节奏（独立详细展示，含精确指数与悬停气泡）。
 * @param {Object} attributes 规范化属性
 * @returns {HTMLElement}
 */
export function renderLearningPace(attributes) {
  const value = Number(attributes.pace_index ?? 0);
  const info = PACE_INFO[attributes.learning_pace] || {
    name: label(LEARNING_PACE, attributes.learning_pace),
    desc: "",
  };
  // 指数默认不直接展示，悬停卡片时以气泡给出（见 indexNodeAttrs 的 data-tip）
  return el("div", indexNodeAttrs("pace-card", value, "学习节奏指数"), [
    el("div", { class: "pace-head" }, [
      el("span", { class: "pace-key", text: "学习节奏" }),
      el("span", { class: "pace-badge", text: info.name }),
    ]),
    el("p", { class: "pace-desc", text: info.desc }),
  ]);
}

/**
 * 渲染汇集关系图：底部两个评价维度，向上汇集到顶部的学习节奏。
 * 节点按各自指数着色，流动光点颜色与维度指数同步；指数默认不显示，
 * 仅在悬停节点时以气泡给出。
 * @param {Object} attributes 规范化属性
 * @param {Object} framework 评价框架（含 dimension_indexes）
 * @returns {HTMLElement}
 */
export function renderFlow(attributes, framework) {
  const paceIndex = Number(attributes.pace_index ?? 0);
  const info = PACE_INFO[attributes.learning_pace] || {
    name: label(LEARNING_PACE, attributes.learning_pace),
  };
  const indexes = (framework && framework.dimension_indexes) || {};
  const dims = ["participation", "practice"];

  const paceNode = el("div", indexNodeAttrs("flow-node flow-pace", paceIndex, "学习节奏指数"), [
    el("span", { text: `学习节奏：${info.name}` }),
  ]);

  const dots = ["a", "b"].map((suffix, i) => {
    const color = indexColor(indexes[dims[i]] ?? 0);
    return el("span", {
      class: `flow-dot flow-dot-${suffix}`,
      style: `background:${color};box-shadow:0 0 8px ${color}`,
    });
  });

  const base = el(
    "div",
    { class: "flow-base" },
    dims.map((dim) => {
      const value = Number(indexes[dim] ?? 0);
      const node = el("div", indexNodeAttrs("flow-node", value, `${label(DIMENSION, dim)}指数`), [
        el("span", { text: label(DIMENSION, dim) }),
      ]);
      const cell = el("div", { class: "flow-cell" }, [node]);
      // 常驻评分等级标签，颜色与指数一致
      const level = dimLevel(framework, dim, value);
      if (level) {
        cell.append(
          el("span", {
            class: "flow-level",
            style: `--index-color:${indexColor(value)}`,
            text: level,
          })
        );
      }
      return cell;
    })
  );

  return el("div", { class: "flow" }, [
    paceNode,
    el("div", { class: "flow-streams", "aria-hidden": "true" }, dots),
    base,
  ]);
}

/** 渲染已规范化的属性概览（分组卡片，值用中文标签）。 */
export function renderAttributes(attributes) {
  const rows = [
    ["障碍类型", labels(DISABILITY, attributes.disabilities)],
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
      el("label", { for: `${prefix}-sensory`, text: "感官偏好" }),
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
      form,
      el("div", { class: "form-actions" }, [
        el("button", {
          class: "btn btn-primary",
          type: "button",
          text: "预览",
          on: { click: preview },
        }),
      ]),
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
