# 前端（web）开发规划

> 版本 v1.0 ｜ 定位：教室机静态客户端（HTML + CSS + JS，独立于后端脚本）
> 服务：由统一入口 `src/kaleido/api/app.py` 托管（Bottle + waitress）

## 一、概述

前端是**纯静态单页应用**，无需构建工具，浏览器直接访问基站地址即可。
它调用统一 API（`/api/v1/*`）完成学生建档、评价框架预览、资源生成、
资源库浏览与异步任务管理。所有 HTML/CSS/JS 均放在 `src/web/`，
**与后端 Python 脚本完全分离**，并按类别分目录组织。

## 二、设计目标

- **无障碍优先**：语义化标签、键盘可导航、焦点可见、`aria-live` 播报、
  支持**字号档位**与**高对比度**切换（偏好存 localStorage）。
- **适配特教场景**：大点击区域（≥40px）、中文标签统一（枚举键→中文映射）、
  弱网友好（统一错误提示）。
- **零构建**：使用原生 ES Module，`<script type="module">` 直接加载。

## 三、目录结构

```
src/web/
├── index.html                      页面骨架（顶栏 + 标签导航 + 主内容 + 提示条）
└── assets/
    ├── css/
    │   ├── tokens.css              设计变量（颜色/字号档位/间距/圆角/阴影）
    │   ├── base.css                全局重置与无障碍基础
    │   ├── layout.css              页面骨架与自适应布局
    │   └── components.css          通用组件（按钮/表单/卡片/表格/标签/提示…）
    └── js/
        ├── core/                   与 UI 无关的基础能力
        │   ├── api.js              接口封装与统一响应解包
        │   ├── dom.js              轻量 DOM 构建工具
        │   ├── format.js           枚举→中文映射与时间格式化
        │   ├── toast.js            全局提示条（live region）
        │   └── settings.js         无障碍显示设置（字号/对比度）
        ├── views/                  各功能视图（页面区块）
        │   ├── students.js         学生档案：左右分栏（列表 + 详情），建档/筛选/删除
        │   ├── framework.js        评价框架：属性表单、框架渲染、预览
        │   ├── forge.js            资源生成
        │   ├── library.js          资源库
        │   └── tasks.js            异步任务队列
        └── app.js                  应用入口：标签导航与视图懒加载
```

分类原则：`core/` 放与具体页面无关的工具，`views/` 放页面级模块；
样式按「变量 → 基础 → 布局 → 组件」分层，避免样式相互覆盖。

## 四、页面与功能

| 标签 | 视图 | 主要能力 |
|---|---|---|
| 学生档案 | `students.js` | 左右分栏：左侧列表、右侧详情；建档（多障碍属性录入）、按类型/认知筛选（进入即自动筛选一次）、查看属性与公共评价标准、删除 |
| 评价框架 | `framework.js` | 临时属性即时预览规范化属性与公共评价标准（不落库） |
| 资源生成 | `forge.js` | 选学生或临时属性、选资源类型、填主题、生成并展示内容与系统 Prompt |
| 资源库 | `library.js` | 按类型/障碍/状态筛选，展开查看资源正文 |
| 任务队列 | `tasks.js` | 提交（含 `forge.generate`）、状态轮询、取消、查看参数/结果/错误 |

## 五、与后端的约定

- 统一响应包裹：`{code, message, data}`，`code===0` 为成功。
- 接口前缀：`/api/v1/*`；静态资源：`/assets/*`。
- 静态资源由统一入口托管：根路径 `/` 返回 `index.html`，`Cache-Control`
  HTML 不缓存、静态资源缓存 1 小时；`/api/*` 未命中不会被当作静态文件。

## 五点五、视觉与交互要点

- **页面切换动画**：标签视图由 `display:none` 恢复可见时自动重放淡入位移动画
  （`layout.css` 的 `.view` / `view-in`）。
- **左右分栏（master-detail）**：学生档案选中后，列表收窄靠左、详情面板从右侧
  滑出（`.student-layout.narrowed` + `panel-in`）；点击「收起」或重新筛选时面板消失。
- **直观展示**：评价维度以**权重进度条**呈现；评分标准以**等级卡片**
  （等级名 + 行为描述 + 证据要求）呈现；证据来源键统一映射为中文名称
  （后端元数据优先，静态兜底），避免直接暴露内部 ID。
- **多障碍**：障碍类型为多选，列表与详情均以标签展示全部障碍。

## 六、无障碍实现要点

- 顶栏提供**字号（标准/大/特大）**与**对比度（标准/高）**切换，作用于
  `<html>` 的 `data-fontsize` / `data-contrast`，由 CSS 变量接管。
- 提供「跳到主内容」跳过链接；标签使用 `role="tab"` / `aria-selected`。
- 表单控件均有关联 `<label>`；提示条为 `role="status" aria-live="polite"`。
- 尊重系统 `prefers-reduced-motion`，关闭动效。

## 七、运行与联调

```powershell
# 正常部署：需要 DEEPSEEK_API_KEY
python -m kaleido.api.app            # 默认 0.0.0.0:8080

# 本地无密钥联调：用离线桩客户端
$env:SEN_KALEIDO_LLM_PROVIDER = "stub"
python -m kaleido.api.app
```

浏览器打开 `http://<基站IP>:8080/`。

## 八、完成定义（DoD）

- 五个标签视图可用，覆盖 profile / forge / vault / tasks 的常用操作。
- 前端与后端脚本目录分离，静态资源按 css / js(core, views) 分类。
- 无障碍基础能力（字号、对比度、键盘、焦点、live region）就绪。
- 统一入口可同时托管 API 与静态前端。

## 九、实现状态（已落地）

- **入口**：`src/kaleido/api/app.py`（合并 profile / vault / forge / tasks 路由 + 静态托管）。
- **页面**：`src/web/index.html` + `assets/css/*` + `assets/js/{core,views}/*`。
- **学生档案**：左右分栏（master-detail）+ 页面切换动画 + 权重进度条 / 评分等级卡片；
  证据来源展示中文名称；障碍类型支持多选。
- **测试**：`tests/integration/test_unified_app.py`（静态托管 + 三模块 API + 异步任务打通 forge）。
