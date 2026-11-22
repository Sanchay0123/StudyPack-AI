"""Models & settings page: provider health, hardware, and a live test prompt."""
from __future__ import annotations

import streamlit as st

from config.hardware import detect_gpus
from config.settings import get_settings
from providers.base import GenerationRequest
from providers.exceptions import ProviderError
from providers.ollama_provider import OllamaProvider
from ui.common import get_router, hero, pill, provider_statuses, stat_card


def render() -> None:
    hero("Models & Settings", "Provider health, hardware, and a live connectivity test.", "System")
    settings = get_settings()

    problems = settings.validate()
    for p in problems:
        st.warning(p)

    st.subheader("Providers")
    primary = st.session_state.get("provider_choice", settings.default_provider)
    if st.button("Refresh status"):
        provider_statuses.clear()
    for s in provider_statuses(primary):
        kind = "ok" if s["available"] else "bad"
        st.markdown(f"{pill('available' if s['available'] else 'unavailable', kind)} **{s['provider']}** — `{s['model']}`  \n{s['message']}",
                    unsafe_allow_html=True)

    st.subheader("Hardware & runtime")
    cols = st.columns(3)
    gpus = detect_gpus()
    with cols[0]:
        if gpus:
            g = gpus[0]
            stat_card("GPU", g.name.replace("NVIDIA GeForce ", ""), f"{g.used_mb} / {g.total_mb} MiB VRAM in use")
        else:
            stat_card("GPU", "None detected", "CPU inference")
    with cols[1]:
        stat_card("Context window", f"{settings.context_length:,} tokens", f"max output {settings.max_output_tokens:,}")
    with cols[2]:
        stat_card("Concurrency", str(settings.max_concurrent_requests), "sequential generation")

    loaded = OllamaProvider(settings).running_models()
    if loaded:
        for m in loaded:
            total, vram = m.get("size", 0), m.get("size_vram", 0)
            share = f"{100 * vram / total:.0f}% on GPU" if total else "unknown"
            st.caption(f"Loaded in Ollama: `{m.get('name')}` — {total / 1e9:.1f} GB total, {share}")
    else:
        st.caption("No model currently loaded in Ollama memory (it loads on first request).")

    with st.expander("Model details"):
        st.json(OllamaProvider(settings).get_model_info())

    st.subheader("Connectivity test")
    prompt = st.text_input("Test prompt", "In one sentence, what is photosynthesis?")
    if st.button("Send test prompt", type="primary"):
        router = get_router()
        with st.spinner("Waiting for the model (first call loads it into memory)..."):
            try:
                result = router.generate(GenerationRequest(system="You are a helpful, concise tutor.", prompt=prompt,
                                                           max_tokens=200, temperature=0.2))
            except ProviderError as exc:
                st.error(f"{exc.__class__.__name__}: {exc}")
            else:
                st.success(f"Response from **{result.provider}** (`{result.model}`) in {result.duration_s:.1f}s"
                           + (f" — {result.output_tokens} tokens" if result.output_tokens else ""))
                st.write(result.text)

    st.subheader("Active configuration")
    st.code("\n".join([
        f"DEFAULT_PROVIDER={settings.default_provider}", f"FALLBACK_PROVIDER={settings.fallback_provider}",
        f"OLLAMA_BASE_URL={settings.ollama_base_url}", f"OLLAMA_MODEL={settings.ollama_model}",
        f"OLLAMA_THINK={settings.ollama_think}", f"GEMINI_MODEL={settings.gemini_model}",
        f"GEMINI_API_KEY={'(set)' if settings.gemini_configured else '(not set)'}",
        f"DEFAULT_CONTEXT_LENGTH={settings.context_length}", f"MAX_OUTPUT_TOKENS={settings.max_output_tokens}",
        f"DB_PATH={settings.db_path}",
    ]), language="ini")
