/**
 * views/forge.js —— 资源生成视图
 * 选择已建档学生或使用临时属性，指定资源类型与主题，调用生成接口。
 */

import { api } from "../core/api.js";
import { el, clear, placeholder, enhanceDisclosure } from "../core/dom.js";
import { label, formatTime } from "../core/format.js";
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
      el("div", { class: "field" }, [
        el("label", { text: "学生来源" }),
        studentSelect,
      ]),
      tempWrapper,
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
      el("button", {
        class: "btn btn-primary",
        type: "button",
        text: "生成资源",
        on: { click: doGenerate },
      }),
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

  /** 执行生成。 */
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

    clear(output);
    output.append(placeholder("正在调用云端模型生成，请稍候…", "loading"));
    const button = root.querySelector(".btn-primary");
    if (button) button.disabled = true;

    try {
      const result = await api.generate(payload);
      clear(output);
      output.append(
        el("h3", { text: "生成结果" }),
        el("div", { class: "badge-row" }, [
          el("span", { class: "badge badge-muted", text: `ID：${result.resource_id}` }),
          el("span", { class: "badge badge-muted", text: `模型：${result.model || "-"}` }),
          el("span", { class: "badge badge-warning", text: `状态：${result.status}` }),
        ]),
        el("pre", { class: "output", text: result.content || "（空内容）" }),
        enhanceDisclosure(
          el("details", { class: "disclosure" }, [
            el("summary", { text: "查看使用的系统提示词" }),
            el("pre", { class: "output", text: result.prompt || "" }),
          ])
        )
      );
      toastSuccess("生成完成（草稿）");
      if (hooks.onGenerated) hooks.onGenerated();
    } catch (err) {
      clear(output);
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
