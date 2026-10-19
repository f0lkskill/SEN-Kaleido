/**
 * views/forge.js —— 资源生成视图
 * 选择已建档学生或使用临时属性，指定资源类型与主题，调用生成接口。
 */

import { api } from "../core/api.js";
import { el, clear, placeholder, enhanceDisclosure, panel } from "../core/dom.js";
import { label, formatTime } from "../core/format.js";
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

  function build() {
    clear(root);
    studentSelect = el("select", { name: "profile_id" });
    resourceSelect = el("select", { name: "resource_type" });
    topicInput = el("input", { type: "text", name: "topic" });
    extraInput = el("textarea", { name: "extra" });
    tempForm = buildAttributesForm("forge");
    tempWrapper = el("div", { hidden: true });
    output = el("div");
    output.append(placeholder("生成结果将显示在此。"));

    studentSelect.addEventListener("change", () => {
      // 未选择学生时展示临时属性表单
      tempWrapper.hidden = studentSelect.value !== "";
    });

    // 左：信息表单；右：生成结果
    const infoCard = el("section", { class: "card" }, [
      panel("学生来源", [
        el("div", { class: "field" }, [
          el("label", { text: "选择学生" }),
          studentSelect,
        ]),
        tempWrapper,
      ]),
      panel("生成设置", [
        el("div", { class: "field-row" }, [
          el("div", { class: "field" }, [
            el("label", { text: "资源类型" }),
            resourceSelect,
          ]),
          el("div", { class: "field" }, [
            el("label", { text: "教学主题" }),
            topicInput,
          ]),
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

      clear(studentSelect);
      studentSelect.append(
        el("option", { value: "", text: "（使用下方临时属性）" })
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
    } catch (err) {
      toastError(`加载选项失败：${err.message}`);
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

    try {
      await api.generateStream(payload, (event) => {
        if (event.type === "reasoning") {
          reasoningBox.hidden = false;
          reasoningPre.textContent += event.text;
          // 思考内容自动滚动到底部
          reasoningPre.scrollTop = reasoningPre.scrollHeight;
        } else if (event.type === "content") {
          // 开始出正文：收起思考过程并切换状态文案（模拟对话体验）
          if (!reasoningBox.hidden && reasoningBox.open) reasoningBox.open = false;
          if (statusText) statusText.textContent = "正在生成正文…";
          raw += event.text;
          scheduleRender();
          // 正文自动滚动到底部，实时跟随最新内容
          contentScroll.scrollTop = contentScroll.scrollHeight;
        } else if (event.type === "done") {
          if (renderTimer) window.clearTimeout(renderTimer);
          statusEl.remove();
          flush();
          contentScroll.scrollTop = contentScroll.scrollHeight;
          meta.append(
            el("span", { class: "badge badge-muted", text: `ID：${event.resource_id}` }),
            el("span", { class: "badge badge-muted", text: `模型：${event.model || "-"}` }),
            el("span", { class: "badge badge-warning", text: `状态：${event.status}` })
          );
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
          statusEl.remove();
          output.append(placeholder(`生成失败：${event.message}`));
          toastError(event.message);
        }
      });
    } catch (err) {
      if (renderTimer) window.clearTimeout(renderTimer);
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
  };
}
