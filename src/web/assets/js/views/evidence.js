/**
 * views/evidence.js —— 证据管理视图（左右分栏：左证据列表，右详情）
 * 支持按学生/来源/状态筛选、新建证据草稿，并通过/拒绝完成审核。
 * 与资源库一致：列表选中后右侧滑出详情，空态与加载态统一。
 */

import { api } from "../core/api.js";
import { el, clear, placeholder, panel } from "../core/dom.js";
import {
  EVIDENCE_STATUS,
  EVIDENCE_STATUS_CLASS,
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

/**
 * 创建证据管理视图。
 * @param {HTMLElement} root 视图容器
 * @param {Object} hooks 跨视图回调：onShowStudent
 */
export function createView(root, hooks = {}) {
  let studentFilter;
  let sourceFilter;
  let statusFilter;
  let summaryBox;
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
    sourceFilter = filterSelect("source_type", []);
    statusFilter = filterSelect("status", Object.entries(EVIDENCE_STATUS));
    summaryBox = el("div", { class: "badge-row" }, [badge("共 0 条")]);
    listBox = el("div", { class: "student-list" });
    detailBox = el("div", { class: "student-detail", hidden: true });
    layout = el("div", { class: "student-layout" }, [listBox, detailBox]);

    const toolbar = el("div", { class: "toolbar" }, [
      el("div", { class: "field" }, [el("label", { text: "学生" }), studentFilter]),
      el("div", { class: "field" }, [el("label", { text: "来源" }), sourceFilter]),
      el("div", { class: "field" }, [el("label", { text: "状态" }), statusFilter]),
      el("div", { class: "spacer" }),
      summaryBox,
      el("button", { class: "btn", type: "button", text: "刷新", on: { click: refresh } }),
      el("button", {
        class: "btn btn-primary",
        type: "button",
        text: "＋ 新增证据",
        on: { click: openCreateModal },
      }),
    ]);

    // 选择即筛选
    studentFilter.addEventListener("change", refresh);
    sourceFilter.addEventListener("change", refresh);
    statusFilter.addEventListener("change", refresh);

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

  /** 汇总计数。 */
  async function loadSummary() {
    try {
      const data = await api.evidenceSummary({ student_id: studentFilter.value });
      const by = data.by_status || {};
      clear(summaryBox);
      summaryBox.append(
        badge(`共 ${data.total || 0} 条`),
        badge(`待审核 ${by.draft || 0}`, "badge-warning"),
        badge(`已通过 ${by.verified || 0}`, "badge-success"),
        badge(`已拒绝 ${by.rejected || 0}`, "badge-danger")
      );
    } catch (err) {
      clear(summaryBox);
      summaryBox.append(badge("统计不可用"));
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
      const [data] = await Promise.all([
        api.listEvidence({
          student_id: studentFilter.value,
          source_type: sourceFilter.value,
          status: statusFilter.value,
          size: 100,
        }),
        loadSummary(),
      ]);
      clear(listBox);
      if (data.items.length === 0) {
        listBox.append(placeholder("暂无证据，点击右上角新增。"));
        return;
      }
      data.items.forEach((item, index) => listBox.append(evidenceCard(item, index)));
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

  /** 单条证据卡片。 */
  function evidenceCard(item, index) {
    const status = item.status || "draft";
    const student = studentMap[item.student_id];
    const studentName = student ? student.name : item.student_id;
    const obsName = observationName(item.observation_key);
    const sourceName = evidenceLabel(item.source_type);
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
        el("span", { class: "avatar", text: (sourceName || "?").slice(0, 1) }),
        el("span", { class: "student-card-body" }, [
          el("h4", { text: item.title || obsName }),
          el("div", { class: "badge-row" }, [
            el("span", { class: "badge badge-info", text: studentName }),
            el("span", { class: "badge badge-muted", text: obsName }),
            badge(
              label(EVIDENCE_STATUS, status),
              EVIDENCE_STATUS_CLASS[status] || "badge-muted"
            ),
          ]),
        ]),
      ]
    );
  }

  /** 组装证据详情。 */
  function buildDetail(item) {
    const status = item.status || "draft";
    const student = studentMap[item.student_id];
    const studentName = student ? student.name : item.student_id;
    const obsName = observationName(item.observation_key);
    const sourceName = evidenceLabel(item.source_type);
    const source = sourceMap[item.source_type] || null;

    const actions = [];
    if (item.student_id && hooks.onShowStudent) {
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
        el("span", { class: "avatar avatar-lg", text: (sourceName || "?").slice(0, 1) }),
        el("h3", { text: item.title || obsName }),
      ]),
      el("div", { class: "detail-actions" }, actions),
    ]);

    const info = el("div", { class: "badge-row" }, [
      badge(`ID：${item.evidence_id}`),
      badge(`学生：${studentName}`, "badge-info"),
      badge(`观测点：${obsName}`),
      badge(`来源：${sourceName}`),
      badge(
        `状态：${label(EVIDENCE_STATUS, status)}`,
        EVIDENCE_STATUS_CLASS[status] || "badge-muted"
      ),
      badge(`采集：${formatTime(item.collected_at)}`),
    ]);
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

    const contentBody = [
      item.content
        ? el("pre", { class: "output", text: item.content })
        : placeholder("暂无内容"),
    ];
    if (item.note) {
      contentBody.push(el("p", { class: "meta", text: `备注/审核意见：${item.note}` }));
    }
    if (Array.isArray(item.attachments) && item.attachments.length) {
      contentBody.push(
        el(
          "div",
          { class: "badge-row" },
          item.attachments.map((name) => badge(String(name)))
        )
      );
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
    return [
      {
        label: "查看详情",
        onSelect: () =>
          showDetail(
            item.evidence_id,
            listBox.querySelector(`[data-evidence-id="${item.evidence_id}"]`)
          ),
      },
      {
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

  /** 新建证据弹窗。 */
  async function openCreateModal() {
    if (Object.keys(studentMap).length === 0) await loadStudents();
    if (Object.keys(studentMap).length === 0) {
      toastError("暂无学生档案，请先建档");
      return;
    }
    if (Object.keys(sourceMap).length === 0) await loadSources();

    const overlay = el("div", {
      class: "modal-overlay",
      role: "dialog",
      "aria-modal": "true",
      "aria-label": "新增证据",
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

    const form = buildCreateForm(close);
    dialog.append(
      el("div", { class: "modal-head" }, [
        el("h3", { text: "新增证据" }),
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
    const firstSelect = form.querySelector("select");
    if (firstSelect) firstSelect.focus();
  }

  /** 构建新增证据表单。 */
  function buildCreateForm(onDone) {
    const studentSelect = el("select", { name: "student_id" });
    studentSelect.append(el("option", { value: "", text: "请选择学生" }));
    for (const student of Object.values(studentMap)) {
      studentSelect.append(el("option", { value: student.profile_id, text: student.name }));
    }

    const observationSelect = el("select", { name: "observation_key", disabled: true });
    observationSelect.append(el("option", { value: "", text: "请先选择学生" }));

    const sourceSelect = el("select", { name: "source_type", disabled: true });
    sourceSelect.append(el("option", { value: "", text: "请先选择观测点" }));
    const sourceHelp = el("p", { class: "meta", hidden: true });

    const titleInput = el("input", {
      type: "text",
      name: "title",
      placeholder: "留空则使用观测点名称",
    });
    const contentInput = el("textarea", { name: "content", rows: 5 });
    const valueInput = el("input", { type: "number", name: "value", step: "any" });
    const levelSelect = el("select", { name: "level" });
    levelSelect.append(el("option", { value: "", text: "不指定" }));
    const collectorInput = el("input", { type: "text", name: "collector" });
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

    /** 填充评分等级。 */
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

    /** 填充可选来源（受观测点 evidence_sources 约束）。 */
    function fillSources(observation) {
      const allowed = (observation && observation.evidence_sources) || [];
      const entries = sourceEntries().filter(
        ([key]) => allowed.length === 0 || allowed.includes(key)
      );
      clear(sourceSelect);
      if (entries.length === 0) {
        sourceSelect.append(el("option", { value: "", text: "无可选来源" }));
        sourceSelect.disabled = true;
        updateSourceHelp();
        return;
      }
      sourceSelect.disabled = false;
      for (const [key, text] of entries) {
        sourceSelect.append(el("option", { value: key, text }));
      }
      updateSourceHelp();
    }

    /** 切换观测点后，联动来源与评分等级。 */
    function onObservationChange() {
      const observation = observationIndex[observationSelect.value] || null;
      fillLevels(observation);
      if (!observation) {
        clear(sourceSelect);
        sourceSelect.disabled = true;
        sourceSelect.append(el("option", { value: "", text: "请先选择观测点" }));
        sourceHelp.hidden = true;
        sourceHelp.textContent = "";
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
      clear(levelSelect);
      levelSelect.append(el("option", { value: "", text: "不指定" }));
      clear(sourceSelect);
      sourceSelect.disabled = true;
      sourceSelect.append(el("option", { value: "", text: "请先选择观测点" }));
      sourceHelp.hidden = true;

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

    studentSelect.addEventListener("change", onStudentChange);
    observationSelect.addEventListener("change", onObservationChange);
    sourceSelect.addEventListener("change", updateSourceHelp);

    const form = el("form", { class: "create-form" }, [
      panel("证据归属", [
        field("学生", studentSelect),
        field("观测点", observationSelect),
        field("证据来源", sourceSelect),
        sourceHelp,
      ]),
      panel("证据内容", [
        field("标题", titleInput),
        field("内容", contentInput),
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
      const studentId = studentSelect.value;
      const observationKey = observationSelect.value;
      const sourceType = sourceSelect.value;
      if (!studentId) {
        toastError("请选择学生");
        return;
      }
      if (!observationKey) {
        toastError("请选择观测点");
        return;
      }
      if (!sourceType) {
        toastError("请选择证据来源");
        return;
      }

      const body = {
        student_id: studentId,
        observation_key: observationKey,
        source_type: sourceType,
        title: titleInput.value.trim(),
        content: contentInput.value.trim(),
        collector: collectorInput.value.trim(),
        note: noteInput.value.trim(),
      };
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

    return form;
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
