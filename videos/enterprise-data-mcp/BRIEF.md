---
workflow: product-launch-video
flow: automation
storyboard: no
message: "一次只读查询：从 Agent 经 MCP 到达 MySQL，结果与审计路径一起演清楚"
destination: youtube
aspect: 1920x1080
language: zh
audience: GitHub 技术访客与招聘官
length: 60s
angle: GitHub 项目 demo — 假 UI 提问 + 数据流节点（Agent → MCP Host → Query → MySQL → 审计）
capture: none
style_preset: code-editorial
---

## Intent

为企业数据直连 MCP 服务做一段约 60 秒、16:9、纯动画的 GitHub 风格项目演示片。
不录屏、不抓站。主线：界面提问 → 数据包穿过 MCP 链路 → 结果回写 → 只读与审计护栏 → 仓库 CTA。
对照制度库片的案卷结构，这里改成「主路径 + 只读/审计护栏」。

本轮交付到 Studio 可预览为止；最终 MP4 由用户自行渲染导出。不提交 git。

## Assets

- 无用户提供素材；no-capture，动效自建。

## Customizations

- 纯动画：kinetic 标题、假 Agent UI、数据流节点与数据包、审计印章。
- 无旁白 TTS（HeyGen 未登录，Kokoro 依赖缺失）→ 画面内中文 kinetic 文案承担信息；`music: none` 保证可静音预览。
- 强转场；避免 UI 假屏幕实录感过重，但需能「演」出界面与数据流。

## Notes

- 产品一句话：企业只读 MySQL 经 MCP 暴露给 Agent（stdio · Streamable HTTP · SSE），含审计与 Demo Agent。
- 主路径：Agent 提问 → MCP Host → Query Service → MySQL → 结果回写 → 审计落库。
- 护栏：只读策略、审计 call_id。
- 预览：`npm run dev` 或 `npx hyperframes preview`；不要在本轮执行 `render`。
