"""
ui/history_tab.py
Aba de histórico de downloads. Exibe uma tabela com os registros passados.
"""

import os

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget,
    QTableWidgetItem, QHeaderView, QPushButton, QLabel, QMessageBox
)
from PyQt6.QtCore import Qt

from core.download_history import STATUS_CANCELLED, STATUS_DONE, STATUS_FAILED


_STATUS_LABELS = {
    STATUS_DONE: ("Concluído", Qt.GlobalColor.green),
    STATUS_FAILED: ("Falhou", Qt.GlobalColor.red),
    STATUS_CANCELLED: ("Cancelado", Qt.GlobalColor.gray),
}

_PATH_ROLE = Qt.ItemDataRole.UserRole


class HistoryTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)

        header_layout = QHBoxLayout()
        header_layout.addWidget(
            QLabel("Histórico de Downloads (últimos 100; clique duplo abre o arquivo)")
        )
        
        self.clear_btn = QPushButton("Limpar Histórico")
        self.export_btn = QPushButton("Exportar JSON")
        header_layout.addStretch()
        header_layout.addWidget(self.export_btn)
        header_layout.addWidget(self.clear_btn)
        layout.addLayout(header_layout)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels([
            "Data/Hora", "Arquivo", "Tamanho", "Duração", "Status"
        ])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.cellDoubleClicked.connect(self._open_row)

        layout.addWidget(self.table)

    def refresh(self, history_data: list):
        """Atualiza a tabela com os dados fornecidos."""
        self.table.setRowCount(0)
        for entry in history_data:
            row = self.table.rowCount()
            self.table.insertRow(row)

            # Entradas antigas só têm "success".
            status = entry.get("status") or (STATUS_DONE if entry.get("success") else STATUS_FAILED)
            label, color = _STATUS_LABELS.get(status, _STATUS_LABELS[STATUS_FAILED])
            ts = entry.get("timestamp", "").replace("T", " ")[:19]
            size = entry.get("size", 0)
            size_text = f"{size / (1024 * 1024):.1f} MB" if status == STATUS_DONE and size else "—"
            dur = entry.get("duration", 0)

            name_item = QTableWidgetItem(entry.get("filename", ""))
            name_item.setData(_PATH_ROLE, entry.get("path", "") if status == STATUS_DONE else "")
            self.table.setItem(row, 0, QTableWidgetItem(ts))
            self.table.setItem(row, 1, name_item)
            self.table.setItem(row, 2, QTableWidgetItem(size_text))
            self.table.setItem(row, 3, QTableWidgetItem(f"{dur:.1f}s"))

            status_item = QTableWidgetItem(label)
            status_item.setForeground(color)
            self.table.setItem(row, 4, status_item)

    def _open_row(self, row: int, _column: int) -> None:
        item = self.table.item(row, 1)
        path = item.data(_PATH_ROLE) if item is not None else ""
        if path and os.path.isfile(path):
            os.startfile(path)
            return
        QMessageBox.information(
            self,
            "Arquivo não encontrado",
            f"O arquivo não está mais em:\n{path}" if path else "Este download não terminou, então não há arquivo.",
        )
