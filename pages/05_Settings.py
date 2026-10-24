"""Vstupní bod pro sekci Nastavení; aplikace má jednotnou navigaci v app.py."""
import streamlit as st
st.session_state["requested_view"] = 'Nastavení'
st.switch_page("app.py")
