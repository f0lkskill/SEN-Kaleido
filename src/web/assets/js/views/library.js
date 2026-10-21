/**
 * views/library.js —— 资源库视图（左右分栏：左资源单，右详情）
 * 左侧按条件筛选并列出资源，选中后右侧展示完整正文（Markdown 渲染）、
 * 元信息标签与生成模板信息。
 */

import { api } from "../core/api.js";
import {
  el,
  clear,
  placeholder,
  panel,
  enhanceDisclosure,
  revealDetail,
} from "../core/dom.js";
import { renderMarkdown } from "../core/markdown.js";
import { confirmDialog } from "../core/dialog.js";
import { openContextMenu } from "../core/contextmenu.js";
import {
  DISABILITY,
  SEVERITY,
  COGNITIVE_LEVEL,
  RESOURCE_STATUS,
  RESOURCE_STATUS_CLASS,
  FACET_VERDICT,
  FACET_VERDICT_CLASS,
  label,
  labels,
  formatTime,
} from "../core/format.js";
import { toastSuccess, toastError } from "../core/toast.js";
import { pinTask } from "../core/taskpin.js";
import { faIcon, resourceIcon, STUDENT_ICON } from "../core/icons.js";
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
  let studentMap = new Map(); // 学生档案缓存
  let closeTimer = null;
  let activeId = null; // 当前选中的资源 ID
  let detailRequest = 0; // 详情请求序号，丢弃过期响应
  let evaluating = false; // 质量校验进行中，避免重复提交

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
      detailBox.style.minHeight = "";
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
        el("span", { class: "plain-icon" }, [faIcon(resourceIcon(item.resource_type))]),
        el("span", { class: "student-card-body" }, [
          el("h4", { text: item.topic }),
          el("div", { class: "badge-row" }, [
            el("span", { class: "badge badge-info", text: typeName }),
            // el("span", { class: "badge badge-muted", text: label(DISABILITY, item.disability) }),
            el("span", {
              class: `badge ${RESOURCE_STATUS_CLASS[item.status] || "badge-muted"}`,
              text: label(RESOURCE_STATUS, item.status),
            }),
            // item.facet
            //   ? el("span", {
            //       class: `badge ${FACET_VERDICT_CLASS[item.facet.verdict] || "badge-muted"}`
            //       // text: `质量：${label(FACET_VERDICT, item.facet.verdict)}`,
            //     })
            //   : null,
          ]),
        ]),
      ]
    );
  }

  /** 来源学生信息板；点击跳转到学生档案。 */
  function renderSourceStudent(item, student) {
    if (!item.profile_id) return null;
    const attributes = (student && student.attributes) || item.attributes || {};
    const name = (student && student.name) || item.profile_id;
    const disabilities = Array.isArray(attributes.disabilities)
      ? attributes.disabilities
      : attributes.disabilities
        ? [attributes.disabilities]
        : [];
    const firstDisability = disabilities[0];
    const extraDisabilities = disabilities.length - 1;
    const detailText = [
      firstDisability
        ? labels(DISABILITY, disabilities)
        : "",
      attributes.severity ? label(SEVERITY, attributes.severity) : "",
      attributes.cognitive_level
        ? `认知：${label(COGNITIVE_LEVEL, attributes.cognitive_level)}`
        : "",
    ]
      .filter(Boolean)
      .join(" · ");
    return el(
      "button",
      {
        class: "student-card detail-source-student",
        type: "button",
        title: detailText ? `${name} · ${detailText}` : "查看学生档案",
        "aria-label": `查看来源学生 ${name}`,
        on: {
          click: () => {
            if (hooks.onShowStudent) hooks.onShowStudent(item.profile_id);
          },
        },
      },
      [
        el("span", { class: "avatar" }, [faIcon(STUDENT_ICON)]),
        el("span", { class: "student-card-body" }, [
          el("h4", { text: name }),
          el("div", { class: "badge-row" }, [
            firstDisability
              ? el("span", {
                  class: "badge badge-info",
                  text:
                    extraDisabilities > 0
                      ? `${label(DISABILITY, firstDisability)} +${extraDisabilities}`
                      : label(DISABILITY, firstDisability),
                })
              : null,
            attributes.severity
              ? el("span", {
                  class: "badge badge-muted",
                  text: label(SEVERITY, attributes.severity),
                })
              : null,
            attributes.cognitive_level
              ? el("span", {
                  class: "badge badge-muted",
                  text: label(COGNITIVE_LEVEL, attributes.cognitive_level),
                })
              : null,
          ]),
        ]),
      ]
    );
  }

  /** 组装资源详情（标题为资源类型，Markdown 正文 + 元信息标签）。 */
  function renderDetail(item, student) {
    const typeName = typeMap[item.resource_type] || item.resource_type;
    const md = el("div", { class: "md" });
    md.innerHTML = renderMarkdown(item.content || "");

    const actions = [];
    // 有来源学生时提供修订入口；预生成（临时属性）则无此按钮
    if (item.profile_id) {
      actions.push(
        el("button", {
          class: "btn btn-sm",
          type: "button",
          text: "修订生成",
          on: {
            click: () => {
              if (hooks.onReviseResource) hooks.onReviseResource(item);
            },
          },
        })
      );
    }
    actions.push(
      el("button", {
        class: "btn btn-sm",
        type: "button",
        text: item.facet ? "重新校验" : "质量校验",
        on: { click: (event) => evaluateResource(item, event.currentTarget) },
      }),
      el("button", {
        class: "btn btn-success btn-sm",
        type: "button",
        text: "通过",
        on: { click: () => setStatus(item.resource_id, "approved") },
      }),
      el("button", {
        class: "btn btn-danger btn-sm",
        type: "button",
        text: "退回",
        on: { click: () => setStatus(item.resource_id, "rejected") },
      }),
      el("button", {
        class: "btn btn-danger btn-sm",
        type: "button",
        text: "删除",
        on: { click: () => removeResource(item) },
      })
    );

    const sourceStudent = renderSourceStudent(item, student);
    const head = el("div", { class: "detail-head detail-head-source" }, [
      el("div", { class: "detail-id" }, [
        el("span", { class: "plain-icon plain-icon-lg" }, [
          faIcon(resourceIcon(item.resource_type)),
        ]),
        el("h3", { class: "detail-title", text: typeName, title: typeName }),
      ]),
      sourceStudent
        ? el("div", { class: "detail-source-link", "aria-hidden": "true" }, [
            el("span", { class: "detail-source-pulse" }),
          ])
        : null,
      sourceStudent,
    ]);
    const actionBar = el("div", { class: "detail-actions quick-actions-content" }, actions);
    const actionsToggle = el("button", {
      class: "panel-title quick-actions-toggle",
      type: "button",
      "aria-expanded": "true",
      text: "快捷操作",
    });
    const actionsPanel = el("section", { class: "panel quick-actions-panel" }, [
      el("div", { class: "quick-actions-head" }, [actionsToggle, actionBar]),
    ]);
    actionsToggle.addEventListener("click", () => {
      const collapsed = actionsPanel.classList.toggle("is-collapsed");
      actionsToggle.setAttribute("aria-expanded", String(!collapsed));
      actionBar.inert = collapsed;
      actionBar.setAttribute("aria-hidden", String(collapsed));
    });

    const panels = [
      panel(null, head),
      actionsPanel,
      panel(
        "资源信息",
        el("div", { class: "badge-row" }, [
          el("span", { class: "badge badge-muted", text: `主题：${item.topic}` }),
          el("span", { class: "badge badge-muted", text: `ID：${item.resource_id}` }),
          el("span", { class: "badge badge-muted", text: `模型：${item.model || "-"}` }),
          el("span", { class: "badge badge-muted", text: label(DISABILITY, item.disability) }),
          el("span", {
            class: `badge ${RESOURCE_STATUS_CLASS[item.status] || "badge-muted"}`,
            text: label(RESOURCE_STATUS, item.status),
          }),
          el("span", { class: "badge badge-muted", text: formatTime(item.updated_at) }),
        ])
      ),
    ];
    panels.push(panel("质量校验", renderFacet(item), { className: "facet-panel" }));
    // 预生成资源（未建档）直接展示临时属性
    if (!item.profile_id && item.attributes) {
      panels.push(panel("临时属性（未建档）", renderAttributes(item.attributes)));
    }
    // 正文默认收起，点击标题展开，避免长文淹没其他信息
    panels.push(
      enhanceDisclosure(
        el("details", { class: "panel content-disclosure" }, [
          el("summary", { class: "panel-title", text: "内容" }),
          el("div", { class: "detail-md" }, [md]),
        ])
      )
    );
    return el("section", { class: "detail-body" }, panels);
  }

  /** 质量校验结论的列表块。 */
  function facetList(title, values) {
    if (!Array.isArray(values) || values.length === 0) return null;
    return el("div", { class: "facet-block" }, [
      el("h4", { class: "facet-subtitle", text: title }),
      el("ul", { class: "facet-list" }, values.map((value) => el("li", { text: value }))),
    ]);
  }

  /** 分数递增载入动画；onFrame 用于同步环形进度。 */
  function animateScore(node, target, onFrame = null) {
    const value = Math.max(0, Math.min(100, Math.round(Number(target) || 0)));
    const render = (current) => {
      node.textContent = String(Math.round(current));
      if (onFrame) onFrame(current);
    };
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      render(value);
      return;
    }
    const duration = 760;
    const start = performance.now();
    const tick = (now) => {
      if (!node.isConnected) return;
      const progress = Math.min(1, (now - start) / duration);
      const eased = 1 - Math.pow(1 - progress, 3);
      render(value * eased);
      if (progress < 1) requestAnimationFrame(tick);
    };
    render(0);
    requestAnimationFrame(tick);
  }

  /** 组装质量报告。 */
  function renderFacet(item) {
    const report = item.facet;
    if (!report) {
      return placeholder("质量校验尚未生成。", "empty");
    }

    const verdict = report.verdict || "review";
    const score = Number(report.score) || 0;
    const scoreNode = el("strong", { text: "0" });
    const head = el("div", { class: "facet-head" }, [
      el("div", { class: "facet-score" }, [
        scoreNode,
        el("span", { text: "/100" }),
      ]),
      el("div", { class: "badge-row" }, [
        el("span", {
          class: `badge ${FACET_VERDICT_CLASS[verdict] || "badge-muted"}`,
          text: label(FACET_VERDICT, verdict)
        }),
        el("span", { class: "badge badge-muted", text: `规则分 ${report.rule_score ?? "-"}` }),
        report.blocking
          ? el("span", { class: "badge badge-danger", text: "存在硬性错误" })
          : null,
        el("span", { class: "badge badge-muted", text: formatTime(report.evaluated_at) }),
      ]),
    ]);
    animateScore(scoreNode, score);

    const dimensions = el(
      "div",
      { class: "facet-dimensions" },
      (report.dimensions || []).map((dimension) => {
        const hasScore = dimension.score !== null && dimension.score !== undefined;
        const value = hasScore
          ? Math.max(0, Math.min(100, Number(dimension.score)))
          : 0;
        const weight = Math.round(Number(dimension.weight || 0) * 100);
        const level = !hasScore
          ? "none"
          : value >= 80
            ? "good"
            : value >= 60
              ? "ok"
              : value >= 40
                ? "warn"
                : "bad";
        const scoreNode = el("strong", { text: hasScore ? "0" : "—" });
        const orb = el(
          "div",
          {
            class: `facet-orb facet-orb-${level}`,
            style: `--value:${hasScore ? 0 : value}`,
            role: "img",
            "aria-label": `${dimension.name}（权重 ${weight}%）：${
              hasScore ? `${Math.round(value)} 分` : "未评分"
            }`,
          },
          [
            el("div", { class: "facet-orb-core" }, [
              scoreNode,
              el("span", { text: hasScore ? "分" : "未评分" }),
            ]),
          ]
        );
        if (hasScore) {
          animateScore(scoreNode, value, (current) => {
            orb.style.setProperty("--value", current);
          });
        }
        return el("div", { class: "facet-dim" }, [
          orb,
          el("div", { class: "facet-dim-name", text: dimension.name }),
          el("div", { class: "facet-dim-weight", text: `权重 ${weight}%` }),
        ]);
      })
    );

    const blocks = [];
    if (dimensions.childElementCount) {
      blocks.push(dimensions);
    }
    if (report.summary) {
      blocks.push(
        el("div", { class: "facet-block" }, [
          el("h4", { class: "facet-subtitle", text: "资源总评" }),
          el("p", { class: "facet-summary", text: report.summary }),
        ])
      );
    }
    blocks.push(facetList("优势表现", report.strengths));
    blocks.push(facetList("模型发现问题", report.issues));

    const ruleIssues = (report.rules && report.rules.issues) || [];
    if (ruleIssues.length) {
      blocks.push(
        el("div", { class: "facet-block" }, [
          el("h4", { class: "facet-subtitle", text: "规则检查" }),
          el(
            "ul",
            { class: "facet-issues" },
            ruleIssues.map((issue) =>
              el("li", { class: `facet-issue ${issue.level || "warning"}` }, [
                el("strong", { text: issue.level === "error" ? "硬性错误" : "警告" }),
                ` ${issue.message}`,
                issue.suggestion
                  ? el("span", { class: "facet-suggestion", text: `建议：${issue.suggestion}` })
                  : null,
              ])
            )
          ),
        ])
      );
    }
    blocks.push(facetList("改进建议", report.suggestions));

    const common = Array.isArray(report.common_prompts) && report.common_prompts.length
      ? report.common_prompts
      : (report.prompts || []).map((text) => ({ disability: "", text }));
    if (common.length) {
      blocks.push(
        el("div", { class: "facet-block" }, [
          el("h4", { class: "facet-subtitle", text: "已沉淀的病症通用规则" }),
          el(
            "ul",
            { class: "facet-list" },
            common.map((item) =>
              el("li", {
                text: item.disability
                  ? `${label(DISABILITY, item.disability)}：${item.text}`
                  : item.text,
              })
            )
          ),
        ])
      );
    }
    if (
      Array.isArray(report.personal_prompts) &&
      report.personal_prompts.length
    ) {
      blocks.push(
        facetList("已写入学生画像的个性提示", report.personal_prompts)
      );
    }

    if (report.use_llm === false) {
      blocks.push(el("p", { class: "meta", text: "本次仅执行规则校验，未启用模型评分。" }));
    } else if (report.llm && report.llm.parsed === false) {
      blocks.push(
        el("p", { class: "meta", text: "模型返回未能解析，综合分已回退为规则分。" })
      );
    }
    return el("div", { class: "facet-report" }, [head, ...blocks.filter(Boolean)]);
  }

  /** 钉住面板中的质量校验摘要。 */
  function facetTaskSummary(task) {
    if (task.error) return `失败：${task.error}`;
    const result = task.result || {};
    if (result.verdict) {
      return `质量校验：${label(FACET_VERDICT, result.verdict)}${
        result.score === undefined ? "" : ` · ${result.score} 分`
      }`;
    }
    if (task.status === "running") return "正在校验资源质量…";
    return "等待质量校验结果…";
  }

  /** 触发质量校验并刷新详情（校验期间按钮转圈、面板显示等待）。 */
  async function evaluateResource(item, trigger = null) {
    if (evaluating) return;
    evaluating = true;

    const originalLabel = trigger ? trigger.textContent : "";
    if (trigger) {
      trigger.disabled = true;
      trigger.classList.add("is-busy");
      trigger.textContent = "";
      trigger.append(
        el("span", { class: "spinner", "aria-hidden": "true" }),
        el("span", { text: "校验中…" })
      );
    }

    // 校验期间销毁旧报告，只显示等待占位，避免旧数据误导
    const facetBody = detailBox.querySelector(".facet-panel .panel-body");
    const waiting = placeholder("正在校验，请稍候…", "loading");
    if (facetBody) {
      clear(facetBody);
      facetBody.append(waiting);
    }

    try {
      const pending = await api.evaluateResource(item.resource_id);
      if (pending && pending.task_id) {
        pinTask(pending, {
          summary: "正在校验资源质量…",
          summarize: facetTaskSummary,
          onOpen: hooks.onShowTask
            ? () => hooks.onShowTask(pending.task_id)
            : null,
        });
      }
      const report = await api.resolveTask(pending);
      toastSuccess(
        `质量校验完成：${label(FACET_VERDICT, report.verdict)}（${report.score} 分）`
      );
      await refresh();
    } catch (err) {
      toastError(err.message);
      // 失败时恢复原有报告
      await refresh();
    } finally {
      evaluating = false;
      if (waiting.isConnected) waiting.remove();
      if (trigger) {
        trigger.disabled = false;
        trigger.classList.remove("is-busy");
        trigger.textContent = originalLabel;
      }
    }
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
      {
        label: "修订生成",
        onSelect: () => {
          if (hooks.onReviseResource) hooks.onReviseResource(item);
        },
      },
      {
        label: item.facet ? "重新校验质量" : "质量校验",
        onSelect: () => evaluateResource(item),
      },
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
      toastSuccess(status === "approved" ? "通过" : "退回");
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
    const markActive = () => {
      if (!cardEl) return;
      for (const node of listBox.querySelectorAll(".student-card")) {
        node.classList.remove("active");
      }
      cardEl.classList.add("active");
    };
    // 重复点击当前资源时只更新选中态，避免详情反复重建造成闪烁
    if (activeId === resourceId && !detailBox.hidden && detailBox.querySelector(".detail-body")) {
      markActive();
      return;
    }

    const requestId = ++detailRequest;
    const scrollY = window.scrollY;
    const hadDetail = !!detailBox.querySelector(".detail-body");
    activeId = resourceId;
    detailBox.hidden = false;
    layout.classList.add("narrowed");
    // 切换资源时保留旧详情，等新内容就绪后再替换，避免高度塌陷和列表跳动
    if (!hadDetail) {
      clear(detailBox);
      detailBox.append(placeholder("正在加载…", "loading"));
    }
    markActive();
    try {
      const item = await api.getResource(resourceId);
      let student = item.profile_id ? studentMap.get(item.profile_id) : null;
      if (item.profile_id && !student) {
        student = await api.getStudent(item.profile_id).catch(() => null);
        if (student) studentMap.set(item.profile_id, student);
      }
      if (requestId !== detailRequest) return;
      clear(detailBox);
      detailBox.append(renderDetail(item, student));
    } catch (err) {
      if (requestId !== detailRequest) return;
      clear(detailBox);
      detailBox.append(placeholder(`加载失败：${err.message}`));
      toastError(err.message);
    } finally {
      if (requestId !== detailRequest) return;
      // 桌面端保持列表当前滚动位置；窄屏详情堆叠在下方时才滚动到详情
      if (window.matchMedia("(min-width: 900px)").matches) {
        window.scrollTo(0, scrollY);
      } else {
        revealDetail(detailBox);
      }
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
