/**
 * views/students.js —— 学生档案视图（左右分栏 + 二级模态建档）
 * 布局：左侧为档案列表，选中后列表收窄向左、右侧滑出详情面板。
 * 详情：属性概览、学习节奏独立展示、维度→学习节奏汇集关系图、
 *       可折叠的评价标准（默认隐藏）；不含维度权重占比。
 */

import { api } from "../core/api.js";
import { el, clear, placeholder, enhanceDisclosure, panel } from "../core/dom.js";
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
import { confirmDialog } from "../core/dialog.js";
import { openContextMenu } from "../core/contextmenu.js";
import {
  buildAttributesForm,
  readAttributes,
  validateAttributes,
  renderFramework,
  renderAttributes,
  renderLearningPace,
  renderFlow,
  ATTRIBUTE_OPTIONS,
} from "./framework.js";

/** 生成筛选下拉。 */
function filterSelect(name, options) {
  const node = el("select", { name });
  node.append(el("option", { value: "", text: "全部" }));
  for (const [value, text] of options) node.append(el("option", { value, text }));
  return node;
}

/** 取姓名首字作为头像文字。 */
function firstChar(name) {
  const text = String(name || "").trim();
  return text ? text[0] : "?";
}

/**
 * 创建学生档案视图。
 * @param {HTMLElement} root 视图容器
 */
