---
format: 1920x1080
duration: 58s
message: show how the MCP system works — ask UI, data flow, result, then guardrails
arc: Hook -> Name -> Ask UI -> Dataflow -> Result -> Guard -> CTA
mode: autonomous
music: none
---

## Video direction

Warm cream paper / coral voltage / Noto Sans SC (CJK) + JetBrains Mono kickers — same register as enterprise-policy-rag. Silent kinetic type. No purple SaaS cards. Full-bleed backgrounds on `class="clip"` layers.

## Frame 1 — Hook

- scene: Thesis punch — 企业数据，Agent 怎么直连？
- duration: 6s
- poster: 3s
- transition_in: cut
- status: animated
- src: compositions/frames/01-hook.html
- asset_candidates: none (invented)

0.0–0.5 cream field + coral flash. 0.5–1.8 kinetic thesis. 1.8–4.0 search-bar expands, types 「只读查询」. 4.0–6.0 soft push-in.

## Frame 2 — Name product

- scene: enterprise-data-mcp + three transports
- duration: 7s
- poster: 3.5s
- transition_in: cut
- status: animated
- src: compositions/frames/02-name.html
- asset_candidates: none

0.0–1.0 title「企业数据直连 MCP」. 1.0–3.5 three transport pills (stdio / HTTP / SSE) cascade in. 3.5–6.0 mono line「只读 MySQL → Agent」. 6.0–7.0 hold.

## Frame 3 — Ask UI

- scene: Demo Agent panel types a natural-language query
- duration: 9s
- poster: 5s
- transition_in: cut
- status: animated
- src: compositions/frames/03-ask-ui.html
- asset_candidates: none

0.0–1.0 panel rises. 1.0–2.5 thesis「用自然语言查企业库」. 2.5–6.5 types「本月销售额最高的前 5 个客户？». 6.5–8.0 发起查询 button pulse. 8.0–9.0 hold.

## Frame 4 — Dataflow

- scene: Packet travels Agent → MCP Host → Query → MySQL
- duration: 12s
- poster: 6s
- transition_in: cut
- status: animated
- src: compositions/frames/04-dataflow.html
- asset_candidates: none

0.0–1.5 four nodes fade in left→right. 1.5–3.0 connecting beams draw. 3.0–9.5 coral packet hops node to node with status labels. 9.5–12.0 MySQL node pulse「SELECT … LIMIT」.

## Frame 5 — Result

- scene: Rows return into Agent answer panel
- duration: 9s
- poster: 5s
- transition_in: cut
- status: animated
- src: compositions/frames/05-result.html
- asset_candidates: none

0.0–1.5 split: left Agent, right result table empty. 1.5–5.5 rows cascade in with numbers. 5.5–7.5 provenance chip「MCP · call_id」. 7.5–9.0 hold.

## Frame 6 — Guard

- scene: READONLY + AUDIT stamps — the guardrails
- duration: 8s
- poster: 4s
- transition_in: cut
- status: animated
- src: compositions/frames/06-guard.html
- asset_candidates: none

0.0–1.0 kicker「护栏」. 1.0–3.5 READONLY stamp slam. 3.5–6.0 AUDIT stamp + sqlite path. 6.0–8.0 line「写操作拒答 · 每调用可回看」.

## Frame 7 — CTA

- scene: Repo name close
- duration: 7s
- poster: 3.5s
- transition_in: cut
- status: animated
- src: compositions/frames/07-cta.html
- asset_candidates: none

0.0–1.0 navy ground + coral glow. 1.0–3.0 mono repo. 3.0–5.0 title + tagline「Agent 直连只读库」. 5.0–7.0 meta「stdio · HTTP · SSE」.
