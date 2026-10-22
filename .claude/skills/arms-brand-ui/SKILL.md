---
name: arms-brand-ui
description: Design rules for every ARMS screen. Use when creating or restyling a template under templates/ or a stylesheet under static/, adding a chart, list, dialog or button, or designing an Excel or PDF export, for any portal (System Administrator, School Head, Registrar, Teacher), the sign-in pages or the landing page, so new work keeps the ARMS palette, layout and the Dean's rulings.
---

# ARMS Brand UI

Build on the shared files instead of styling a page on its own:

- `templates/shared/portal_base.html`: the signed-in layout (sidebar, top bar, cards, buttons, badges, tables, forms) and its CSS variables.
- `static/shared/css/arms-sidebar.css`, `static/shared/css/portal-pages.css`, and `static/shared/css/arms-theme.css`, which loads last: larger text, darker secondary text, red destructive actions.
- `templates/accounts/auth_base.html` with `static/shared/css/auth.css` for sign-in and account pages.
- `static/shared/logo/arms-mark.svg` is the logo source. Every standalone page includes `{% include 'shared/_favicon.html' %}`, and sidebars show `<img class="brand-mark">`, not a per-portal icon.

## Palette

| Use | Value |
|---|---|
| Page background | `--gray-bg` #f5f7fb; cards are white, radius 20px, `--card-shadow` |
| Buttons, links, focus rings, accents | palette blue #123499 (`--caribbean-blue`; `--secondary-green` holds the same blue despite its name), hover #051650, light #4a6fd4 |
| Brand and AI elements | `--ai-gradient` #667eea to #764ba2: the logo tile, the active sidebar item, Poro AI panels |
| Text | `--text-primary` #2d3748, `--text-secondary` #4a5568, headings `--rich-black` #00072D |
| Status pills | traffic-light badges: `.badge-success`, `.badge-warning`, `.badge-danger` |
| Destructive actions | red #dc3545 for delete, remove, drop, deactivate and log out (`.btn-danger-outline`) |

Never use dark navy (#00072D or #051650) as the background of a sidebar, dialog or page. Never use green for buttons or accents. Never hardcode colors that a variable already names.

## Type and icons

- Portal text uses 'Segoe UI', 'Century Gothic', sans-serif. Landing page and logo headings use Inter 800.
- Icons are Flaticon UIcons (`<i class="fi fi-rr-...">`), already loaded by `portal_base.html`.
- No emojis anywhere: templates, messages, exports and Poro AI text.

## Layout rules from the Dean's review

1. Show one overall status for the current selection (for example "Approaching Proficiency"), not one card per proficiency level.
2. Don't add a chart that repeats what a status card or table already says. Prefer one direct visual plus a table.
3. On the School Head dashboard, the sections table is visible right after sign-in, and its rows open the section page.
4. "Show all" opens a modal dialog with search and sort; it never stretches the card. Offer only sort keys that change the order.
5. Charts that compare many items use one row per item on a shared scale. Legend markers are true circles.
6. Exports look designed: a title block with the school's name, a styled header row and readable column widths. Never a bare CSV.

## Words

- The product is "ARMS". Never write the retired name Formify. "LIS" refers to DepEd's Learner Information System.
- Use plain, specific labels such as "Learners below 75" and "Download report".
- Cite the source of a rule where it shows, for example "Remediation is required (DepEd Order No. 8, s. 2015)".
- Facts about the partner school, NPTCI, come only from its supplied seal and photos.

## Before you finish

- View the page signed in at desktop width and at phone width. The sidebar folds away at 768px and below.
- Put it next to an existing page of the same portal; spacing, card style and buttons should match.
- When `frontend-design` suggests a new palette or typeface, keep these rules instead. That skill helps with hierarchy and copy, not with replacing the brand.
