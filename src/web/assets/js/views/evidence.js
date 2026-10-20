/**
 * views/evidence.js —— 证据管理视图（左右分栏：左证据列表，右详情）
 * 证据分为「公有证据（未归类）」与「归类证据（已划分所有者）」两组展示；
 * 支持文本/图像/视频证据的新建与上传，并把公有证据归类到学生。
 */

import { api } from "../core/api.js";
import { el, clear, placeholder, panel } from "../core/dom.js";
import {
  EVIDENCE_STATUS,
  EVIDENCE_STATUS_CLASS,
  EVIDENCE_SCOPE,
  MEDIA_TYPE,
  EVIDENCE_MODALITY,
  EVIDENCE_PROCESSED_BY,
  EVIDENCE_COST,
  EVIDENCE_SOURCE,
  OBSERVATION,
  label,
  evidenceLabel,
  formatTime,
} from "../core/format.js";
import { toastSuccess, toastError } from "../core/toast.js";
import { confirmDialog } from "../core/dialog.js";
import { openContextMenu } from "../core/contextmenu.js";

/** 当前没有登录体系，审核人暂用固定身份。 */
const REVIEWER = "教师";

const FILE_ACCEPT = {
  text: ".txt,.md,text/plain,text/markdown",
  image: ".png,.jpg,.jpeg,.gif,.webp,.svg,image/*",
  video: ".mp4,.webm,.ogg,.mov,video/*",
};

const IMAGE_SUFFIX = /\.(png|jpe?g|gif|webp|svg)$/i;
const VIDEO_SUFFIX = /\.(mp4|webm|ogg|mov)$/i;

/** 生成筛选下拉。 */
function filterSelect(name, options, allText = "全部") {
  const node = el("select", { name });
  node.append(el("option", { value: "", text: allText }));
  for (const [value, text] of options) node.append(el("option", { value, text }));
  return node;
}

/** 生成徽章。 */
function badge(text, className = "badge-muted") {
  return el("span", { class: `badge ${className}`, text });
}

/** 生成表单字段。 */
function field(text, control) {
  return el("div", { class: "field" }, [el("label", { text }), control]);
}

/** 媒体图标文字。 */
function mediaIcon(media) {
  return media === "image" ? "图" : media === "video" ? "影" : "文";
}

/** 按 URL 后缀判断图片。 */
function isImageUrl(url) {
  return IMAGE_SUFFIX.test(String(url).split("?")[0]);
}

/** 按 URL 后缀判断视频。 */
function isVideoUrl(url) {
  return VIDEO_SUFFIX.test(String(url).split("?")[0]);
}

/** 按文件类型推断媒体类型。 */
function inferMediaType(file) {
  const type = String(file.type || "");
  const name = String(file.name || "").toLowerCase();
  if (type.startsWith("image/") || IMAGE_SUFFIX.test(name)) return "image";
  if (type.startsWith("video/") || VIDEO_SUFFIX.test(name)) return "video";
  if (type.startsWith("text/") || /\.(txt|md)$/i.test(name)) return "text";
  return "";
}

