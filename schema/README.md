# aiprov namespace

`aiprov: <https://w3id.org/aiprov/ns#>` — an extension to [PROV-O](https://www.w3.org/TR/prov-o/)
for artefacts produced with AI in the loop.

- `aiprov-schema.ttl` — the vocabulary (OWL/RDFS in Turtle). Versioned documents live at
  `https://w3id.org/aiprov/ns/<major.minor>`.
- Classes: `AIAgent`, `HumanAgent`, `ToolAgent` (agents); `AuthoringPass`, `AuditPass`,
  `BuildPass`, `RepairPass` (activities); `Artefact`, `Claim`, `Source`, `Prompt` (entities);
  `VerificationState` with `ladderPosition`.
- Invariants: no parentless claim; the rungs `human-confirmed` and `human-read` may only be
  granted by a `HumanAgent`.
- Attribute catalogue with provider-API mappings: [`../docs/attributes.md`](../docs/attributes.md).

Extend, don't fork: subclass `prov:` and `aiprov:` terms in your own namespace.
