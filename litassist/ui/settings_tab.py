import streamlit as st

from litassist import ai, config
from litassist.pubmed import PubMed, PubMedError
from litassist.sources import OpenAlex, SourceError
from litassist.ui.common import flash, show_flash
from litassist.zotero import Zotero, ZoteroError


def render(settings: dict) -> None:
    st.subheader("Settings")
    st.caption(f"Your data and settings are stored in {config.data_dir()}. Keys stay on this computer and are only "
               "sent to the service they belong to.")
    show_flash("settings")
    with st.form("settings"):
        st.markdown("**Searching**")
        email = st.text_input("Your email (PubMed, Europe PMC and Unpaywall ask for this)", settings["ncbi_email"])
        ncbi_key = st.text_input("NCBI API key (optional, makes PubMed faster)", settings["ncbi_api_key"],
                                 type="password")
        oa_key = st.text_input("OpenAlex API key (free, needed if OpenAlex says its shared allowance is used up)",
                               settings["openalex_api_key"], type="password")

        st.markdown("**AI**")
        primary = st.radio("Main AI model", ["gemini", "anthropic"], horizontal=True,
                           index=0 if settings["ai_primary"] == "gemini" else 1,
                           format_func={"gemini": "Gemini (Google)", "anthropic": "Claude (Anthropic)"}.get)
        backup = st.checkbox("If the main model fails, try the other one", settings["ai_use_backup"] == "yes")
        c1, c2 = st.columns(2)
        gkey = c1.text_input("Gemini API key", settings["gemini_api_key"], type="password")
        gmodels = list(ai.GEMINI_MODELS)
        gmodel = c1.selectbox("Gemini model", gmodels, format_func=ai.GEMINI_MODELS.get,
                              index=gmodels.index(settings["gemini_model"]) if settings["gemini_model"] in gmodels else 0)
        akey = c2.text_input("Anthropic API key", settings["anthropic_api_key"], type="password")
        amodels = list(ai.ANTHROPIC_MODELS)
        amodel = c2.selectbox("Claude model", amodels, format_func=ai.ANTHROPIC_MODELS.get,
                              index=amodels.index(settings["anthropic_model"]) if settings["anthropic_model"] in amodels else 0)

        st.markdown("**Zotero**")
        z1, z2 = st.columns(2)
        zid = z1.text_input("Zotero user ID (a number)", settings["zotero_user_id"])
        zkey = z2.text_input("Zotero API key", settings["zotero_api_key"], type="password")
        if st.form_submit_button("Save settings", type="primary"):
            config.save_settings({
                "ncbi_email": email, "ncbi_api_key": ncbi_key, "openalex_api_key": oa_key,
                "ai_primary": primary, "ai_use_backup": "yes" if backup else "no",
                "gemini_api_key": gkey, "gemini_model": gmodel, "anthropic_api_key": akey, "anthropic_model": amodel,
                "zotero_user_id": zid, "zotero_api_key": zkey,
            })
            flash("settings", "Settings saved.")
            st.rerun()

    st.markdown("**Test connections**")
    t = st.columns(5)
    if t[0].button("Test PubMed"):
        try:
            st.success(PubMed(email=settings["ncbi_email"], api_key=settings["ncbi_api_key"]).check())
        except PubMedError as exc:
            st.error(str(exc))
    if t[1].button("Test OpenAlex"):
        try:
            n = OpenAlex(settings["ncbi_email"], settings["openalex_api_key"]).count("IVF Ghana")
            st.success(f"OpenAlex is working. Test search found {n} records.")
        except SourceError as exc:
            st.error(str(exc))
    if t[2].button("Test Gemini"):
        try:
            st.success(ai.check("gemini", settings))
        except ai.AIError as exc:
            st.error(str(exc))
    if t[3].button("Test Claude"):
        try:
            st.success(ai.check("anthropic", settings))
        except ai.AIError as exc:
            st.error(str(exc))
    if t[4].button("Test Zotero"):
        try:
            st.success(Zotero(settings["zotero_user_id"], settings["zotero_api_key"]).check())
        except ZoteroError as exc:
            st.error(str(exc))

    with st.expander("Where do I get these keys?"):
        st.write("Gemini: sign in at aistudio.google.com with your Google account and click Get API key.")
        st.write("Anthropic: create a key at platform.claude.com/settings/keys.")
        st.write("OpenAlex: create a free key at openalex.org/settings/api.")
        st.write("NCBI: sign in at ncbi.nlm.nih.gov, open Account settings, and create an API key.")
        st.write("Zotero: zotero.org/settings/keys. Your user ID is at the top of that page. Create a private key "
                 "with 'Allow library access' and 'Allow write access' ticked.")
        st.write("Paste keys here only. Never paste a key into a chat, email or document.")
