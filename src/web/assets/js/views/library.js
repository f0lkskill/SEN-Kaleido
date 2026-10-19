/**
 * views/library.js —— 资源库视图（左右分栏：左资源单，右详情）
 * 左侧按条件筛选并列出资源，选中后右侧展示完整正文（Markdown 渲染）、
 * 元信息标签与生成模板信息。
 */

import { api } from "../core/api.js";
import { el, clear, placeholder, panel } from "../core/dom.js";
import { renderMarkdown } from "../core/markdown.js";
import { confirmDialog } from "../core/dialog.js";
import { openContextMenu } from "../core/contextmenu.js";
import { DISABILITY, RESOURCE_STATUS, label, formatTime } from "../core/format.js";
import { toastSuccess, toastError } from "../core/toast.js";
import { renderAttributes, ATTRIBUTE_OPTIONS } from "./framework.js";

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
export function createView(root, hooks = {}) {
  let typeFilter;
  let disabilityFilter;
  let statusFilter;
  let listBox;
  let detailBox;
  let layout;
  let counter;
  let typeMap = {}; // 资源类型键 -> 中文名
  let closeTimer = null;
  let activeId = null; // 当前选中的资源 ID

  function build() {
    clear(root);
    typeFilter = el("select", { name: "resource_type_filter" });
    disabilityFilter = filterSelect("disability", ATTRIBUTE_OPTIONS.disability);
    statusFilter = filterSelect("status", STATUS_OPTIONS);
    listBox = el("div", { class: "student-list" });
    detailBox = el("div", { class: "student-detail", hidden: true });
    layout = el("div", { class: "student-layout" }, [listBox, detailBox]);
    counter = el("span", { class: "badge badge-muted", text: "共 0 条" });

    const toolbar = el("div", { class: "toolbar" }, [
      el("div", { class: "field" }, [el("label", { text: "资源类型" }), typeFilter]),
      el("div", { class: "field" }, [el("label", { text: "障碍类型" }), disabilityFilter]),
      el("div", { class: "field" }, [el("label", { text: "状态" }), statusFilter]),
      el("div", { class: "spacer" }),
      counter,
      el("button", { class: "btn", type: "button", text: "刷新", on: { click: refresh } }),
    ]);

    // 选择即筛选
    typeFilter.addEventListener("change", refresh);
    disabilityFilter.addEventListener("change", refresh);
    statusFilter.addEventListener("change", refresh);

    const card = el("section", { class: "card" }, [toolbar, layout]);
    root.append(card);
  }

  /** 加载资源类型（用于下拉与中文名映射）。 */
  async function loadTypes() {
    try {
      typeMap = await api.resourceTypes();
      clear(typeFilter);
      typeFilter.append(el("option", { value: "", text: "全部" }));
      for (const [value, text] of Object.entries(typeMap)) {
        typeFilter.append(el("option", { value, text }));
      }
    } catch (err) {
      toastError(`加载资源类型失败：${err.message}`);
    }
  }

  /** 收起详情面板（带回弹动画）。 */
  function closeDetail() {
    if (detailBox.hidden) return;
    layout.classList.remove("narrowed");
    activeId = null;
    for (const node of listBox.querySelectorAll(".student-card")) {
      node.classList.remove("active");
    }
    const finish = () => {
      if (closeTimer) {
        window.clearTimeout(closeTimer);
        closeTimer = null;
      }
      // 收起动画期间若已重新选中资源，则不再收起（避免清空新面板）
      if (activeId) return;
      detailBox.hidden = true;
      clear(detailBox);
    };
    const body = detailBox.querySelector(".detail-body");
    if (body && typeof body.animate === "function") {
      const anim = body.animate(
        [
          { opacity: 1, transform: "translateX(0)" },
          { opacity: 0, transform: "translateX(28px)" },
        ],
        { duration: 240, easing: "ease-in", fill: "forwards" }
      );
      anim.onfinish = finish;
      closeTimer = window.setTimeout(finish, 420);
    } else {
      finish();
    }
  }

  /** 拉取资源列表（autoSelect 为真时默认展示第一条）。 */
  async function refresh(autoSelect = false) {
    const restoreId = activeId;
    closeDetail();
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
      data.items.forEach((item, index) => listBox.append(resourceCard(item, index)));
      // 优先恢复原选中项，其次（首次进入）默认第一条
      const target =
        restoreId && data.items.some((it) => it.resource_id === restoreId)
          ? restoreId
          : autoSelect && data.items.length
            ? data.items[0].resource_id
            : null;
      if (target) {
        const card = listBox.querySelector(`[data-resource-id="${target}"]`);
        showDetail(target, card);
      }
    } catch (err) {
      clear(listBox);
      listBox.append(placeholder(`加载失败：${err.message}`));
      toastError(err.message);
    }
  }

  /** 单条资源卡片。 */
  function resourceCard(item, index) {
    const typeName = typeMap[item.resource_type] || item.resource_type;
    return el(
      "button",
      {
        class: "student-card",
        type: "button",
        "data-resource-id": item.resource_id,
        style: `animation-delay:${Math.min(index, 12) * 30}ms`,
        on: {
          click: (event) => showDetail(item.resource_id, event.currentTarget),
          contextmenu: (event) => openContextMenu(event, resourceMenu(item)),
        },
      },
      [
        el("span", { class: "avatar", text: (typeName || "?").slice(0, 1) }),
        el("span", { class: "student-card-body" }, [
          el("h4", { text: item.topic }),
          el("div", { class: "badge-row" }, [
            el("span", { class: "badge badge-info", text: typeName }),
            el("span", { class: "badge badge-muted", text: label(DISABILITY, item.disability) }),
            el("span", { class: "badge badge-warning", text: label(RESOURCE_STATUS, item.status) }),
          ]),
        ]),
      ]
    );
  }

  /** 组装资源详情（标题为资源类型，Markdown 正文 + 元信息标签）。 */
  function renderDetail(item) {
    const typeName = typeMap[item.resource_type] || item.resource_type;
    const md = el("div", { class: "md" });
    md.innerHTML = renderMarkdown(item.content || "");

    const actions = [];
    // 有来源学生时提供快捷跳转；预生成（临时属性）则无此按钮
    if (item.profile_id) {
      actions.push(
        el("button", {
          class: "btn btn-sm",
          type: "button",
          text: "来源学生",
          on: {
            click: () => {
              if (hooks.onShowStudent) hooks.onShowStudent(item.profile_id);
            },
          },
        })
      );
    }
    actions.push(
      el("button", {
        class: "btn btn-sm",
        type: "button",
        text: "通过",
        on: { click: () => setStatus(item.resource_id, "approved") },
      }),
      el("button", {
        class: "btn btn-sm",
        type: "button",
        text: "退回",
        on: { click: () => setStatus(item.resource_id, "rejected") },
      }),
      el("button", {
        class: "btn btn-danger btn-sm",
        type: "button",
        text: "删除",
        on: { click: () => removeResource(item) },
      }),
      el("button", { class: "btn btn-sm", type: "button", text: "收起", on: { click: closeDetail } })
    );

    const head = el("div", { class: "detail-head" }, [
      el("div", { class: "detail-id" }, [
        el("span", { class: "avatar avatar-lg", text: (typeName || "?").slice(0, 1) }),
        el("h3", { text: typeName }),
      ]),
      el("div", { class: "detail-actions" }, actions),
    ]);

    const panels = [
      panel(null, head),
      panel(
        "资源信息",
        el("div", { class: "badge-row" }, [
          el("span", { class: "badge badge-muted", text: `主题：${item.topic}` }),
          el("span", { class: "badge badge-muted", text: `ID：${item.resource_id}` }),
          el("span", { class: "badge badge-muted", text: `模型：${item.model || "-"}` }),
          el("span", { class: "badge badge-muted", text: label(DISABILITY, item.disability) }),
          el("span", { class: "badge badge-warning", text: label(RESOURCE_STATUS, item.status) }),
          el("span", { class: "badge badge-muted", text: formatTime(item.updated_at) }),
        ])
      ),
    ];
    // 预生成资源（未建档）直接展示临时属性
    if (!item.profile_id && item.attributes) {
      panels.push(panel("临时属性（未建档）", renderAttributes(item.attributes)));
    }
    panels.push(panel("内容", el("div", { class: "detail-md" }, [md])));
    return el("section", { class: "detail-body" }, panels);
  }

  /** 资源右键菜单项。 */
  function resourceMenu(item) {
    return [
      {
        label: "查看详情",
        onSelect: () =>
          showDetail(
            item.resource_id,
            listBox.querySelector(`[data-resource-id="${item.resource_id}"]`)
          ),
      },
      { label: "复制 ID", onSelect: () => copyText(item.resource_id) },
      null,
      { label: "通过", onSelect: () => setStatus(item.resource_id, "approved") },
      { label: "退回", onSelect: () => setStatus(item.resource_id, "rejected") },
      null,
      { label: "删除", danger: true, onSelect: () => removeResource(item) },
    ];
  }

  /** 复制文本到剪贴板。 */
  async function copyText(text) {
    try {
      await navigator.clipboard.writeText(text);
      toastSuccess("已复制到剪贴板");
    } catch (err) {
      toastError("复制失败，请手动复制");
    }
  }

  /** 更新资源审核状态（通过 / 退回）。 */
  async function setStatus(resourceId, status) {
    try {
      await api.updateResourceStatus(resourceId, status);
      toastSuccess(status === "approved" ? "已通过" : "已退回");
      refresh();
    } catch (err) {
      toastError(err.message);
    }
  }

  /** 删除资源（自定义确认对话框）。 */
  async function removeResource(item) {
    const ok = await confirmDialog({
      title: "删除资源",
      message: `确认删除资源「${item.topic}」？此操作不可撤销。`,
      confirmText: "删除",
      danger: true,
    });
    if (!ok) return;
    try {
      await api.deleteResource(item.resource_id);
      toastSuccess("已删除");
      activeId = null;
      refresh();
    } catch (err) {
      toastError(err.message);
    }
  }

  /** 展示资源详情。 */
  async function showDetail(resourceId, cardEl) {
    if (closeTimer) {
      window.clearTimeout(closeTimer);
      closeTimer = null;
    }
    activeId = resourceId;
    detailBox.hidden = false;
    layout.classList.add("narrowed");
    clear(detailBox);
    detailBox.append(placeholder("正在加载…", "loading"));
    if (cardEl) {
      for (const node of listBox.querySelectorAll(".student-card")) {
        node.classList.remove("active");
      }
      cardEl.classList.add("active");
    }
    try {
      const item = await api.getResource(resourceId);
      clear(detailBox);
      detailBox.append(renderDetail(item));
    } catch (err) {
      clear(detailBox);
      detailBox.append(placeholder(`加载失败：${err.message}`));
      toastError(err.message);
    }
  }

  build();

  return {
    refresh() {
      refresh();
    },
    /** 首次进入时加载类型、拉取列表并默认展示第一条。 */
    init() {
      loadTypes().then(() => refresh(true));
    },
  };
}
