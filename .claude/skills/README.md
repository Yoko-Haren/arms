# Skills for ARMS

Each folder holds one skill: a `SKILL.md` that teaches an AI agent one task, plus any files it needs. Claude Code loads them from here automatically. `CLAUDE.md` at the repository root says when each one applies.

## Written for ARMS

| Skill | Use it for |
|---|---|
| [arms-brand-ui](arms-brand-ui/SKILL.md) | Any page, chart, dialog or export: palette, layout, the Dean's rulings |
| [deped-school-forms](deped-school-forms/SKILL.md) | SF1 imports, e-class records and school forms on DepEd's templates |
| [arms-verify](arms-verify/SKILL.md) | The checks to run before a commit, including a signed-in page check for every role |

## Installed from providers

Copied unchanged from each provider's repository at the commit shown, with its license.

| Skill | Provider and source | License |
|---|---|---|
| [frontend-design](frontend-design/SKILL.md) | Anthropic, [anthropics/skills@dbd4588](https://github.com/anthropics/skills/tree/dbd4588f9e1033efb41dad4bef2f7947c8993d44/skills/frontend-design) | Apache-2.0 ([LICENSE.txt](frontend-design/LICENSE.txt)) |
| [web-design-guidelines](web-design-guidelines/SKILL.md) | Vercel, [vercel-labs/agent-skills@063bee9](https://github.com/vercel-labs/agent-skills/tree/063bee94c3f4df8453406c830b0a7df0f2860278/skills/web-design-guidelines) | MIT, per the repository's README |
| [supabase-postgres-best-practices](supabase-postgres-best-practices/SKILL.md) | Supabase, [supabase/agent-skills@c9be0e9](https://github.com/supabase/agent-skills/tree/c9be0e931b7930f7d02126d04774d904c381e7d7/skills/supabase-postgres-best-practices) | MIT ([LICENSE.txt](supabase-postgres-best-practices/LICENSE.txt)) |

When `frontend-design` and `arms-brand-ui` disagree, `arms-brand-ui` wins. ARMS keeps its own palette and type.
