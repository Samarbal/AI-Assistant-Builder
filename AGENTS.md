# Project rules for AI development

## Project context

This project is an AI Assistant Builder platform: users create and configure specialized AI assistants, ground them with their own knowledge, test them, publish them, and embed them into external websites.

## Development rules

- Capture intent before writing specifications, implementation plans, or application code. Use the existing `.agents/skills/intent-interview/SKILL.md` for intent interviews and preserve that skill unchanged.
- Use `docs/glossary.md` for established terminology and `intent/_template.md` for intent documents.
- Record unknowns as open questions. Do not invent requirements or present assumptions as agreed decisions.
- Keep intent documents in draft status after an interview. Do not infer approval from their existence.
- Keep work within the requested scope. At this foundation stage, do not create application code, initialize FastAPI, define a database schema, or select AI providers, vector databases, or infrastructure.
- Add specifications, plans, and architecture decision records only when the corresponding work is requested and supported by established intent. Record decisions with their rationale; leave undecided choices open.
- Preserve unrelated files and user changes. Validate documentation for consistency and report exactly what changed.

## Documentation locations

- `intent/`: problem, users, goals, workflows, scope, constraints, and open questions.
- `docs/glossary.md`: established project terminology.
- `docs/ai-sdlc/specs/`: future specifications.
- `docs/ai-sdlc/plans/`: future implementation plans.
- `docs/ai-sdlc/adr/`: future architecture decision records.
