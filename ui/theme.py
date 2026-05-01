"""
ui/theme.py
Tema "Midnight Pro" v2 — hierarquia por cor de fundo, não por bordas.
Sem caixas dentro de caixas. Bordas apenas em elementos interativos.
"""

BG_WIN      = "#0b0d14"
BG_SURFACE  = "#0f1220"
BG_INPUT    = "#141828"
BG_HOVER    = "#1a1e30"
BORDER      = "#1e2438"
BORDER_ACT  = "#3d5aff"
ACCENT      = "#3d5aff"
ACCENT_HOV  = "#5570ff"
ACCENT_PRS  = "#2e47e8"
SUCCESS     = "#22c97a"
WARNING     = "#f0a832"
DANGER      = "#e8475f"
TEXT_PRI    = "#d8e0f0"
TEXT_SEC    = "#5c6a94"
TEXT_DIS    = "#2e364f"

STYLESHEET = f"""
/* ── BASE ──────────────────────────────────────────────── */
QMainWindow, QDialog {{
    background-color: {BG_WIN};
    color: {TEXT_PRI};
}}
QWidget {{
    background-color: transparent;
    color: {TEXT_PRI};
    font-family: "Segoe UI", "SF Pro Display", sans-serif;
    font-size: 13px;
    outline: none;
}}

/* ── MENU ──────────────────────────────────────────────── */
QMenuBar {{
    background-color: {BG_SURFACE};
    color: {TEXT_PRI};
    border-bottom: 1px solid {BORDER};
    padding: 2px 6px;
}}
QMenuBar::item {{
    background: transparent;
    padding: 5px 12px;
    border-radius: 4px;
}}
QMenuBar::item:selected {{ background-color: {BG_HOVER}; }}
QMenu {{
    background-color: {BG_INPUT};
    border: 1px solid {BORDER};
    border-radius: 7px;
    padding: 4px;
}}
QMenu::item {{
    padding: 6px 22px 6px 12px;
    border-radius: 4px;
}}
QMenu::item:selected {{ background-color: {ACCENT}; color: #fff; }}
QMenu::separator {{ height: 1px; background: {BORDER}; margin: 4px 8px; }}

/* ── ABAS ──────────────────────────────────────────────── */
QTabWidget::pane {{
    background-color: {BG_SURFACE};
    border: none;
}}
QTabBar {{ background: transparent; }}
QTabBar::tab {{
    background: transparent;
    color: {TEXT_SEC};
    border: none;
    border-bottom: 2px solid transparent;
    padding: 10px 22px;
    margin-right: 2px;
    font-weight: 500;
}}
QTabBar::tab:hover {{
    color: {TEXT_PRI};
    border-bottom: 2px solid {BORDER};
}}
QTabBar::tab:selected {{
    color: #fff;
    font-weight: 700;
    border-bottom: 2px solid {ACCENT};
}}

/* ── GROUP BOX — título como separador, sem caixa ──────── */
QGroupBox {{
    background-color: {BG_SURFACE};
    border: 1px solid {BORDER};
    border-radius: 8px;
    margin-top: 18px;
    padding-top: 15px;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 10px;
    top: 0px;
    padding: 0 5px;
    color: {ACCENT};
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 1.2px;
    text-transform: uppercase;
}}
QGroupBox#settings_group {{
    background-color: {BG_SURFACE};
    border-color: {BORDER};
    margin-top: 16px;
    padding-top: 12px;
}}
QGroupBox#settings_group::title {{
    color: {TEXT_SEC};
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0;
    text-transform: none;
}}

/* ── LABELS ────────────────────────────────────────────── */
QLabel {{
    background: transparent;
    color: {TEXT_SEC};
    font-size: 12px;
    font-weight: 500;
}}
QLabel#chrome_intro {{
    color: {TEXT_SEC};
    font-size: 12px;
    font-weight: 400;
    padding: 0 2px 2px 2px;
}}
QLabel#chrome_field_label {{
    color: {TEXT_SEC};
    font-size: 12px;
    font-weight: 500;
}}
QLabel#chrome_status_value {{
    color: {TEXT_PRI};
    font-size: 12px;
    font-weight: 500;
}}
QLabel#chrome_status_warning {{
    color: #b8a06a;
    font-size: 12px;
    font-weight: 500;
}}
QLabel#chrome_steps {{
    color: {TEXT_SEC};
    font-size: 12px;
    font-weight: 400;
}}

/* ── INPUTS ────────────────────────────────────────────── */
QLineEdit {{
    background-color: {BG_INPUT};
    color: {TEXT_PRI};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 7px 10px;
    selection-background-color: {ACCENT};
    selection-color: #fff;
}}
QLineEdit:focus {{
    border-color: {BORDER_ACT};
    background-color: #10142a;
}}
QLineEdit:disabled {{
    color: {TEXT_DIS};
    background-color: transparent;
    border-color: {BORDER};
}}
QLineEdit#chrome_path_field {{
    background-color: {BG_WIN};
    color: #7b86ad;
    border-color: {BORDER};
    font-size: 11px;
    padding: 6px 8px;
}}

QSpinBox {{
    background-color: {BG_INPUT};
    color: {TEXT_PRI};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 5px 8px;
    min-width: 75px;
}}
QSpinBox:focus {{ border-color: {BORDER_ACT}; }}
QSpinBox::up-button, QSpinBox::down-button {{
    background-color: {BG_HOVER};
    border: none;
    border-left: 1px solid {BORDER};
    width: 18px;
}}
QSpinBox::up-button:hover, QSpinBox::down-button:hover {{
    background-color: #20263a;
}}
QSpinBox::up-button {{
    subcontrol-origin: border;
    subcontrol-position: top right;
    border-top-right-radius: 5px;
}}
QSpinBox::down-button {{
    subcontrol-origin: border;
    subcontrol-position: bottom right;
    border-bottom-right-radius: 5px;
}}
QSpinBox::up-arrow {{
    image: url("ui/assets/chevron-up.svg");
    width: 8px;
    height: 8px;
}}
QSpinBox::down-arrow {{
    image: url("ui/assets/chevron-down.svg");
    width: 8px;
    height: 8px;
}}
QSpinBox::up-arrow:disabled, QSpinBox::down-arrow:disabled {{
    image: none;
}}

/* ── BOTÕES GENÉRICOS ──────────────────────────────────── */
QPushButton {{
    background-color: {BG_INPUT};
    color: {TEXT_PRI};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 7px 18px;
    font-weight: 500;
    font-size: 12px;
}}
QPushButton:hover {{
    background-color: {BG_HOVER};
    border-color: {ACCENT};
    color: #fff;
}}
QPushButton:pressed {{
    background-color: {ACCENT_PRS};
    border-color: {ACCENT_PRS};
}}
QPushButton:disabled {{
    background-color: transparent;
    color: {TEXT_DIS};
    border-color: {BORDER};
}}

/* ── INICIAR ───────────────────────────────────────────── */
QPushButton#start_btn {{
    background-color: {BG_INPUT};
    color: #cfe9db;
    border: 1px solid #2f5f49;
    border-radius: 6px;
    font-weight: 600;
    font-size: 12px;
    min-height: 38px;
}}
QPushButton#start_btn:hover {{
    background-color: #182236;
    border-color: #4f8f72;
    color: #effaf4;
}}
QPushButton#start_btn:pressed {{
    background-color: #14251d;
    border-color: #3f7d61;
}}
QPushButton#start_btn:disabled {{
    background-color: transparent;
    color: {TEXT_DIS};
    border-color: {BORDER};
}}

/* ── PAUSAR ────────────────────────────────────────────── */
QPushButton#pause_btn {{
    background-color: {BG_INPUT};
    color: {TEXT_PRI};
    border: 1px solid {BORDER};
    border-radius: 6px;
    font-weight: 500;
    font-size: 12px;
    min-height: 38px;
}}
QPushButton#pause_btn:hover {{
    background-color: #1b1d27;
    color: #f1d49a;
    border-color: #80683d;
}}
QPushButton#pause_btn:pressed {{
    background-color: #241d12;
    color: #f1d49a;
    border-color: #6f572e;
}}
QPushButton#pause_btn:disabled {{
    background-color: transparent;
    color: {TEXT_DIS};
    border-color: {BORDER};
}}

/* ── PARAR ─────────────────────────────────────────────── */
QPushButton#stop_btn {{
    background-color: {BG_INPUT};
    color: {TEXT_PRI};
    border: 1px solid {BORDER};
    border-radius: 6px;
    font-weight: 500;
    font-size: 12px;
    min-height: 38px;
}}
QPushButton#stop_btn:hover {{
    background-color: #211923;
    color: #efc6cd;
    border-color: #864651;
}}
QPushButton#stop_btn:pressed {{
    background-color: #28151b;
    color: #efc6cd;
    border-color: #743844;
}}
QPushButton#stop_btn:disabled {{
    background-color: transparent;
    color: {TEXT_DIS};
    border-color: {BORDER};
}}

/* ── PROCURAR ──────────────────────────────────────────── */
QPushButton#browse_btn {{
    background-color: transparent;
    color: {ACCENT};
    border: 1px solid {ACCENT};
    border-radius: 6px;
    padding: 7px 16px;
    font-weight: 600;
    font-size: 12px;
    min-width: 90px;
}}
QPushButton#browse_btn:hover {{ background-color: {ACCENT}; color: #fff; }}
QPushButton#browse_btn:pressed {{ background-color: {ACCENT_PRS}; color: #fff; }}

/* ── PROGRESS BAR — fina e discreta ───────────────────── */
QProgressBar {{
    background-color: {BG_INPUT};
    border: 1px solid {BORDER};
    border-radius: 6px;
    height: 18px;
    text-align: center;
    color: #fff;
    font-size: 11px;
    font-weight: 600;
}}
QProgressBar::chunk {{
    background-color: {ACCENT};
    border-radius: 5px;
}}

/* ── FRAME — sem borda, fundo transparente ─────────────── */
QFrame {{
    background-color: transparent;
    border: none;
}}

/* ── STATUS BAR ────────────────────────────────────────── */
QStatusBar {{
    background-color: {BG_SURFACE};
    color: {TEXT_SEC};
    border-top: 1px solid {BORDER};
    font-size: 11px;
}}

/* ── SCROLL BAR ────────────────────────────────────────── */
QScrollBar:vertical {{
    background: transparent;
    width: 6px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {BORDER};
    border-radius: 3px;
    min-height: 20px;
}}
QScrollBar::handle:vertical:hover {{ background: {ACCENT}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}

QScrollBar:horizontal {{
    background: transparent;
    height: 6px;
}}
QScrollBar::handle:horizontal {{
    background: {BORDER};
    border-radius: 3px;
    min-width: 20px;
}}
QScrollBar::handle:horizontal:hover {{ background: {ACCENT}; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}

/* ── TEXT EDIT (log) ───────────────────────────────────── */
QTextEdit {{
    background-color: {BG_WIN};
    color: #8896c8;
    border: none;
    border-top: 1px solid {BORDER};
    border-radius: 0;
    padding: 8px 10px;
    font-family: "Cascadia Code", "Consolas", monospace;
    font-size: 11.5px;
    selection-background-color: {ACCENT};
}}

/* ── TABELA ────────────────────────────────────────────── */
QTableWidget {{
    background-color: {BG_SURFACE};
    alternate-background-color: {BG_INPUT};
    gridline-color: {BORDER};
    border: none;
    color: {TEXT_PRI};
    selection-background-color: {ACCENT};
    selection-color: #fff;
}}
QHeaderView::section {{
    background-color: {BG_WIN};
    color: {TEXT_SEC};
    border: none;
    border-right: 1px solid {BORDER};
    border-bottom: 1px solid {BORDER};
    padding: 7px 10px;
    font-weight: 600;
    font-size: 11px;
    letter-spacing: .5px;
    text-transform: uppercase;
}}

/* ── TOOLTIP ───────────────────────────────────────────── */
QToolTip {{
    background-color: {BG_INPUT};
    color: {TEXT_PRI};
    border: 1px solid {BORDER};
    border-radius: 5px;
    padding: 5px 8px;
    font-size: 12px;
}}

/* ── COMBOBOX ──────────────────────────────────────────── */
QComboBox {{
    background-color: {BG_INPUT};
    color: {TEXT_PRI};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 6px 10px;
}}
QComboBox:focus {{ border-color: {BORDER_ACT}; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{
    background-color: {BG_INPUT};
    border: 1px solid {BORDER};
    selection-background-color: {ACCENT};
    color: {TEXT_PRI};
    outline: none;
}}

/* ── CHECKBOX ──────────────────────────────────────────── */
QCheckBox {{
    color: {TEXT_PRI};
    spacing: 8px;
    background: transparent;
}}
QCheckBox::indicator {{
    width: 16px;
    height: 16px;
    border: 1px solid {BORDER};
    border-radius: 3px;
    background: {BG_INPUT};
}}
QCheckBox::indicator:checked {{
    background-color: {ACCENT};
    border-color: {ACCENT};
}}
QCheckBox::indicator:hover {{ border-color: {ACCENT}; }}
QCheckBox#settings_check {{
    color: {TEXT_PRI};
    font-weight: 400;
}}
QCheckBox#settings_check::indicator {{
    background-color: {BG_INPUT};
    border-color: {BORDER};
}}
QCheckBox#settings_check::indicator:checked {{
    background-color: #4f6cff;
    border-color: #4f6cff;
}}

/* ── DIALOG ────────────────────────────────────────────── */
QDialog {{ background-color: {BG_WIN}; }}
QDialogButtonBox QPushButton {{
    min-width: 80px;
    padding: 7px 20px;
}}
QDialogButtonBox#settings_buttons QPushButton {{
    min-width: 110px;
}}
"""


def apply_app_theme(app):
    """Aplica o tema Midnight Pro v2 — flat, sem caixas aninhadas."""
    app.setStyleSheet(STYLESHEET)
