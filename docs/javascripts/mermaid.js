// Material for MkDocs renders Mermaid itself, but reuses a `mermaid` that is
// already on the page (loaded just before this file in mkdocs.yml). Wrap its
// initialize call to fill gaps in Material's Mermaid theme: Mermaid's own
// defaults otherwise win for lifelines, box borders and step numbers.
const extraCSS = `
  .actor-line { stroke: var(--md-mermaid-sequence-actor-line-color) !important; }
  rect.rect { stroke: none !important; }
  [id$="sequencenumber"] { fill: var(--md-mermaid-sequence-number-bg-color) !important; }
  .sequenceNumber { font-weight: 700; }
  .node:not(.accent) rect,
  .node:not(.accent) path {
    stroke: var(--md-mermaid-sequence-actor-border-color) !important;
  }
  .node rect { rx: 6px; ry: 6px; }
  .accent .nodeLabel, .accent .nodeLabel p { color: #10200c !important; }
  .cluster rect {
    fill: var(--md-mermaid-sequence-box-bg-color) !important;
    stroke: none !important;
    rx: 10px;
    ry: 10px;
  }
  .cluster .nodeLabel, .cluster-label span {
    color: var(--md-mermaid-sequence-box-fg-color) !important;
  }
`;

const initialize = mermaid.initialize.bind(mermaid);
mermaid.initialize = (config) =>
  initialize({
    ...config,
    themeCSS: (config.themeCSS || "") + extraCSS,
    sequence: {
      ...config.sequence,
      // Compact enough that most diagrams fit the column without shrinking.
      actorFontSize: "14px",
      messageFontSize: "14px",
      noteFontSize: "14px",
      width: 110,
      actorMargin: 30,
      boxMargin: 8,
      noteMargin: 8,
      messageMargin: 30,
      mirrorActors: false,
    },
  });
