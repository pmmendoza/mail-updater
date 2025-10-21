# AGENT Instruction Alignment — 2025-10-20

## 1. Inconsistencies & Proposed Resolutions

| Topic | AGENTS.md | AGENTS_TODO.md | Issue | Proposed Resolution |
|-------|-----------|----------------|-------|---------------------|
| Command triggers | Mentions #plan/#do only implicitly via chat commands section | Explicitly defines #plan/#do procedures | AGENTS.md lacks clarity that only these two commands (plus open prompts) should be used to instruct the agent | Update AGENTS.md §3 to state clearly that supported entry points are `#plan`, `#do`, or natural-language prompts. |
| Allowed files during #plan | AGENTS.md does not limit file edits | AGENTS_TODO.md §3.1 forbids editing other files | Potential conflict if AGENTS.md is interpreted as general permission | Amend AGENTS.md to cross-reference AGENTS_TODO rules when executing #plan; clarify in #plan steps that only AGENTS_TODO.md (and change log if needed) may be edited. |
| Session notification workflow | AGENTS.md mandates say/ntfy usage | AGENTS_TODO.md does not mention notifications | Could lead to redundant or missed instructions | Mirror the notification summary in AGENTS_TODO.md or reference AGENTS.md explicitly under “Session start” to avoid drift. |
| Mode declaration | AGENTS.md requires setting mode at top of AGENTS_TODO.md | AGENTS_TODO.md currently lacks `session:` header from earlier versions | Missing mode could violate AGENTS.md rule | Reintroduce `session: mode=...` header in AGENTS_TODO.md and ensure instructions remind agent to update it. |
| Task status flow | AGENTS.md (#do) expects statuses `[d]→[/]→[P]→[N]→[E]→[>]` | AGENTS_TODO.md uses `[>]`, `[x]`, etc. but doesn’t restate flow | Agent might forget intermediate states | Add a short reminder in AGENTS_TODO.md “Statuses” section to mirror the status flow from AGENTS.md. |

## 2. Planned Adjustments

### AGENTS.md
1. Update §3 (Chat Commands) to explicitly state that user entry points are either `#plan`, `#do`, or a natural-language instruction, and that the agent must follow the corresponding procedures in AGENTS_TODO.md.
2. Add cross-reference in §3.1/§3.2 indicating file-edit constraints for #plan vs #do (pointing to AGENTS_TODO.md requirements).
3. Mention in §0 that AGENTS_TODO.md contains live sprint/task data and must include a `session:` mode line.

### AGENTS_TODO.md
1. Reintroduce a header such as `session: mode=local-edit` (or current mode) to comply with AGENTS.md §1.
2. In §0 Notation, add a sentence referencing the status flow and pointer to AGENTS.md.
3. Under a new “Session Start” note, reference the notification steps in AGENTS.md so both files stay aligned.
4. Maintain the new #plan/#do instructions but ensure they refer back to AGENTS.md for general policy.
5. Keep sprint and project structure while ensuring tasks reference the desired mode/status flow.

These changes keep AGENTS.md as the canonical policy document while making AGENTS_TODO.md the actionable sprint board, aligned with the updated command workflow.
