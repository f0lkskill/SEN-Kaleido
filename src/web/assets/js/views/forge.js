/**
 * views/forge.js —— 资源生成视图
 * 选择已建档学生或使用临时属性，指定资源类型与主题，调用生成接口。
 */

import { api } from "../core/api.js";
import { el, clear, placeholder, enhanceDisclosure, panel } from "../core/dom.js";
import { label, labels, DISABILITY, SEVERITY, COGNITIVE_LEVEL } from "../core/format.js";
import { renderMarkdown } from "../core/markdown.js";
import { toastSuccess, toastError } from "../core/toast.js";
import { buildAttributesForm, readAttributes } from "./framework.js";

/**
 * 创建资源生成视图。
 * @param {HTMLElement} root 视图容器
 * @param {Object} [hooks] 钩子：onGenerated 生成成功后回调
 */
export function createView(root, hooks = {}) {
  let studentSelect;
  let resourceSelect;
  let topicInput;
  let extraInput;
  let tempForm;
  let tempWrapper;
  let output;
  let studentPanel;
  let promptBoardBox;
  let sourceBanner;
  let studentsCache = [];
  let pendingProfile = null;
  let pendingSource = null;
  let sourceResourceId = null;
  let selectedPromptIds = new Set();

  function build() {
    clear(root);
    studentSelect = el("select", { name: "profile_id" });
    resourceSelect = el("select", { name: "resource_type" });
    topicInput = el("input", {
      type: "text",
      name: "topic",
      placeholder: "请输入教学主题",
    });
    extraInput = el("textarea", { name: "extra" });
    tempForm = buildAttributesForm("forge");
    tempWrapper = el("div", { hidden: true });
    output = el("div");
    output.append(placeholder("生成结果将显示在此。"));
    studentPanel = el("div", { class: "selected-student", hidden: true });
    promptBoardBox = el("div", { class: "prompt-picker", hidden: true });
    sourceBanner = el("div", { class: "source-banner", hidden: true });

    studentSelect.addEventListener("change", () => {
      // 未选择学生时展示临时属性表单
      tempWrapper.hidden = studentSelect.value !== "";
      sourceResourceId = null;
      renderSourceBanner();
      renderSelectedStudent();
      loadPromptBoard();
    });

    // 左：信息表单；右：生成结果
    const infoCard = el("section", { class: "card" }, [
      panel("", [
        el("div", { class: "field" }, [
          el("label", { text: "选择学生" }),
          studentSelect,
        ]),
        studentPanel,
        promptBoardBox,
        tempWrapper,
      ]),
      panel("生成设置", [
        sourceBanner,
        el("div", { class: "field" }, [
          el("label", { text: "资源类型" }),
          resourceSelect,
        ]),
        el("div", { class: "field" }, [
          el("label", { text: "教学主题" }),
          topicInput,
        ]),
        el("div", { class: "field" }, [
          el("label", { text: "补充要求（可选）" }),
          extraInput,
        ]),
      ]),
      el("div", { class: "form-actions" }, [
        el("button", {
          class: "btn btn-primary",
          type: "button",
          text: "生成资源",
          on: { click: doGenerate },
        }),
      ]),
    ]);

    const resultCard = el("section", { class: "card" }, [output]);

    tempWrapper.append(tempForm);
    root.append(
      el("div", { class: "split split-narrow-left" }, [
        el("div", { class: "split-aside" }, [infoCard]),
        el("div", {}, [resultCard]),
      ])
    );
  }

  /** 加载下拉选项。 */
  async function loadOptions() {
    try {
      const [students, types] = await Promise.all([
        api.listStudents({ size: 200 }),
        api.resourceTypes(),
      ]);

      const previous = pendingProfile || studentSelect.value;
      clear(studentSelect);
      studentSelect.append(
        el("option", { value: "", text: "（使用临时档案）" })
      );
      for (const item of students.items) {
        studentSelect.append(
          el("option", { value: item.profile_id, text: item.name })
        );
      }

      clear(resourceSelect);
      for (const [value, text] of Object.entries(types)) {
        resourceSelect.append(el("option", { value, text }));
      }
      studentsCache = students.items;
      // 选项重建后 value 会被重置，这里恢复原选中/待预选的学生
      if (previous && selectStudent(previous)) pendingProfile = null;
      else renderSelectedStudent();
      applyPending();
    } catch (err) {
      toastError(`加载选项失败：${err.message}`);
    }
  }

  /** 渲染所选学生的信息板（复用档案列表卡片样式）。 */
  function renderSelectedStudent() {
    clear(studentPanel);
    const id = studentSelect.value;
    const item = studentsCache.find((student) => student.profile_id === id);
    if (!item) {
      studentPanel.hidden = true;
      return;
    }
    studentPanel.hidden = false;
    studentPanel.append(
      el("div", { class: "student-card" }, [
        el("span", { class: "avatar", text: (item.name || "?").slice(0, 1) }),
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
      ])
    );
  }

  /** 选中指定学生并刷新信息板；返回是否成功。 */
  function selectStudent(profileId) {
    const option = Array.from(studentSelect.options).find((o) => o.value === profileId);
    if (!option) return false;
    studentSelect.value = profileId;
    tempWrapper.hidden = true;
    renderSelectedStudent();
    loadPromptBoard();
    return true;
  }

  /** 应用待预选的学生与原资源。 */
  function applyPending() {
    if (pendingProfile && selectStudent(pendingProfile)) pendingProfile = null;
    if (pendingSource && resourceSelect.options.length) {
      applySource(pendingSource);
      pendingSource = null;
    }
  }

  /** 记录“基于原资源修订”的来源，并填充主题/类型。 */
  function applySource(source) {
    if (!source) return;
    sourceResourceId = source.resource_id || null;
    if (source.topic) topicInput.value = source.topic;
    if (source.resource_type) {
      const option = Array.from(resourceSelect.options).find(
        (item) => item.value === source.resource_type
      );
      if (option) resourceSelect.value = source.resource_type;
    }
    renderSourceBanner();
  }

  /** 展示/隐藏原资源修订提示。 */
  function renderSourceBanner() {
    clear(sourceBanner);
    if (!sourceResourceId) {
      sourceBanner.hidden = true;
      return;
    }
    sourceBanner.hidden = false;
    sourceBanner.append(
      el("span", { text: `基于原资源 ${sourceResourceId} 生成修订版` }),
      el("button", {
        class: "btn btn-sm",
        type: "button",
        text: "取消",
        on: {
          click: () => {
            sourceResourceId = null;
            renderSourceBanner();
          },
        },
      })
    );
  }

  /** 加载所选学生的规则板并渲染勾选项。 */
  async function loadPromptBoard() {
    selectedPromptIds = new Set();
    promptBoardBox.hidden = true;
    clear(promptBoardBox);
    const profileId = studentSelect.value;
    if (!profileId) return;
    try {
      const board = await api.getPromptBoard(profileId);
      // 学生切换过快时丢弃过期响应
      if (studentSelect.value !== profileId) return;
      if (!board.length) return;
      selectedPromptIds = new Set(
        board.filter((item) => item.enabled).map((item) => item.prompt_id)
      );
      promptBoardBox.hidden = false;
      const list = el("div", { class: "prompt-picker-list" });
      for (const item of board) {
        const checkbox = el("input", {
          type: "checkbox",
          checked: Boolean(item.enabled),
        });
        checkbox.addEventListener("change", () => {
          if (checkbox.checked) selectedPromptIds.add(item.prompt_id);
          else selectedPromptIds.delete(item.prompt_id);
        });
        // label 包裹复选框：点击整张卡片即可启用/关闭
        list.append(
          el("label", { class: "check prompt-picker-item" }, [
            checkbox,
            el("span", { text: item.text }),
          ])
        );
      }
      // 规则板默认收起，点击标题展开
      promptBoardBox.append(
        enhanceDisclosure(
          el("details", { class: "prompt-picker-collapse" }, [
            el("summary", { text: "选用画像规则板提示词" }),
            list,
            el("p", { class: "meta", text: "仅勾选的启用提示词会加入本次生成。" }),
          ])
        )
      );
    } catch (err) {
      toastError(`加载规则板失败：${err.message}`);
    }
  }

  /** 执行生成（流式：实时显示模型思考与正文增量）。 */
  async function doGenerate() {
    const topic = topicInput.value.trim();
    if (!topic) {
      toastError("请填写教学主题");
      return;
    }
    const payload = {
      resource_type: resourceSelect.value,
      topic,
      extra: extraInput.value.trim() ? { note: extraInput.value.trim() } : {},
    };
    if (studentSelect.value) {
      payload.profile_id = studentSelect.value;
      if (selectedPromptIds.size) {
        payload.prompt_ids = [...selectedPromptIds];
      }
      if (sourceResourceId) payload.source_resource_id = sourceResourceId;
    } else {
      payload.attributes = readAttributes(tempForm);
    }

    // 结果区：加载指示 + 思考过程（默认展开，出正文时自动收回） + 正文 + 元信息
    clear(output);
    const statusEl = el("div", { class: "gen-status" }, [
      el("span", { class: "spinner" }),
      el("span", { text: "模型思考中…" }),
    ]);
    const statusText = statusEl.querySelector("span:last-child");
    const reasoningPre = el("pre", { class: "output reasoning" });
    const reasoningBox = el("details", { class: "collapse", open: true, hidden: true }, [
      el("summary", {}, [el("span", { text: "模型思考过程" })]),
      el("div", { class: "collapse-body" }, [reasoningPre]),
    ]);
    const meta = el("div", { class: "badge-row" });
    const contentBox = el("div", { class: "md" });
    const contentScroll = el("div", { class: "gen-scroll" }, [contentBox]);
    const promptBox = el("div");
    output.append(statusEl, reasoningBox, meta, contentScroll, promptBox);

    const button = root.querySelector(".btn-primary");
    if (button) button.disabled = true;

    // 正文累积 + 节流渲染，避免每个分片都重排
    let raw = "";
    let renderTimer = null;
    const flush = () => {
      contentBox.innerHTML = renderMarkdown(raw);
    };
    const scheduleRender = () => {
      if (renderTimer) return;
      renderTimer = window.setTimeout(() => {
        renderTimer = null;
        flush();
      }, 120);
    };

    // 思考内容只保留最近一段并节流渲染，避免 DOM 无限增长导致卡顿
    const REASONING_WINDOW = 4000;
    let reasoningRaw = "";
    let reasoningTimer = null;
    const flushReasoning = () => {
      reasoningTimer = null;
      reasoningPre.textContent = reasoningRaw;
      reasoningPre.scrollTop = reasoningPre.scrollHeight;
    };
    const scheduleReasoning = () => {
      if (reasoningTimer) return;
      reasoningTimer = window.setTimeout(flushReasoning, 120);
    };

    try {
      await api.generateStream(payload, (event) => {
        if (event.type === "reasoning") {
          reasoningBox.hidden = false;
          reasoningRaw += event.text;
          // 超出窗口时逐步丢弃最早的内容
          if (reasoningRaw.length > REASONING_WINDOW) {
            reasoningRaw = reasoningRaw.slice(
              reasoningRaw.length - REASONING_WINDOW
            );
          }
          scheduleReasoning();
        } else if (event.type === "content") {
          if (reasoningTimer) {
            window.clearTimeout(reasoningTimer);
            flushReasoning();
          }
          // 开始出正文：收起思考过程并切换状态文案（模拟对话体验）
          if (!reasoningBox.hidden && reasoningBox.open) reasoningBox.open = false;
          if (statusText) statusText.textContent = "正在生成正文…";
          raw += event.text;
          scheduleRender();
          // 正文自动滚动到底部，实时跟随最新内容
          contentScroll.scrollTop = contentScroll.scrollHeight;
        } else if (event.type === "done") {
          if (renderTimer) window.clearTimeout(renderTimer);
          if (reasoningTimer) {
            window.clearTimeout(reasoningTimer);
            flushReasoning();
          }
          statusEl.remove();
          flush();
          contentScroll.scrollTop = contentScroll.scrollHeight;
          meta.append(
            el("span", { class: "badge badge-muted", text: `ID：${event.resource_id}` }),
            el("span", { class: "badge badge-muted", text: `模型：${event.model || "-"}` }),
            el("span", { class: "badge badge-warning", text: `状态：${event.status}` })
          );
          // 后端口径的质量检查结果（结构化，样式由前端组统一）
          if (event.quality) {
            if (event.quality.ok) {
              meta.append(el("span", { class: "badge badge-success", text: "质量检查通过" }));
            } else {
              for (const issue of event.quality.issues || []) {
                meta.append(el("span", { class: "badge badge-warning", text: issue.message }));
              }
            }
          }
          promptBox.append(
            enhanceDisclosure(
              el("details", { class: "disclosure" }, [
                el("summary", { text: "查看使用的系统提示词" }),
                el("pre", { class: "output", text: event.prompt || "" }),
              ])
            )
          );
          toastSuccess("生成完成（草稿）");
          if (hooks.onGenerated) hooks.onGenerated();
        } else if (event.type === "error") {
          if (reasoningTimer) window.clearTimeout(reasoningTimer);
          statusEl.remove();
          output.append(placeholder(`生成失败：${event.message}`));
          toastError(event.message);
        }
      });
    } catch (err) {
      if (renderTimer) window.clearTimeout(renderTimer);
      if (reasoningTimer) window.clearTimeout(reasoningTimer);
      statusEl.remove();
      output.append(placeholder(`生成失败：${err.message}`));
      toastError(err.message);
    } finally {
      if (button) button.disabled = false;
    }
  }

  build();
  loadOptions();

  return {
    refresh() {
      loadOptions();
    },
    /** 预选指定学生（用于从学生档案/资源库快速跳转生成）。 */
    preselect(profileId, source = null) {
      pendingProfile = profileId;
      pendingSource = source;
      applyPending();
    },
  };
}
