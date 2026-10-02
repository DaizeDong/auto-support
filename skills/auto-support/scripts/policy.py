"""One policy schema for the initializer, doctor, hook, and draft CLI."""
from __future__ import annotations

import json
import math
from pathlib import Path
import re

DEFAULT_ALLOW = ["README*", "docs/**", "public-faq/**", "CHANGELOG*", "examples/**", "**/*.example"]
DEFAULT_DENY = ["**/.env", "**/.env.*", "*.pem", "*.key", "id_rsa", "secrets/**",
                "credentials/**", "vault/**", "src/**", "internal/**", "proprietary/**",
                "algorithms/**", "**/customer_data/**", "**/*.pii.*", "**/CLAUDE.md", ".git/**"]
DEFAULT_CONFIDENCE = {"retrieval_min": 0.7, "faithfulness_min": 0.7, "high_band": 0.9}
REPLY_MODES = {"draft_human_review", "relay_only", "auto_post"}


class PolicyError(ValueError):
    pass


def valid_slug(value):
    return isinstance(value, str) and re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", value) is not None


def validate_policy(value):
    if not isinstance(value, dict):
        raise PolicyError("policy must be a JSON object")
    required = ("schema_version", "product_slug", "product_root", "index_allowlist",
                "secret_denylist", "confidence", "escalation", "reply_mode", "discord")
    missing = [key for key in required if key not in value]
    if missing:
        raise PolicyError("policy missing required fields: " + ", ".join(missing))
    if type(value["schema_version"]) is not int or value["schema_version"] != 1:
        raise PolicyError("policy schema_version must be 1")
    if not valid_slug(value["product_slug"]):
        raise PolicyError("policy product_slug must be a kebab-case slug")
    if not isinstance(value["product_root"], str) or not value["product_root"].strip():
        raise PolicyError("policy product_root must be a nonempty string")
    for key in ("index_allowlist", "secret_denylist"):
        items = value[key]
        if not isinstance(items, list) or not items or any(not isinstance(x, str) or not x.strip() for x in items):
            raise PolicyError("policy " + key + " must be a nonempty list of nonempty strings")
    conf = value["confidence"]
    if not isinstance(conf, dict):
        raise PolicyError("policy confidence must be an object")
    for key in DEFAULT_CONFIDENCE:
        n = conf.get(key)
        if type(n) not in (int, float) or not math.isfinite(n) or not 0 <= n <= 1:
            raise PolicyError("policy confidence." + key + " must be a number from 0 to 1")
    if conf["high_band"] < max(conf["retrieval_min"], conf["faithfulness_min"]):
        raise PolicyError("policy high_band must be at least both minimum thresholds")
    if not isinstance(value["reply_mode"], str) or value["reply_mode"] not in REPLY_MODES:
        raise PolicyError("policy reply_mode is invalid")
    for key in ("escalation", "discord"):
        if not isinstance(value[key], dict):
            raise PolicyError("policy " + key + " must be an object")
    return value


def load_policy(path):
    try:
        with Path(path).expanduser().open(encoding="utf-8-sig") as stream:
            value = json.load(stream)
    except (OSError, ValueError) as exc:
        # Never echo policy contents, which may contain misconfigured secrets.
        raise PolicyError("policy cannot be read as JSON (" + type(exc).__name__ + ")") from exc
    return validate_policy(value)


def resolve_product_root(policy_path, value):
    root = value["product_root"]
    if root == "<PRODUCT_ROOT>":
        try:
            product = json.loads(Path(policy_path).with_name("product.json").read_text(encoding="utf-8-sig"))
        except (OSError, ValueError) as exc:
            raise PolicyError("product.json is missing or invalid") from exc
        if not isinstance(product, dict) or product.get("slug") != value["product_slug"]:
            raise PolicyError("product.json slug does not match the policy")
        root = product.get("product_root")
    if not isinstance(root, str) or not root.strip() or "<" in root or not Path(root).expanduser().is_absolute():
        raise PolicyError("product_root must resolve to an absolute directory in product.json")
    result = Path(root).expanduser().resolve()
    if not result.is_dir():
        raise PolicyError("resolved product_root directory does not exist")
    return result
