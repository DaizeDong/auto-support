"""Synthetic scope interpretations authored independently of the production parser.

This intercepts only llmcall.call. Expectations come from named generator recipes;
unknown documents receive no interpretation. It does not measure model accuracy.
"""
from functools import wraps
import hashlib
import itertools
import json
import sys
from types import SimpleNamespace


def install(monkeypatch, fixtures):
    documents = {}
    missing = []
    unrelated = {
        ("instruction_case", "large"): {"Background", "Glossary"},
        ("procedure_case", "large"): {"Reference appendix", "Terminology appendix"},
        ("prose_dependency_case", "unrelated"): {"Typography discussion"},
        ("prose_dependency_case", "unrelated-appendix"): {"Verification", "Snapshot inventory"},
        ("scoped_document_case", "local-before"): {"Background"},
        ("scoped_document_case", "local-after"): {"Background"},
        ("semantic_scope_case", "unrelated"): {"Exhibition catalogue"},
    }

    def wrap(name):
        original = getattr(fixtures, name)

        @wraps(original)
        def generate(*args, **kwargs):
            result = original(*args, **kwargs)
            content = result[1]
            digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
            kind = args[1] if len(args) > 1 else kwargs.get("kind", kwargs.get("relationship"))
            documents[digest] = unrelated.get((name, kind), set())
            return result
        return generate

    for name in ("instruction_case", "procedure_case", "prose_dependency_case",
                 "scoped_document_case", "markdown_preparation_case", "semantic_scope_case"):
        monkeypatch.setattr(fixtures, name, wrap(name))

    def call(prompt, *, schema):
        request = json.loads(prompt.split("SCOPE_DOCUMENT_JSON\n", 1)[1])
        digest = request["source_sha256"]
        if digest not in documents:
            missing.append(digest)
            return SimpleNamespace(data=None, provider=None, error="unregistered synthetic source")
        independent = documents[digest]
        sections = request["sections"]
        lines = request["lines"]
        relations = []
        for left, right in itertools.combinations(sections, 2):
            headings = {lines[item["start"]].strip().lstrip("#").strip() for item in (left, right)}
            if left["key"] == -1:
                relation = "right_requires_left"
            elif headings & independent:
                relation = "independent"
            else:
                relation = "mutual"
            relations.append({"left": left["key"], "right": right["key"], "relation": relation,
                              "evidence": [dict(left), dict(right)],
                              "explanation": "Relationship specified by this synthetic document's author."})
        data = {"source_sha256": digest, "relations": relations}
        return SimpleNamespace(data=data, provider="synthetic-intercept", error=None, text=json.dumps(data))

    module = SimpleNamespace(call=call, missing=missing)
    monkeypatch.setitem(sys.modules, "llmcall", module)
    return module
