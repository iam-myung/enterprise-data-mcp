# 企业数据直连 MCP 服务

本地演示 / 参考实现：企业**只读** MySQL 数据经 MCP 暴露给 Agent（stdio · Streamable HTTP · 旧 SSE），含审计与 Demo Agent。

> **定位**：V1 本地验收完成（见 `.docs/V1_DELIVERY.md`）。**非生产**：无公网鉴权、无 SSO、无 SLA；默认仅本机回环，勿直接暴露公网。

| 文档 | 说明 |
| --- | --- |
| [.docs/PRD.md](.docs/PRD.md) · [SPEC.md](.docs/SPEC.md) · [API.md](.docs/API.md) | 产品 / 技术 / MCP 契约 |
| [.docs/V1_DELIVERY.md](.docs/V1_DELIVERY.md) | 交付与验收状态（权威） |
| [DEPENDENCIES.md](DEPENDENCIES.md) | 依赖用途与钉版本 |
| [mcp_compat_matrix.toml](mcp_compat_matrix.toml) | MCP 协议 / FastMCP 兼容矩阵 |
| [工程指导.html](工程指导.html) | 可选：源码导览（教学用） |

下文保证：在仓库根按步骤可从零安装、启动，并完成一次真实查询。

---

## 仓库布局（交付根 = 仓库根）

```text
<repo>/
├── src/enterprise_data_mcp/       # MCP 服务
├── src/enterprise_data_mcp_demo/  # Demo Agent（与服务端隔离）
├── tests/  scripts/  config/  docker/
├── pyproject.toml                 # 包元数据与依赖（权威）
├── requirements.txt               # 由 toml 导出（兼容用）
├── requirements-dev.txt
└── .docs/                         # 契约与交付说明
```

请始终在仓库根工作：`cd <repo>`。

---

## 1. 依赖（机器前提）

详见 [DEPENDENCIES.md](DEPENDENCIES.md)。

| 依赖 | 要求 |
| --- | --- |
| OS | Windows / macOS / Linux |
| Python | **3.11.x**（`>=3.11,<3.12`） |
| pip | 随 Python 提供 |
| Docker Desktop | 演示 MySQL（宿主 `127.0.0.1:3307`） |
| Git | 克隆本仓库 |

可选：conda 环境 `dev_env_311`。

---

## 2. 安装

```bash
# 在仓库根目录（推荐：可编辑安装，注册 CLI）
python -m pip install -U pip
python -m pip install -e ".[dev]"
```

仅装依赖（不注册本包入口）时可用：

```bash
python -m pip install -r requirements.txt
python -m pip install -r requirements-dev.txt
# 仍需：python -m pip install -e .
```

安装成功后应能找到：

```bash
enterprise-data-mcp-stdio --help
enterprise-data-mcp-http --help
enterprise-data-mcp-sse --help
enterprise-data-mcp-demo --help
```

Windows 上若 `Scripts` 不在 PATH，改用 `python -m enterprise_data_mcp.hosts.stdio` 等。

---

## 3. 配置（环境变量）

```bash
cp .env.example .env
```

### 3.1 对接 Compose 演示库

`.env.example` 中 `MYSQL_PASSWORD=changeme` 仅为占位。对接本仓库 Compose 时改为：

```env
MYSQL_HOST=127.0.0.1
MYSQL_PORT=3307
MYSQL_USER=edmcp_ro
MYSQL_PASSWORD=demoro
MYSQL_DATABASE=edmcp_demo
```

（Compose 口令见 `docker/compose.yaml`：应用用户 `demoro` / root `demoroot`。）

### 3.2 常用变量

