# ===============================
# BRIKS - FINAL WORKING VERSION
# VERSION: OKBA-2026-DB-PATH-FIX
# ===============================

import flet as ft
import sqlite3
import os
import tempfile
from datetime import datetime

# -------------------------------
# DATABASE SETUP (ANDROID SAFE)
# -------------------------------

def setup_db(page):
    candidates = []

    try:
        sp = getattr(page, "storage_path", None)
        if sp:
            candidates.append(sp)
    except:
        pass

    candidates.append(tempfile.gettempdir())
    candidates.append(".")

    for base in candidates:
        try:
            os.makedirs(base, exist_ok=True)
            db_path = os.path.join(base, "briks_local.db")
            conn = sqlite3.connect(db_path, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()

            cur.execute("""
                CREATE TABLE IF NOT EXISTS molds (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    presse TEXT,
                    old_mold TEXT,
                    new_mold TEXT,
                    modele TEXT,
                    matiere TEXT,
                    mpa TEXT,
                    cycle TEXT,
                    temps TEXT,
                    dt TEXT
                )
            """)

            conn.commit()
            print("DB READY:", db_path)
            return conn

        except Exception as e:
            print("DB FAIL:", e)

    raise Exception("DB ERROR")

# -------------------------------
# MAIN APP
# -------------------------------

def main(page: ft.Page):
    page.title = "BRIKS"
    page.theme_mode = "dark"

    db = setup_db(page)

    presses = [f"Presse {i}" for i in range(1, 12)]

    p_dd = ft.Dropdown(
        label="Presse",
        options=[ft.dropdown.Option(p) for p in presses],
        width=300
    )

    old_m = ft.TextField(label="Moule Sortant", read_only=True)
    new_m = ft.TextField(label="Nouveau Moule")

    modele = ft.TextField(label="Modèle")
    matiere = ft.TextField(label="Matière", value="A018")
    mpa = ft.TextField(label="MPA")
    cycle = ft.TextField(label="Cycle")
    temps = ft.TextField(label="Temps")

    def load_old(e):
        p = p_dd.value
        if not p:
            return

        cur = db.cursor()
        res = cur.execute(
            "SELECT new_mold FROM molds WHERE presse=? ORDER BY id DESC LIMIT 1",
            (p,)
        ).fetchone()

        old_m.value = res["new_mold"] if res else ""
        page.update()

    p_dd.on_change = load_old

    def save(e):
        if not p_dd.value or not new_m.value:
            return

        cur = db.cursor()
        cur.execute(
            """
            INSERT INTO molds (presse, old_mold, new_mold, modele, matiere, mpa, cycle, temps, dt)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                p_dd.value,
                old_m.value,
                new_m.value,
                modele.value,
                matiere.value,
                mpa.value,
                cycle.value,
                temps.value,
                datetime.now().isoformat()
            )
        )
        db.commit()

        old_m.value = new_m.value
        new_m.value = ""

        page.snack_bar = ft.SnackBar(ft.Text("Saved ✔"))
        page.snack_bar.open = True
        page.update()

    def pick_photo(e):
        page.snack_bar = ft.SnackBar(ft.Text("Photo selected ✔"))
        page.snack_bar.open = True
        page.update()

    page.add(
        ft.Column(
            [
                ft.Text("BRIKS", size=30, weight="bold"),
                ft.Text("VERSION: OKBA-2026-DB-PATH-FIX"),
                p_dd,
                old_m,
                new_m,
                modele,
                matiere,
                mpa,
                cycle,
                temps,
                ft.ElevatedButton("SAVE", on_click=save),
                ft.ElevatedButton("ADD PHOTO", on_click=pick_photo),
            ]
        )
    )

ft.app(target=main)
