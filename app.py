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
    """)
    conn.commit()
    conn.close()

# ── API helpers ──────────────────────────────────────────────────────────────

def json_response(data, status=200):
    return status, json.dumps(data, ensure_ascii=False, default=str)

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
    conn.close()
    
    ti = totals["total_income"] or 0
    te = totals["total_expense"] or 0
    return {
        "total_income": ti,
        "total_expense": te,
        "balance": ti - te,
        "savings_rate": round((ti - te) / ti * 100, 1) if ti > 0 else 0,
        "tx_count": totals["tx_count"],
        "by_category": [dict(r) for r in by_cat],
        "by_month": [dict(r) for r in by_month],
        "savings": [dict(r) for r in savings],
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
nav{background:#0d0f14;border-bottom:1px solid #1e2235;padding:0 32px;display:flex;gap:4px;position:sticky;top:64px;z-index:49}
.tab{background:none;border:none;color:#6b7280;cursor:pointer;padding:12px 20px;font-size:12px;letter-spacing:1.5px;text-transform:uppercase;font-family:'JetBrains Mono',monospace;border-bottom:2px solid transparent;transition:all .2s}
.tab.active{color:#c9a84c;border-bottom-color:#c9a84c}
.tab:hover{color:#e8eaf0}
main{padding:32px;max-width:1100px;margin:0 auto}
.card{background:#141720;border:1px solid #1e2235;border-radius:12px;padding:24px;margin-bottom:16px}
.grid3{display:grid;grid-template-columns:repeat(3,1fr);gap:16px;margin-bottom:16px}
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
.input{background:#0d0f14;border:1px solid #2d3148;border-radius:8px;padding:10px 14px;color:#e8eaf0;font-family:'JetBrains Mono',monospace;font-size:13px;width:100%;outline:none;transition:border .15s}
.input:focus{border-color:#c9a84c}
select.input option{background:#141720}
.badge-i{background:#0d2918;color:#34d399;padding:3px 10px;border-radius:20px;font-size:11px;display:inline-block}
.badge-e{background:#2a0d0d;color:#f87171;padding:3px 10px;border-radius:20px;font-size:11px;display:inline-block}
.progress-bar{height:8px;background:#1e2235;border-radius:4px;overflow:hidden}
.progress-fill{height:100%;border-radius:4px;transition:width .4s}
.overlay{position:fixed;inset:0;background:rgba(0,0,0,.75);display:flex;align-items:center;justify-content:center;z-index:200;backdrop-filter:blur(4px)}
.modal{background:#141720;border:1px solid #2d3148;border-radius:16px;padding:32px;width:440px;max-width:95vw}
.form-group{display:flex;flex-direction:column;gap:12px;margin-bottom:20px}
.row-btns{display:flex;gap:8px;margin-top:4px}
.tx-row{display:flex;align-items:center;justify-content:space-between;padding:14px 0;border-bottom:1px solid #1e2235}
.tx-row:last-child{border-bottom:none}
.tx-meta{font-size:11px;color:#4b5563;margin-top:3px}
.hidden{display:none}
.color-dot{width:26px;height:26px;border-radius:50%;cursor:pointer;border:3px solid transparent;transition:border .15s}
.color-dot.sel{border-color:#fff}
.month-filter{display:flex;align-items:center;gap:10px}
.filter-row{display:flex;align-items:center;justify-content:space-between;margin-bottom:20px}
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
  <button class="tab" onclick="showTab('report')">▦ Отчёт</button>
</nav>

<main>
  <!-- DASHBOARD -->
  <div id="tab-dashboard">
    <div class="grid3" id="dash-stats"></div>
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

<!-- Modal: Transaction -->
<div class="overlay hidden" id="modal-tx" onclick="if(event.target===this)closeModal('modal-tx')">
  <div class="modal">
    <h3 class="serif" style="font-size:20px;margin-bottom:20px">Новая операция</h3>
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
      <button class="btn btn-gold" style="flex:1" onclick="submitTx()">Добавить</button>
    </div>
  </div>
</div>

<!-- Modal: Saving -->
<div class="overlay hidden" id="modal-saving" onclick="if(event.target===this)closeModal('modal-saving')">
  <div class="modal">
    <h3 class="serif" style="font-size:20px;margin-bottom:20px">Новая копилка</h3>
    <div class="form-group">
      <input class="input" id="s-name" placeholder="Название (напр. Отпуск 🏖️)">
      <input class="input" id="s-goal" type="number" placeholder="Цель (₽)" min="1">
      <input class="input" id="s-current" type="number" placeholder="Уже накоплено (₽, если есть)" min="0">
      <div>
        <div style="font-size:11px;color:#6b7280;letter-spacing:1px;margin-bottom:8px">ЦВЕТ</div>
        <div style="display:flex;gap:8px" id="color-picker"></div>
      </div>
    </div>
    <div class="row-btns">
      <button class="btn btn-ghost" style="flex:1" onclick="closeModal('modal-saving')">Отмена</button>
      <button class="btn btn-gold" style="flex:1" onclick="submitSaving()">Создать</button>
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

<script>
const COLORS = ['#c9a84c','#6366f1','#10b981','#f87171','#38bdf8','#ec4899','#a78bfa'];
const CATS_EXPENSE = ['Продукты','Транспорт','ЖКХ','Развлечения','Здоровье','Одежда','Семья','Кафе/Рестораны','Кредиты','Связь','Образование','Прочее'];
const CATS_INCOME = ['Зарплата','Фриланс','Инвестиции','Подарки','Прочее'];

let currentTxType = 'expense';
let currentSavingId = null;
let selectedColor = COLORS[0];

// Инициализация
document.getElementById('today-date').textContent = new Date().toLocaleDateString('ru-RU',{day:'numeric',month:'long',year:'numeric'});
document.getElementById('tx-date').value = new Date().toISOString().slice(0,10);
document.getElementById('tx-month-filter').value = new Date().toISOString().slice(0,7);

// Цветовой пикер
function buildColorPicker(){
  const el = document.getElementById('color-picker');
  el.innerHTML = COLORS.map(c=>`<div class="color-dot${c===selectedColor?' sel':''}" style="background:${c}" onclick="selectColor('${c}')"></div>`).join('');
}
function selectColor(c){ selectedColor=c; buildColorPicker(); }
buildColorPicker();

// Вкладки
function showTab(id){
  ['dashboard','transactions','savings','report'].forEach(t=>{
    document.getElementById('tab-'+t).classList.toggle('hidden',t!==id);
    document.querySelectorAll('.tab').forEach((btn,i)=>{
      const names=['dashboard','transactions','savings','report'];
      btn.classList.toggle('active',names[i]===id);
    });
  });
  if(id==='dashboard') loadDashboard();
  if(id==='transactions') loadTransactions();
  if(id==='savings') loadSavings();
  if(id==='report') loadReport();
}

// Форматирование
function fmt(n){ return Number(n).toLocaleString('ru-RU')+' ₽'; }

// API
async function api(path, method='GET', body=null){
  const opts = {method, headers:{'Content-Type':'application/json'}};
  if(body) opts.body = JSON.stringify(body);
  const r = await fetch('/api'+path, opts);
  return r.json();
}

// DASHBOARD
async function loadDashboard(){
  const [report, txs, savings] = await Promise.all([
    api('/report'), api('/transactions?limit=6'), api('/savings')
  ]);
  
  // Статы
  const statsEl = document.getElementById('dash-stats');
  statsEl.innerHTML = [
    {label:'Доходы',val:report.total_income,color:'#34d399',sign:'+'},
    {label:'Расходы',val:report.total_expense,color:'#f87171',sign:'-'},
    {label:'Баланс',val:report.balance,color:report.balance>=0?'#c9a84c':'#f87171',sign:report.balance>=0?'+':''},
  ].map(s=>`<div class="card" style="margin-bottom:0">
    <div class="section-title">${s.label}</div>
    <div class="stat-num" style="color:${s.color}">${s.sign}${fmt(Math.abs(s.val))}</div>
  </div>`).join('');

  // Категории расходов
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

  // Копилки
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

  // Последние операции
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

// TRANSACTIONS
async function loadTransactions(){
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
        <div style="display:flex;align-items:center;gap:12px">
          <div style="font-size:14px;font-weight:600;color:${t.type==='income'?'#34d399':'#f87171'}">${t.type==='income'?'+':'-'}${fmt(t.amount)}</div>
          <button class="btn btn-danger" style="padding:5px 10px;font-size:11px" onclick="deleteTx(${t.id})">✕</button>
        </div>
      </div>`).join('')
    : '<div style="color:#4b5563;text-align:center;padding:20px">Операций нет</div>';
}

async function deleteTx(id){
  if(!confirm('Удалить операцию?')) return;
  await api('/transactions/'+id, 'DELETE');
  loadTransactions(); loadDashboard();
}

// SAVINGS
async function loadSavings(){
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
          <button class="btn btn-ghost" style="padding:6px 12px;font-size:11px" onclick="openDeposit(${s.id},'${s.name.replace(/'/,"\\'")}')">Пополнить</button>
          <button class="btn btn-danger" style="padding:6px 10px;font-size:11px" onclick="deleteSaving(${s.id})">✕</button>
        </div>
      </div>
    </div>`;
  }).join('') || '<div style="color:#4b5563;text-align:center;padding:40px;grid-column:1/-1">Нет копилок. Создайте первую!</div>';
}

async function deleteSaving(id){
  if(!confirm('Удалить копилку? Все данные пополнений будут удалены.')) return;
  await api('/savings/'+id, 'DELETE');
  loadSavings();
}

// REPORT
async function loadReport(){
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
          {l:'В копилках накоплено',v:fmt(savingsTotal),c:'#c9a84c'},
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
    </div>
    <div class="card">
      <div class="section-title">Статус копилок</div>
      <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:12px">
        ${r.savings.map(s=>{
          const pct=Math.min(100,Math.round(s.current/s.goal*100));
          return `<div style="padding:14px;background:#0d0f14;border-radius:8px;border:1px solid #1e2235">
            <div style="margin-bottom:6px;font-size:13px">${s.name}</div>
            <div style="font-size:11px;color:#6b7280;margin-bottom:4px">${fmt(s.current)} / ${fmt(s.goal)}</div>
            <div class="progress-bar"><div class="progress-fill" style="width:${pct}%;background:${s.color}"></div></div>
            <div style="font-size:12px;color:${s.color};margin-top:5px;font-weight:600">${pct}%</div>
          </div>`;
        }).join('') || '<div style="color:#4b5563;font-size:13px">Нет копилок</div>'}
      </div>
    </div>`;
}

// Modal helpers
function openModal(id){ document.getElementById(id).classList.remove('hidden'); }
function closeModal(id){ document.getElementById(id).classList.add('hidden'); }

// TX Modal
function setTxType(t){
  currentTxType=t;
  document.getElementById('type-expense-btn').className='btn '+(t==='expense'?'btn-gold':'btn-ghost');
  document.getElementById('type-income-btn').className='btn '+(t==='income'?'btn-gold':'btn-ghost');
  const cats = t==='income'?CATS_INCOME:CATS_EXPENSE;
  document.getElementById('tx-category').innerHTML=cats.map(c=>`<option>${c}</option>`).join('');
}
function openTxModal(){
  setTxType('expense');
  document.getElementById('tx-amount').value='';
  document.getElementById('tx-desc').value='';
  document.getElementById('tx-date').value=new Date().toISOString().slice(0,10);
  openModal('modal-tx');
}
async function submitTx(){
  const amount=document.getElementById('tx-amount').value;
  const category=document.getElementById('tx-category').value;
  const date=document.getElementById('tx-date').value;
  if(!amount||!category||!date){alert('Заполните обязательные поля');return;}
  await api('/transactions','POST',{
    type:currentTxType, amount:parseFloat(amount),
    category, description:document.getElementById('tx-desc').value, date
  });
  closeModal('modal-tx');
  loadTransactions(); loadDashboard();
}

// Saving Modal
function openSavingModal(){
  document.getElementById('s-name').value='';
  document.getElementById('s-goal').value='';
  document.getElementById('s-current').value='';
  selectedColor=COLORS[0]; buildColorPicker();
  openModal('modal-saving');
}
async function submitSaving(){
  const name=document.getElementById('s-name').value;
  const goal=document.getElementById('s-goal').value;
  if(!name||!goal){alert('Заполните обязательные поля');return;}
  await api('/savings','POST',{
    name, goal:parseFloat(goal),
    current:parseFloat(document.getElementById('s-current').value||0),
    color:selectedColor
  });
  closeModal('modal-saving');
  loadSavings(); loadDashboard();
}

// Deposit Modal
function openDeposit(id, name){
  currentSavingId=id;
  document.getElementById('deposit-name').textContent=name;
  document.getElementById('deposit-amount').value='';
  document.getElementById('deposit-note').value='';
  openModal('modal-deposit');
}
async function submitDeposit(){
  const amount=document.getElementById('deposit-amount').value;
  if(!amount){alert('Введите сумму');return;}
  await api('/savings/'+currentSavingId+'/deposit','POST',{
    amount:parseFloat(amount),
    note:document.getElementById('deposit-note').value
  });
  closeModal('modal-deposit');
  loadSavings(); loadDashboard();
}

// Запуск
loadDashboard();
</script>
</body>
</html>
"""

# ── HTTP Handler ─────────────────────────────────────────────────────────────

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args): pass  # тихий лог

    def send_json(self, status, data):
        body = data.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        qs = parse_qs(parsed.query)

        if path == "/" or path == "/index.html":
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

        elif path == "/api/report":
            month = qs.get("month", [None])[0]
            self.send_json(200, json.dumps(get_report(month), ensure_ascii=False, default=str))

        else:
            self.send_response(404)
            self.end_headers()

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

        else:
            self.send_response(404)
            self.end_headers()

    def do_DELETE(self):
        parts = self.path.split("/")
        if self.path.startswith("/api/transactions/"):
            delete_transaction(int(parts[3]))
            self.send_json(200, '{"ok":true}')
        elif self.path.startswith("/api/savings/"):
            delete_saving(int(parts[3]))
            self.send_json(200, '{"ok":true}')
        else:
            self.send_response(404)
            self.end_headers()

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
