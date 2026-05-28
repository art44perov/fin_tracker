"""
ФинЛичный — локальная система учёта финансов
Запуск: python app.py
Открыть браузер: http://localhost:8000
"""

import sqlite3
import json
import os
import webbrowser
import threading
from datetime import datetime, date
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

DB_PATH = "finance.db"

# ── База данных ─────────────────────────────────────────────────────────────

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            type TEXT NOT NULL CHECK(type IN ('income','expense')),
            amount REAL NOT NULL,
            category TEXT NOT NULL,
            description TEXT DEFAULT '',
            date TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS savings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            goal REAL NOT NULL,
            current REAL DEFAULT 0,
            color TEXT DEFAULT '#6366f1',
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS savings_deposits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            saving_id INTEGER REFERENCES savings(id),
            amount REAL NOT NULL,
            date TEXT NOT NULL,
            note TEXT DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS credits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            total_amount REAL NOT NULL,
            remaining REAL NOT NULL,
            monthly_payment REAL NOT NULL,
            interest_rate REAL DEFAULT 0,
            start_date TEXT NOT NULL,
            end_date TEXT,
            color TEXT DEFAULT '#f87171',
            note TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS credit_payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            credit_id INTEGER REFERENCES credits(id),
            amount REAL NOT NULL,
            date TEXT NOT NULL,
            note TEXT DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS debts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            debtor_name TEXT NOT NULL,
            description TEXT NOT NULL,
            total_amount REAL NOT NULL,
            paid_amount REAL DEFAULT 0,
            status TEXT DEFAULT 'active' CHECK(status IN ('active','partial','paid')),
            due_date TEXT,
            color TEXT DEFAULT '#c9a84c',
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS debt_payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            debt_id INTEGER REFERENCES debts(id),
            amount REAL NOT NULL,
            date TEXT NOT NULL,
            note TEXT DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS recurring (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            amount REAL NOT NULL,
            category TEXT NOT NULL,
            day_of_month INTEGER DEFAULT 1,
            color TEXT DEFAULT '#6366f1',
            note TEXT DEFAULT '',
            active INTEGER DEFAULT 1,
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS recurring_marks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            recurring_id INTEGER REFERENCES recurring(id),
            month TEXT NOT NULL,
            paid INTEGER DEFAULT 0,
            paid_date TEXT,
            UNIQUE(recurring_id, month)
        );
    """)
    conn.commit()
    conn.close()

# ── API helpers ──────────────────────────────────────────────────────────────

def get_transactions(filters=None):
    conn = get_db()
    q = "SELECT * FROM transactions WHERE 1=1"
    params = []
    if filters:
        if filters.get("type"):
            q += " AND type=?"; params.append(filters["type"])
        if filters.get("month"):
            q += " AND strftime('%Y-%m', date)=?"; params.append(filters["month"])
    q += " ORDER BY date DESC, id DESC"
    rows = conn.execute(q, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def add_transaction(data):
    conn = get_db()
    cur = conn.execute(
        "INSERT INTO transactions (type,amount,category,description,date) VALUES (?,?,?,?,?)",
        (data["type"], float(data["amount"]), data["category"],
         data.get("description",""), data["date"])
    )
    conn.commit()
    row = conn.execute("SELECT * FROM transactions WHERE id=?", (cur.lastrowid,)).fetchone()
    conn.close()
    return dict(row)

def update_transaction(tx_id, data):
    conn = get_db()
    conn.execute(
        "UPDATE transactions SET type=?,amount=?,category=?,description=?,date=? WHERE id=?",
        (data["type"], float(data["amount"]), data["category"],
         data.get("description",""), data["date"], tx_id)
    )
    conn.commit()
    row = conn.execute("SELECT * FROM transactions WHERE id=?", (tx_id,)).fetchone()
    conn.close()
    return dict(row) if row else None

def delete_transaction(tx_id):
    conn = get_db()
    conn.execute("DELETE FROM transactions WHERE id=?", (tx_id,))
    conn.commit()
    conn.close()

def get_savings():
    conn = get_db()
    rows = conn.execute("SELECT * FROM savings ORDER BY id").fetchall()
    conn.close()
    return [dict(r) for r in rows]

def add_saving(data):
    conn = get_db()
    cur = conn.execute(
        "INSERT INTO savings (name,goal,current,color) VALUES (?,?,?,?)",
        (data["name"], float(data["goal"]), float(data.get("current",0)), data.get("color","#6366f1"))
    )
    conn.commit()
    row = conn.execute("SELECT * FROM savings WHERE id=?", (cur.lastrowid,)).fetchone()
    conn.close()
    return dict(row)

def update_saving(saving_id, data):
    conn = get_db()
    conn.execute(
        "UPDATE savings SET name=?,goal=?,current=?,color=? WHERE id=?",
        (data["name"], float(data["goal"]), float(data.get("current",0)), data.get("color","#6366f1"), saving_id)
    )
    conn.commit()
    row = conn.execute("SELECT * FROM savings WHERE id=?", (saving_id,)).fetchone()
    conn.close()
    return dict(row) if row else None

def deposit_saving(saving_id, amount, note=""):
    conn = get_db()
    conn.execute("UPDATE savings SET current = MIN(goal, current + ?) WHERE id=?", (float(amount), saving_id))
    conn.execute(
        "INSERT INTO savings_deposits (saving_id, amount, date, note) VALUES (?,?,?,?)",
        (saving_id, float(amount), date.today().isoformat(), note)
    )
    conn.commit()
    row = conn.execute("SELECT * FROM savings WHERE id=?", (saving_id,)).fetchone()
    conn.close()
    return dict(row)

def delete_saving(saving_id):
    conn = get_db()
    conn.execute("DELETE FROM savings_deposits WHERE saving_id=?", (saving_id,))
    conn.execute("DELETE FROM savings WHERE id=?", (saving_id,))
    conn.commit()
    conn.close()

# ── Credits ──────────────────────────────────────────────────────────────────

def get_credits():
    conn = get_db()
    rows = conn.execute("SELECT * FROM credits ORDER BY id").fetchall()
    conn.close()
    return [dict(r) for r in rows]

def add_credit(data):
    conn = get_db()
    cur = conn.execute(
        "INSERT INTO credits (name,total_amount,remaining,monthly_payment,interest_rate,start_date,end_date,color,note) VALUES (?,?,?,?,?,?,?,?,?)",
        (data["name"], float(data["total_amount"]), float(data["remaining"]),
         float(data["monthly_payment"]), float(data.get("interest_rate",0)),
         data["start_date"], data.get("end_date",""), data.get("color","#f87171"), data.get("note",""))
    )
    conn.commit()
    row = conn.execute("SELECT * FROM credits WHERE id=?", (cur.lastrowid,)).fetchone()
    conn.close()
    return dict(row)

def update_credit(credit_id, data):
    conn = get_db()
    conn.execute(
        "UPDATE credits SET name=?,total_amount=?,remaining=?,monthly_payment=?,interest_rate=?,start_date=?,end_date=?,color=?,note=? WHERE id=?",
        (data["name"], float(data["total_amount"]), float(data["remaining"]),
         float(data["monthly_payment"]), float(data.get("interest_rate",0)),
         data["start_date"], data.get("end_date",""), data.get("color","#f87171"), data.get("note",""), credit_id)
    )
    conn.commit()
    row = conn.execute("SELECT * FROM credits WHERE id=?", (credit_id,)).fetchone()
    conn.close()
    return dict(row) if row else None

def pay_credit(credit_id, amount, note=""):
    conn = get_db()
    conn.execute("UPDATE credits SET remaining = MAX(0, remaining - ?) WHERE id=?", (float(amount), credit_id))
    conn.execute(
        "INSERT INTO credit_payments (credit_id, amount, date, note) VALUES (?,?,?,?)",
        (credit_id, float(amount), date.today().isoformat(), note)
    )
    conn.commit()
    row = conn.execute("SELECT * FROM credits WHERE id=?", (credit_id,)).fetchone()
    conn.close()
    return dict(row)

def delete_credit(credit_id):
    conn = get_db()
    conn.execute("DELETE FROM credit_payments WHERE credit_id=?", (credit_id,))
    conn.execute("DELETE FROM credits WHERE id=?", (credit_id,))
    conn.commit()
    conn.close()

# ── Debts ────────────────────────────────────────────────────────────────────

def get_debts():
    conn = get_db()
    rows = conn.execute("SELECT * FROM debts ORDER BY status, id").fetchall()
    conn.close()
    return [dict(r) for r in rows]

def add_debt(data):
    conn = get_db()
    cur = conn.execute(
        "INSERT INTO debts (debtor_name,description,total_amount,paid_amount,due_date,color) VALUES (?,?,?,?,?,?)",
        (data["debtor_name"], data["description"], float(data["total_amount"]),
         float(data.get("paid_amount",0)), data.get("due_date",""), data.get("color","#c9a84c"))
    )
    conn.commit()
    row = conn.execute("SELECT * FROM debts WHERE id=?", (cur.lastrowid,)).fetchone()
    conn.close()
    return dict(row)

def update_debt(debt_id, data):
    conn = get_db()
    paid = float(data.get("paid_amount",0))
    total = float(data["total_amount"])
    status = "paid" if paid >= total else ("partial" if paid > 0 else "active")
    conn.execute(
        "UPDATE debts SET debtor_name=?,description=?,total_amount=?,paid_amount=?,due_date=?,color=?,status=? WHERE id=?",
        (data["debtor_name"], data["description"], total, paid,
         data.get("due_date",""), data.get("color","#c9a84c"), status, debt_id)
    )
    conn.commit()
    row = conn.execute("SELECT * FROM debts WHERE id=?", (debt_id,)).fetchone()
    conn.close()
    return dict(row) if row else None

def pay_debt(debt_id, amount, note=""):
    conn = get_db()
    debt = dict(conn.execute("SELECT * FROM debts WHERE id=?", (debt_id,)).fetchone())
    new_paid = debt["paid_amount"] + float(amount)
    status = "paid" if new_paid >= debt["total_amount"] else "partial"
    conn.execute("UPDATE debts SET paid_amount=?, status=? WHERE id=?", (min(new_paid, debt["total_amount"]), status, debt_id))
    conn.execute(
        "INSERT INTO debt_payments (debt_id, amount, date, note) VALUES (?,?,?,?)",
        (debt_id, float(amount), date.today().isoformat(), note)
    )
    conn.commit()
    row = conn.execute("SELECT * FROM debts WHERE id=?", (debt_id,)).fetchone()
    conn.close()
    return dict(row)

def delete_debt(debt_id):
    conn = get_db()
    conn.execute("DELETE FROM debt_payments WHERE debt_id=?", (debt_id,))
    conn.execute("DELETE FROM debts WHERE id=?", (debt_id,))
    conn.commit()
    conn.close()

# ── Recurring ────────────────────────────────────────────────────────────────

def get_recurring(month=None):
    conn = get_db()
    rows = conn.execute("SELECT * FROM recurring WHERE active=1 ORDER BY day_of_month, id").fetchall()
    result = []
    cur_month = month or date.today().strftime("%Y-%m")
    for r in rows:
        rec = dict(r)
        mark = conn.execute(
            "SELECT * FROM recurring_marks WHERE recurring_id=? AND month=?",
            (r["id"], cur_month)
        ).fetchone()
        rec["paid"] = bool(mark and mark["paid"]) if mark else False
        rec["paid_date"] = mark["paid_date"] if mark else None
        rec["month"] = cur_month
        result.append(rec)
    conn.close()
    return result

def add_recurring(data):
    conn = get_db()
    cur = conn.execute(
        "INSERT INTO recurring (name,amount,category,day_of_month,color,note) VALUES (?,?,?,?,?,?)",
        (data["name"], float(data["amount"]), data["category"],
         int(data.get("day_of_month",1)), data.get("color","#6366f1"), data.get("note",""))
    )
    conn.commit()
    row = conn.execute("SELECT * FROM recurring WHERE id=?", (cur.lastrowid,)).fetchone()
    conn.close()
    return dict(row)

def update_recurring(rec_id, data):
    conn = get_db()
    conn.execute(
        "UPDATE recurring SET name=?,amount=?,category=?,day_of_month=?,color=?,note=? WHERE id=?",
        (data["name"], float(data["amount"]), data["category"],
         int(data.get("day_of_month",1)), data.get("color","#6366f1"), data.get("note",""), rec_id)
    )
    conn.commit()
    row = conn.execute("SELECT * FROM recurring WHERE id=?", (rec_id,)).fetchone()
    conn.close()
    return dict(row) if row else None

def toggle_recurring_paid(rec_id, month, paid):
    conn = get_db()
    paid_date = date.today().isoformat() if paid else None
    conn.execute(
        "INSERT INTO recurring_marks (recurring_id, month, paid, paid_date) VALUES (?,?,?,?) ON CONFLICT(recurring_id,month) DO UPDATE SET paid=excluded.paid, paid_date=excluded.paid_date",
        (rec_id, month, 1 if paid else 0, paid_date)
    )
    conn.commit()
    conn.close()

def delete_recurring(rec_id):
    conn = get_db()
    conn.execute("DELETE FROM recurring_marks WHERE recurring_id=?", (rec_id,))
    conn.execute("DELETE FROM recurring WHERE id=?", (rec_id,))
    conn.commit()
    conn.close()

def get_report(month=None):
    conn = get_db()
    where = ""
    params = []
    if month:
        where = "WHERE strftime('%Y-%m', date)=?"
        params = [month]

    totals = conn.execute(f"""
        SELECT
            SUM(CASE WHEN type='income' THEN amount ELSE 0 END) as total_income,
            SUM(CASE WHEN type='expense' THEN amount ELSE 0 END) as total_expense,
            COUNT(*) as tx_count
        FROM transactions {where}
    """, params).fetchone()

    by_cat = conn.execute(f"""
        SELECT category, type, SUM(amount) as total
        FROM transactions {where}
        GROUP BY category, type
        ORDER BY total DESC
    """, params).fetchall()

    by_month = conn.execute("""
        SELECT strftime('%Y-%m', date) as month,
               SUM(CASE WHEN type='income' THEN amount ELSE 0 END) as income,
               SUM(CASE WHEN type='expense' THEN amount ELSE 0 END) as expense
        FROM transactions
        GROUP BY month ORDER BY month DESC LIMIT 12
    """).fetchall()

    savings = conn.execute("SELECT * FROM savings").fetchall()
    credits = conn.execute("SELECT * FROM credits").fetchall()
    debts = conn.execute("SELECT * FROM debts WHERE status != 'paid'").fetchall()
    conn.close()

    ti = totals["total_income"] or 0
    te = totals["total_expense"] or 0
    total_credit_debt = sum(c["remaining"] for c in credits)
    total_monthly_credits = sum(c["monthly_payment"] for c in credits)
    total_debts_owed = sum(d["total_amount"] - d["paid_amount"] for d in debts)

    return {
        "total_income": ti,
        "total_expense": te,
        "balance": ti - te,
        "savings_rate": round((ti - te) / ti * 100, 1) if ti > 0 else 0,
        "tx_count": totals["tx_count"],
        "by_category": [dict(r) for r in by_cat],
        "by_month": [dict(r) for r in by_month],
        "savings": [dict(r) for r in savings],
        "total_credit_debt": total_credit_debt,
        "total_monthly_credits": total_monthly_credits,
        "total_debts_owed": total_debts_owed,
    }

# ── HTML интерфейс ───────────────────────────────────────────────────────────

HTML = r"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>ФинЛичный</title>
<style>
@import url('https://fonts.googleapis.com/css2?family=Playfair+Display:wght@400;700&family=JetBrains+Mono:wght@300;400;600&display=swap');

*{box-sizing:border-box;margin:0;padding:0}
body{min-height:100vh;background:#0d0f14;color:#e8eaf0;font-family:'JetBrains Mono',monospace}
::-webkit-scrollbar{width:4px}::-webkit-scrollbar-track{background:#1a1d27}::-webkit-scrollbar-thumb{background:#2d3148;border-radius:2px}
.serif{font-family:'Playfair Display',serif}
header{background:#0d0f14;border-bottom:1px solid #1e2235;padding:0 32px;display:flex;align-items:center;justify-content:space-between;height:64px;position:sticky;top:0;z-index:50}
.logo{display:flex;align-items:center;gap:10px;font-family:'Playfair Display',serif;font-size:20px}
.logo-icon{color:#c9a84c;font-size:24px}
nav{background:#0d0f14;border-bottom:1px solid #1e2235;padding:0 32px;display:flex;gap:4px;position:sticky;top:64px;z-index:49;overflow-x:auto}
.tab{background:none;border:none;color:#6b7280;cursor:pointer;padding:12px 20px;font-size:12px;letter-spacing:1.5px;text-transform:uppercase;font-family:'JetBrains Mono',monospace;border-bottom:2px solid transparent;transition:all .2s;white-space:nowrap}
.tab.active{color:#c9a84c;border-bottom-color:#c9a84c}
.tab:hover{color:#e8eaf0}
main{padding:32px;max-width:1100px;margin:0 auto}
.card{background:#141720;border:1px solid #1e2235;border-radius:12px;padding:24px;margin-bottom:16px}
.grid3{display:grid;grid-template-columns:repeat(3,1fr);gap:16px;margin-bottom:16px}
.grid4{display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin-bottom:16px}
.grid2{display:grid;grid-template-columns:1.4fr 1fr;gap:16px;margin-bottom:16px}
.section-title{font-size:10px;letter-spacing:2px;text-transform:uppercase;color:#6b7280;margin-bottom:14px}
.stat-num{font-family:'Playfair Display',serif;font-size:28px;font-weight:700}
.btn{padding:10px 22px;border:none;border-radius:8px;cursor:pointer;font-size:12px;font-family:'JetBrains Mono',monospace;letter-spacing:.5px;transition:all .15s}
.btn-gold{background:#c9a84c;color:#0d0f14;font-weight:700}
.btn-gold:hover{background:#e0be6a;transform:translateY(-1px)}
.btn-ghost{background:transparent;border:1px solid #2d3148;color:#9ca3af}
.btn-ghost:hover{border-color:#c9a84c;color:#c9a84c}
.btn-danger{background:transparent;border:1px solid #4b1a1a;color:#f87171}
.btn-danger:hover{background:#4b1a1a}
.btn-edit{background:transparent;border:1px solid #1e3148;color:#60a5fa}
.btn-edit:hover{background:#1e3148}
.input{background:#0d0f14;border:1px solid #2d3148;border-radius:8px;padding:10px 14px;color:#e8eaf0;font-family:'JetBrains Mono',monospace;font-size:13px;width:100%;outline:none;transition:border .15s}
.input:focus{border-color:#c9a84c}
select.input option{background:#141720}
.badge-i{background:#0d2918;color:#34d399;padding:3px 10px;border-radius:20px;font-size:11px;display:inline-block}
.badge-e{background:#2a0d0d;color:#f87171;padding:3px 10px;border-radius:20px;font-size:11px;display:inline-block}
.badge-warn{background:#2a1f0d;color:#f59e0b;padding:3px 10px;border-radius:20px;font-size:11px;display:inline-block}
.badge-ok{background:#0d2918;color:#34d399;padding:3px 10px;border-radius:20px;font-size:11px;display:inline-block}
.progress-bar{height:8px;background:#1e2235;border-radius:4px;overflow:hidden}
.progress-fill{height:100%;border-radius:4px;transition:width .4s}
.overlay{position:fixed;inset:0;background:rgba(0,0,0,.75);display:flex;align-items:center;justify-content:center;z-index:200;backdrop-filter:blur(4px)}
.modal{background:#141720;border:1px solid #2d3148;border-radius:16px;padding:32px;width:460px;max-width:95vw;max-height:90vh;overflow-y:auto}
.form-group{display:flex;flex-direction:column;gap:12px;margin-bottom:20px}
.form-row{display:grid;grid-template-columns:1fr 1fr;gap:10px}
.row-btns{display:flex;gap:8px;margin-top:4px}
.tx-row{display:flex;align-items:center;justify-content:space-between;padding:14px 0;border-bottom:1px solid #1e2235}
.tx-row:last-child{border-bottom:none}
.tx-meta{font-size:11px;color:#4b5563;margin-top:3px}
.hidden{display:none}
.color-dot{width:26px;height:26px;border-radius:50%;cursor:pointer;border:3px solid transparent;transition:border .15s}
.color-dot.sel{border-color:#fff}
.month-filter{display:flex;align-items:center;gap:10px}
.filter-row{display:flex;align-items:center;justify-content:space-between;margin-bottom:20px;flex-wrap:wrap;gap:10px}
.credit-card{background:#141720;border:1px solid #1e2235;border-radius:12px;padding:20px}
.debt-card{background:#141720;border:1px solid #1e2235;border-radius:12px;padding:20px}
.rec-row{display:flex;align-items:center;justify-content:space-between;padding:14px 0;border-bottom:1px solid #1e2235}
.rec-row:last-child{border-bottom:none}
.toggle-paid{width:38px;height:22px;border-radius:11px;border:none;cursor:pointer;position:relative;transition:background .2s;flex-shrink:0}
.toggle-paid.on{background:#34d399}
.toggle-paid.off{background:#2d3148}
.label{font-size:11px;color:#6b7280;letter-spacing:1px;margin-bottom:4px;display:block}
</style>
</head>
<body>
<header>
  <div class="logo"><span class="logo-icon">◈</span> ФинЛичный</div>
  <div style="font-size:11px;color:#4b5563" id="today-date"></div>
</header>
<nav>
  <button class="tab active" onclick="showTab('dashboard')">◈ Обзор</button>
  <button class="tab" onclick="showTab('transactions')">⇄ Операции</button>
  <button class="tab" onclick="showTab('savings')">◎ Копилки</button>
  <button class="tab" onclick="showTab('credits')">⬡ Кредиты</button>
  <button class="tab" onclick="showTab('debts')">✦ Долги</button>
  <button class="tab" onclick="showTab('recurring')">↻ Рег. платежи</button>
  <button class="tab" onclick="showTab('report')">▦ Отчёт</button>
</nav>
<main>

<!-- DASHBOARD -->
<div id="tab-dashboard">
  <div class="grid4" id="dash-stats"></div>
  <div class="grid2">
    <div class="card">
      <div class="section-title">Расходы по категориям</div>
      <div id="dash-cats"></div>
    </div>
    <div class="card">
      <div class="section-title">Копилки — прогресс</div>
      <div id="dash-savings"></div>
    </div>
  </div>
  <div class="grid2">
    <div class="card">
      <div class="section-title">Кредиты — остатки</div>
      <div id="dash-credits"></div>
    </div>
    <div class="card">
      <div class="section-title">Долги мне</div>
      <div id="dash-debts"></div>
    </div>
  </div>
  <div class="card">
    <div class="section-title">Последние операции</div>
    <div id="dash-recent"></div>
  </div>
</div>

<!-- TRANSACTIONS -->
<div id="tab-transactions" class="hidden">
  <div class="filter-row">
    <div class="month-filter">
      <span style="font-size:11px;color:#6b7280;letter-spacing:1px">МЕС:</span>
      <input type="month" class="input" id="tx-month-filter" style="width:160px" onchange="loadTransactions()">
    </div>
    <button class="btn btn-gold" onclick="openTxModal()">+ Добавить</button>
  </div>
  <div class="card">
    <div id="tx-list"></div>
  </div>
</div>

<!-- SAVINGS -->
<div id="tab-savings" class="hidden">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:20px">
    <h2 class="serif" style="font-size:22px">Копилки</h2>
    <button class="btn btn-gold" onclick="openSavingModal()">+ Новая копилка</button>
  </div>
  <div id="savings-grid" style="display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:16px"></div>
</div>

<!-- CREDITS -->
<div id="tab-credits" class="hidden">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:20px">
    <h2 class="serif" style="font-size:22px">Кредиты</h2>
    <button class="btn btn-gold" onclick="openCreditModal()">+ Новый кредит</button>
  </div>
  <div id="credits-summary" style="margin-bottom:16px"></div>
  <div id="credits-grid" style="display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:16px"></div>
</div>

<!-- DEBTS -->
<div id="tab-debts" class="hidden">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:20px">
    <h2 class="serif" style="font-size:22px">Долги мне</h2>
    <button class="btn btn-gold" onclick="openDebtModal()">+ Новый долг</button>
  </div>
  <div id="debts-summary" style="margin-bottom:16px"></div>
  <div style="display:flex;gap:10px;margin-bottom:16px;flex-wrap:wrap">
    <button class="btn btn-ghost" id="debt-filter-all" onclick="setDebtFilter('all')" style="font-size:11px;padding:6px 14px">Все</button>
    <button class="btn btn-ghost" id="debt-filter-active" onclick="setDebtFilter('active')" style="font-size:11px;padding:6px 14px">Активные</button>
    <button class="btn btn-ghost" id="debt-filter-partial" onclick="setDebtFilter('partial')" style="font-size:11px;padding:6px 14px">Частично</button>
    <button class="btn btn-ghost" id="debt-filter-paid" onclick="setDebtFilter('paid')" style="font-size:11px;padding:6px 14px">Выплачено</button>
  </div>
  <div id="debts-list"></div>
</div>

<!-- RECURRING -->
<div id="tab-recurring" class="hidden">
  <div class="filter-row">
    <h2 class="serif" style="font-size:22px">Регулярные платежи</h2>
    <div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap">
      <div class="month-filter">
        <span style="font-size:11px;color:#6b7280">МЕС:</span>
        <input type="month" class="input" id="rec-month-filter" style="width:160px" onchange="loadRecurring()">
      </div>
      <button class="btn btn-gold" onclick="openRecurringModal()">+ Добавить</button>
    </div>
  </div>
  <div id="recurring-summary" style="margin-bottom:16px"></div>
  <div class="card">
    <div id="recurring-list"></div>
  </div>
</div>

<!-- REPORT -->
<div id="tab-report" class="hidden">
  <div class="filter-row">
    <h2 class="serif" style="font-size:22px">Финансовый отчёт</h2>
    <div class="month-filter">
      <span style="font-size:11px;color:#6b7280">МЕС:</span>
      <input type="month" class="input" id="report-month-filter" style="width:160px" onchange="loadReport()">
      <button class="btn btn-ghost" style="padding:8px 14px" onclick="document.getElementById('report-month-filter').value='';loadReport()">Всё время</button>
    </div>
  </div>
  <div id="report-content"></div>
</div>

</main>

<!-- ══════════════ MODALS ══════════════ -->

<!-- Modal: Transaction -->
<div class="overlay hidden" id="modal-tx" onclick="if(event.target===this)closeModal('modal-tx')">
  <div class="modal">
    <h3 class="serif" style="font-size:20px;margin-bottom:20px" id="modal-tx-title">Новая операция</h3>
    <div class="row-btns" style="margin-bottom:16px">
      <button class="btn btn-gold" id="type-expense-btn" onclick="setTxType('expense')" style="flex:1">Расход</button>
      <button class="btn btn-ghost" id="type-income-btn" onclick="setTxType('income')" style="flex:1">Доход</button>
    </div>
    <div class="form-group">
      <input class="input" id="tx-amount" type="number" placeholder="Сумма (₽)" min="0">
      <select class="input" id="tx-category"></select>
      <input class="input" id="tx-desc" placeholder="Описание (необязательно)">
      <input class="input" id="tx-date" type="date">
    </div>
    <div class="row-btns">
      <button class="btn btn-ghost" style="flex:1" onclick="closeModal('modal-tx')">Отмена</button>
      <button class="btn btn-gold" style="flex:1" id="tx-submit-btn" onclick="submitTx()">Добавить</button>
    </div>
  </div>
</div>

<!-- Modal: Saving -->
<div class="overlay hidden" id="modal-saving" onclick="if(event.target===this)closeModal('modal-saving')">
  <div class="modal">
    <h3 class="serif" style="font-size:20px;margin-bottom:20px" id="modal-saving-title">Новая копилка</h3>
    <div class="form-group">
      <input class="input" id="s-name" placeholder="Название (напр. Отпуск 🏖️)">
      <input class="input" id="s-goal" type="number" placeholder="Цель (₽)" min="1">
      <input class="input" id="s-current" type="number" placeholder="Уже накоплено (₽)" min="0">
      <div>
        <div style="font-size:11px;color:#6b7280;letter-spacing:1px;margin-bottom:8px">ЦВЕТ</div>
        <div style="display:flex;gap:8px" id="color-picker-saving"></div>
      </div>
    </div>
    <div class="row-btns">
      <button class="btn btn-ghost" style="flex:1" onclick="closeModal('modal-saving')">Отмена</button>
      <button class="btn btn-gold" style="flex:1" id="saving-submit-btn" onclick="submitSaving()">Создать</button>
    </div>
  </div>
</div>

<!-- Modal: Deposit -->
<div class="overlay hidden" id="modal-deposit" onclick="if(event.target===this)closeModal('modal-deposit')">
  <div class="modal">
    <h3 class="serif" style="font-size:20px;margin-bottom:6px">Пополнить копилку</h3>
    <p id="deposit-name" style="color:#6b7280;font-size:13px;margin-bottom:20px"></p>
    <input class="input" id="deposit-amount" type="number" placeholder="Сумма (₽)" min="1" style="margin-bottom:8px">
    <input class="input" id="deposit-note" placeholder="Комментарий (необязательно)" style="margin-top:8px;margin-bottom:20px">
    <div class="row-btns">
      <button class="btn btn-ghost" style="flex:1" onclick="closeModal('modal-deposit')">Отмена</button>
      <button class="btn btn-gold" style="flex:1" onclick="submitDeposit()">Пополнить</button>
    </div>
  </div>
</div>

<!-- Modal: Credit -->
<div class="overlay hidden" id="modal-credit" onclick="if(event.target===this)closeModal('modal-credit')">
  <div class="modal">
    <h3 class="serif" style="font-size:20px;margin-bottom:20px" id="modal-credit-title">Новый кредит</h3>
    <div class="form-group">
      <input class="input" id="c-name" placeholder="Название (напр. Ипотека, Авто)">
      <div class="form-row">
        <div><span class="label">Общая сумма (₽)</span><input class="input" id="c-total" type="number" placeholder="500000" min="1"></div>
        <div><span class="label">Остаток (₽)</span><input class="input" id="c-remaining" type="number" placeholder="350000" min="0"></div>
      </div>
      <div class="form-row">
        <div><span class="label">Ежемес. платёж (₽)</span><input class="input" id="c-monthly" type="number" placeholder="15000" min="1"></div>
        <div><span class="label">Ставка (%)</span><input class="input" id="c-rate" type="number" placeholder="12.5" min="0" step="0.1"></div>
      </div>
      <div class="form-row">
        <div><span class="label">Дата начала</span><input class="input" id="c-start" type="date"></div>
        <div><span class="label">Дата окончания</span><input class="input" id="c-end" type="date"></div>
      </div>
      <input class="input" id="c-note" placeholder="Примечание (необязательно)">
      <div>
        <div style="font-size:11px;color:#6b7280;letter-spacing:1px;margin-bottom:8px">ЦВЕТ</div>
        <div style="display:flex;gap:8px" id="color-picker-credit"></div>
      </div>
    </div>
    <div class="row-btns">
      <button class="btn btn-ghost" style="flex:1" onclick="closeModal('modal-credit')">Отмена</button>
      <button class="btn btn-gold" style="flex:1" id="credit-submit-btn" onclick="submitCredit()">Сохранить</button>
    </div>
  </div>
</div>

<!-- Modal: Credit Pay -->
<div class="overlay hidden" id="modal-cpay" onclick="if(event.target===this)closeModal('modal-cpay')">
  <div class="modal">
    <h3 class="serif" style="font-size:20px;margin-bottom:6px">Внести платёж</h3>
    <p id="cpay-name" style="color:#6b7280;font-size:13px;margin-bottom:20px"></p>
    <input class="input" id="cpay-amount" type="number" placeholder="Сумма (₽)" min="1" style="margin-bottom:8px">
    <input class="input" id="cpay-note" placeholder="Комментарий" style="margin-top:8px;margin-bottom:20px">
    <div class="row-btns">
      <button class="btn btn-ghost" style="flex:1" onclick="closeModal('modal-cpay')">Отмена</button>
      <button class="btn btn-gold" style="flex:1" onclick="submitCreditPay()">Внести</button>
    </div>
  </div>
</div>

<!-- Modal: Debt -->
<div class="overlay hidden" id="modal-debt" onclick="if(event.target===this)closeModal('modal-debt')">
  <div class="modal">
    <h3 class="serif" style="font-size:20px;margin-bottom:20px" id="modal-debt-title">Новый долг</h3>
    <div class="form-group">
      <input class="input" id="d-debtor" placeholder="Имя / компания (кто должен)">
      <input class="input" id="d-desc" placeholder="Описание работы / услуги">
      <div class="form-row">
        <div><span class="label">Сумма (₽)</span><input class="input" id="d-total" type="number" placeholder="10000" min="1"></div>
        <div><span class="label">Уже оплачено (₽)</span><input class="input" id="d-paid" type="number" placeholder="0" min="0"></div>
      </div>
      <div><span class="label">Ожидаемая дата оплаты</span><input class="input" id="d-due" type="date"></div>
      <div>
        <div style="font-size:11px;color:#6b7280;letter-spacing:1px;margin-bottom:8px">ЦВЕТ</div>
        <div style="display:flex;gap:8px" id="color-picker-debt"></div>
      </div>
    </div>
    <div class="row-btns">
      <button class="btn btn-ghost" style="flex:1" onclick="closeModal('modal-debt')">Отмена</button>
      <button class="btn btn-gold" style="flex:1" id="debt-submit-btn" onclick="submitDebt()">Сохранить</button>
    </div>
  </div>
</div>

<!-- Modal: Debt Pay -->
<div class="overlay hidden" id="modal-dpay" onclick="if(event.target===this)closeModal('modal-dpay')">
  <div class="modal">
    <h3 class="serif" style="font-size:20px;margin-bottom:6px">Отметить оплату</h3>
    <p id="dpay-name" style="color:#6b7280;font-size:13px;margin-bottom:20px"></p>
    <input class="input" id="dpay-amount" type="number" placeholder="Сумма (₽)" min="1" style="margin-bottom:8px">
    <input class="input" id="dpay-note" placeholder="Комментарий" style="margin-top:8px;margin-bottom:20px">
    <div class="row-btns">
      <button class="btn btn-ghost" style="flex:1" onclick="closeModal('modal-dpay')">Отмена</button>
      <button class="btn btn-gold" style="flex:1" onclick="submitDebtPay()">Отметить</button>
    </div>
  </div>
</div>

<!-- Modal: Recurring -->
<div class="overlay hidden" id="modal-rec" onclick="if(event.target===this)closeModal('modal-rec')">
  <div class="modal">
    <h3 class="serif" style="font-size:20px;margin-bottom:20px" id="modal-rec-title">Новый рег. платёж</h3>
    <div class="form-group">
      <input class="input" id="r-name" placeholder="Название (напр. Аренда, Netflix)">
      <div class="form-row">
        <div><span class="label">Сумма (₽)</span><input class="input" id="r-amount" type="number" placeholder="3000" min="1"></div>
        <div><span class="label">День месяца</span><input class="input" id="r-day" type="number" placeholder="1" min="1" max="31"></div>
      </div>
      <select class="input" id="r-category">
        <option>ЖКХ</option><option>Аренда</option><option>Подписки</option>
        <option>Связь</option><option>Страховка</option><option>Кредит</option><option>Прочее</option>
      </select>
      <input class="input" id="r-note" placeholder="Примечание (необязательно)">
      <div>
        <div style="font-size:11px;color:#6b7280;letter-spacing:1px;margin-bottom:8px">ЦВЕТ</div>
        <div style="display:flex;gap:8px" id="color-picker-rec"></div>
      </div>
    </div>
    <div class="row-btns">
      <button class="btn btn-ghost" style="flex:1" onclick="closeModal('modal-rec')">Отмена</button>
      <button class="btn btn-gold" style="flex:1" id="rec-submit-btn" onclick="submitRecurring()">Сохранить</button>
    </div>
  </div>
</div>

<script>
const COLORS = ['#c9a84c','#6366f1','#10b981','#f87171','#38bdf8','#ec4899','#a78bfa'];
const CATS_EXPENSE = ['Продукты','Транспорт','ЖКХ','Развлечения','Здоровье','Одежда','Семья','Кафе/Рестораны','Кредиты','Связь','Образование','Прочее'];
const CATS_INCOME = ['Зарплата','Фриланс','Инвестиции','Подарки','Прочее'];

let currentTxType = 'expense';
let editingTxId = null;
let editingSavingId = null;
let editingCreditId = null;
let currentCreditId = null;
let editingDebtId = null;
let currentDebtId = null;
let editingRecId = null;
let currentDebtFilter = 'all';

const colorSelected = {saving: COLORS[0], credit: COLORS[3], debt: COLORS[0], rec: COLORS[1]};

document.getElementById('today-date').textContent = new Date().toLocaleDateString('ru-RU',{day:'numeric',month:'long',year:'numeric'});
document.getElementById('tx-date').value = new Date().toISOString().slice(0,10);
document.getElementById('tx-month-filter').value = new Date().toISOString().slice(0,7);
document.getElementById('rec-month-filter').value = new Date().toISOString().slice(0,7);

// Color pickers
function buildColorPicker(containerId, key) {
  const el = document.getElementById(containerId);
  el.innerHTML = COLORS.map(c=>`<div class="color-dot${c===colorSelected[key]?' sel':''}" style="background:${c}" onclick="selectColor('${c}','${key}','${containerId}')"></div>`).join('');
}
function selectColor(c, key, containerId) { colorSelected[key]=c; buildColorPicker(containerId, key); }

['saving','credit','debt','rec'].forEach(k => {
  buildColorPicker(`color-picker-${k}`, k);
});

// Tabs
function showTab(id) {
  ['dashboard','transactions','savings','credits','debts','recurring','report'].forEach(t => {
    document.getElementById('tab-'+t).classList.toggle('hidden', t!==id);
  });
  document.querySelectorAll('.tab').forEach((btn,i) => {
    const names=['dashboard','transactions','savings','credits','debts','recurring','report'];
    btn.classList.toggle('active', names[i]===id);
  });
  if(id==='dashboard') loadDashboard();
  if(id==='transactions') loadTransactions();
  if(id==='savings') loadSavings();
  if(id==='credits') loadCredits();
  if(id==='debts') loadDebts();
  if(id==='recurring') loadRecurring();
  if(id==='report') loadReport();
}

function fmt(n) { return Number(n).toLocaleString('ru-RU')+' ₽'; }

async function api(path, method='GET', body=null) {
  const opts = {method, headers:{'Content-Type':'application/json'}};
  if(body) opts.body = JSON.stringify(body);
  const r = await fetch('/api'+path, opts);
  return r.json();
}

// ── DASHBOARD ─────────────────────────────────────────────────────────────
async function loadDashboard() {
  const [report, txs, savings, credits, debts] = await Promise.all([
    api('/report'), api('/transactions?limit=6'), api('/savings'), api('/credits'), api('/debts')
  ]);

  const totalSavings = savings.reduce((a,s)=>a+s.current,0);
  const totalCreditDebt = credits.reduce((a,c)=>a+c.remaining,0);
  const totalDebtsOwed = debts.filter(d=>d.status!=='paid').reduce((a,d)=>a+(d.total_amount-d.paid_amount),0);

  document.getElementById('dash-stats').innerHTML = [
    {label:'Доходы',val:report.total_income,color:'#34d399',sign:'+'},
    {label:'Расходы',val:report.total_expense,color:'#f87171',sign:'-'},
    {label:'Баланс',val:report.balance,color:report.balance>=0?'#c9a84c':'#f87171',sign:report.balance>=0?'+':''},
    {label:'В копилках',val:totalSavings,color:'#818cf8',sign:''},
  ].map(s=>`<div class="card" style="margin-bottom:0">
    <div class="section-title">${s.label}</div>
    <div class="stat-num" style="color:${s.color}">${s.sign}${fmt(Math.abs(s.val))}</div>
  </div>`).join('');

  const cats = report.by_category.filter(c=>c.type==='expense');
  const maxCat = cats[0]?.total || 1;
  document.getElementById('dash-cats').innerHTML = cats.slice(0,6).map(c=>`
    <div style="margin-bottom:10px">
      <div style="display:flex;justify-content:space-between;margin-bottom:4px">
        <span style="font-size:13px">${c.category}</span>
        <span style="color:#9ca3af;font-size:12px">${fmt(c.total)}</span>
      </div>
      <div class="progress-bar"><div class="progress-fill" style="width:${(c.total/maxCat*100).toFixed(1)}%;background:#c9a84c88"></div></div>
    </div>`).join('') || '<div style="color:#4b5563;font-size:13px">Нет данных</div>';

  document.getElementById('dash-savings').innerHTML = savings.map(s=>{
    const pct = Math.min(100,(s.current/s.goal*100)).toFixed(0);
    return `<div style="margin-bottom:14px">
      <div style="display:flex;justify-content:space-between;margin-bottom:5px">
        <span style="font-size:13px">${s.name}</span>
        <span style="font-size:11px;color:#6b7280">${pct}%</span>
      </div>
      <div class="progress-bar"><div class="progress-fill" style="width:${pct}%;background:${s.color}"></div></div>
      <div style="font-size:11px;color:#4b5563;margin-top:4px">${fmt(s.current)} / ${fmt(s.goal)}</div>
    </div>`;
  }).join('') || '<div style="color:#4b5563;font-size:13px">Нет копилок</div>';

  document.getElementById('dash-credits').innerHTML = credits.length ? credits.map(c=>{
    const pct = Math.min(100,((c.total_amount-c.remaining)/c.total_amount*100)).toFixed(0);
    return `<div style="margin-bottom:14px">
      <div style="display:flex;justify-content:space-between;margin-bottom:5px">
        <span style="font-size:13px">${c.name}</span>
        <span style="font-size:11px;color:#f87171">${fmt(c.remaining)}</span>
      </div>
      <div class="progress-bar"><div class="progress-fill" style="width:${pct}%;background:${c.color}66"></div></div>
      <div style="font-size:11px;color:#4b5563;margin-top:4px">Платёж: ${fmt(c.monthly_payment)}/мес</div>
    </div>`;
  }).join('') + `<div style="font-size:11px;color:#6b7280;margin-top:8px;padding-top:8px;border-top:1px solid #1e2235">Итого долг: <span style="color:#f87171">${fmt(totalCreditDebt)}</span></div>`
  : '<div style="color:#4b5563;font-size:13px">Нет кредитов</div>';

  const activeDebts = debts.filter(d=>d.status!=='paid');
  document.getElementById('dash-debts').innerHTML = activeDebts.length ? activeDebts.map(d=>{
    const owed = d.total_amount - d.paid_amount;
    const overdue = d.due_date && d.due_date < new Date().toISOString().slice(0,10);
    return `<div style="margin-bottom:12px;display:flex;justify-content:space-between;align-items:center">
      <div>
        <div style="font-size:13px">${d.debtor_name}</div>
        <div style="font-size:11px;color:#4b5563">${d.description.slice(0,30)}${d.description.length>30?'…':''}</div>
      </div>
      <div style="text-align:right">
        <div style="font-size:13px;color:${d.color};font-weight:600">${fmt(owed)}</div>
        ${overdue?'<div style="font-size:10px;color:#f87171">просрочен</div>':''}
      </div>
    </div>`;
  }).join('') + `<div style="font-size:11px;color:#6b7280;margin-top:8px;padding-top:8px;border-top:1px solid #1e2235">Итого: <span style="color:#c9a84c">${fmt(totalDebtsOwed)}</span></div>`
  : '<div style="color:#4b5563;font-size:13px">Нет долгов</div>';

  document.getElementById('dash-recent').innerHTML = txs.map(t=>`
    <div class="tx-row">
      <div style="display:flex;align-items:center;gap:12px">
        <span class="${t.type==='income'?'badge-i':'badge-e'}">${t.type==='income'?'↑':'↓'}</span>
        <div>
          <div style="font-size:13px">${t.description||t.category}</div>
          <div class="tx-meta">${t.category} · ${t.date}</div>
        </div>
      </div>
      <div style="font-size:14px;font-weight:600;color:${t.type==='income'?'#34d399':'#f87171'}">${t.type==='income'?'+':'-'}${fmt(t.amount)}</div>
    </div>`).join('') || '<div style="color:#4b5563;font-size:13px">Нет операций</div>';
}

// ── TRANSACTIONS ───────────────────────────────────────────────────────────
async function loadTransactions() {
  const month = document.getElementById('tx-month-filter').value;
  const url = '/transactions' + (month ? '?month='+month : '');
  const txs = await api(url);
  document.getElementById('tx-list').innerHTML = txs.length
    ? txs.map(t=>`
      <div class="tx-row">
        <div style="display:flex;align-items:center;gap:12px">
          <span class="${t.type==='income'?'badge-i':'badge-e'}">${t.type==='income'?'Доход':'Расход'}</span>
          <div>
            <div style="font-size:13px">${t.description||'—'}</div>
            <div class="tx-meta">${t.category} · ${t.date}</div>
          </div>
        </div>
        <div style="display:flex;align-items:center;gap:8px">
          <div style="font-size:14px;font-weight:600;color:${t.type==='income'?'#34d399':'#f87171'}">${t.type==='income'?'+':'-'}${fmt(t.amount)}</div>
          <button class="btn btn-edit" style="padding:5px 10px;font-size:11px" onclick="openEditTxModal(${JSON.stringify(t).replace(/"/g,'&quot;')})">✎</button>
          <button class="btn btn-danger" style="padding:5px 10px;font-size:11px" onclick="deleteTx(${t.id})">✕</button>
        </div>
      </div>`).join('')
    : '<div style="color:#4b5563;text-align:center;padding:20px">Операций нет</div>';
}

async function deleteTx(id) {
  if(!confirm('Удалить операцию?')) return;
  await api('/transactions/'+id, 'DELETE');
  loadTransactions(); loadDashboard();
}

// ── SAVINGS ────────────────────────────────────────────────────────────────
async function loadSavings() {
  const savings = await api('/savings');
  document.getElementById('savings-grid').innerHTML = savings.map(s=>{
    const pct = Math.min(100,Math.round(s.current/s.goal*100));
    const left = s.goal - s.current;
    return `<div class="card" style="border-top:3px solid ${s.color};margin-bottom:0">
      <div style="font-size:18px;margin-bottom:12px;font-family:'Playfair Display',serif">${s.name}</div>
      <div class="section-title">Накоплено</div>
      <div style="font-size:24px;font-weight:700;color:${s.color};font-family:'JetBrains Mono',monospace;margin-bottom:12px">${fmt(s.current)}</div>
      <div class="progress-bar" style="margin-bottom:8px"><div class="progress-fill" style="width:${pct}%;background:${s.color}"></div></div>
      <div style="display:flex;justify-content:space-between;font-size:11px;color:#4b5563;margin-bottom:16px">
        <span>${pct}% выполнено</span><span>Осталось: ${fmt(left)}</span>
      </div>
      <div style="display:flex;justify-content:space-between;align-items:center">
        <span style="font-size:11px;color:#4b5563">Цель: ${fmt(s.goal)}</span>
        <div style="display:flex;gap:6px">
          <button class="btn btn-ghost" style="padding:6px 12px;font-size:11px" onclick="openDeposit(${s.id},'${s.name.replace(/'/,"\'")}')">Пополнить</button>
          <button class="btn btn-edit" style="padding:6px 10px;font-size:11px" onclick="openEditSavingModal(${JSON.stringify(s).replace(/"/g,'&quot;')})">✎</button>
          <button class="btn btn-danger" style="padding:6px 10px;font-size:11px" onclick="deleteSaving(${s.id})">✕</button>
        </div>
      </div>
    </div>`;
  }).join('') || '<div style="color:#4b5563;text-align:center;padding:40px;grid-column:1/-1">Нет копилок. Создайте первую!</div>';
}

async function deleteSaving(id) {
  if(!confirm('Удалить копилку? Все данные пополнений будут удалены.')) return;
  await api('/savings/'+id, 'DELETE');
  loadSavings();
}

// ── CREDITS ────────────────────────────────────────────────────────────────
async function loadCredits() {
  const credits = await api('/credits');
  const totalRemaining = credits.reduce((a,c)=>a+c.remaining,0);
  const totalMonthly = credits.reduce((a,c)=>a+c.monthly_payment,0);

  document.getElementById('credits-summary').innerHTML = credits.length ? `
    <div class="grid3">
      <div class="card" style="margin-bottom:0">
        <div class="section-title">Кредитов</div>
        <div class="stat-num" style="color:#9ca3af">${credits.length}</div>
      </div>
      <div class="card" style="margin-bottom:0">
        <div class="section-title">Общий остаток</div>
        <div class="stat-num" style="color:#f87171">${fmt(totalRemaining)}</div>
      </div>
      <div class="card" style="margin-bottom:0">
        <div class="section-title">Платёж в месяц</div>
        <div class="stat-num" style="color:#f59e0b">${fmt(totalMonthly)}</div>
      </div>
    </div>` : '';

  document.getElementById('credits-grid').innerHTML = credits.map(c=>{
    const paid = c.total_amount - c.remaining;
    const pct = Math.min(100,Math.round(paid/c.total_amount*100));
    const monthsLeft = c.monthly_payment > 0 ? Math.ceil(c.remaining / c.monthly_payment) : '?';
    return `<div class="credit-card" style="border-top:3px solid ${c.color}">
      <div style="display:flex;justify-content:space-between;align-items:start;margin-bottom:16px">
        <div>
          <div style="font-size:17px;font-family:'Playfair Display',serif">${c.name}</div>
          ${c.interest_rate>0?`<div style="font-size:11px;color:#6b7280;margin-top:2px">Ставка: ${c.interest_rate}%</div>`:''}
        </div>
        <div style="display:flex;gap:6px">
          <button class="btn btn-edit" style="padding:5px 10px;font-size:11px" onclick="openEditCreditModal(${JSON.stringify(c).replace(/"/g,'&quot;')})">✎</button>
          <button class="btn btn-danger" style="padding:5px 10px;font-size:11px" onclick="deleteCredit(${c.id})">✕</button>
        </div>
      </div>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:16px">
        <div>
          <div class="section-title">Остаток</div>
          <div style="font-size:20px;font-weight:700;color:${c.color}">${fmt(c.remaining)}</div>
        </div>
        <div>
          <div class="section-title">Ежемес. платёж</div>
          <div style="font-size:20px;font-weight:700;color:#f59e0b">${fmt(c.monthly_payment)}</div>
        </div>
      </div>
      <div class="progress-bar" style="margin-bottom:8px"><div class="progress-fill" style="width:${pct}%;background:${c.color}"></div></div>
      <div style="display:flex;justify-content:space-between;font-size:11px;color:#4b5563;margin-bottom:16px">
        <span>${pct}% выплачено</span>
        <span>~${monthsLeft} мес. осталось</span>
      </div>
      ${c.note?`<div style="font-size:12px;color:#6b7280;margin-bottom:12px">${c.note}</div>`:''}
      <button class="btn btn-gold" style="width:100%;padding:8px" onclick="openCreditPay(${c.id},'${c.name.replace(/'/,"\'")}')">Внести платёж</button>
    </div>`;
  }).join('') || '<div style="color:#4b5563;text-align:center;padding:40px;grid-column:1/-1">Нет кредитов. Добавьте первый!</div>';
}

async function deleteCredit(id) {
  if(!confirm('Удалить кредит?')) return;
  await api('/credits/'+id, 'DELETE');
  loadCredits(); loadDashboard();
}

// ── DEBTS ──────────────────────────────────────────────────────────────────
let allDebts = [];

function setDebtFilter(f) {
  currentDebtFilter = f;
  ['all','active','partial','paid'].forEach(x => {
    document.getElementById('debt-filter-'+x).className = 'btn '+(x===f?'btn-gold':'btn-ghost');
    document.getElementById('debt-filter-'+x).style.cssText = 'font-size:11px;padding:6px 14px';
  });
  renderDebts();
}

async function loadDebts() {
  allDebts = await api('/debts');
  const activeDebts = allDebts.filter(d=>d.status!=='paid');
  const totalOwed = activeDebts.reduce((a,d)=>a+(d.total_amount-d.paid_amount),0);
  const totalAll = allDebts.reduce((a,d)=>a+d.total_amount,0);

  document.getElementById('debts-summary').innerHTML = allDebts.length ? `
    <div class="grid3">
      <div class="card" style="margin-bottom:0">
        <div class="section-title">Всего долгов</div>
        <div class="stat-num" style="color:#9ca3af">${allDebts.length}</div>
      </div>
      <div class="card" style="margin-bottom:0">
        <div class="section-title">Ожидается к получению</div>
        <div class="stat-num" style="color:#c9a84c">${fmt(totalOwed)}</div>
      </div>
      <div class="card" style="margin-bottom:0">
        <div class="section-title">Всего выставлено</div>
        <div class="stat-num" style="color:#9ca3af">${fmt(totalAll)}</div>
      </div>
    </div>` : '';

  setDebtFilter(currentDebtFilter);
}

function renderDebts() {
  const filtered = currentDebtFilter === 'all' ? allDebts : allDebts.filter(d=>d.status===currentDebtFilter);
  const statusLabel = {active:'Ожидает оплаты', partial:'Частично', paid:'Выплачено'};
  const statusColor = {active:'#f59e0b', partial:'#818cf8', paid:'#34d399'};

  document.getElementById('debts-list').innerHTML = filtered.length ? filtered.map(d=>{
    const owed = d.total_amount - d.paid_amount;
    const pct = Math.min(100,Math.round(d.paid_amount/d.total_amount*100));
    const overdue = d.due_date && d.status!=='paid' && d.due_date < new Date().toISOString().slice(0,10);
    return `<div class="card debt-card" style="border-left:4px solid ${d.color}">
      <div style="display:flex;justify-content:space-between;align-items:start">
        <div style="flex:1">
          <div style="display:flex;align-items:center;gap:8px;margin-bottom:6px">
            <span style="font-size:16px;font-family:'Playfair Display',serif">${d.debtor_name}</span>
            <span style="font-size:10px;padding:2px 8px;border-radius:10px;background:${statusColor[d.status]}22;color:${statusColor[d.status]}">${statusLabel[d.status]}</span>
            ${overdue?'<span style="font-size:10px;padding:2px 8px;border-radius:10px;background:#f8717122;color:#f87171">Просрочен</span>':''}
          </div>
          <div style="font-size:13px;color:#9ca3af;margin-bottom:12px">${d.description}</div>
        </div>
        <div style="display:flex;gap:6px;margin-left:12px">
          <button class="btn btn-edit" style="padding:5px 10px;font-size:11px" onclick="openEditDebtModal(${JSON.stringify(d).replace(/"/g,'&quot;')})">✎</button>
          <button class="btn btn-danger" style="padding:5px 10px;font-size:11px" onclick="deleteDebt(${d.id})">✕</button>
        </div>
      </div>
      <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px;margin-bottom:12px">
        <div>
          <div class="section-title">Итого</div>
          <div style="font-size:16px;font-weight:600">${fmt(d.total_amount)}</div>
        </div>
        <div>
          <div class="section-title">Оплачено</div>
          <div style="font-size:16px;font-weight:600;color:#34d399">${fmt(d.paid_amount)}</div>
        </div>
        <div>
          <div class="section-title">Остаток</div>
          <div style="font-size:16px;font-weight:600;color:${d.color}">${fmt(owed)}</div>
        </div>
      </div>
      <div class="progress-bar" style="margin-bottom:8px"><div class="progress-fill" style="width:${pct}%;background:${d.color}"></div></div>
      <div style="display:flex;justify-content:space-between;align-items:center">
        <div style="font-size:11px;color:#4b5563">${d.due_date?'Срок: '+d.due_date:''}</div>
        ${d.status!=='paid'?`<button class="btn btn-gold" style="padding:6px 16px;font-size:11px" onclick="openDebtPay(${d.id},'${d.debtor_name.replace(/'/,"\'")}')">Отметить оплату</button>`:'<span style="font-size:11px;color:#34d399">✓ Выплачено</span>'}
      </div>
    </div>`;
  }).join('')
  : '<div style="color:#4b5563;text-align:center;padding:40px">Нет долгов в этой категории</div>';
}

async function deleteDebt(id) {
  if(!confirm('Удалить запись о долге?')) return;
  await api('/debts/'+id, 'DELETE');
  loadDebts(); loadDashboard();
}

// ── RECURRING ──────────────────────────────────────────────────────────────
async function loadRecurring() {
  const month = document.getElementById('rec-month-filter').value;
  const url = '/recurring' + (month ? '?month='+month : '');
  const items = await api(url);
  const total = items.reduce((a,r)=>a+r.amount,0);
  const paid = items.filter(r=>r.paid).reduce((a,r)=>a+r.amount,0);
  const unpaid = total - paid;

  document.getElementById('recurring-summary').innerHTML = items.length ? `
    <div class="grid3">
      <div class="card" style="margin-bottom:0">
        <div class="section-title">Всего в месяц</div>
        <div class="stat-num" style="color:#9ca3af">${fmt(total)}</div>
      </div>
      <div class="card" style="margin-bottom:0">
        <div class="section-title">Оплачено</div>
        <div class="stat-num" style="color:#34d399">${fmt(paid)}</div>
      </div>
      <div class="card" style="margin-bottom:0">
        <div class="section-title">Не оплачено</div>
        <div class="stat-num" style="color:#f87171">${fmt(unpaid)}</div>
      </div>
    </div>` : '';

  document.getElementById('recurring-list').innerHTML = items.length ? items.map(r=>`
    <div class="rec-row">
      <div style="display:flex;align-items:center;gap:14px">
        <div style="width:10px;height:10px;border-radius:50%;background:${r.color};flex-shrink:0"></div>
        <div>
          <div style="font-size:14px">${r.name}</div>
          <div class="tx-meta">${r.category} · ${r.day_of_month} числа${r.note?' · '+r.note:''}</div>
        </div>
      </div>
      <div style="display:flex;align-items:center;gap:12px">
        <div style="font-size:14px;font-weight:600;color:${r.paid?'#34d399':'#9ca3af'}">${fmt(r.amount)}</div>
        <div style="display:flex;align-items:center;gap:6px">
          <button class="toggle-paid ${r.paid?'on':'off'}" onclick="togglePaid(${r.id},'${r.month}',${!r.paid})" title="${r.paid?'Оплачено, нажмите чтобы отменить':'Отметить как оплачено'}"></button>
          <span style="font-size:10px;color:${r.paid?'#34d399':'#6b7280'}">${r.paid?'Оплачено':'Не оплачено'}</span>
        </div>
        <button class="btn btn-edit" style="padding:5px 10px;font-size:11px" onclick="openEditRecModal(${JSON.stringify(r).replace(/"/g,'&quot;')})">✎</button>
        <button class="btn btn-danger" style="padding:5px 10px;font-size:11px" onclick="deleteRec(${r.id})">✕</button>
      </div>
    </div>`).join('')
  : '<div style="color:#4b5563;text-align:center;padding:20px">Нет регулярных платежей</div>';
}

async function togglePaid(id, month, paid) {
  await api('/recurring/'+id+'/toggle', 'POST', {month, paid});
  loadRecurring();
}

async function deleteRec(id) {
  if(!confirm('Удалить регулярный платёж?')) return;
  await api('/recurring/'+id, 'DELETE');
  loadRecurring();
}

// ── REPORT ─────────────────────────────────────────────────────────────────
async function loadReport() {
  const month = document.getElementById('report-month-filter').value;
  const url = '/report' + (month ? '?month='+month : '');
  const r = await api(url);
  const savingsTotal = r.savings.reduce((a,s)=>a+s.current,0);

  document.getElementById('report-content').innerHTML = `
    <div class="grid2">
      <div class="card">
        <div class="section-title">Финансовый результат</div>
        ${[
          {l:'Общий доход',v:fmt(r.total_income),c:'#34d399'},
          {l:'Общий расход',v:fmt(r.total_expense),c:'#f87171'},
          {l:'Чистый результат',v:(r.balance>=0?'+':'')+fmt(r.balance),c:r.balance>=0?'#c9a84c':'#f87171'},
          {l:'Норма сбережений',v:r.savings_rate+'%',c:'#818cf8'},
          {l:'Кол-во операций',v:r.tx_count,c:'#9ca3af'},
          {l:'В копилках',v:fmt(savingsTotal),c:'#c9a84c'},
          {l:'Долг по кредитам',v:fmt(r.total_credit_debt),c:'#f87171'},
          {l:'Ежемес. по кредитам',v:fmt(r.total_monthly_credits),c:'#f59e0b'},
          {l:'Ожидается от должников',v:fmt(r.total_debts_owed),c:'#c9a84c'},
        ].map(s=>`<div style="display:flex;justify-content:space-between;padding:10px 0;border-bottom:1px solid #1e2235">
          <span style="font-size:13px;color:#9ca3af">${s.l}</span>
          <span style="font-size:14px;font-weight:600;color:${s.c}">${s.v}</span>
        </div>`).join('')}
      </div>
      <div class="card">
        <div class="section-title">Топ расходов</div>
        ${r.by_category.filter(c=>c.type==='expense').slice(0,7).map((c,i)=>`
          <div style="display:flex;align-items:center;gap:10px;margin-bottom:10px">
            <span style="font-size:11px;color:#4b5563;width:14px">${i+1}</span>
            <div style="flex:1">
              <div style="display:flex;justify-content:space-between;margin-bottom:3px">
                <span style="font-size:13px">${c.category}</span>
                <span style="font-size:12px;color:#9ca3af">${fmt(c.total)}</span>
              </div>
              <div class="progress-bar" style="height:4px">
                <div class="progress-fill" style="width:${r.total_expense>0?(c.total/r.total_expense*100).toFixed(1):0}%;background:#c9a84c"></div>
              </div>
            </div>
          </div>`).join('') || '<div style="color:#4b5563">Нет данных</div>'}
      </div>
    </div>
    <div class="card">
      <div class="section-title">История по месяцам</div>
      <div style="overflow-x:auto">
        <table style="width:100%;border-collapse:collapse;font-size:13px">
          <thead><tr style="color:#6b7280;font-size:11px;letter-spacing:1px">
            <th style="text-align:left;padding:8px 0">МЕС</th>
            <th style="text-align:right;padding:8px 0">ДОХОД</th>
            <th style="text-align:right;padding:8px 0">РАСХОД</th>
            <th style="text-align:right;padding:8px 0">РЕЗУЛЬТАТ</th>
          </tr></thead>
          <tbody>
            ${r.by_month.map(m=>{
              const bal=m.income-m.expense;
              return `<tr style="border-top:1px solid #1e2235">
                <td style="padding:10px 0;color:#9ca3af">${m.month}</td>
                <td style="text-align:right;padding:10px 0;color:#34d399">+${fmt(m.income)}</td>
                <td style="text-align:right;padding:10px 0;color:#f87171">-${fmt(m.expense)}</td>
                <td style="text-align:right;padding:10px 0;font-weight:600;color:${bal>=0?'#c9a84c':'#f87171'}">${bal>=0?'+':''}${fmt(bal)}</td>
              </tr>`;
            }).join('') || '<tr><td colspan="4" style="text-align:center;padding:20px;color:#4b5563">Нет данных</td></tr>'}
          </tbody>
        </table>
      </div>
    </div>`;
}

// ══ MODAL HELPERS ══════════════════════════════════════════════════════════
function openModal(id) { document.getElementById(id).classList.remove('hidden'); }
function closeModal(id) { document.getElementById(id).classList.add('hidden'); }

// ── TX Modal ───────────────────────────────────────────────────────────────
function setTxType(t) {
  currentTxType=t;
  document.getElementById('type-expense-btn').className='btn '+(t==='expense'?'btn-gold':'btn-ghost');
  document.getElementById('type-income-btn').className='btn '+(t==='income'?'btn-gold':'btn-ghost');
  const cats = t==='income'?CATS_INCOME:CATS_EXPENSE;
  document.getElementById('tx-category').innerHTML=cats.map(c=>`<option>${c}</option>`).join('');
}

function openTxModal() {
  editingTxId = null;
  document.getElementById('modal-tx-title').textContent = 'Новая операция';
  document.getElementById('tx-submit-btn').textContent = 'Добавить';
  setTxType('expense');
  document.getElementById('tx-amount').value='';
  document.getElementById('tx-desc').value='';
  document.getElementById('tx-date').value=new Date().toISOString().slice(0,10);
  openModal('modal-tx');
}

function openEditTxModal(t) {
  editingTxId = t.id;
  document.getElementById('modal-tx-title').textContent = 'Редактировать операцию';
  document.getElementById('tx-submit-btn').textContent = 'Сохранить';
  setTxType(t.type);
  document.getElementById('tx-amount').value = t.amount;
  document.getElementById('tx-desc').value = t.description||'';
  document.getElementById('tx-date').value = t.date;
  // Set category after setTxType builds the list
  setTimeout(()=>{
    const sel = document.getElementById('tx-category');
    for(let o of sel.options) { if(o.value===t.category) { o.selected=true; break; } }
  }, 0);
  openModal('modal-tx');
}

async function submitTx() {
  const amount=document.getElementById('tx-amount').value;
  const category=document.getElementById('tx-category').value;
  const date=document.getElementById('tx-date').value;
  if(!amount||!category||!date){alert('Заполните обязательные поля');return;}
  const payload = {type:currentTxType, amount:parseFloat(amount), category, description:document.getElementById('tx-desc').value, date};
  if(editingTxId) {
    await api('/transactions/'+editingTxId, 'PUT', payload);
  } else {
    await api('/transactions','POST', payload);
  }
  closeModal('modal-tx');
  loadTransactions(); loadDashboard();
}

// ── Saving Modal ───────────────────────────────────────────────────────────
function openSavingModal() {
  editingSavingId = null;
  document.getElementById('modal-saving-title').textContent = 'Новая копилка';
  document.getElementById('saving-submit-btn').textContent = 'Создать';
  document.getElementById('s-name').value='';
  document.getElementById('s-goal').value='';
  document.getElementById('s-current').value='';
  colorSelected.saving=COLORS[0]; buildColorPicker('color-picker-saving','saving');
  openModal('modal-saving');
}

function openEditSavingModal(s) {
  editingSavingId = s.id;
  document.getElementById('modal-saving-title').textContent = 'Редактировать копилку';
  document.getElementById('saving-submit-btn').textContent = 'Сохранить';
  document.getElementById('s-name').value=s.name;
  document.getElementById('s-goal').value=s.goal;
  document.getElementById('s-current').value=s.current;
  colorSelected.saving=s.color||COLORS[0]; buildColorPicker('color-picker-saving','saving');
  openModal('modal-saving');
}

async function submitSaving() {
  const name=document.getElementById('s-name').value;
  const goal=document.getElementById('s-goal').value;
  if(!name||!goal){alert('Заполните обязательные поля');return;}
  const payload = {name, goal:parseFloat(goal), current:parseFloat(document.getElementById('s-current').value||0), color:colorSelected.saving};
  if(editingSavingId) {
    await api('/savings/'+editingSavingId, 'PUT', payload);
  } else {
    await api('/savings','POST', payload);
  }
  closeModal('modal-saving');
  loadSavings(); loadDashboard();
}

// Deposit Modal
function openDeposit(id, name) {
  currentSavingId=id;
  document.getElementById('deposit-name').textContent=name;
  document.getElementById('deposit-amount').value='';
  document.getElementById('deposit-note').value='';
  openModal('modal-deposit');
}
let currentSavingId = null;
async function submitDeposit() {
  const amount=document.getElementById('deposit-amount').value;
  if(!amount){alert('Введите сумму');return;}
  await api('/savings/'+currentSavingId+'/deposit','POST',{amount:parseFloat(amount),note:document.getElementById('deposit-note').value});
  closeModal('modal-deposit');
  loadSavings(); loadDashboard();
}

// ── Credit Modal ───────────────────────────────────────────────────────────
function openCreditModal() {
  editingCreditId = null;
  document.getElementById('modal-credit-title').textContent = 'Новый кредит';
  document.getElementById('credit-submit-btn').textContent = 'Добавить';
  ['c-name','c-total','c-remaining','c-monthly','c-rate','c-note'].forEach(id=>document.getElementById(id).value='');
  document.getElementById('c-start').value = new Date().toISOString().slice(0,10);
  document.getElementById('c-end').value = '';
  colorSelected.credit=COLORS[3]; buildColorPicker('color-picker-credit','credit');
  openModal('modal-credit');
}

function openEditCreditModal(c) {
  editingCreditId = c.id;
  document.getElementById('modal-credit-title').textContent = 'Редактировать кредит';
  document.getElementById('credit-submit-btn').textContent = 'Сохранить';
  document.getElementById('c-name').value=c.name;
  document.getElementById('c-total').value=c.total_amount;
  document.getElementById('c-remaining').value=c.remaining;
  document.getElementById('c-monthly').value=c.monthly_payment;
  document.getElementById('c-rate').value=c.interest_rate||'';
  document.getElementById('c-start').value=c.start_date;
  document.getElementById('c-end').value=c.end_date||'';
  document.getElementById('c-note').value=c.note||'';
  colorSelected.credit=c.color||COLORS[3]; buildColorPicker('color-picker-credit','credit');
  openModal('modal-credit');
}

async function submitCredit() {
  const name=document.getElementById('c-name').value;
  const total=document.getElementById('c-total').value;
  const remaining=document.getElementById('c-remaining').value;
  const monthly=document.getElementById('c-monthly').value;
  if(!name||!total||!monthly){alert('Заполните обязательные поля');return;}
  const payload = {
    name, total_amount:parseFloat(total),
    remaining:parseFloat(remaining||total),
    monthly_payment:parseFloat(monthly),
    interest_rate:parseFloat(document.getElementById('c-rate').value||0),
    start_date:document.getElementById('c-start').value,
    end_date:document.getElementById('c-end').value,
    note:document.getElementById('c-note').value,
    color:colorSelected.credit
  };
  if(editingCreditId) {
    await api('/credits/'+editingCreditId, 'PUT', payload);
  } else {
    await api('/credits','POST', payload);
  }
  closeModal('modal-credit');
  loadCredits(); loadDashboard();
}

function openCreditPay(id, name) {
  currentCreditId=id;
  document.getElementById('cpay-name').textContent=name;
  document.getElementById('cpay-amount').value='';
  document.getElementById('cpay-note').value='';
  openModal('modal-cpay');
}

async function submitCreditPay() {
  const amount=document.getElementById('cpay-amount').value;
  if(!amount){alert('Введите сумму');return;}
  await api('/credits/'+currentCreditId+'/pay','POST',{amount:parseFloat(amount),note:document.getElementById('cpay-note').value});
  closeModal('modal-cpay');
  loadCredits(); loadDashboard();
}

// ── Debt Modal ─────────────────────────────────────────────────────────────
function openDebtModal() {
  editingDebtId = null;
  document.getElementById('modal-debt-title').textContent = 'Новый долг';
  document.getElementById('debt-submit-btn').textContent = 'Добавить';
  ['d-debtor','d-desc','d-total','d-paid','d-due'].forEach(id=>document.getElementById(id).value='');
  colorSelected.debt=COLORS[0]; buildColorPicker('color-picker-debt','debt');
  openModal('modal-debt');
}

function openEditDebtModal(d) {
  editingDebtId = d.id;
  document.getElementById('modal-debt-title').textContent = 'Редактировать долг';
  document.getElementById('debt-submit-btn').textContent = 'Сохранить';
  document.getElementById('d-debtor').value=d.debtor_name;
  document.getElementById('d-desc').value=d.description;
  document.getElementById('d-total').value=d.total_amount;
  document.getElementById('d-paid').value=d.paid_amount;
  document.getElementById('d-due').value=d.due_date||'';
  colorSelected.debt=d.color||COLORS[0]; buildColorPicker('color-picker-debt','debt');
  openModal('modal-debt');
}

async function submitDebt() {
  const debtor=document.getElementById('d-debtor').value;
  const desc=document.getElementById('d-desc').value;
  const total=document.getElementById('d-total').value;
  if(!debtor||!desc||!total){alert('Заполните обязательные поля');return;}
  const payload = {
    debtor_name:debtor, description:desc,
    total_amount:parseFloat(total),
    paid_amount:parseFloat(document.getElementById('d-paid').value||0),
    due_date:document.getElementById('d-due').value,
    color:colorSelected.debt
  };
  if(editingDebtId) {
    await api('/debts/'+editingDebtId, 'PUT', payload);
  } else {
    await api('/debts','POST', payload);
  }
  closeModal('modal-debt');
  loadDebts(); loadDashboard();
}

function openDebtPay(id, name) {
  currentDebtId=id;
  document.getElementById('dpay-name').textContent=name;
  document.getElementById('dpay-amount').value='';
  document.getElementById('dpay-note').value='';
  openModal('modal-dpay');
}

async function submitDebtPay() {
  const amount=document.getElementById('dpay-amount').value;
  if(!amount){alert('Введите сумму');return;}
  await api('/debts/'+currentDebtId+'/pay','POST',{amount:parseFloat(amount),note:document.getElementById('dpay-note').value});
  closeModal('modal-dpay');
  loadDebts(); loadDashboard();
}

// ── Recurring Modal ────────────────────────────────────────────────────────
function openRecurringModal() {
  editingRecId = null;
  document.getElementById('modal-rec-title').textContent = 'Новый рег. платёж';
  document.getElementById('rec-submit-btn').textContent = 'Добавить';
  ['r-name','r-amount','r-note'].forEach(id=>document.getElementById(id).value='');
  document.getElementById('r-day').value='1';
  colorSelected.rec=COLORS[1]; buildColorPicker('color-picker-rec','rec');
  openModal('modal-rec');
}

function openEditRecModal(r) {
  editingRecId = r.id;
  document.getElementById('modal-rec-title').textContent = 'Редактировать платёж';
  document.getElementById('rec-submit-btn').textContent = 'Сохранить';
  document.getElementById('r-name').value=r.name;
  document.getElementById('r-amount').value=r.amount;
  document.getElementById('r-day').value=r.day_of_month;
  document.getElementById('r-note').value=r.note||'';
  colorSelected.rec=r.color||COLORS[1]; buildColorPicker('color-picker-rec','rec');
  setTimeout(()=>{
    const sel = document.getElementById('r-category');
    for(let o of sel.options) { if(o.value===r.category) { o.selected=true; break; } }
  }, 0);
  openModal('modal-rec');
}

async function submitRecurring() {
  const name=document.getElementById('r-name').value;
  const amount=document.getElementById('r-amount').value;
  if(!name||!amount){alert('Заполните обязательные поля');return;}
  const payload = {
    name, amount:parseFloat(amount),
    category:document.getElementById('r-category').value,
    day_of_month:parseInt(document.getElementById('r-day').value)||1,
    note:document.getElementById('r-note').value,
    color:colorSelected.rec
  };
  if(editingRecId) {
    await api('/recurring/'+editingRecId, 'PUT', payload);
  } else {
    await api('/recurring','POST', payload);
  }
  closeModal('modal-rec');
  loadRecurring();
}

// Запуск
loadDashboard();
</script>
</body>
</html>
"""

