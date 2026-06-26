# auto-support

只用公开文档回答产品 Discord 用户的使用问题 —— fail-closed 护栏把机密/算法/PII 锁在里面；拿不准就升级给创始人。

[![Claude Code Skill](https://img.shields.io/badge/Claude%20Code-Skill-orange?style=flat)](https://docs.anthropic.com/en/docs/claude-code)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Languages](https://img.shields.io/badge/Languages-EN%20%2F%20CN-blue?style=flat)](#languages)
[![Roadmap](https://img.shields.io/badge/Roadmap-v0.1.0-purple?style=flat)](ROADMAP.md)

[English](README.md) | [中文版](README_CN.md)

---

## ⭐ 先读这里 — 设计理念

一个会读产品仓库的客服 bot，离泄露公司只有一个 prompt 的距离。所以统领原则很直白：**它的第一职责是
把机密锁住，而不是答题。** 宁可漏答，不可泄露一次。关键在于：**写进 prompt 的护栏只是建议，模型每次都
能无视**（AWS 实证：只口头禁止 → 3/3 泄露；加一个确定性 hook → 3/3 拦截）—— 所以本 skill 的所有
保证都落在模型之外：`permissions.deny` + fail-closed `PreToolUse` hook + 纯 stdlib 检测 + 出口 DLP
闸。模型根本打不开机密文件，也就无从泄露。

📜 **[完整设计理念 -> PHILOSOPHY.md](PHILOSOPHY.md)**

---

## 它是什么(不是什么)

**是：** 一个 Claude Code 插件，部署到产品仓库根目录的 `.claude/`，只用该产品的**公开**文档回答其
Discord 用户的使用问题，带确定性防泄密护栏、拿不准即升级创始人。MVP 走「人审草稿/relay」，不自动直发。

**不是：** 通用聊天机器人、代码讲解器，或任何为了「帮忙」去读源码/机密的东西。allowlist 之外的问题一律
拒答 + 升级，绝不凭记忆作答。

## 工作原理 — 纵深四闸（fail-closed）

```
Discord 消息 ─▶ 入口(注入+意图, spotlight) ─▶ 检索(只在 allowlist, 片段先扫密)
            ─▶ grounding(检索置信 × 忠实度) ─▶ 出口(结构化 schema + DLP + canary + 引用核验)
            ─▶ 草稿 ─▶ 创始人审核 ─▶ approve ─▶ 用户   (任一闸不过 ⇒ 中性拒答 + 升级)
```

知识边界 = **allowlist 优先、默认拒绝、denylist 优先**：机密从不被打开，自然拼不进答案。状态
（FAQ/未决/升级）复用 `schedule-reminder` 基座；升级复用本机 Discord relay，带 SRE 式去抖。

## 安装

```
/plugin install github:DaizeDong/auto-support
```

或手动克隆:

```bash
git clone https://github.com/DaizeDong/auto-support.git ~/.claude/plugins/auto-support
```

## 快速开始

1. 按 `reference/config-schema.md` 建私有 `auto-support-config`，填 `product_root`、
   `index_allowlist`、`secret_denylist`、创始人频道（Discord token 走 DPAPI）。
2. `apply.py` 用 `skills/auto-support/templates/settings.json.template` 合成产品根
   `.claude/settings.json`（deny globs + PreToolUse hook）。
3. 开任何非草稿回复模式前先过红队闸：`cd skills/auto-support && python -m pytest tests/ -q`。

## 配置

`auto-support` 是**带 config 的 skill** —— 机密与每产品知识边界都放在一个**独立、私有**的伴随仓
（`auto-support-config`，Mode B），每个产品一份隔离的 `policy.json`。完整规范+字段表见
**[CONFIG.md](CONFIG.md)**（深层布局见 `skills/auto-support/reference/config-schema.md`）。

- **挂载(发现顺序):** `$AUTO_SUPPORT_CONFIG` → `$AUTO_SUPPORT_CONFIG_DIR` →
  `~/.auto-support-config/` → `~/.config/auto-support-config/`。命中第一个即用；都没有 ⇒ hook 回退到
  内置 deny 默认（fail-closed）。当前产品由 `$AUTO_SUPPORT_POLICY`（指向 `products/<slug>/policy.json`）
  或唯一产品选定。
- **首次配置:**
  ```bash
  cd skills/auto-support
  python scripts/init_config.py --slug <product>   # 生成符合规范的骨架(确定性)
  export AUTO_SUPPORT_CONFIG=~/.auto-support-config
  python scripts/verify_config.py                  # doctor:逐项 PASS/FAIL,明确报缺什么
  ```
- **切换 config(即插即用):** 把环境变量指向另一个 config 目录即可 —— config 自包含(`product_root`
  为占位符,无任何写死路径)：`export AUTO_SUPPORT_CONFIG=~/configs/product-a` ↔ `~/configs/product-b`。
- **密钥:** Mode B —— `secrets/*` 已 gitignore,永不入库；`policy.json` 里的 `@secret:...` 指针由
  config 仓的 `apply.py` 从 DPAPI 密文注入。请用库外备份。

## 如何触发

以插件形式部署，按每条 Discord 消息跑 `scripts/answer_pipeline.py`（或 headless `/auto-support
<msg>`）。仅在 @提及 / 回复 bot / 指定 support 频道时触发。

## 示例输出

通过的一轮返回带引用的 grounded 草稿（`public-faq/faq.md:4`）；被拦/拿不准的一轮只返回一句中性话术
（`这个问题我无法确定，已转交团队跟进。`）并升级创始人。

## 局限

MVP 走草稿/relay（红队套件在真实产品上通过前不自动直发）。暂无向量库（用原生 Read/Grep 精确引用）。
纯 Windows 无 OS 沙箱层 —— 完整防御纵深需在 WSL2/devcontainer 下跑。完整忠实度裁判 LLM 是集成接口。

## 语言

中文 (`README_CN.md`) · English (`README.md`, 权威版)

## Roadmap · 贡献 · 许可

见 [ROADMAP.md](ROADMAP.md) · [CONTRIBUTING.md](CONTRIBUTING.md) · [LICENSE](LICENSE)(MIT)。
