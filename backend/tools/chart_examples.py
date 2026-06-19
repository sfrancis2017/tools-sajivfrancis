"""Canonical chart specs — one per library. Used by tests and the tools-page demo.

Each entry is a full request body shape: {"library", "spec", "output", "title"}.
Importing this module pulls in NO chart engines (plain dicts only).
"""
from __future__ import annotations

EXAMPLES: dict[str, dict] = {
    # Plotly grouped bar — EA capability maturity by domain.
    "plotly": {
        "library": "plotly",
        "output": "html",
        "title": "EA Capability Maturity by Domain",
        "spec": {
            "data": [
                {"type": "bar", "name": "Current",
                 "x": ["Finance", "Procurement", "Manufacturing", "HR"],
                 "y": [3.2, 2.8, 3.7, 2.1]},
                {"type": "bar", "name": "Target",
                 "x": ["Finance", "Procurement", "Manufacturing", "HR"],
                 "y": [4.5, 4.0, 4.6, 3.5]},
            ],
            "layout": {"barmode": "group",
                       "yaxis": {"range": [0, 5], "title": {"text": "Maturity (1-5)"}}},
        },
    },
    # Altair scatter — project complexity vs. risk.
    "altair": {
        "library": "altair",
        "output": "html",
        "title": "Project Risk vs Complexity",
        "spec": {
            "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
            "mark": "point",
            "data": {"values": [
                {"complexity": 3, "risk": 4, "project": "S/4HANA Finance"},
                {"complexity": 5, "risk": 5, "project": "Integration Suite"},
                {"complexity": 2, "risk": 2, "project": "Ariba Onboarding"},
            ]},
            "encoding": {
                "x": {"field": "complexity", "type": "quantitative"},
                "y": {"field": "risk", "type": "quantitative"},
                "tooltip": [{"field": "project"}],
            },
        },
    },
    # Matplotlib horizontal bar.
    "matplotlib": {
        "library": "matplotlib",
        "output": "png",
        "title": "Adoption by Function",
        "spec": {
            "chart_type": "bar",
            "data": {"x": ["IT", "Marketing", "Finance", "HR", "Ops"],
                     "y": [88, 71, 54, 42, 39]},
            "kwargs": {"horizontal": True, "title": "AI Adoption by Function (%)",
                       "xlabel": "% reporting use", "color": "#156082"},
        },
    },
    # Seaborn heatmap — integration dependency matrix.
    "seaborn": {
        "library": "seaborn",
        "output": "png",
        "title": "Integration Dependency Matrix",
        "spec": {
            "chart_type": "heatmap",
            "data": {
                "z": [[0, 3, 1, 2], [3, 0, 2, 1], [1, 2, 0, 3], [2, 1, 3, 0]],
                "x": ["ERP", "CRM", "WMS", "BI"],
                "y": ["ERP", "CRM", "WMS", "BI"],
            },
            "kwargs": {"cmap": "rocket", "annot": True,
                       "title": "Integration Dependencies (count)"},
        },
    },
}