# ── HTTP Handler ─────────────────────────────────────────────────────────────

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args): pass

    def send_json(self, status, data):
        body = (data if isinstance(data, bytes) else data.encode("utf-8"))
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        qs = parse_qs(parsed.query)

        if path in ("/", "/index.html"):
            body = HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", len(body))
            self.end_headers()
            self.wfile.write(body)

        elif path == "/api/transactions":
            filters = {}
            if "type" in qs: filters["type"] = qs["type"][0]
            if "month" in qs: filters["month"] = qs["month"][0]
            txs = get_transactions(filters)
            limit = int(qs.get("limit", [9999])[0])
            self.send_json(200, json.dumps(txs[:limit], ensure_ascii=False, default=str))

        elif path == "/api/savings":
            self.send_json(200, json.dumps(get_savings(), ensure_ascii=False, default=str))

        elif path == "/api/credits":
            self.send_json(200, json.dumps(get_credits(), ensure_ascii=False, default=str))

        elif path == "/api/debts":
            self.send_json(200, json.dumps(get_debts(), ensure_ascii=False, default=str))

        elif path == "/api/recurring":
            month = qs.get("month", [None])[0]
            self.send_json(200, json.dumps(get_recurring(month), ensure_ascii=False, default=str))

        elif path == "/api/report":
            month = qs.get("month", [None])[0]
            self.send_json(200, json.dumps(get_report(month), ensure_ascii=False, default=str))

        else:
            self.send_response(404); self.end_headers()

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length)) if length else {}
        path = self.path

        if path == "/api/transactions":
            tx = add_transaction(body)
            self.send_json(201, json.dumps(tx, ensure_ascii=False, default=str))

        elif path == "/api/savings":
            s = add_saving(body)
            self.send_json(201, json.dumps(s, ensure_ascii=False, default=str))

        elif path.startswith("/api/savings/") and path.endswith("/deposit"):
            saving_id = int(path.split("/")[3])
            s = deposit_saving(saving_id, body["amount"], body.get("note",""))
            self.send_json(200, json.dumps(s, ensure_ascii=False, default=str))

        elif path == "/api/credits":
            c = add_credit(body)
            self.send_json(201, json.dumps(c, ensure_ascii=False, default=str))

        elif path.startswith("/api/credits/") and path.endswith("/pay"):
            credit_id = int(path.split("/")[3])
            c = pay_credit(credit_id, body["amount"], body.get("note",""))
            self.send_json(200, json.dumps(c, ensure_ascii=False, default=str))

        elif path == "/api/debts":
            d = add_debt(body)
            self.send_json(201, json.dumps(d, ensure_ascii=False, default=str))

        elif path.startswith("/api/debts/") and path.endswith("/pay"):
            debt_id = int(path.split("/")[3])
            d = pay_debt(debt_id, body["amount"], body.get("note",""))
            self.send_json(200, json.dumps(d, ensure_ascii=False, default=str))

        elif path == "/api/recurring":
            r = add_recurring(body)
            self.send_json(201, json.dumps(r, ensure_ascii=False, default=str))

        elif path.startswith("/api/recurring/") and path.endswith("/toggle"):
            rec_id = int(path.split("/")[3])
            toggle_recurring_paid(rec_id, body["month"], body["paid"])
            self.send_json(200, '{"ok":true}')

        else:
            self.send_response(404); self.end_headers()

    def do_PUT(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length)) if length else {}
        parts = self.path.split("/")

        if self.path.startswith("/api/transactions/"):
            tx_id = int(parts[3])
            tx = update_transaction(tx_id, body)
            self.send_json(200, json.dumps(tx, ensure_ascii=False, default=str))

        elif self.path.startswith("/api/savings/") and len(parts)==4:
            saving_id = int(parts[3])
            s = update_saving(saving_id, body)
            self.send_json(200, json.dumps(s, ensure_ascii=False, default=str))

        elif self.path.startswith("/api/credits/") and len(parts)==4:
            credit_id = int(parts[3])
            c = update_credit(credit_id, body)
            self.send_json(200, json.dumps(c, ensure_ascii=False, default=str))

        elif self.path.startswith("/api/debts/") and len(parts)==4:
            debt_id = int(parts[3])
            d = update_debt(debt_id, body)
            self.send_json(200, json.dumps(d, ensure_ascii=False, default=str))

        elif self.path.startswith("/api/recurring/") and len(parts)==4:
            rec_id = int(parts[3])
            r = update_recurring(rec_id, body)
            self.send_json(200, json.dumps(r, ensure_ascii=False, default=str))

        else:
            self.send_response(404); self.end_headers()

    def do_DELETE(self):
        parts = self.path.split("/")

        if self.path.startswith("/api/transactions/"):
            delete_transaction(int(parts[3]))
            self.send_json(200, '{"ok":true}')

        elif self.path.startswith("/api/savings/"):
            delete_saving(int(parts[3]))
            self.send_json(200, '{"ok":true}')

        elif self.path.startswith("/api/credits/"):
            delete_credit(int(parts[3]))
            self.send_json(200, '{"ok":true}')

        elif self.path.startswith("/api/debts/"):
            delete_debt(int(parts[3]))
            self.send_json(200, '{"ok":true}')

        elif self.path.startswith("/api/recurring/"):
            delete_recurring(int(parts[3]))
            self.send_json(200, '{"ok":true}')

        else:
            self.send_response(404); self.end_headers()

# ── Запуск ───────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    init_db()
    PORT = 8000
    server = HTTPServer(("127.0.0.1", PORT), Handler)
    print(f"✓ ФинЛичный запущен: http://localhost:{PORT}")
    print(f"✓ База данных: {os.path.abspath(DB_PATH)}")
    print("  Нажмите Ctrl+C для остановки\n")
    threading.Timer(1.2, lambda: webbrowser.open(f"http://localhost:{PORT}")).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nОстановлен.")
