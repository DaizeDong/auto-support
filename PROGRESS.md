# auto-support — PROGRESS

> 注:stage-1 审计声称已写入本仓 PROGRESS.md，但本文件此前在仓内不存在（未持久化到
> CodesSelf/auto-support）。本文件由第二轮再迭代会话新建，仅记录第二轮内容。

### 第二轮再迭代+修复(auto-support)

日期 2026-06-25。基线 78 测试全绿、check_conformance 20/20。本轮按 stage-1 审计修复全部
security_issues（2 HIGH / 1 MED / 2 LOW），每项配「会失败→修复后通过」回归守卫；并对
target 跑了一轮 self-evolve。结果 97 测试全绿，零既有契约破坏（向后兼容）。

#### 已修（每项均经 HEAD 源实证「修前确有缺口」）
- **HIGH-1 路径遍历击穿知识边界**（guardrails.path_verdict）：新增 `_has_traversal`，对任何
  含 `..` 段的路径 fail-closed DENY（reason=`path-traversal`），覆盖 `%2e%2e`、双重 percent
  (`%252e%252e`)、`..%2f`、反斜杠 `..\\` 等编码形。修前实证：HEAD 源 `docs/../src/ranking.py`
  → allowed=True；真 hook `Read{docs/../secrets/customers.csv}` → exit0 ALLOW。修后全 DENY。
- **HIGH-2 PreToolUse Bash 闸 fail-OPEN + 解释器绕过**（pretooluse_hook.py Bash 分支）：
  末尾 `allow()` 改 **默认 DENY**（仅 echo/pwd/ls/… 安全前导命令或显式 read 工具放行）；
  新增 `_BASH_INTERP`（python/python3/node/perl/ruby/php/deno/bun/lua/dd/tr/cut/xargs/eval/
  exec/source）一律 block；新增 `_BASH_INREDIR` 解析 `< path` 输入重定向并 path-check。
  修前实证：HEAD hook `python -c open('.env')` → exit0、`tr a-z A-Z < .env` → exit0。修后全 exit2。
- **MED egress 软泄露漏 base85/rot13**（guardrails.egress_leak_verdict）：新增 `_b85_views`
  （base85/ascii85 解码）+ 把 `_caesar_views`（rotN/ROT13）接到 egress 复扫。修前实证：
  base85/rot13 包裹的 `PROPRIETARY_RANKING_FORMULA_CANARY` → safe=True。修后 safe=False。
- **LOW 入口注入漏检 base32/percent/交错单字符**（detect_injection/_decode_layers）：
  `_decode_layers` 加 base32 视图；detect_injection 加 percent-decode 派生视图 + de-spaced
  长短语(≥12 去空格)子串匹配（catch `i-g-n-o-r-e p-r-e-v-i-o-u-s`）。修前实证三者均
  suspicious=False，修后均 True；benign 仍不误报。
- **LOW 仓无通用 .env ignore**（.gitignore）：加 `.env`/`**/.env`/`**/.env.*` 防御性忽略，
  并 `!**/tests/fixtures/**/.env*` 反忽略保留 mock canary fixture（实证：根 .env 被 ignore，
  mock fixture .env 仍 NOT-IGNORED 保持 tracked）。

回归守卫新增 **19 个测试函数**（97 总，全绿）：
- `tests/test_security_fixes.py`（11）：路径遍历(明文/编码/benign)、egress base85+rot13(+sanity+FP)、
  入口 base32/percent/interleaved(+FP)。
- `tests/test_pretooluse_hook.py`（8，**端到端子进程驱动真 hook**，填补 stage-1 spec-gap#4
  「hook 从未在攻击者可控路径下被测」）：Read 遍历/直读/公共、Bash 解释器/`<`重定向/默认 deny/
  benign 放行、write/net/未知 mcp/无 path 契约。
- 全部判据客观（path_verdict().allowed / egress_leak_verdict().safe / detect_injection().suspicious /
  hook 退出码），非「guard 自称」。

#### 本轮 self-evolve（run d7cb924a13dd, base-ref=HEAD@修复 commit, tier=A）
- **--live**：后台启动 + monitor。到 PROFILE(tier=A) → REFLECT(round1) 即停滞（双 `cc`+`codex exec`
  校验慢；Windows GBK 环境，与前 6 批 live REFLECT 挂起/崩同因），**~未达 JUDGE**，按协议切 builtin。
- **--proposer builtin --single**：跑完判决，`accepted_versions=[]`、final_phase=PROPOSE
  —— builtin 为确定性占位 proposer，无法合成真实改进 → 0 候选可判（与前 6 批同），**自迭代闭环
  仍未实现**。
- 故本轮**真增益来自人作 proposer 落地**（上列 5 修复 + 19 守卫），acceptor 信号 = A 档 pytest
  78→97 全绿；harness 自动 ACCEPT = 0（如实）。

#### net_gain（本轮）
**有**：安全维度 (0→1) 实增益——堵死 2 个 HIGH（路径遍历端到端放行机密 / Bash fail-OPEN 解释器
绕过），1 MED + 2 LOW；新增 19 守卫含首套 hook 端到端 enforcement 测试。修复后 SKILL.md/
PHILOSOPHY「机密物理读不到」「覆盖 python open('.env')/cat .env」「fail-closed」诸承诺由
「文档声称但被绕过」转为「测试可证」。

#### 残留 / 未尽
- self-evolve **自动 proposer 闭环仍未通**（builtin 占位 0-accept；live 在本机 GBK 下 REFLECT
  停滞未达 JUDGE）——增益持续靠人作 proposer；自迭代 harness 仅供 A 档 pytest 信号。
- spec_gaps（stage-1，状态未变，均为已诚实标注的 deferred）：G1/G2 held-out 量化 v0.2 才接线；
  真实产品根对接 / Discord bot 注册 / 私有 config 仓首推 / WSL2 OS sandbox 仍 DEFERRED
  （Win11 无原生 sandbox，纵深防御 = 权限层 + hook；本轮已补齐 hook 端到端测试，两 HIGH 既闭）。
- budget 库级 WARNING 90%（73 skill 共 ~13466/15000）非本 skill 引入（自身 desc 113 字符），
  属库级总量逼近静默截断，待库级治理。
- 提交：本轮修复 + 守卫已本地 commit（未 push，留待用户）。
