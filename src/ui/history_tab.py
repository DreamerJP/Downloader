"""
ui/history_tab.py
Aba de histórico de downloads. Exibe uma tabela com os registros passados.
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, 
    QTableWidgetItem, QHeaderView, QPushButton, QLabel, QMessageBox
)
from PyQt6.QtCore import Qt


class HistoryTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)

        header_layout = QHBoxLayout()
        header_layout.addWidget(QLabel("Histórico de Downloads (Últimos 100)"))
        
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
        
        layout.addWidget(self.table)

    def refresh(self, history_data: list):
        """Atualiza a tabela com os dados fornecidos."""
        self.table.setRowCount(0)
        for entry in history_data:
            row = self.table.rowCount()
            self.table.insertRow(row)
            
            # Formatação simplificada
            ts = entry.get("timestamp", "").replace("T", " ")[:19]
            size_mb = entry.get("size", 0) / (1024*1024)
            dur = entry.get("duration", 0)
            success = "Concluído" if entry.get("success") else "Falhou"
            
            self.table.setItem(row, 0, QTableWidgetItem(ts))
            self.table.setItem(row, 1, QTableWidgetItem(entry.get("filename", "")))
            self.table.setItem(row, 2, QTableWidgetItem(f"{size_mb:.1f} MB"))
            self.table.setItem(row, 3, QTableWidgetItem(f"{dur:.1f}s"))
            
            status_item = QTableWidgetItem(success)
            if success == "Concluído":
                status_item.setForeground(Qt.GlobalColor.green)
            else:
                status_item.setForeground(Qt.GlobalColor.red)
            self.table.setItem(row, 4, status_item)
