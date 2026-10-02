# Document scope and completeness

The extractor keeps a document preamble as a separately cited source range. A local
prerequisite in that range does not make every sibling chapter mandatory. Explicit
same-document Markdown references retain their target sections, including transitive
dependencies. Missing targets cause refusal.

Bounded neighboring sections and structured procedure blocks remain together. A large
plain-prose peer is a possible chapter boundary, not proof of an independent chapter.
Before using such a boundary, the extractor asks installed `llmcall.call` to interpret
the complete admitted document. It supplies every candidate section, exact source
ranges and their digests. It requires one directional dependency, independence or
uncertainty judgment for every section pair, with source evidence and an explanation.
Prose independence is not inferred from an obligation-word list, and documents need no
special annotations.

The model uses llmcall's current default judge routing, model, timeout and fallback policy.
The complete document is screened for detected secrets, PII and injection indicators
before it reaches that transport. No excerpts are substituted for the full document
during scope interpretation. If the interpreter is unavailable, returns uncertainty,
omits a pair, repeats a pair, names an unknown section or changes a source range or
digest, extraction is incomplete and the draft pipeline refuses a matching document.
It does not fall back to assuming the prose is unrelated.

Validated semantic dependencies are added to the source graph alongside preamble,
Markdown-reference and bounded-group edges. The extractor takes dependency closure
before applying the total retrieval budget. Required material that exceeds that budget
causes refusal; a positively interpreted unrelated chapter can stay outside the answer.
All emitted text remains an exact, cited source range.

`retrieval.search()` exposes `scope_graphs` with document digests, section ranges,
dependencies and the semantic pair interpretations. Runtime interpretations stay in
memory here; there is no new persistence path or public-tool DATA fallback. The installed
llmcall interface retains its own configured private operational logging policy.

`verify_source()` checks source identity, range hashes and existing endpoints. The
semantic response binder additionally requires exhaustive pair coverage and exact
endpoint evidence records. These checks establish provenance and structural validity.
They do not prove that a model understood the document correctly or that a declared
independence is semantically true. Literal citation fidelity also does not prove procedure
completeness. Independent semantic effectiveness checks remain necessary.

The business tests intercept only the model transport with interpretations authored from
synthetic generator recipes. Production parsing, binding, closure, extraction and answer
gates still execute. Missing synthetic responses are explicit test transport failures;
they are not silently treated as valid independent sections. Passing those tests proves
the integration behavior under those responses, not a real model's reliability.