| 变量 | 含义 | 本地建议 |
| --- | --- | --- |
| `MCP_CONTAINER` | `demo`=内存假数据；`mysql`=真实 MySQL | 真查询用 `mysql` |
| `MCP_TRANSPORT` | `stdio` / `streamable_http` / `sse` | 按 Host 选择 |
| `MCP_CALLER_ID` | 调用方身份 | 如 `demo-stdio-client` |
| `MCP_POLICY_PROFILE` | 授权策略档 | `demo_readonly` |
| `ACCESS_POLICY_PATH` | 策略 YAML | `config/access_policy.example.yaml` |
| `AUDIT_DB_PATH` | 审计 SQLite | `var/audit.sqlite3` |
| `MCP_HOST` / `MCP_PORT` / `MCP_PATH` | HTTP/SSE 监听 | 本机默认 `127.0.0.1` |
| `MCP_ALLOWED_ORIGINS` | 允许的 Origin | 如 `http://127.0.0.1:3000` |
| `MCP_MAX_REQUEST_BODY_BYTES` | 请求体上限 | **1024～1048576** |
| `DEMO_MODEL` | `deterministic` / `openai` / `real` | 离线用 `deterministic` |
| `MODEL_API_KEY` / `MODEL_BASE_URL` / `MODEL_NAME` | 真模型 | 仅 `openai\|real` |
| `DEMO_MCP_TRANSPORT` | Demo 连 MCP：`stdio` 或 `streamable_http` | 默认可 `stdio` |

密钥只放 `.env`（已 gitignore），勿写入 `.env.example` 或源码。

官方入口与 pytest **读取进程环境变量**；仅有 `.env` 文件不等于已注入。PowerShell 示例：

```powershell
Get-Content .env | ForEach-Object {
  if ($_ -match '^\s*#' -or $_ -notmatch '=') { return }
  $k,$v = $_.Split('=',2)
  Set-Item -Path "Env:$($k.Trim())" -Value $v.Trim().Trim('"').Trim("'")
}
```

跑全量 pytest 时，**不要**把父进程的 `MCP_CONTAINER=mysql` 长期导出后留给依赖 `demo` 容器的 smoke（那些用例需 Fake 空结果）。真库用例会自行拉起 / 使用 Compose。

---

## 4. 启动 Compose（真实 MySQL）

```bash
# 仅演示库
docker compose -f docker/compose.yaml up -d --wait mysql

# 或连同 Compose 内 HTTP/SSE MCP
docker compose -f docker/compose.yaml up -d --wait
```

```bash
docker compose -f docker/compose.yaml ps
# mysql 应为 healthy
# curl http://127.0.0.1:18080/healthz
# curl http://127.0.0.1:18081/healthz
```

```bash
docker compose -f docker/compose.yaml down
# 连同卷：docker compose -f docker/compose.yaml down -v
```

---

## 5. 启动 MCP Host（本机进程）

真查询时先加载环境，并设置：

```bash
export MCP_CONTAINER=mysql
export MYSQL_PASSWORD=demoro
```

### 5.1 stdio（推荐本地 Agent / 演示）

```bash
enterprise-data-mcp-stdio
# 或: python -m enterprise_data_mcp.hosts.stdio
```

stdout 仅协议消息；日志在 stderr。

### 5.2 Streamable HTTP

```bash
export MCP_TRANSPORT=streamable_http
export MCP_HOST=127.0.0.1
export MCP_PORT=8080
export MCP_PATH=/mcp
export MCP_ALLOWED_ORIGINS=http://127.0.0.1:3000
export MCP_MAX_REQUEST_BODY_BYTES=1048576
export MCP_MAX_INFLIGHT_REQUESTS=32
enterprise-data-mcp-http
```

健康检查：`curl http://127.0.0.1:8080/healthz` → `{"status":"ok"}`

### 5.3 旧 SSE

```bash
export MCP_TRANSPORT=sse
export MCP_HOST=127.0.0.1
export MCP_PORT=8081
export MCP_PATH=/sse
export MCP_ALLOWED_ORIGINS=http://127.0.0.1:3000
enterprise-data-mcp-sse
```

---

## 6. 一次真实查询（验收路径）

