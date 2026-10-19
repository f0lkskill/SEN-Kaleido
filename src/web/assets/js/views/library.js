/**
 * views/library.js —— 资源库视图
 * 按资源类型/障碍类型/状态筛选，列表查看生成资源并展开正文。
 */

import { api } from "../core/api.js";
import { el, clear, placeholder } from "../core/dom.js";
import {
  DISABILITY,
  RESOURCE_STATUS,
  label,
  formatTime,
} from "../core/format.js";
import { toastError } from "../core/toast.js";
import { ATTRIBUTE_OPTIONS } from "./framework.js";

const STATUS_OPTIONS = Object.entries(RESOURCE_STATUS);

/** 生成筛选下拉。 */
function filterSelect(name, options, allText = "全部") {
  const node = el("select", { name });
  node.append(el("option", { value: "", text: allText }));
  for (const [value, text] of options) node.append(el("option", { value, text }));
  return node;
}

/**
 * 创建资源库视图。
 * @param {HTMLElement} root 视图容器
 */
export function createView(root) {
  let typeFilter;
  let disabilityFilter;
  let statusFilter;
  let resourceSelect;
  let listBox;
  let counter;

  function build() {
    clear(root);
    resourceSelect = el("select", { name: "resource_type_filter" });
    typeFilter = resourceSelect;
    disabilityFilter = filterSelect("disability", ATTRIBUTE_OPTIONS.disability);
    statusFilter = filterSelect("status", STATUS_OPTIONS);
    listBox = el("div", { class: "list" });
    counter = el("span", { class: "badge badge-muted", text: "共 0 条" });

    const toolbar = el("div", { class: "toolbar" }, [
      el("div", { class: "field" }, [
        el("label", { text: "资源类型" }),
        typeFilter,
      ]),
      el("div", { class: "field" }, [
        el("label", { text: "障碍类型" }),
        disabilityFilter,
      ]),
      el("div", { class: "field" }, [
        el("label", { text: "状态" }),
        statusFilter,
      ]),
      el("button", {
        class: "btn",
        type: "button",
        text: "刷新",
        on: { click: refresh },
      }),
      el("div", { class: "spacer" }),
      counter,
    ]);

    const card = el("section", { class: "card" }, [
      el("div", { class: "card-header" }, [el("h2", { text: "资源库" })]),
      toolbar,
      listBox,
    ]);
    root.append(card);
  }

  /** 加载资源类型下拉。 */
  async function loadTypes() {
    try {
      const types = await api.resourceTypes();
      clear(typeFilter);
      typeFilter.append(el("option", { value: "", text: "全部" }));
      for (const [value, text] of Object.entries(types)) {
        typeFilter.append(el("option", { value, text }));
      }
    } catch (err) {
      toastError(`加载资源类型失败：${err.message}`);
    }
  }

  /** 拉取资源列表。 */
  async function refresh() {
    clear(listBox);
    listBox.append(placeholder("正在加载…", "loading"));
    try {
      const data = await api.listResources({
        resource_type: typeFilter.value,
        disability: disabilityFilter.value,
        status: statusFilter.value,
        size: 100,
      });
      counter.textContent = `共 ${data.total} 条`;
      clear(listBox);
      if (data.items.length === 0) {
        listBox.append(placeholder("暂无资源，请先在「资源生成」中生成。"));
        return;
      }
      for (const item of data.items) listBox.append(resourceItem(item));
    } catch (err) {
      clear(listBox);
      listBox.append(placeholder(`加载失败：${err.message}`));
      toastError(err.message);
    }
  }

  /** 单条资源。 */
  function resourceItem(item) {
    return el("details", { class: "list-item disclosure" }, [
      el("summary", {}, [
        `[${label(DISABILITY, item.disability)}] ${item.topic} `,
        el("span", { class: "badge badge-muted", text: label(RESOURCE_STATUS, item.status) }),
      ]),
      el("p", { class: "meta", text: `ID：${item.resource_id} · 模型：${item.model || "-"} · ${formatTime(item.updated_at)}` }),
      el("pre", { class: "output", text: item.content || "（空内容）" }),
    ]);
  }

  build();

  return {
    refresh() {
      refresh();
    },
    /** 首次进入时加载类型并拉取列表。 */
    init() {
      loadTypes().then(refresh);
    },
  };
}
