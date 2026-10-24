"""Vstupní bod pro sekci Porovnání; aplikace má jednotnou navigaci v app.py."""
import streamlit as st
st.session_state["requested_view"] = 'Porovnání'
st.switch_page("app.py")
