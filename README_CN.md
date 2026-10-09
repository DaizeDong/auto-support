# auto-support

根据产品公开文档起草带引用的回答，检查访问路径和内容，并将无法支持的问题提交团队复核。

[![Claude Code Skill](https://img.shields.io/badge/Claude%20Code-Skill-orange?style=flat)](https://docs.anthropic.com/en/docs/claude-code)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Languages](https://img.shields.io/badge/Languages-EN%20%2F%20CN-blue?style=flat)](#语言)
[![Roadmap](https://img.shields.io/badge/Roadmap-v0.1.2-purple?style=flat)](ROADMAP.md)

[English](README.md) | [中文版](README_CN.md)

---

## 设计理念

产品客服需要给出有用的答案，同时限制对私有实现资料的访问。因此，选定的公开文档构成知识
边界，检索和宿主 hook 在模型之外核对路径，草稿还必须保留匹配的原文与引用。单靠 prompt 中
的一句禁止访问，无法执行这条边界。

这套设计会缩小可回答的问题范围：自由生成器可能继续作答的问题，自带 CLI 可能拒绝。
文档范围无法确定时也会拒答。长篇散文章节使用 `llmcall` 解释范围，这种判断仍可能出错；
精确的原文范围只能证明来源，不能证明解释正确。改写答案需要另行验证的集成。

草稿、升级请求和消息投递分别报告结果。中性拒答可以请求升级，只有确认的 relay 回执才表示
发送成功。私有持久化状态用于防止把一次结果不明的发送自动重发。宿主 hook 的覆盖范围和
真实投递仍需部署验证；插件本身不安装操作系统沙箱。

[完整设计理念](PHILOSOPHY.md)。

## 适用范围

这是用于产品 Discord 客服的 Claude Code 插件，通过公开文档检索生成带引用的草稿，再由创始人
审核或通过 relay 处理。部署配置位于产品根目录的 `.claude/`。自带 CLI 返回本地草稿，不自动发布回复。

需要源码、机密或公开 allowlist 之外资料的问题会被拒答并提交复核。通用聊天和代码讲解不在适用
范围内；缺少证据时不能凭记忆补答。

## 工作原理， 纵深四闸（fail-closed）

```
Discord 消息 ─▶ 入口(注入+意图, spotlight) ─▶ 检索(只在 allowlist, 片段先扫密)
            ─▶ grounding(检索置信 × 忠实度) ─▶ 出口(结构化 schema + DLP + canary + 引用核验)
            ─▶ 草稿 ─▶ 创始人审核 ─▶ approve ─▶ 用户   (任一闸不过 ⇒ 中性拒答 + 升级)
```

知识边界 = **allowlist 优先、默认拒绝、denylist 优先**：检索和 hook 同时检查请求路径及其解析目标，
两者都必须属于所选公开目录。通知和持久化前会过滤检测到的凭据与个人信息。状态
（FAQ/未决/升级）复用 `schedule-reminder` 基座；升级复用本机 Discord relay，带 SRE 式去抖。

检索会保留局部前言，并跟随同一文档内的显式章节引用。拆分较长的散文章节时，系统通过已安装的
`llmcall` 接口，按当前默认裁判路由解释整篇文档中的章节关系。解释缺失、不确定，或无法与原文准确
对应时，会拒绝回答。行号、范围和摘要可以核对来源，但模型仍可能误判关系；合成测试尚不能证明
真实模型的判断效果。详见[来源范围](docs/source-scope.md)。

## 安装

```
/plugin install github:DaizeDong/auto-support
```

或手动克隆：

```bash
git clone --recurse-submodules https://github.com/DaizeDong/auto-support.git ~/.claude/plugins/auto-support
```

## 快速开始

在仓库根目录运行：

```bash
python scripts/init_config.py --slug example --out ../auto-support-config
```

把 `products/example/product.json` 中的 `product_root` 填为产品公开文档目录的绝对路径。
生成的策略支持目录内的文档格式，包括直接放在根目录的 `usage.md`，拒绝规则仍然生效。再运行：

```bash
python scripts/verify_config.py --config-dir ../auto-support-config
python skills/auto-support/scripts/answer_pipeline.py --policy ../auto-support-config/products/example/policy.json --query "How do I install the SDK?"
```

这会生成带引用的草稿，无需 Discord 凭据。真实配置和运行记录应保存在私有伴生仓，并纳入版本管理。
消息投递还需要单独配置宿主 hook、relay 和审批；初始化器没有提供 `apply.py`。

## 配置

每个产品的配置和运行记录放在独立、纳入版本管理的 PRIVATE `auto-support-config` 伴生仓中，
每个产品有自己的 `policy.json`。[CONFIG.md](CONFIG.md)规定发现顺序、策略选择、初始化和切换；
[字段参考](skills/auto-support/reference/config-schema.md)说明目录结构。

切换伴生仓前，清除优先级更高的旧变量，并同时更新 doctor/状态存储选择和草稿 CLI、hook 使用的
`AUTO_SUPPORT_POLICY`。策略必须属于选定的伴生仓。`DRAFT READY` 只验证配置和本地文档目录。

当前凭据配置采用 Mode B：`secrets/*` 不进入 Git，凭据需要获准的独立备份。运行记录和升级状态
仍须纳入版本管理。可选的 `@secret:...` 引用由另外配置的投递适配器解析。

持久化对话前，按[提醒存储设置](CONFIG.md#reminder-persistence-setup)选择并初始化 PRIVATE 调度器
数据库。状态保留和恢复见 [DATA.md](DATA.md)；结果不明的投递锁须保留到核对完成。

## 如何触发

说“根据这个产品的公开文档回答这条问题”即可开始。技能先确定产品，仅在缺少文档目录或产品不唯一时
集中补问，验证策略后返回带引用的草稿或拒答。显式演示可以用 `--demo --root <公开文档目录>`。
自动接收 Discord 消息需要另外安装监听器。

## 示例输出

通过的一轮返回带引用的 grounded 草稿（`public-faq/faq.md:4`）；被拦/拿不准的一轮只返回一句中性话术
（`这个问题我无法确定，请联系团队进一步确认。`）。JSON 中请求升级不等于已经投递。
`escalate.py --dry-run` 只报告计划；只有 relay 真正成功才标记 `sent=true` 并开始冷却计时。
超时或回执无法确认时，返回 `sent=null` 和 `reconciliation_required=true`，保留私有投递锁。先核对接收端，再处理状态和锁；严重告警也不能绕过这次未确认的投递。

## 局限

自带 CLI 只接受未改写的检索原文及匹配引用，自定义生成器也受这个约束；改写需要另外验证的集成。
拆分较长的散文章节依赖所配置的模型，固定的合成响应只能验证集成行为。Discord 监听、密钥配置、宿主 hook
和真实投递需要单独验证；单元测试通过不会自动开启发布。提醒桥接依赖 `schedule-reminder`。
写运行记录前需要 Git 和已认证的 `gh` 核实所有已配置远端的有效拉取、推送目标都为 PRIVATE，
包括 URL 重写后的目标。默认或分支推送选择必须指向已核实的命名远端；公开目标或无法确认的配置
都会阻止写入。失败时不会回退到工具仓。本技能不安装 OS 沙箱。

## 语言

中文 (`README_CN.md`) · English (`README.md`, 权威版)

## Roadmap · 贡献 · 许可

见 [ROADMAP.md](ROADMAP.md) · [CONTRIBUTING.md](CONTRIBUTING.md) · [LICENSE](LICENSE)(MIT)。
