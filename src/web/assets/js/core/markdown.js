/**
 * core/markdown.js —— 极简 Markdown → HTML
 * 支持标题、粗体/斜体、行内代码、代码块、有序/无序列表、引用、链接、
 * 分隔线与标准表格。先对文本做 HTML 转义以避免 XSS；够用于呈现模型输出。
 */

/** HTML 转义，防止注入。 */
function escapeHtml(text) {
  return String(text)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

/** 行内标记解析（代码、粗体、斜体、链接）。 */
function inline(text) {
  let out = escapeHtml(text);
  out = out.replace(/`([^`]+)`/g, "<code>$1</code>");
  out = out.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  out = out.replace(/(^|[^*])\*([^*\s][^*]*?)\*/g, "$1<em>$2</em>");
  out = out.replace(
    /\[([^\]]+)\]\(([^)\s]+)\)/g,
    '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>'
  );
  return out;
}

/** 是否为表格分隔行（形如 | --- | --- |）。 */
function isTableSeparator(line) {
  return line.includes("-") && /^\s*\|?[\s:|-]+\|?\s*$/.test(line);
}

/** 拆分表格一行为单元格。 */
function splitRow(line) {
  return line
    .trim()
    .replace(/^\|/, "")
    .replace(/\|$/, "")
    .split("|")
    .map((cell) => cell.trim());
}

/**
 * 把 Markdown 文本渲染为 HTML 字符串。
 * @param {string} source 原始 Markdown
 * @returns {string} HTML 字符串
 */
export function renderMarkdown(source) {
  const lines = String(source || "").replace(/\r\n?/g, "\n").split("\n");
  const html = [];
  let listType = null;
  let inCode = false;
  let codeLines = [];

  const closeList = () => {
    if (listType) {
      html.push(`</${listType}>`);
      listType = null;
    }
  };
  const openList = (type) => {
    if (listType !== type) {
      closeList();
      html.push(`<${type}>`);
      listType = type;
    }
  };

  for (let i = 0; i < lines.length; i += 1) {
    const line = lines[i];

    // 代码块围栏（保留内部空白，用于示意排版）
    if (/^\s*```/.test(line)) {
      if (inCode) {
        html.push(`<pre class="md-code"><code>${escapeHtml(codeLines.join("\n"))}</code></pre>`);
        codeLines = [];
        inCode = false;
      } else {
        closeList();
        inCode = true;
      }
      continue;
    }
    if (inCode) {
      codeLines.push(line);
      continue;
    }

    if (/^\s*$/.test(line)) {
      closeList();
      continue;
    }

    // 表格：当前行含 |，且下一行是分隔行
    if (line.includes("|") && isTableSeparator(lines[i + 1] || "")) {
      closeList();
      const header = splitRow(line);
      const rows = [];
      let j = i + 2;
      while (j < lines.length && lines[j].includes("|") && !/^\s*$/.test(lines[j])) {
        rows.push(splitRow(lines[j]));
        j += 1;
      }
      const head = header.map((cell) => `<th>${inline(cell)}</th>`).join("");
      const bodyRows = rows
        .map((row) => {
          const cells = [];
          for (let c = 0; c < header.length; c += 1) cells.push(`<td>${inline(row[c] || "")}</td>`);
          return `<tr>${cells.join("")}</tr>`;
        })
        .join("");
      html.push(
        `<table class="md-table"><thead><tr>${head}</tr></thead><tbody>${bodyRows}</tbody></table>`
      );
      i = j - 1;
      continue;
    }

    const heading = line.match(/^(#{1,6})\s+(.*)$/);
    if (heading) {
      closeList();
      const level = heading[1].length;
      html.push(`<h${level}>${inline(heading[2])}</h${level}>`);
      continue;
    }

    if (/^\s*([-*_])(\s*\1){2,}\s*$/.test(line)) {
      closeList();
      html.push("<hr />");
      continue;
    }

    const quote = line.match(/^\s*>\s?(.*)$/);
    if (quote) {
      closeList();
      html.push(`<blockquote>${inline(quote[1])}</blockquote>`);
      continue;
    }

    const ul = line.match(/^\s*[-*+]\s+(.*)$/);
    if (ul) {
      openList("ul");
      html.push(`<li>${inline(ul[1])}</li>`);
      continue;
    }

    const ol = line.match(/^\s*\d+[.)]\s+(.*)$/);
    if (ol) {
      openList("ol");
      html.push(`<li>${inline(ol[1])}</li>`);
      continue;
    }

    closeList();
    html.push(`<p>${inline(line)}</p>`);
  }

  if (inCode) {
    html.push(`<pre class="md-code"><code>${escapeHtml(codeLines.join("\n"))}</code></pre>`);
  }
  closeList();
  return html.join("\n");
}
