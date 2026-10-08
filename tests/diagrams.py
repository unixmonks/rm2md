"""Hand-drawn diagram pages for tests (fakepage specs)."""

# Top-down flowchart with a decision and a loop back, plus a task under it.
FLOW = [
    ("h", "Deploy process"),
    ("node", "box", 700, 360, 300, 90, "write code"),
    ("arrow", 700, 405, 700, 495),
    ("node", "box", 700, 540, 300, 90, "run tests"),
    ("arrow", 700, 585, 700, 665),
    ("node", "diamond", 700, 760, 340, 190, "pass?"),
    ("arrow", 870, 760, 1080, 760, "yes"),
    ("node", "circle", 1200, 760, 230, 130, "deploy"),
    ("arrow", 530, 760, 300, 760, "no"),
    ("node", "box", 210, 760, 170, 90, "fix"),
    ("arrow", 210, 715, 210, 540),
    ("arrow", 210, 540, 550, 540),
    ("at", 1000),
    ("task", "add staging step #devops", False),
]

# Left-to-right box-and-arrow architecture sketch, beside plain notes.
ARCH = [
    ("h", "System sketch"),
    ("t", "how requests flow:"),
    ("node", "box", 220, 420, 240, 100, "phone"),
    ("arrow", 340, 420, 520, 420),
    ("node", "box", 640, 420, 240, 100, "API"),
    ("arrow", 760, 420, 940, 420, "SQL"),
    ("node", "box", 1080, 420, 260, 100, "Postgres"),
    ("arrow", 640, 470, 640, 620, "jobs"),
    ("node", "box", 640, 680, 260, 100, "worker"),
    ("at", 860),
    ("t", "- cache later maybe"),
]

# A picture, not a diagram: should become a short description, never Mermaid.
HOUSE = [
    ("h", "Weekend"),
    ("node", "box", 500, 600, 400, 300, ""),
    ("arrow", 300, 450, 500, 300),
    ("arrow", 500, 300, 700, 450),
    ("node", "box", 500, 680, 90, 140, ""),
    ("node", "circle", 1050, 330, 150, 150, ""),
    ("at", 900),
    ("t", "drew the cabin"),
]