export function createView(root, hooks = {}) {
  let filterDisability;
  let filterCognitive;
  let listBox;
  let layout;
  let detailBox;
  let totalBadge;
  let activeId = null; // 当前选中的档案 ID
  let closeTimer = null; // 收起动画定时器

  function build() {
    clear(root);

    // ---- 工具条：筛选 ----
    filterDisability = filterSelect("disability", ATTRIBUTE_OPTIONS.disability);
    filterCognitive = filterSelect("cognitive_level", ATTRIBUTE_OPTIONS.cognitive_level);
    // 选择即筛选：下拉变化立刻触发刷新
    filterDisability.addEventListener("change", refresh);
    filterCognitive.addEventListener("change", refresh);
    totalBadge = el("span", { class: "badge badge-muted", text: "共 0 人" });

    // 新建按钮与筛选器同行，置于右侧
    const toolbar = el("div", { class: "toolbar" }, [
      el("div", { class: "field" }, [el("label", { text: "障碍类型" }), filterDisability]),
      el("div", { class: "field" }, [el("label", { text: "认知等级" }), filterCognitive]),
      el("div", { class: "spacer" }),
      totalBadge,
      el("button", {
        class: "btn btn-primary",
        type: "button",
        text: "＋ 新建学生",
        on: { click: openCreateModal },
      }),
    ]);

    listBox = el("div", { class: "student-list" });
    detailBox = el("div", { class: "student-detail", hidden: true });
    layout = el("div", { class: "student-layout" }, [listBox, detailBox]);

    const card = el("section", { class: "card" }, [toolbar, layout]);
    root.append(card);
  }

  /** 打开二级模态窗口进行建档。 */
  function openCreateModal() {
    const overlay = el("div", {
      class: "modal-overlay",
      role: "dialog",
      "aria-modal": "true",
      "aria-label": "新建学生",
    });
    const dialog = el("div", { class: "modal" });

    const close = () => {
      overlay.classList.add("leaving");
      document.removeEventListener("keydown", onKey);
      setTimeout(() => overlay.remove(), 200);
    };
    const onKey = (event) => {
      if (event.key === "Escape") close();
    };

    const form = buildCreateForm(close);
    dialog.append(
      el("div", { class: "modal-head" }, [
        el("h3", { text: "新建学生" }),
        el("button", { class: "btn btn-sm", type: "button", text: "关闭", on: { click: close } }),
      ]),
      form
    );
    overlay.append(dialog);
    // 点击遮罩关闭
    overlay.addEventListener("click", (event) => {
      if (event.target === overlay) close();
    });
    document.addEventListener("keydown", onKey);
    document.body.append(overlay);
    const firstInput = form.querySelector("input, select");
    if (firstInput) firstInput.focus();
  }

  /**
   * 构建建档表单。
   * @param {Function} onDone 建档成功后的回调（用于关闭模态）
   */
  function buildCreateForm(onDone) {
    const nameInput = el("input", { type: "text", name: "name", required: true });
    const attrsForm = buildAttributesForm("create");
    const frameworkCheck = el("input", {
      type: "checkbox",
      name: "generate_framework",
      checked: true,
    });

    const form = el("form", { class: "create-form" }, [
      panel(null, [
        el("div", { class: "field" }, [el("label", { text: "学生姓名/化名" }), nameInput]),
      ]),
      attrsForm,
      panel(null, [el("label", { class: "check" }, [frameworkCheck, "同时生成评价框架"])]),
      el("div", { class: "form-actions" }, [
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
        if (onDone) onDone();
        refresh();
      } catch (err) {
        toastError(err.message);
      }
    });

    return form;
  }

  /** 关闭详情面板：用 Web Animations API 播放收起动画后恢复列表全宽。 */
  function closeDetail() {
    if (detailBox.hidden) return;
    layout.classList.remove("narrowed");
    activeId = null;
    for (const item of listBox.querySelectorAll(".student-card")) {
      item.classList.remove("active");
    }

    const finish = () => {
      if (closeTimer) {
        window.clearTimeout(closeTimer);
        closeTimer = null;
      }
      // 收起动画期间若已重新选中档案，则不再收起（避免清空新面板）
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
      // 兜底：动画事件未回调时也要收起
      closeTimer = window.setTimeout(finish, 420);
    } else {
      finish();
    }
  }

  /** 拉取并渲染学生列表（会同时收起详情面板，卡片依次入场）。 */
  async function refresh(autoSelect = false) {
    // 记录滚动位置与选中项，渲染后恢复，避免列表重建时跳顶或丢失选择
    const scrollY = window.scrollY;
    const restoreId = activeId;
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
      } else {
        data.items.forEach((item, index) => listBox.append(studentCard(item, index)));
        // 优先恢复原选中项，其次（首次进入）默认第一位学生
        const target =
          restoreId && data.items.some((it) => it.profile_id === restoreId)
            ? restoreId
            : autoSelect && data.items.length
              ? data.items[0].profile_id
              : null;
        if (target) {
          const card = listBox.querySelector(`[data-profile-id="${target}"]`);
          showDetail(target, card);
        }
      }
    } catch (err) {
      clear(listBox);
      listBox.append(placeholder(`加载失败：${err.message}`));
      toastError(err.message);
    } finally {
      window.scrollTo(0, scrollY);
    }
  }

  /** 单个学生卡片（带圆形头像与依次入场延时）。 */
  function studentCard(item, index) {
    const button = el(
      "button",
      {
        class: "student-card",
        type: "button",
        "data-profile-id": item.profile_id,
        style: `animation-delay:${Math.min(index, 12) * 30}ms`,
        on: {
          click: () => showDetail(item.profile_id, button),
          contextmenu: (event) => openContextMenu(event, studentMenu(item, button)),
        },
      },
      [
        el("span", { class: "avatar", text: firstChar(item.name) }),
        el("span", { class: "student-card-body" }, [
          el("h4", { text: item.name }),
          el("div", { class: "badge-row" }, [
            el("span", { class: "badge badge-info", text: labels(DISABILITY, item.disabilities) }),
            el("span", { class: "badge badge-muted", text: label(SEVERITY, item.severity) }),
            el("span", {
              class: "badge badge-muted",
              text: `认知：${label(COGNITIVE_LEVEL, item.cognitive_level)}`,
            }),
          ]),
        ]),
      ]
    );
    return button;
  }

  /** 组装详情内容（按板块分区）。 */
  function buildDetail(item) {
    const attributes = item.attributes;
    const head = el("div", { class: "detail-head" }, [
      el("div", { class: "detail-id" }, [
        el("span", { class: "avatar avatar-lg", text: firstChar(item.name) }),
        el("h3", { text: `${item.name}` }),
      ]),
      el("div", { class: "detail-actions" }, [
        el("button", {
          class: "btn btn-sm",
          type: "button",
          text: item.portrait ? "刷新画像" : "生成画像",
          on: { click: (event) => generatePortrait(item, event.currentTarget) },
        }),
        el("button", {
          class: "btn btn-primary btn-sm",
          type: "button",
          text: "创建课件",
          on: {
            click: () => {
              if (hooks.onGenerateFor) hooks.onGenerateFor(item.profile_id, item.name);
            },
          },
        }),
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
    ]);

    return el("section", { class: "detail-body" }, [
      panel(null, head),
      panel("学生属性", renderAttributes(attributes)),
      panel("学生画像", renderPortrait(item.portrait)),
      panel("学习节奏", renderLearningPace(attributes)),
      panel("维度与学习节奏关系", renderFlow(attributes, item.framework)),
      panel(
        "评价标准与观测点",
        // 评价标准默认隐藏，点击展开查看观测点与评分等级
        enhanceDisclosure(
          el("details", { class: "collapse" }, [
            el("summary", {}, [el("span", { text: "展开查看观测点与评分等级" })]),
            el("div", { class: "collapse-body" }, [renderFramework(item.framework)]),
          ])
        )
      ),
      el("p", { class: "meta detail-meta", text: `更新时间：${formatTime(item.updated_at)}` }),
    ]);
  }

  /** 渲染学生画像摘要（基于证据生成）。 */
  function renderPortrait(portrait) {
    if (!portrait || !portrait.summary) {
      return placeholder("尚未生成学生画像。点击右上方「生成画像」基于该学生的证据生成。");
    }
    const wrap = el("div", { class: "portrait" });
    wrap.append(el("p", { class: "portrait-summary", text: portrait.summary }));
    const groups = [
      ["优势表现", portrait.strengths],
      ["需要支持", portrait.needs],
      ["教学建议", portrait.suggestions],
    ];
    for (const [title, items] of groups) {
      if (!Array.isArray(items) || items.length === 0) continue;
      wrap.append(
        el("div", { class: "portrait-block" }, [
          el("span", { class: "badge badge-info", text: title }),
          el(
            "ul",
            { class: "portrait-list" },
            items.map((text) => el("li", { text: String(text) }))
          ),
        ])
      );
    }
    wrap.append(
      el("p", {
        class: "meta",
        text:
          `基于 ${portrait.evidence_count || 0} 条证据 · ` +
          `图像 ${portrait.image_count || 0} · 视频 ${portrait.video_count || 0} · ` +
          `${portrait.model || "未知模型"} · ${formatTime(portrait.generated_at)}`,
      })
    );
    return wrap;
  }

  /** 基于证据生成学生画像，并刷新详情。 */
  async function generatePortrait(item, button) {
    const original = button ? button.textContent : "";
    if (button) {
      button.disabled = true;
      button.textContent = "分析中…";
    }
    try {
      await api.generatePortrait(item.profile_id);
      toastSuccess("学生画像已生成");
      const card = listBox.querySelector(`[data-profile-id="${item.profile_id}"]`);
      await showDetail(item.profile_id, card);
    } catch (err) {
      toastError(err.message);
    } finally {
      if (button && button.isConnected) {
        button.disabled = false;
        button.textContent = original || "生成画像";
      }
    }
  }

  /** 展示学生详情（列表收窄、右侧滑出面板；切换学生重新播放进入动画）。 */
  async function showDetail(profileId, cardEl) {
    // 取消可能仍在进行的收起定时器，避免误清空新详情
    if (closeTimer) {
      window.clearTimeout(closeTimer);
      closeTimer = null;
    }
    detailBox.classList.remove("leaving");
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
    const scrollY = window.scrollY;
    try {
      const item = await api.getStudent(profileId);
      clear(detailBox);
      detailBox.append(buildDetail(item));
    } catch (err) {
      clear(detailBox);
      detailBox.append(placeholder(`加载失败：${err.message}`));
      toastError(err.message);
    } finally {
      // 切换档案时保持页面滚动位置，不跳到顶部
      window.scrollTo(0, scrollY);
    }
  }

  /** 学生右键菜单项。 */
  function studentMenu(item, cardEl) {
    return [
      { label: "查看详情", onSelect: () => showDetail(item.profile_id, cardEl) },
      {
        label: "创建课件",
        onSelect: () => {
          if (hooks.onGenerateFor) hooks.onGenerateFor(item.profile_id, item.name);
        },
      },
      {
        label: item.portrait ? "刷新画像" : "生成画像",
        onSelect: () => generatePortrait(item),
      },
      { label: "复制 ID", onSelect: () => copyText(item.profile_id) },
      null,
      { label: "删除", danger: true, onSelect: () => remove(item) },
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

  /** 删除学生档案（自定义确认对话框）。 */
  async function remove(item) {
    const ok = await confirmDialog({
      title: "删除档案",
      message: `确认删除「${item.name}」的档案？此操作不可撤销。`,
      confirmText: "删除",
      danger: true,
    });
    if (!ok) return;
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
    /** 首次进入：加载元数据、自动筛选一次并默认展示第一位。 */
    async init() {
      await loadEvidenceSources();
      await refresh(true);
    },
    /** 定位并展示指定学生（供资源库跳转使用）。 */
    async showStudent(profileId) {
      let card = listBox.querySelector(`[data-profile-id="${profileId}"]`);
      if (!card) {
        await refresh(false);
        card = listBox.querySelector(`[data-profile-id="${profileId}"]`);
      }
      if (card) showDetail(profileId, card);
    },
    refresh,
  };
}