自然语言 → Demo Agent → **真实** stdio MCP → **真实** Compose MySQL → 回答含数据集 / 查询时间 / 返回条数。

```bash
# 1) MySQL 已 healthy（§4）
# 2) 关键项：
export MCP_CONTAINER=mysql
export MYSQL_HOST=127.0.0.1
export MYSQL_PORT=3307
export MYSQL_USER=edmcp_ro
export MYSQL_PASSWORD=demoro
export MYSQL_DATABASE=edmcp_demo
export MCP_CALLER_ID=demo-stdio-client
export MCP_POLICY_PROFILE=demo_readonly
export DEMO_MODEL=deterministic
export DEMO_MCP_TRANSPORT=stdio

# 3)
enterprise-data-mcp-demo "列出商品名称"
```

期望输出含：

```text
数据集：sales_inventory_daily
查询时间：...
返回条数：...
```

且 `返回条数` > 0。真模型时设 `DEMO_MODEL=openai`（或 `real`）并配置 `MODEL_*`（DashScope 兼容示例：`MODEL_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1`，`MODEL_NAME=qwen-turbo`）。

Compose HTTP MCP 已启动时：

```bash
export DEMO_MCP_TRANSPORT=streamable_http
export DEMO_MCP_URL=http://127.0.0.1:18080/mcp
export DEMO_MCP_ORIGIN=http://127.0.0.1:3000
enterprise-data-mcp-demo "列出商品名称"
```

---

## 7. 测试与质量门禁

```bash
# 全量（需 Docker/MySQL；建议先 compose up mysql，且父进程勿强制 MCP_CONTAINER=mysql）
python -m pytest tests -q --timeout=180

# Golden Query GQ-01～GQ-10
python -m pytest tests/integration/adapters/outbound/mysql/test_golden_queries_mysql.py -q

# 发布门禁（真实执行子检查）
python scripts/quality_gate.py
```

可选：`pre-commit install`（见 `.pre-commit-config.yaml`）。

---

## 8. 常见故障

| 现象 | 可能原因 | 处理 |
| --- | --- | --- |
| `Data source unavailable` | MySQL 未起 / 口令或端口不对 | `compose up -d --wait mysql`；`MYSQL_PASSWORD=demoro`、`MYSQL_PORT=3307` |
| Docker / compose 失败 | Desktop 未就绪 | 启动 Docker 后重试；环境不可用应视为 BLOCK |
| Host 启动即退出：`MCP_MAX_REQUEST_BODY_BYTES...` | 体积极限低于 1024 | 设为 `1048576` 或至少 `1024` |
| `MODEL_* is required` | `DEMO_MODEL=openai\|real` 未配密钥 | 改回 `deterministic`，或补齐 `MODEL_*` |
| Demo 连不上 Compose MCP | Origin / URL 错误 | `DEMO_MCP_URL=http://127.0.0.1:18080/mcp`，Origin `http://127.0.0.1:3000` |
| 改了 `.env` 仍无效 | 未注入进程 | 按 §3 导出到当前 shell |
| 找不到 CLI | Scripts 不在 PATH | `python -m enterprise_data_mcp.hosts.stdio` |
| 全量 pytest 中 demo smoke 失败 | 父进程 `MCP_CONTAINER=mysql` | 清掉该变量后再跑，或只跑真库相关用例 |

---

## 9. 入口速查

| 入口 | 命令 |
| --- | --- |
| stdio Host | `enterprise-data-mcp-stdio` / `python -m enterprise_data_mcp.hosts.stdio` |
| Streamable HTTP | `enterprise-data-mcp-http` / `python -m enterprise_data_mcp.hosts.streamable_http` |
| 旧 SSE | `enterprise-data-mcp-sse` / `python -m enterprise_data_mcp.hosts.sse` |
| Demo Agent | `enterprise-data-mcp-demo "<自然语言>"` |
| Compose | `docker compose -f docker/compose.yaml up -d --wait` |
