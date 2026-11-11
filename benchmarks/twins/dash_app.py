"""The frameworks benchmark's app on Dash: the same pages, rows and Apply as ComposeUI's.

gunicorn -w 1 --threads 8 -b 127.0.0.1:PORT --chdir <this folder> dash_app:server
"""

from __future__ import annotations

import dash
from dash import MATCH, Input, Output, ctx, dcc, html

PAGES = 20
ROWS = 10

app = dash.Dash(__name__)


def row(number: int, index: int) -> html.Div:
    return html.Div(
        [
            html.Span("Field", id={"t": "label", "p": number, "r": index}),
            dcc.Input(type="text"),
            dcc.Input(type="number", step=1),
            dcc.Checklist(options=["On"]),
            html.Button("Apply", id={"t": "apply", "p": number, "r": index}),
        ],
        style={"display": "flex", "gap": "8px"},
    )


def page(number: int) -> html.Div:
    return html.Div([html.P(f"Content {number}"), *(row(number, r) for r in range(ROWS))])


app.layout = html.Div(
    [
        dcc.Location(id="url"),
        html.Nav(
            [
                dcc.Link(f"Page {number}", href=f"/p{number}", style={"marginRight": "8px"})
                for number in range(PAGES)
            ]
        ),
        html.Div(id="content"),
    ]
)


@app.callback(Output("content", "children"), Input("url", "pathname"))
def show(path: str | None) -> html.Div:
    return page(int(path[2:]) if path and path.startswith("/p") else 0)


@app.callback(
    Output({"t": "label", "p": MATCH, "r": MATCH}, "children"),
    Input({"t": "apply", "p": MATCH, "r": MATCH}, "n_clicks"),
    prevent_initial_call=True,
)
def applied(_clicks: int) -> str:
    return f"Applied {ctx.triggered_id['r']}"


server = app.server
