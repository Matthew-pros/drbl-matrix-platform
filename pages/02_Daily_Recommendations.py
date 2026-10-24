"""Vstupní bod pro sekci Denní doporučení; aplikace má jednotnou navigaci v app.py."""
import streamlit as st
st.session_state["requested_view"] = 'Denní doporučení'
st.switch_page("app.py")
