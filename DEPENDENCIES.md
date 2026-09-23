# Dependencies

权威版本以根目录 `pyproject.toml` 为准；本文件说明**用途与边界**。锁文件见 `uv.lock`（可选工具）；安装命令见 `README.md`。

Python：**3.11.x**（`requires-python = ">=3.11,<3.12"`）。

---

## 1. 机器前提（非 pip）

| 依赖 | 用途 | 备注 |
| --- | --- | --- |
| Python 3.11 | 运行时 | conda / pyenv / 系统解释器均可；本仓库常用 `dev_env_311` |
| Docker Desktop | 演示 MySQL 与 Compose MCP | 真库端口 `127.0.0.1:3307`；见 `docker/compose.yaml` |
| Git | 克隆仓库 | — |

---

## 2. 运行时依赖（`pip install -e .`）

| 包 | 钉版本 | 用途 | 边界 |
| --- | --- | --- | --- |
| `fastmcp` | `4.0.3` | MCP Resources / Tools / 三传输 Host | 唯一直接使用的高层 MCP 框架 |
| `pyyaml` | `6.0.3` | 授权策略 YAML | 仅 Policy Adapter 边界 |
| `pydantic` | `2.13.4` | 配置与入站/出站边界校验 | Domain **不得**依赖 |
| `mysql-connector-python` | `9.3.0` | MySQL Catalog / Query Adapter | 仅 outbound MySQL Adapter |
| `opentelemetry-api` | `1.44.0` | Trace API | 可观测性 Adapter |
| `opentelemetry-sdk` | `1.44.0` | Trace SDK | 可观测性 Adapter |
| `prometheus_client` | `0.26.0` | 指标 | 可观测性 Adapter |

间接依赖（由 FastMCP 引入，业务代码勿直接依赖其私有传输实现）：

- MCP Python SDK、Starlette、Uvicorn 等 — 以 `uv.lock` / 安装后解析为准；协议兼容矩阵见 `mcp_compat_matrix.toml`。

---

## 3. 开发依赖（`pip install -e ".[dev]"`）

| 包 | 用途 |
| --- | --- |
| `pytest` / `pytest-timeout` / `pytest-cov` / `coverage` | 测试与 Domain 覆盖率门禁 |
| `import-linter` | 架构分层（`.importlinter`） |
| `pre-commit` | 提交前钩子 |
| `ruff` | Lint |
| `mypy` / `types-PyYAML` | 静态类型（Domain strict） |
| `bandit` | 安全静态扫描 |
| `pip-audit` | 依赖漏洞扫描 |

发布门禁脚本：`python scripts/quality_gate.py`（会实际执行上述子检查，而非只核对文件名）。

---

## 4. 不在 pip 清单中的外部系统

| 系统 | 用途 | 说明 |
| --- | --- | --- |
| MySQL 8.4（Compose） | 演示库 + Golden Query | 镜像与种子在 `docker/` |
| SQLite 文件 | 审计库 | 路径由 `AUDIT_DB_PATH` 配置，默认 `var/audit.sqlite3` |
| 可选 LLM HTTP API | Demo Agent 真模型 | 仅 `DEMO_MODEL=openai\|real`；离线用 `deterministic` |

---

## 5. 安装与升级

```bash
# 推荐：可编辑安装（注册 console scripts）
python -m pip install -e .
python -m pip install -e ".[dev]"

# 兼容导出（仅装依赖；要本包入口仍需 pip install -e .）
python -m pip install -r requirements.txt
python -m pip install -r requirements-dev.txt
```

`requirements.txt` / `requirements-dev.txt` 由 `pyproject.toml` 导出，**以 `pyproject.toml` 为准**；变更依赖时先改 toml，再同步这两份文件。

升级规则（与 SPEC 一致）：

- 禁止把外部样例工程的 requirements 直接合并进本仓库。
- 直接依赖升级须单独评估，并跑契约 / smoke / `quality_gate`。
- Domain 层不得引入第三方包。
