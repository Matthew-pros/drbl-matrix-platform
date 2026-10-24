"""Vstupní bod pro sekci Dashboard; aplikace má jednotnou navigaci v app.py."""
import streamlit as st
st.session_state["requested_view"] = 'Dashboard'
st.switch_page("app.py")
