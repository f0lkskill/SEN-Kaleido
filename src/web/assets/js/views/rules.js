/**
 * views/rules.js —— 病症通用提示词规则集
 * 展示模型从资源质检中沉淀的共性问题，按病症分组，支持通过、拒绝与删除。
 */

import { api } from "../core/api.js";
import { el, clear, placeholder, panel } from "../core/dom.js";
import { DISABILITY, label, formatTime } from "../core/format.js";
import { toastSuccess, toastError } from "../core/toast.js";
import { confirmDialog } from "../core/dialog.js";

const RULE_STATUS = {
  pending: "待审核",
  approved: "已通过",
  rejected: "已拒绝",
};

const RULE_STATUS_CLASS = {
  pending: "badge-warning",
  approved: "badge-success",
  rejected: "badge-danger",
};

const DISABILITY_ORDER = Object.keys(DISABILITY);

/** 生成筛选下拉。 */
function filterSelect(name, options) {
  const node = el("select", { name });
  for (const [value, text] of options) node.append(el("option", { value, text }));
  return node;
}

/**
 * 创建规则集视图。
 * @param {HTMLElement} root 视图容器
 */
export function createView(root) {
  let statusFilter;
  let disabilityFilter;
  let statsBox;
  let listBox;
  let items = [];

  function build() {
    clear(root);
    statusFilter = filterSelect("rule_status", [
      ["", "全部状态"],
      ...Object.entries(RULE_STATUS),
    ]);
    disabilityFilter = filterSelect("rule_disability", [
      ["", "全部病症"],
      ...Object.entries(DISABILITY),
    ]);
    statusFilter.addEventListener("change", render);
    disabilityFilter.addEventListener("change", render);
    statsBox = el("div", { class: "rules-stats" });
    listBox = el("div", { class: "rules-list" });

    root.append(
      el("section", { class: "card" }, [
        panel("规则集", [
          el("p", {
            class: "meta",
            text:
              "模型在资源质检中提炼的病症共性问题会先进入这里；通过后自动参与" +
              "同类病症的资源生成。学生个体差异写入学生画像，不进入通用规则集。",
          }),
          el("div", { class: "rules-toolbar" }, [
            statusFilter,
            disabilityFilter,
            el("button", {
              class: "btn btn-sm",
              type: "button",
              text: "刷新",
              on: { click: refresh },
            }),
          ]),
          statsBox,
          listBox,
        ]),
      ])
    );
  }

  async function refresh() {
    try {
      const data = await api.listPromptRules();
      items = Array.isArray(data.items) ? data.items : [];
      render();
    } catch (err) {
      clear(listBox);
      listBox.append(placeholder(`加载规则集失败：${err.message}`));
      toastError(err.message);
    }
  }

  function render() {
    const status = statusFilter.value;
    const disability = disabilityFilter.value;
    const visible = items.filter(
      (item) =>
        (!status || item.status === status) &&
        (!disability || item.disability === disability)
    );
    renderStats();

    clear(listBox);
    if (!visible.length) {
      listBox.append(
        placeholder(
          "暂无规则。到资源库对课件做质量校验后，模型提炼的共性问题会按病症沉淀到这里。"
        )
      );
      return;
    }

    const groups = new Map();
    for (const item of visible) {
      const key = item.disability || "unknown";
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(item);
    }
    const keys = [...groups.keys()].sort((left, right) => {
      const a = DISABILITY_ORDER.indexOf(left);
      const b = DISABILITY_ORDER.indexOf(right);
      return (a < 0 ? 99 : a) - (b < 0 ? 99 : b);
    });
    for (const key of keys) {
      listBox.append(
        el("section", { class: "rules-group" }, [
          el("h4", { class: "rules-group-title", text: label(DISABILITY, key) }),
          el(
            "div",
            { class: "rules-group-list" },
            groups.get(key).map(ruleItem)
          ),
        ])
      );
    }
  }

  function renderStats() {
    clear(statsBox);
    for (const status of ["pending", "approved", "rejected"]) {
      const count = items.filter((item) => item.status === status).length;
      statsBox.append(
        el("div", { class: "rules-stat" }, [
          el("strong", { text: String(count) }),
          el("span", { text: RULE_STATUS[status] }),
        ])
      );
    }
  }

  function ruleItem(rule) {
    const actions = el("div", { class: "rule-actions" });
    if (rule.status !== "approved") {
      actions.append(
        el("button", {
          class: "btn btn-sm btn-primary",
          type: "button",
          text: "通过",
          on: { click: () => updateStatus(rule, "approved") },
        })
      );
    }
    if (rule.status !== "rejected") {
      actions.append(
        el("button", {
          class: "btn btn-sm",
          type: "button",
          text: "拒绝",
          on: { click: () => updateStatus(rule, "rejected") },
        })
      );
    }
    actions.append(
      el("button", {
        class: "btn btn-sm btn-danger",
        type: "button",
        text: "删除",
        on: { click: () => removeRule(rule) },
      })
    );

    return el("article", { class: "rule-item" }, [
      el("p", { class: "rule-text", text: rule.text }),
      el("div", { class: "rule-meta" }, [
        el("span", {
          class: `badge ${RULE_STATUS_CLASS[rule.status] || "badge-muted"}`,
          text: RULE_STATUS[rule.status] || rule.status,
        }),
        rule.source_topic
          ? el("span", {
              class: "badge badge-muted",
              text: `来源：${rule.source_topic}`,
            })
          : null,
        rule.model
          ? el("span", { class: "badge badge-muted", text: rule.model })
          : null,
        el("span", { class: "meta", text: formatTime(rule.created_at) }),
      ]),
      actions,
    ]);
  }

  async function updateStatus(rule, status) {
    try {
      await api.updatePromptRule(rule.rule_id, { status });
      rule.status = status;
      toastSuccess(
        status === "approved"
          ? "规则已通过，将参与后续生成"
          : "规则已拒绝"
      );
      render();
    } catch (err) {
      toastError(err.message);
    }
  }

  async function removeRule(rule) {
    const ok = await confirmDialog({
      title: "删除规则",
      message: "确认删除这条规则？删除后不可恢复。",
      confirmText: "删除",
      danger: true,
    });
    if (!ok) return;
    try {
      await api.deletePromptRule(rule.rule_id);
      items = items.filter((item) => item.rule_id !== rule.rule_id);
      toastSuccess("规则已删除");
      render();
    } catch (err) {
      toastError(err.message);
    }
  }

  build();
  refresh();

  return {
    /** 切换到此标签时重新拉取规则。 */
    refresh,
  };
}
