#!/usr/bin/env python3
"""Doctor for the `auto-support-config` companion repo (config-spec E3). Resolves the config dir via
the documented discovery order, selects one product's policy.json, validates it against the per-product
schema, and prints PASS/FAIL per check naming exactly what is missing. Exit 0 = ready, 1 = not ready,
2 = usage error.

Discovery order (config-spec E2):
  1. $AUTO_SUPPORT_CONFIG   2. $AUTO_SUPPORT_CONFIG_DIR   3. ~/.auto-support-config/
  4. ~/.config/auto-support-config/
Product selection: $AUTO_SUPPORT_POLICY (path to products/<slug>/policy.json) wins; else the sole
product under <config>/products/ when exactly one exists.

Usage:
  python verify_config.py [--config-dir <dir>] [--policy <policy.json>] [--slug <name>]
Stdlib only. Never echoes secret values (only presence). A real secret in a committed file is a FAIL.
"""
import argparse
import json
import os
import sys

ENV_VAR = "AUTO_SUPPORT_CONFIG"
PASS, FAIL = "PASS", "FAIL"
REQUIRED_TOP = ["schema_version", "product_slug", "product_root", "index_allowlist",
                "secret_denylist", "confidence", "escalation", "reply_mode", "discord"]
REPLY_MODES = {"draft_human_review", "relay_only", "auto_post"}
ABS_MARKERS = ("C:\\", "C:/", "D:\\", "D:/", "/home/", "/Users/", "/root/")


def discover_config(override):
    if override:
        return os.path.abspath(os.path.expanduser(override)), "explicit (--config-dir)"
    for v in (ENV_VAR, ENV_VAR + "_DIR"):
        val = os.environ.get(v)
        if val:
            return os.path.abspath(os.path.expanduser(val)), "env:%s" % v
    for d in (os.path.expanduser("~/.auto-support-config"),
              os.path.expanduser("~/.config/auto-support-config")):
        if os.path.isdir(d):
            return d, "default:%s" % d
    return None, None


def resolve_policy(cfg, slug, explicit):
    if explicit:
        return os.path.abspath(os.path.expanduser(explicit)), "explicit (--policy)"
    envp = os.environ.get("AUTO_SUPPORT_POLICY")
    if envp:
        return os.path.abspath(os.path.expanduser(envp)), "env:AUTO_SUPPORT_POLICY"
    if not cfg:
        return None, None
    pdir = os.path.join(cfg, "products")
    if slug:
        return os.path.join(pdir, slug, "policy.json"), "slug:%s" % slug
    if os.path.isdir(pdir):
        slugs = [d for d in sorted(os.listdir(pdir)) if os.path.isfile(os.path.join(pdir, d, "policy.json"))]
        if len(slugs) == 1:
            return os.path.join(pdir, slugs[0], "policy.json"), "sole product:%s" % slugs[0]
        if len(slugs) > 1:
            return None, "ambiguous (%d products; set $AUTO_SUPPORT_POLICY or --slug)" % len(slugs)
    return None, None


def main():
    ap = argparse.ArgumentParser(description="Validate the auto-support-config companion repo.")
    ap.add_argument("--config-dir", default=None)
    ap.add_argument("--policy", default=None)
    ap.add_argument("--slug", default=None)
    a = ap.parse_args()

    cfg, how = discover_config(a.config_dir)
    print("Config doctor for skill 'auto-support'")
    print("Discovery env var: %s (and %s_DIR), fallback ~/.auto-support-config" % (ENV_VAR, ENV_VAR))
    if not cfg and not (a.policy or os.environ.get("AUTO_SUPPORT_POLICY")):
        print("  [%s] config located -> none found." % FAIL)
        print("       Set %s=<dir> or run: python scripts/init_config.py" % ENV_VAR)
        return 1
    if cfg:
        print("  config dir via %s -> %s" % (how, cfg))

    policy, phow = resolve_policy(cfg, a.slug, a.policy)
    if not policy or not os.path.isfile(policy):
        print("  [%s] product policy located -> %s" % (FAIL, phow or "none found"))
        print("       Set $AUTO_SUPPORT_POLICY=<...>/products/<slug>/policy.json or --slug <name>.")
        return 1
    print("  policy via %s -> %s" % (phow, policy))
    print("-" * 64)

    results = []

    def check(name, ok, detail=""):
        results.append((name, ok, detail))

    try:
        with open(policy, "r", encoding="utf-8-sig") as f:
            pol = json.load(f)
        check("policy.json valid JSON", True)
    except Exception as e:
        check("policy.json valid JSON", False, str(e))
        pol = None

    if pol is not None:
        for k in REQUIRED_TOP:
            check("required field: %s" % k, k in pol)
        check("schema_version == 1", pol.get("schema_version") == 1,
              "got %r" % pol.get("schema_version"))
        check("index_allowlist is a non-empty list",
              isinstance(pol.get("index_allowlist"), list) and len(pol.get("index_allowlist")) > 0)
        check("secret_denylist is a non-empty list",
              isinstance(pol.get("secret_denylist"), list) and len(pol.get("secret_denylist")) > 0)
        check("reply_mode is valid", pol.get("reply_mode") in REPLY_MODES,
              "got %r (want %s)" % (pol.get("reply_mode"), "|".join(sorted(REPLY_MODES))))
        # E5 self-contained: product_root must be a placeholder, not a baked-in absolute path.
        pr = str(pol.get("product_root", ""))
        check("product_root is a placeholder (self-contained, E5)",
              pr == "<PRODUCT_ROOT>" or not any(m in pr for m in ABS_MARKERS),
              "raw absolute path %r -> resolve via apply.py / per-machine product.json" % pr)
        # Secrets are pointers, never inlined plaintext.
        esc = pol.get("escalation", {}) if isinstance(pol.get("escalation"), dict) else {}
        fc = str(esc.get("founder_channel", ""))
        check("founder_channel is an @secret pointer (not inlined)",
              fc.startswith("@secret:") or fc == "", "got %r" % fc)

    # gitignore secrets gate (E6) at the config-repo root.
    if cfg:
        gi = os.path.join(cfg, ".gitignore")
        gi_ok = os.path.isfile(gi)
        check(".gitignore present", gi_ok)
        if gi_ok:
            txt = open(gi, "r", encoding="utf-8", errors="replace").read()
            check(".gitignore blocks secrets (secrets/* + *.env)",
                  "secrets/" in txt and "*.env" in txt)
        check("secrets/ dir present", os.path.isdir(os.path.join(cfg, "secrets")))

    n_fail = sum(1 for _, ok, _ in results if not ok)
    for nm, ok, detail in results:
        line = "  [%s] %s" % (PASS if ok else FAIL, nm)
        if detail and not ok:
            line += "  -> %s" % detail
        print(line)
    print("-" * 64)
    if n_fail:
        print("NOT READY: %d check(s) failed. Fix the above (or re-run init_config.py)." % n_fail)
        return 1
    print("READY: %s conforms. Fill <PRODUCT_ROOT>/secrets and run apply.py to deploy." % policy)
    return 0


if __name__ == "__main__":
    sys.exit(main())
