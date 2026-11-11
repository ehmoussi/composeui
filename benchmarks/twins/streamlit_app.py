"""The frameworks benchmark's app on Streamlit: the same pages, rows and Apply as ComposeUI's.

streamlit run streamlit_app.py --server.port PORT --server.headless true
"""

from __future__ import annotations

import functools

import streamlit as st

PAGES = 20
ROWS = 10


def page(number: int) -> None:
    st.write(f"Content {number}")
    for row in range(ROWS):
        label, name, count, flag, apply = st.columns(5)
        shown = label.empty()
        name.text_input("Name", key=f"name-{number}-{row}", label_visibility="collapsed")
        count.number_input(
            "Count", key=f"count-{number}-{row}", step=1, label_visibility="collapsed"
        )
        flag.checkbox("On", key=f"flag-{number}-{row}")
        clicked = apply.button("Apply", key=f"apply-{number}-{row}")
        shown.write(f"Applied {row}" if clicked else "Field")


st.navigation(
    [
        st.Page(
            functools.partial(page, number),
            title=f"Page {number}",
            url_path=f"p{number}",
            default=number == 0,
        )
        for number in range(PAGES)
    ]
).run()
