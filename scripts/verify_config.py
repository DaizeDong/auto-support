#!/usr/bin/env python3
"""Doctor for the `auto-support-config` companion repo (config-spec E3). Resolves the config dir via
the documented discovery order, selects one product's policy.json, validates it against the per-product
schema, and prints PASS/FAIL per check naming exactly what is missing. Exit 0 = ready, 1 = not ready,
2 = usage error.

Discovery is shared with runtime_data and pinned Guards: doctor --config-dir, then
AUTO_SUPPORT_DATA_DIR, AUTO_SUPPORT_CONFIG, AUTO_SUPPORT_CONFIG_DIR, proven sibling,
~/.auto-support-config and legacy ~/.auto-support-data. Invalid explicit selections fail.
The initializer's --out is a separate deliberate creation destination.
Product selection: $AUTO_SUPPORT_POLICY (path to products/<slug>/policy.json) wins; else the sole
product under <config>/products/ when exactly one exists.

Usage:
  python verify_config.py [--config-dir <dir>] [--policy <policy.json>] [--slug <name>]
Stdlib only. This reports schema and local draft readiness; it does not scan committed secret values.
"""
import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills/auto-support/scripts"))
import policy as P

ENV_VAR = "AUTO_SUPPORT_CONFIG"
PASS, FAIL = "PASS", "FAIL"
REQUIRED_TOP = ["schema_version", "product_slug", "product_root", "index_allowlist",
                "secret_denylist", "confidence", "escalation", "reply_mode", "discord"]
REPLY_MODES = {"draft_human_review", "relay_only", "auto_post"}


def discover_config(override):
    import runtime_data
    root = runtime_data._guard_base(companion=True, override=override, required=False)
    return (str(root), 'shared companion resolver') if root else (None, None)


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
    if a.slug and not P.valid_slug(a.slug):
        ap.error("--slug must be a kebab-case product slug")

    try:
        cfg, how = discover_config(a.config_dir)
    except RuntimeError as exc:
        print("NOT READY: " + str(exc))
        return 1
    print("Config doctor for skill 'auto-support'")
    print("Discovery: shared runtime companion resolver; see CONFIG.md")
    if not cfg and not (a.policy or os.environ.get("AUTO_SUPPORT_POLICY")):
        print("  [%s] config located -> none found." % FAIL)
        print("       Set %s=<dir> or run: python scripts/init_config.py" % ENV_VAR)
        return 1
    if cfg:
        print("RESOLVED: " + cfg)
        print("  config dir via %s -> %s" % (how, cfg))

    policy, phow = resolve_policy(cfg, a.slug, a.policy)
    if not policy or not os.path.isfile(policy):
        print("  [%s] product policy located -> %s" % (FAIL, phow or "none found"))
        print("       Set $AUTO_SUPPORT_POLICY=<...>/products/<slug>/policy.json or --slug <name>.")
        return 1
    if not cfg:
        cfg = str(Path(policy).resolve().parents[2])
    if not Path(policy).resolve().is_relative_to(Path(cfg).resolve() / "products"):
        print("NOT READY: selected policy must belong to the resolved companion products directory")
        return 1
    print("  policy via %s -> %s" % (phow, policy))
    print("-" * 64)

    results = []

    def check(name, ok, detail=""):
        results.append((name, ok, detail))

    try:
        pol = P.load_policy(policy)
        check("policy.json schema", True)
    except P.PolicyError as e:
        check("policy.json schema", False, str(e))
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
        # Private per-product policies may select an absolute root directly.
        # The shared resolver below validates both documented selection modes.
        # Secrets are pointers, never inlined plaintext.
        esc = pol.get("escalation", {}) if isinstance(pol.get("escalation"), dict) else {}
        fc = str(esc.get("founder_channel", ""))
        check("founder_channel is an @secret pointer (not inlined)",
              fc.startswith("@secret:") or fc == "", "use an @secret reference")

    # ---- registry.json: the config repo's own manifest ----
    # Found by config_mutation_probe: this file was never named in this script, so
    # deleting or emptying it left the doctor printing READY. A doctor that says
    # "conforms" while the manifest it conforms to is missing is worse than silent.
    if cfg:
        reg_p = os.path.join(cfg, "registry.json")
        reg = None
        if not os.path.isfile(reg_p):
            check("registry.json present", False, reg_p)
        else:
            check("registry.json present", True)
            try:
                with open(reg_p, "r", encoding="utf-8-sig") as f:
                    reg = json.load(f)
                check("registry.json valid JSON", True)
            except Exception as e:
                check("registry.json valid JSON", False, str(e))
            if isinstance(reg, dict):
                check("registry.schema_version == 1", reg.get("schema_version") == 1,
                      "got %r" % reg.get("schema_version"))
                check("registry.products is a non-empty list",
                      isinstance(reg.get("products"), list) and len(reg.get("products")) > 0,
                      "got %r" % type(reg.get("products")).__name__)
                check("registry.mode is a string", isinstance(reg.get("mode"), str),
                      "got %r" % type(reg.get("mode")).__name__)
                check("registry.spec is a string", isinstance(reg.get("spec"), str),
                      "got %r" % type(reg.get("spec")).__name__)
                check("registry includes the selected product", bool(pol) and isinstance(reg.get("products"), list) and pol["product_slug"] in reg["products"])
            else:
                check("registry.json is an object", False,
                      "top level is %s" % type(reg).__name__)

    # ---- product.json: the per-machine half of the policy ----
    # policy.json carries <PRODUCT_ROOT> as a placeholder on purpose (E5); product.json is
    # where the real path lives. It was mentioned only in a comment here, and all 23 field
    # mutations were accepted -- meaning a product.json with no product_root at all passed.
    prod_p = os.path.join(os.path.dirname(policy), "product.json") if policy else None
    check("product.json present", bool(prod_p and os.path.isfile(prod_p)))
    if prod_p and os.path.isfile(prod_p):
        prod = None
        try:
            with open(prod_p, "r", encoding="utf-8-sig") as f:
                prod = json.load(f)
            check("product.json valid JSON", True)
        except Exception as e:
            check("product.json valid JSON", False, str(e))
        if isinstance(prod, dict):
            check("product.slug is a non-empty string",
                  isinstance(prod.get("slug"), str) and bool(prod.get("slug")))
            check("product.slug matches policy", bool(pol) and prod.get("slug") == pol["product_slug"])
            root = prod.get("product_root")
            check("product.product_root is a non-empty string",
                  isinstance(root, str) and bool(root), "got %r" % type(root).__name__)
            if isinstance(root, str) and root:
                # The placeholder belongs in policy.json, never here: this file is the
                # machine-specific half, so an unresolved placeholder means the
                # operator has not yet configured the documentation directory.
                check("product.product_root is resolved (not the placeholder)",
                      "<PRODUCT_ROOT>" not in root)
            check("product.status supports drafts", isinstance(prod.get("status"), str) and prod.get("status") in ("draft", "active"),
                  "got %r" % type(prod.get("status")).__name__)
        else:
            check("product.json is an object", False,
                  "top level is %s" % type(prod).__name__)
    if pol:
        try:
            P.resolve_product_root(policy, pol)
            check("product documentation root resolves", True)
        except P.PolicyError as exc:
            check("product documentation root resolves", False, str(exc))

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
    print("READY: DRAFT READY: policy and public-docs root validated. Discord delivery and live retrieval remain unverified.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
