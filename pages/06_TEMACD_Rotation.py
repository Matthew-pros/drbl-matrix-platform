"""Navigation entry point for the TEMACD rotation section."""
import streamlit as st

st.session_state["requested_view"] = "TEMACD Rotace"
st.switch_page("app.py")