/** 文件大小格式化。 */
function formatSize(size) {
  const value = Number(size) || 0;
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / 1024 / 1024).toFixed(1)} MB`;
}

/** 取证据媒体类型（兼容旧数据）。 */
function mediaTypeOf(item) {
  if (MEDIA_TYPE[item.media_type]) return item.media_type;
  const attachments = item.attachments || [];
  if (attachments.some(isImageUrl)) return "image";
  if (attachments.some(isVideoUrl)) return "video";
  return "text";
}

/** 是否公有证据。 */
function isPublic(item) {
  return item.scope === "public";
}

/**
 * 创建证据管理视图。
 * @param {HTMLElement} root 视图容器
 * @param {Object} hooks 跨视图回调：onShowStudent
 */
export function createView(root, hooks = {}) {
  let studentFilter;
  let scopeFilter;
  let mediaFilter;
  let sourceFilter;
  let statusFilter;
  let listBox;
  let detailBox;
  let layout;

  let studentMap = {}; // profile_id -> 学生列表项
  let sourceMap = {}; // source_type -> 来源定义
  const observationNames = { ...OBSERVATION };

  let activeId = null; // 当前选中的证据 ID
  let closeTimer = null;

  function build() {
    clear(root);

    studentFilter = filterSelect("student_id", [], "全部学生");
    scopeFilter = filterSelect("scope", Object.entries(EVIDENCE_SCOPE), "全部归属");
    mediaFilter = filterSelect("media_type", Object.entries(MEDIA_TYPE), "全部媒体");
    sourceFilter = filterSelect("source_type", []);
    statusFilter = filterSelect("status", Object.entries(EVIDENCE_STATUS));
    listBox = el("div", { class: "student-list" });
    detailBox = el("div", { class: "student-detail", hidden: true });
    layout = el("div", { class: "student-layout" }, [listBox, detailBox]);

    const toolbar = el("div", { class: "toolbar toolbar-with-actions" }, [
      el("div", { class: "toolbar-filters" }, [
        el("div", { class: "field" }, [el("label", { text: "归属" }), scopeFilter]),
        el("div", { class: "field" }, [el("label", { text: "媒体" }), mediaFilter]),
        el("div", { class: "field" }, [el("label", { text: "学生" }), studentFilter]),
        el("div", { class: "field" }, [el("label", { text: "来源" }), sourceFilter]),
        el("div", { class: "field" }, [el("label", { text: "状态" }), statusFilter]),
      ]),
      el("div", { class: "toolbar-actions" }, [
        el("button", { class: "btn", type: "button", text: "刷新", on: { click: refresh } }),
        el("button", {
          class: "btn btn-primary",
          type: "button",
          text: "＋ 新增证据",
          on: { click: openCreateModal },
        }),
      ]),
    ]);

    // 选择即筛选
    for (const select of [studentFilter, scopeFilter, mediaFilter, sourceFilter, statusFilter]) {
      select.addEventListener("change", refresh);
    }

    root.append(el("section", { class: "card" }, [toolbar, layout]));
  }

  /** 来源定义（后端失败时回退到静态键名）。 */
  function sourceEntries() {
    const entries = Object.entries(sourceMap);
    if (entries.length) {
      return entries.map(([key, def]) => [key, (def && def.name) || evidenceLabel(key)]);
    }
    return Object.entries(EVIDENCE_SOURCE);
  }

  /** 加载学生列表并刷新筛选下拉。 */
  async function loadStudents() {
    try {
      const data = await api.listStudents({ size: 200 });
      studentMap = {};
      clear(studentFilter);
      studentFilter.append(el("option", { value: "", text: "全部学生" }));
      for (const item of data.items || []) {
        studentMap[item.profile_id] = item;
        studentFilter.append(el("option", { value: item.profile_id, text: item.name }));
      }
    } catch (err) {
      toastError(`加载学生失败：${err.message}`);
    }
  }

  /** 加载证据来源定义并刷新筛选下拉。 */
  async function loadSources() {
    try {
      const data = await api.evidenceSources();
      sourceMap = data && typeof data === "object" ? data : {};
    } catch (err) {
      sourceMap = {};
    }
    clear(sourceFilter);
    sourceFilter.append(el("option", { value: "", text: "全部" }));
    for (const [key, text] of sourceEntries()) {
      sourceFilter.append(el("option", { value: key, text }));
    }
  }

  /** 观测点中文名。 */
  function observationName(key) {
    return observationNames[key] || String(key || "-");
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
      // 收起动画期间若已重新选中证据，则不再收起（避免清空新面板）
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

  /** 拉取证据列表（autoSelect 为真时默认展示第一条）。 */
  async function refresh(autoSelect = false) {
    const restoreId = activeId;
    closeDetail();
    clear(listBox);
    listBox.append(placeholder("正在加载…", "loading"));
    try {
      const data = await api.listEvidence({
        student_id: studentFilter.value,
        scope: scopeFilter.value,
        media_type: mediaFilter.value,
        source_type: sourceFilter.value,
        status: statusFilter.value,
        size: 100,
      });
      clear(listBox);
      if (data.items.length === 0) {
        listBox.append(placeholder("暂无证据，点击右上角新增。"));
        return;
      }
      renderList(data.items);
      // 优先恢复原选中项，其次（首次进入）默认第一条
      const target =
        restoreId && data.items.some((item) => item.evidence_id === restoreId)
          ? restoreId
          : autoSelect && data.items.length
            ? data.items[0].evidence_id
            : null;
      if (target) {
        const card = listBox.querySelector(`[data-evidence-id="${target}"]`);
        showDetail(target, card);
      }
    } catch (err) {
      clear(listBox);
      listBox.append(placeholder(`加载失败：${err.message}`));
      toastError(err.message);
    }
  }

  /** 渲染列表：未选择归属筛选时按公有/归类分组。 */
  function renderList(items) {
    let index = 0;
    const appendCards = (groupItems) => {
      for (const item of groupItems) listBox.append(evidenceCard(item, index++));
    };
    if (scopeFilter.value) {
      appendCards(items);
      return;
    }
    const publicItems = items.filter(isPublic);
    const classifiedItems = items.filter((item) => !isPublic(item));
    const groups = [
      { title: "公有证据（未归类）", items: publicItems, className: "badge-info" },
      { title: "归类证据（已划分所有者）", items: classifiedItems, className: "badge-muted" },
    ];
    for (const group of groups) {
      if (group.items.length === 0) continue;
      listBox.append(
        el("div", { class: "evidence-group-head" }, [
          badge(group.title, group.className),
        ])
      );
      appendCards(group.items);
    }
  }

  /** 单条证据卡片。 */
  function evidenceCard(item, index) {
    const status = item.status || "draft";
    const scope = isPublic(item) ? "public" : "classified";
    const media = mediaTypeOf(item);
    const student = studentMap[item.student_id];
    const owner = scope === "public" ? "待归类" : student ? student.name : item.student_id;
    const obsName = scope === "public" ? "未绑定观测点" : observationName(item.observation_key);
    return el(
      "button",
      {
        class: "student-card",
        type: "button",
        "data-evidence-id": item.evidence_id,
        style: `animation-delay:${Math.min(index, 12) * 30}ms`,
        on: {
          click: (event) => showDetail(item.evidence_id, event.currentTarget),
          contextmenu: (event) => openContextMenu(event, evidenceMenu(item)),
        },
      },
      [
        el("span", { class: "avatar", text: mediaIcon(media) }),
        el("span", { class: "student-card-body" }, [
          el("h4", { text: item.title || obsName }),
          el("div", { class: "badge-row" }, [
            badge(EVIDENCE_SCOPE[scope], scope === "public" ? "badge-info" : "badge-muted"),
            badge(owner),
            badge(MEDIA_TYPE[media], media === "image" ? "badge-info" : "badge-muted"),
            badge(
              label(EVIDENCE_STATUS, status),
              EVIDENCE_STATUS_CLASS[status] || "badge-muted"
            ),
          ]),
        ]),
      ]
    );
  }

  /** 渲染媒体附件预览（图片 / 视频 / 其它链接）。 */
  function renderAttachments(item) {
    const attachments = item.attachments || [];
    if (attachments.length === 0) return null;
    const nodes = [];
    for (const url of attachments) {
      if (isImageUrl(url)) {
        nodes.push(
          el("img", {
            class: "evidence-media",
            src: url,
            alt: item.title || "证据图片",
            loading: "lazy",
          })
        );
      } else if (isVideoUrl(url)) {
        nodes.push(
          el("video", { class: "evidence-media", controls: true, preload: "metadata" }, [
            el("source", { src: url }),
          ])
        );
      } else {
        nodes.push(
          el("a", {
            class: "badge badge-info",
            href: url,
            target: "_blank",
            rel: "noopener",
            text: "查看附件",
          })
        );
      }
    }
    return el("div", { class: "evidence-media-grid" }, nodes);
  }

  /** 组装证据详情。 */
  function buildDetail(item) {
    const status = item.status || "draft";
    const scope = isPublic(item) ? "public" : "classified";
    const media = mediaTypeOf(item);
    const student = studentMap[item.student_id];
    const studentName = student ? student.name : item.student_id;
    const obsName = observationName(item.observation_key);
    const sourceName = evidenceLabel(item.source_type);
    const source = sourceMap[item.source_type] || null;

    const actions = [];
    if (scope === "public") {
      actions.push(
        el("button", {
          class: "btn btn-primary btn-sm",
          type: "button",
          text: "归类到学生",
          on: { click: () => openClassifyModal(item) },
        })
      );
    } else if (item.student_id && hooks.onShowStudent) {
      actions.push(
        el("button", {
          class: "btn btn-sm",
          type: "button",
          text: "来源学生",
          on: { click: () => hooks.onShowStudent(item.student_id) },
        })
      );
    }
    if (status !== "verified") {
      actions.push(
        el("button", {
          class: "btn btn-primary btn-sm",
          type: "button",
          text: "通过",
          on: { click: () => review(item, "verified") },
        })
      );
    }
    if (status !== "rejected") {
      actions.push(
        el("button", {
          class: "btn btn-sm",
          type: "button",
          text: "拒绝",
          on: { click: () => review(item, "rejected") },
        })
      );
    }
    actions.push(
      el("button", {
        class: "btn btn-danger btn-sm",
        type: "button",
        text: "删除",
        on: { click: () => removeEvidence(item) },
      }),
      el("button", { class: "btn btn-sm", type: "button", text: "收起", on: { click: closeDetail } })
    );

    const head = el("div", { class: "detail-head" }, [
      el("div", { class: "detail-id" }, [
        el("span", { class: "avatar avatar-lg", text: mediaIcon(media) }),
        el("h3", { text: item.title || obsName }),
      ]),
      el("div", { class: "detail-actions" }, actions),
    ]);

    const info = el("div", { class: "badge-row" }, [
      badge(`ID：${item.evidence_id}`),
      badge(EVIDENCE_SCOPE[scope], scope === "public" ? "badge-info" : "badge-muted"),
      badge(`媒体：${label(MEDIA_TYPE, media)}`),
      badge(`来源：${sourceName}`),
      badge(
        `状态：${label(EVIDENCE_STATUS, status)}`,
        EVIDENCE_STATUS_CLASS[status] || "badge-muted"
      ),
      badge(`采集：${formatTime(item.collected_at)}`),
    ]);
    if (scope === "classified") {
      info.append(badge(`学生：${studentName}`, "badge-info"));
      info.append(badge(`观测点：${obsName}`));
    } else {
      info.append(badge("未归类：可稍后指定学生与观测点", "badge-warning"));
    }
    if (item.collector) info.append(badge(`采集人：${item.collector}`));
    if (item.value !== null && item.value !== undefined) {
      info.append(badge(`量化值：${item.value}`));
    }
    if (item.level !== null && item.level !== undefined) {
      info.append(badge(`等级：${item.level} 级`));
    }

    const panels = [panel(null, head), panel("证据信息", info)];
    if (source) {
      const sourceBadges = [
        badge(`形态：${label(EVIDENCE_MODALITY, source.modality)}`),
        badge(`加工：${label(EVIDENCE_PROCESSED_BY, source.processed_by)}`),
        badge(`成本：${label(EVIDENCE_COST, source.cost)}`),
      ];
      if (source.requires_segmentation) {
        sourceBadges.push(badge("需先转为结构化事件", "badge-warning"));
      }
      panels.push(panel("来源说明", el("div", { class: "badge-row" }, sourceBadges)));
    }

    const contentBody = [];
    if (item.content) {
      contentBody.push(el("pre", { class: "output", text: item.content }));
    }
    const mediaNode = renderAttachments(item);
    if (mediaNode) contentBody.push(mediaNode);
    if (contentBody.length === 0) contentBody.push(placeholder("暂无内容"));
    if (item.note) {
      contentBody.push(el("p", { class: "meta", text: `备注/审核意见：${item.note}` }));
    }
    panels.push(panel("证据内容", contentBody));

    if (status !== "draft") {
      panels.push(
        panel(
          "审核记录",
          el("div", { class: "badge-row" }, [
            badge(`审核人：${item.verified_by || "-"}`),
            badge(`审核时间：${formatTime(item.verified_at)}`),
          ])
        )
      );
    }
    panels.push(el("p", { class: "meta detail-meta", text: `更新于 ${formatTime(item.updated_at)}` }));

    return el("section", { class: "detail-body" }, panels);
  }

  /** 证据右键菜单项。 */
  function evidenceMenu(item) {
    const status = item.status || "draft";
    const publicItem = isPublic(item);
    return [
      {
        label: "查看详情",
        onSelect: () =>
          showDetail(
            item.evidence_id,
            listBox.querySelector(`[data-evidence-id="${item.evidence_id}"]`)
          ),
      },
      publicItem
        ? { label: "归类到学生", onSelect: () => openClassifyModal(item) }
        : {
            label: "来源学生",
            disabled: !item.student_id || !hooks.onShowStudent,
            onSelect: () => {
              if (hooks.onShowStudent) hooks.onShowStudent(item.student_id);
            },
          },
      null,
      {
        label: "通过",
        disabled: status === "verified",
        onSelect: () => review(item, "verified"),
      },
      {
        label: "拒绝",
        disabled: status === "rejected",
        onSelect: () => review(item, "rejected"),
      },
      null,
      { label: "复制 ID", onSelect: () => copyText(item.evidence_id) },
      { label: "删除", danger: true, onSelect: () => removeEvidence(item) },
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

  /** 审核证据（通过 / 拒绝）。 */
  async function review(item, status) {
    if (status === "rejected") {
      const ok = await confirmDialog({
        title: "拒绝证据",
        message: `确认拒绝「${item.title || observationName(item.observation_key)}」？证据将保留，可稍后重新审核。`,
        confirmText: "拒绝",
        danger: true,
      });
      if (!ok) return;
    }
    try {
      await api.reviewEvidence(item.evidence_id, {
        status,
        verified_by: REVIEWER,
      });
      toastSuccess(status === "verified" ? "已通过" : "已拒绝");
      refresh();
    } catch (err) {
      toastError(err.message);
    }
  }

  /** 删除证据（自定义确认对话框）。 */
  async function removeEvidence(item) {
    const ok = await confirmDialog({
      title: "删除证据",
      message: `确认删除「${item.title || observationName(item.observation_key)}」？此操作不可撤销。`,
      confirmText: "删除",
      danger: true,
    });
    if (!ok) return;
    try {
      await api.deleteEvidence(item.evidence_id);
      toastSuccess("已删除");
      activeId = null;
      refresh();
    } catch (err) {
      toastError(err.message);
    }
  }

  /** 展示证据详情。 */
  async function showDetail(evidenceId, cardEl) {
    if (closeTimer) {
      window.clearTimeout(closeTimer);
      closeTimer = null;
    }
    activeId = evidenceId;
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
      const item = await api.getEvidence(evidenceId);
      clear(detailBox);
      detailBox.append(buildDetail(item));
    } catch (err) {
      clear(detailBox);
      detailBox.append(placeholder(`加载失败：${err.message}`));
      toastError(err.message);
    }
  }

  /** 通用弹窗。 */
  function openModal(title, buildForm) {
    const overlay = el("div", {
      class: "modal-overlay",
      role: "dialog",
      "aria-modal": "true",
      "aria-label": title,
    });
    const dialog = el("div", { class: "modal" });
    const close = () => {
      overlay.classList.add("leaving");
      document.removeEventListener("keydown", onKey);
      window.setTimeout(() => overlay.remove(), 200);
    };
    const onKey = (event) => {
      if (event.key === "Escape") close();
    };

    const form = buildForm(close);
    dialog.append(
      el("div", { class: "modal-head" }, [
        el("h3", { text: title }),
        el("button", { class: "btn btn-sm", type: "button", text: "关闭", on: { click: close } }),
      ]),
      form
    );
    overlay.append(dialog);
    overlay.addEventListener("click", (event) => {
      if (event.target === overlay) close();
    });
    document.addEventListener("keydown", onKey);
    document.body.append(overlay);
    const firstControl = form.querySelector("select, input, textarea");
    if (firstControl) firstControl.focus();
  }

  /** 新建证据弹窗。 */
  async function openCreateModal() {
    if (Object.keys(studentMap).length === 0) await loadStudents();
    if (Object.keys(sourceMap).length === 0) await loadSources();
    openModal("新增证据", buildCreateForm);
  }

  /** 构建新增证据表单。 */
  function buildCreateForm(onDone) {
    const scopeSelect = el("select", { name: "scope" });
    scopeSelect.append(el("option", { value: "public", text: "公有证据（未归类）" }));
    scopeSelect.append(el("option", { value: "classified", text: "归类到学生" }));

    const studentSelect = el("select", { name: "student_id", disabled: true });
    studentSelect.append(el("option", { value: "", text: "请选择学生" }));
    for (const student of Object.values(studentMap)) {
      studentSelect.append(el("option", { value: student.profile_id, text: student.name }));
    }

    const observationSelect = el("select", { name: "observation_key", disabled: true });
    observationSelect.append(el("option", { value: "", text: "请先选择学生" }));

    const sourceSelect = el("select", { name: "source_type" });
    const sourceHelp = el("p", { class: "meta", hidden: true });

    const mediaSelect = el("select", { name: "media_type" });
    for (const [value, text] of Object.entries(MEDIA_TYPE)) {
      mediaSelect.append(el("option", { value, text }));
    }

    const fileInput = el("input", { type: "file", name: "file" });
    const fileHint = el("p", { class: "meta", text: "支持文本、图像（PNG/JPG/SVG）与视频（MP4/WebM），单文件不超过 100MB。" });

    const titleInput = el("input", {
      type: "text",
      name: "title",
      placeholder: "留空则使用观测点或来源名称",
    });
    const contentInput = el("textarea", {
      name: "content",
      rows: 6,
      placeholder: "纯文本可直接在这里编写；图像/视频可填写描述或结构化事件。",
    });
    const valueInput = el("input", { type: "number", name: "value", step: "any" });
    const levelSelect = el("select", { name: "level" });
    levelSelect.append(el("option", { value: "", text: "不指定" }));
    const collectorInput = el("input", { type: "text", name: "collector", placeholder: "如：王老师" });
    const noteInput = el("input", { type: "text", name: "note" });

    let profileToken = 0;
    let observationIndex = {};

    /** 更新来源提示。 */
    function updateSourceHelp() {
      const source = sourceMap[sourceSelect.value];
      if (!source) {
        sourceHelp.hidden = true;
        sourceHelp.textContent = "";
        return;
      }
      const parts = [];
      if (source.modality) {
        parts.push(`形态：${label(EVIDENCE_MODALITY, source.modality)}`);
      }
      if (source.processed_by) {
        parts.push(`加工：${label(EVIDENCE_PROCESSED_BY, source.processed_by)}`);
      }
      if (source.cost) parts.push(`成本：${label(EVIDENCE_COST, source.cost)}`);
      if (source.requires_segmentation) parts.push("需先转为结构化事件");
      sourceHelp.textContent = parts.join(" · ");
      sourceHelp.hidden = parts.length === 0;
    }

    /** 填充分级。 */
    function fillLevels(observation) {
      clear(levelSelect);
      levelSelect.append(el("option", { value: "", text: "不指定" }));
      for (const level of (observation && observation.rubrics) || []) {
        levelSelect.append(
          el("option", {
            value: String(level.level),
            text: `${level.level} 级 · ${level.label}`,
          })
        );
      }
    }

    /** 重置来源下拉。 */
    function resetSources(text = "请先选择观测点") {
      clear(sourceSelect);
      sourceSelect.disabled = true;
      sourceSelect.append(el("option", { value: "", text }));
      sourceHelp.hidden = true;
      sourceHelp.textContent = "";
    }

    /** 填充可选来源（受观测点 evidence_sources 约束；公有证据可选全部来源）。 */
    function fillSources(observation, publicMode = false) {
      const allowed = (observation && observation.evidence_sources) || [];
      const entries = publicMode
        ? sourceEntries()
        : sourceEntries().filter(([key]) => allowed.length === 0 || allowed.includes(key));
      const previous = sourceSelect.value;
      clear(sourceSelect);
      sourceSelect.disabled = entries.length === 0;
      if (entries.length === 0) {
        sourceSelect.append(el("option", { value: "", text: "无可选来源" }));
        sourceHelp.hidden = true;
        sourceHelp.textContent = "";
        return;
      }
      for (const [key, text] of entries) {
        sourceSelect.append(el("option", { value: key, text }));
      }
      if (entries.some(([key]) => key === previous)) sourceSelect.value = previous;
      updateSourceHelp();
    }

    /** 切换观测点后，联动来源与评分等级。 */
    function onObservationChange() {
      const observation = observationIndex[observationSelect.value] || null;
      fillLevels(observation);
      if (!observation) {
        resetSources();
        return;
      }
      fillSources(observation);
    }

    /** 切换学生后，加载该学生的观测点。 */
    async function onStudentChange() {
      const token = ++profileToken;
      observationIndex = {};
      clear(observationSelect);
      observationSelect.disabled = true;
      observationSelect.append(el("option", { value: "", text: "正在加载…" }));
      fillLevels(null);
      resetSources();

      const studentId = studentSelect.value;
      if (!studentId) {
        clear(observationSelect);
        observationSelect.append(el("option", { value: "", text: "请先选择学生" }));
        return;
      }

      try {
        const profile = await api.getStudent(studentId);
        if (token !== profileToken) return;
        const observations = [];
        for (const indicator of profile.framework.indicators || []) {
          for (const observation of indicator.observations || []) {
            observations.push({ ...observation, indicatorName: indicator.name });
            observationNames[observation.key] = observation.name;
          }
        }
        clear(observationSelect);
        if (observations.length === 0) {
          observationSelect.append(el("option", { value: "", text: "该学生暂无观测点" }));
          return;
        }
        observationSelect.disabled = false;
        observationSelect.append(el("option", { value: "", text: "请选择观测点" }));
        for (const observation of observations) {
          observationIndex[observation.key] = observation;
          observationSelect.append(
            el("option", {
              value: observation.key,
              text: `${observation.indicatorName} / ${observation.name}`,
            })
          );
        }
      } catch (err) {
        if (token !== profileToken) return;
        clear(observationSelect);
        observationSelect.append(el("option", { value: "", text: "加载失败" }));
        toastError(err.message);
      }
    }

    /** 切换归属：公有证据无需学生与观测点。 */
    function updateScopeState() {
      const publicMode = scopeSelect.value === "public";
      studentSelect.disabled = publicMode;
      if (publicMode) {
        clear(observationSelect);
        observationSelect.disabled = true;
        observationSelect.append(el("option", { value: "", text: "公有证据无需选择观测点" }));
        fillLevels(null);
        fillSources(null, true);
        return;
      }
      if (studentSelect.value) {
        onStudentChange();
      } else {
        clear(observationSelect);
        observationSelect.disabled = true;
        observationSelect.append(el("option", { value: "", text: "请先选择学生" }));
        fillLevels(null);
        resetSources();
      }
    }

    /** 切换媒体类型：更新文件选择器接受类型。 */
    function updateMediaState() {
      const media = mediaSelect.value;
      fileInput.accept = FILE_ACCEPT[media] || "";
      if (media === "text") {
        fileHint.textContent =
          "纯文本可直接在上方内容框现场编写，无需上传文件；也可上传 .txt/.md 文件。";
      } else if (media === "image") {
        fileHint.textContent = "请选择图像文件（PNG/JPG/GIF/WebP/SVG），单文件不超过 100MB。";
      } else {
        fileHint.textContent = "请选择视频文件（MP4/WebM/OGG/MOV），单文件不超过 100MB。";
      }
    }

    /** 选择文件后自动识别媒体类型。 */
    async function onFileChange() {
      const file = fileInput.files && fileInput.files[0];
      if (!file) return;
      const guessed = inferMediaType(file);
      if (guessed && guessed !== mediaSelect.value) {
        mediaSelect.value = guessed;
        updateMediaState();
      }
      fileHint.textContent = `${file.name} · ${formatSize(file.size)}`;
      if (guessed === "text" && !contentInput.value.trim()) {
        try {
          const text = await file.text();
          contentInput.value = text.slice(0, 20000);
        } catch (err) {
          // 读取失败时保留手动输入
        }
      }
    }

    scopeSelect.addEventListener("change", updateScopeState);
    studentSelect.addEventListener("change", onStudentChange);
    observationSelect.addEventListener("change", onObservationChange);
    sourceSelect.addEventListener("change", updateSourceHelp);
    mediaSelect.addEventListener("change", updateMediaState);
    fileInput.addEventListener("change", onFileChange);

    const form = el("form", { class: "create-form" }, [
      panel("证据归属", [
        field("归属类型", scopeSelect),
        field("学生", studentSelect),
        field("观测点", observationSelect),
        field("证据来源", sourceSelect),
        sourceHelp,
      ]),
      panel("媒体与内容", [
        field("媒体类型", mediaSelect),
        field("内容 / 结构化描述", contentInput),
        field("上传文件（文本可选，图像/视频必选）", fileInput),
        fileHint,
        field("标题", titleInput),
        el("div", { class: "field-row" }, [
          field("量化值", valueInput),
          field("等级", levelSelect),
        ]),
        field("采集人", collectorInput),
        field("备注", noteInput),
      ]),
      el("div", { class: "form-actions" }, [
        el("button", { class: "btn btn-primary", type: "submit", text: "保存为草稿" }),
      ]),
    ]);

    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const scope = scopeSelect.value;
      const studentId = scope === "classified" ? studentSelect.value : "";
      const observationKey = scope === "classified" ? observationSelect.value : "";
      const sourceType = sourceSelect.value;
      if (scope === "classified" && !studentId) {
        toastError("请选择学生");
        return;
      }
      if (scope === "classified" && !observationKey) {
        toastError("请选择观测点");
        return;
      }
      if (!sourceType) {
        toastError("请选择证据来源");
        return;
      }

      let mediaType = mediaSelect.value;
      let content = contentInput.value.trim();
      const attachments = [];
      const file = fileInput.files && fileInput.files[0];
      if (file) {
        try {
          const uploaded = await api.uploadEvidenceFile(file);
          attachments.push(uploaded.url);
          mediaType = uploaded.media_type || mediaType;
          if (mediaType === "text" && !content) {
            content = (await file.text()).slice(0, 20000);
          }
        } catch (err) {
          toastError(err.message);
          return;
        }
      }
      if (mediaType === "text" && !content && attachments.length === 0) {
        toastError("请填写文本内容或上传文本文件");
        return;
      }
      if ((mediaType === "image" || mediaType === "video") && attachments.length === 0) {
        toastError("请选择图像/视频文件");
        return;
      }

      const body = {
        scope,
        source_type: sourceType,
        media_type: mediaType,
        title: titleInput.value.trim(),
        content,
        attachments,
        collector: collectorInput.value.trim(),
        note: noteInput.value.trim(),
      };
      if (scope === "classified") {
        body.student_id = studentId;
        body.observation_key = observationKey;
      }
      const valueText = valueInput.value.trim();
      if (valueText !== "") {
        const value = Number(valueText);
        if (Number.isNaN(value)) {
          toastError("量化值必须是数字");
          return;
        }
        body.value = value;
      }
      if (levelSelect.value) body.level = Number(levelSelect.value);

      try {
        const record = await api.createEvidence(body);
        toastSuccess(`已新增证据：${record.evidence_id}`);
        activeId = record.evidence_id;
        if (onDone) onDone();
        refresh();
      } catch (err) {
        toastError(err.message);
      }
    });

    updateScopeState();
    updateMediaState();
    return form;
  }

  /** 归类弹窗：把公有证据划分到学生与观测点。 */
  async function openClassifyModal(item) {
    if (Object.keys(studentMap).length === 0) await loadStudents();
    if (Object.keys(studentMap).length === 0) {
      toastError("暂无学生档案，请先建档");
      return;
    }
    openModal("归类证据", (close) => {
      const studentSelect = el("select", { name: "student_id" });
      studentSelect.append(el("option", { value: "", text: "请选择学生" }));
      for (const student of Object.values(studentMap)) {
        studentSelect.append(el("option", { value: student.profile_id, text: student.name }));
      }

      const observationSelect = el("select", { name: "observation_key", disabled: true });
      observationSelect.append(el("option", { value: "", text: "请先选择学生" }));

      const sourceSelect = el("select", { name: "source_type", disabled: true });
      sourceSelect.append(el("option", { value: "", text: "请先选择观测点" }));

      const titleInput = el("input", {
        type: "text",
        name: "title",
        value: item.title || "",
        placeholder: "留空则使用观测点名称",
      });

      let profileToken = 0;
      let observationIndex = {};

      function fillSources(observation) {
        const allowed = (observation && observation.evidence_sources) || [];
        const entries = sourceEntries().filter(
          ([key]) => allowed.length === 0 || allowed.includes(key)
        );
        clear(sourceSelect);
        sourceSelect.disabled = entries.length === 0;
        if (entries.length === 0) {
          sourceSelect.append(el("option", { value: "", text: "无可选来源" }));
          return;
        }
        for (const [key, text] of entries) {
          sourceSelect.append(el("option", { value: key, text }));
        }
        const preferred = entries.find(([key]) => key === item.source_type);
        sourceSelect.value = preferred ? preferred[0] : entries[0][0];
      }

      async function onStudentChange() {
        const token = ++profileToken;
        observationIndex = {};
        clear(observationSelect);
        observationSelect.disabled = true;
        observationSelect.append(el("option", { value: "", text: "正在加载…" }));
        clear(sourceSelect);
        sourceSelect.disabled = true;
        sourceSelect.append(el("option", { value: "", text: "请先选择观测点" }));
        const studentId = studentSelect.value;
        if (!studentId) {
          clear(observationSelect);
          observationSelect.append(el("option", { value: "", text: "请先选择学生" }));
          return;
        }
        try {
          const profile = await api.getStudent(studentId);
          if (token !== profileToken) return;
          const observations = [];
          for (const indicator of profile.framework.indicators || []) {
            for (const observation of indicator.observations || []) {
              observations.push({ ...observation, indicatorName: indicator.name });
              observationNames[observation.key] = observation.name;
            }
          }
          clear(observationSelect);
          if (observations.length === 0) {
            observationSelect.append(el("option", { value: "", text: "该学生暂无观测点" }));
            return;
          }
          observationSelect.disabled = false;
          observationSelect.append(el("option", { value: "", text: "请选择观测点" }));
          for (const observation of observations) {
            observationIndex[observation.key] = observation;
            observationSelect.append(
              el("option", {
                value: observation.key,
                text: `${observation.indicatorName} / ${observation.name}`,
              })
            );
          }
        } catch (err) {
          if (token !== profileToken) return;
          clear(observationSelect);
          observationSelect.append(el("option", { value: "", text: "加载失败" }));
          toastError(err.message);
        }
      }

      function onObservationChange() {
        const observation = observationIndex[observationSelect.value] || null;
        if (!observation) {
          clear(sourceSelect);
          sourceSelect.disabled = true;
          sourceSelect.append(el("option", { value: "", text: "请先选择观测点" }));
          return;
        }
        fillSources(observation);
      }

      studentSelect.addEventListener("change", onStudentChange);
      observationSelect.addEventListener("change", onObservationChange);

      const form = el("form", { class: "create-form" }, [
        panel("归类目标", [
          el("p", {
            class: "meta",
            text: `当前证据：${item.title || item.evidence_id}（${label(MEDIA_TYPE, mediaTypeOf(item))}）`,
          }),
          field("学生", studentSelect),
          field("观测点", observationSelect),
          field("证据来源", sourceSelect),
          field("标题", titleInput),
        ]),
        el("div", { class: "form-actions" }, [
          el("button", { class: "btn btn-primary", type: "submit", text: "确认归类" }),
        ]),
      ]);

      form.addEventListener("submit", async (event) => {
        event.preventDefault();
        if (!studentSelect.value) {
          toastError("请选择学生");
          return;
        }
        if (!observationSelect.value) {
          toastError("请选择观测点");
          return;
        }
        if (!sourceSelect.value) {
          toastError("请选择证据来源");
          return;
        }
        try {
          await api.classifyEvidence(item.evidence_id, {
            student_id: studentSelect.value,
            observation_key: observationSelect.value,
            source_type: sourceSelect.value,
            title: titleInput.value.trim() || undefined,
          });
          toastSuccess("已归类到学生");
          activeId = item.evidence_id;
          close();
          refresh();
        } catch (err) {
          toastError(err.message);
        }
      });

      return form;
    });
  }

  build();

  return {
    /** 首次进入：加载学生与来源元数据，拉取列表并默认展示第一条。 */
    async init() {
      await loadStudents();
      await loadSources();
      await refresh(true);
    },
    refresh() {
      refresh();
    },
  };
}
