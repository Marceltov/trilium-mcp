---
status: accepted
date: 2026-09-27
---

# Mermaid diagrams rendered by the docs site, replacing PlantUML PNGs

## Context and Problem Statement

The architecture and flow diagrams were PlantUML sources rendered to PNGs by a pre-commit hook, which needed `plantuml` installed locally and had to be enabled per clone. The PNGs were drawn on white, so on the docs site's dark theme they sat in white panels, and their styling was separate from the site's palette. How should the docs carry diagrams that look consistent with the site in both themes and are easy to change?

## Considered Options

* Keep PlantUML, restyle the theme and render SVGs instead of PNGs.
* Mermaid written inline in the docs pages, rendered by Material for MkDocs in the browser.
* Hand-drawn SVGs.

## Decision Outcome

Chosen option: "Mermaid, rendered by Material for MkDocs", because Material already ships Mermaid support that follows the site's light/dark palette, the diagram source sits next to the text that explains it, and there is no render step, hook or committed image to keep in sync. Hand-drawn SVGs would look most polished but make every change a coordinate edit; restyled PlantUML would still render one fixed color scheme.

Material's Mermaid theme misses a few sequence-diagram elements (lifelines, box borders, step numbers), so `docs/javascripts/mermaid.js` loads Mermaid before Material and wraps its initialize call to add those rules and a compact sequence layout. The colors themselves are CSS variables in `docs/stylesheets/extra.css`.

### Consequences

* Good, because diagrams switch with the site theme and share its palette and font.
* Good, because the `.githooks/pre-commit` hook, `plantuml` and the committed PNGs are gone.
* Bad, because the wrapper depends on Material reusing an already-loaded `mermaid` and on Mermaid's SVG class names; a Material or Mermaid upgrade can break the colors (check both themes after upgrading). Mermaid is pinned in `mkdocs.yml` for that reason.
* Bad, because the diagrams are drawn in the browser, so they don't appear when the Markdown is read outside the site, apart from GitHub's own Mermaid rendering.
