"""Reusable rendering components (Mermaid diagrams, provenance-labelled sections, sources)."""
from __future__ import annotations

import html
import json
from typing import Any

import streamlit as st
import streamlit.components.v1 as components

from ui.common import pill

PROV = {"source": ("From source", "ok"), "supplementary": ("Supplementary", "warn"), "inferred": ("Inferred", "bad")}


def mermaid(code: str, height: int = 380, key: str = "") -> None:
    """Render Mermaid client-side with the vendored library (static/mermaid.min.js, works offline)."""
    payload = json.dumps(code)
    components.html(f"""
<div id="m{key}" style="font-family: sans-serif;"></div>
<pre id="e{key}" style="display:none;color:#9B2C2C;white-space:pre-wrap;font-size:12px"></pre>
<script src="/app/static/mermaid.min.js"></script>
<script>
  (async () => {{
    const el = document.getElementById("m{key}");
    try {{
      mermaid.initialize({{startOnLoad: false, theme: "neutral", securityLevel: "strict"}});
      const {{svg}} = await mermaid.render("g{key}", {payload});
      el.innerHTML = svg;
    }} catch (err) {{
      const e = document.getElementById("e{key}");
      e.style.display = "block";
      e.textContent = "This diagram could not be rendered (" + err.message + "). Source:\\n" + {payload};
    }}
  }})();
</script>""", height=height, scrolling=True)


def provenance_badge(provenance: str) -> str:
    label, kind = PROV.get(provenance, (provenance or "unlabelled", "muted"))
    return pill(label, kind)


def source_refs(labels: list[str], sources: dict[str, Any]) -> list[str]:
    return list(dict.fromkeys(sources[l]["ref"] for l in labels if l in sources))


def render_note_section(section: dict[str, Any], sources: dict[str, Any], chunk_lookup: dict[str, str] | None = None,
                        highlight: str = "") -> None:
    prov = section.get("provenance", "inferred")
    st.markdown(f"#### {section['heading']}")
    refs = source_refs(section.get("source_labels", []), sources)
    ref_text = " · ".join(html.escape(r) for r in refs)
    edited = pill("edited by you", "muted") if section.get("edited_by_user") else ""
    st.markdown(f"{provenance_badge(prov)}{edited} <span class='sp-ref'>{ref_text}</span>", unsafe_allow_html=True)
    content = section.get("content", "")
    if highlight:
        content = _highlight(content, highlight)
    with st.container():
        st.markdown(f"<div class='sp-prov-{prov}'>", unsafe_allow_html=True)
        st.markdown(content)
        st.markdown("</div>", unsafe_allow_html=True)
    if chunk_lookup is not None and section.get("source_labels"):
        with st.expander("Show supporting source text"):
            for label in section["source_labels"]:
                info = sources.get(label)
                if not info:
                    continue
                st.caption(info["ref"])
                st.text(chunk_lookup.get(info["chunk_id"], "(source chunk no longer available)")[:2500])


def _highlight(text: str, query: str) -> str:
    import re
    if not query.strip():
        return text
    return re.sub(f"({re.escape(query)})", r"**\1**", text, flags=re.I)


def empty_state(message: str) -> None:
    st.markdown(f"<div class='sp-card' style='text-align:center;color:#6B7280'>{html.escape(message)}</div>", unsafe_allow_html=True)
