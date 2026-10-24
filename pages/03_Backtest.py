"""Vstupní bod pro sekci Backtest; aplikace má jednotnou navigaci v app.py."""
import streamlit as st
st.session_state["requested_view"] = 'Backtest'
st.switch_page("app.py")
