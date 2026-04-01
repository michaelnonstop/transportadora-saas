from __future__ import annotations

import os
import sqlite3
from contextlib import closing
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Optional

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from starlette.middleware.sessions import SessionMiddleware

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "transportadora.db"
SECRET_KEY = os.getenv("SECRET_KEY", "troque-esta-chave-em-producao")

app = FastAPI(title="Transportadora Control Pro")
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


# -------------------------------
# Database helpers
# -------------------------------
def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with closing(get_conn()) as conn:
        cur = conn.cursor()
        cur.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company_name TEXT NOT NULL,
                email TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL,
                plan TEXT NOT NULL DEFAULT 'Profissional',
                status TEXT NOT NULL DEFAULT 'ativo',
                due_date TEXT NOT NULL,
                grace_days INTEGER NOT NULL DEFAULT 3,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS clients (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                document TEXT,
                phone TEXT,
                city TEXT,
                notes TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS employees (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                role TEXT NOT NULL,
                phone TEXT,
                vehicle TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS services (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                service_code TEXT NOT NULL,
                client_name TEXT NOT NULL,
                origin TEXT NOT NULL,
                destination TEXT NOT NULL,
                driver_name TEXT,
                status TEXT NOT NULL,
                amount REAL NOT NULL DEFAULT 0,
                service_date TEXT NOT NULL,
                notes TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS expenses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                description TEXT NOT NULL,
                category TEXT NOT NULL,
                amount REAL NOT NULL,
                expense_date TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            """
        )

        user_count = cur.execute("SELECT COUNT(*) AS total FROM users").fetchone()["total"]
        if user_count == 0:
            due = (date.today() + timedelta(days=15)).isoformat()
            cur.execute(
                """
                INSERT INTO users (company_name, email, password, plan, status, due_date, grace_days)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "Non Stop Transportes",
                    "admin@demo.com",
                    "123456",
                    "Profissional",
                    "ativo",
                    due,
                    3,
                ),
            )
            cur.executemany(
                "INSERT INTO clients (name, document, phone, city, notes) VALUES (?, ?, ?, ?, ?)",
                [
                    ("Mercado Central", "12.345.678/0001-10", "(11) 99888-1001", "Atibaia", "Cliente recorrente"),
                    ("Farmácia Imperial", "22.345.678/0001-99", "(11) 99888-1002", "Bragança Paulista", "Coletas diárias"),
                ],
            )
            cur.executemany(
                "INSERT INTO employees (name, role, phone, vehicle) VALUES (?, ?, ?, ?)",
                [
                    ("Carlos Silva", "Motorista", "(11) 97777-2200", "Fiorino - ABC1D23"),
                    ("Ana Souza", "Operadora", "(11) 96666-3300", "Escritório"),
                ],
            )
            cur.executemany(
                """
                INSERT INTO services (service_code, client_name, origin, destination, driver_name, status, amount, service_date, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    ("OS-1001", "Mercado Central", "Atibaia", "São Paulo", "Carlos Silva", "Concluído", 380.0, date.today().isoformat(), "Entrega expressa"),
                    ("OS-1002", "Farmácia Imperial", "Bragança Paulista", "Campinas", "Carlos Silva", "Em rota", 240.0, date.today().isoformat(), "Coleta farmacêutica"),
                ],
            )
            cur.executemany(
                "INSERT INTO expenses (description, category, amount, expense_date) VALUES (?, ?, ?, ?)",
                [
                    ("Combustível", "Operacional", 180.0, date.today().isoformat()),
                    ("Pedágio", "Viagem", 35.0, date.today().isoformat()),
                ],
            )
        conn.commit()


@app.on_event("startup")
def startup() -> None:
    init_db()


# -------------------------------
# Auth / billing helpers
# -------------------------------
def get_current_user(request: Request) -> sqlite3.Row:
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401)
    with closing(get_conn()) as conn:
        user = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if not user:
        request.session.clear()
        raise HTTPException(status_code=401)
    return user


def billing_state(user: sqlite3.Row) -> str:
    today = date.today()
    due = datetime.strptime(user["due_date"], "%Y-%m-%d").date()
    if user["status"] in {"cancelado", "bloqueado"}:
        return "bloqueado"
    if today <= due:
        return "ativo"
    if today <= due + timedelta(days=int(user["grace_days"])):
        return "atrasado"
    return "bloqueado"


def require_login(request: Request) -> sqlite3.Row:
    try:
        return get_current_user(request)
    except HTTPException:
        raise HTTPException(status_code=303, detail="Redirecionando")


def require_active_user(request: Request) -> sqlite3.Row:
    user = get_current_user(request)
    state = billing_state(user)
    if state == "bloqueado":
        raise HTTPException(status_code=403, detail="Assinatura bloqueada")
    return user


def context(
    request: Request,
    page: str,
    user: Optional[sqlite3.Row] = None,
    **extra: Any,
) -> dict[str, Any]:
    current_user = user
    billing = None

    if not current_user:
        try:
            current_user = get_current_user(request)
            billing = billing_state(current_user)
        except HTTPException:
            current_user = None
    else:
        billing = billing_state(current_user)

    return {
        "request": request,
        "page": page,
        "current_user": current_user,
        "billing": billing,
        **extra,
    }


@app.exception_handler(HTTPException)
async def custom_http_exception_handler(request: Request, exc: HTTPException):
    if exc.status_code == 401:
        return RedirectResponse("/login", status_code=303)
    if exc.status_code == 403:
        return RedirectResponse("/assinatura", status_code=303)
    return HTMLResponse(
        f"<h1>Erro {exc.status_code}</h1><p>{exc.detail}</p>",
        status_code=exc.status_code,
    )


# -------------------------------
# Routes
# -------------------------------
@app.get("/", response_class=HTMLResponse)
def root(request: Request):
    try:
        get_current_user(request)
        return RedirectResponse("/dashboard", status_code=303)
    except HTTPException:
        return RedirectResponse("/login", status_code=303)


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context=context(request, "login", error=None),
    )


@app.post("/login", response_class=HTMLResponse)
def do_login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
):
    with closing(get_conn()) as conn:
        user = conn.execute(
            "SELECT * FROM users WHERE email = ? AND password = ?",
            (email.strip().lower(), password.strip()),
        ).fetchone()

    if not user:
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context=context(request, "login", error="E-mail ou senha inválidos."),
            status_code=400,
        )

    request.session["user_id"] = user["id"]
    return RedirectResponse("/dashboard", status_code=303)


@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request, user: sqlite3.Row = Depends(require_active_user)):
    with closing(get_conn()) as conn:
        total_clients = conn.execute("SELECT COUNT(*) AS total FROM clients").fetchone()["total"]
        total_employees = conn.execute("SELECT COUNT(*) AS total FROM employees").fetchone()["total"]
        total_services = conn.execute("SELECT COUNT(*) AS total FROM services").fetchone()["total"]
        revenue = conn.execute(
            "SELECT COALESCE(SUM(amount), 0) AS total FROM services WHERE status = 'Concluído'"
        ).fetchone()["total"]
        expenses = conn.execute("SELECT COALESCE(SUM(amount), 0) AS total FROM expenses").fetchone()["total"]
        recent_services = conn.execute(
            "SELECT * FROM services ORDER BY id DESC LIMIT 5"
        ).fetchall()

    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context=context(
            request,
            "dashboard",
            user=user,
            total_clients=total_clients,
            total_employees=total_employees,
            total_services=total_services,
            revenue=revenue,
            expenses=expenses,
            profit=revenue - expenses,
            recent_services=recent_services,
        ),
    )


@app.get("/clientes", response_class=HTMLResponse)
def clients_page(request: Request, user: sqlite3.Row = Depends(require_active_user)):
    with closing(get_conn()) as conn:
        clients = conn.execute("SELECT * FROM clients ORDER BY id DESC").fetchall()

    return templates.TemplateResponse(
        request=request,
        name="clients.html",
        context=context(request, "clientes", user=user, clients=clients),
    )


@app.post("/clientes")
def add_client(
    request: Request,
    name: str = Form(...),
    document: str = Form(""),
    phone: str = Form(""),
    city: str = Form(""),
    notes: str = Form(""),
    user: sqlite3.Row = Depends(require_active_user),
):
    with closing(get_conn()) as conn:
        conn.execute(
            "INSERT INTO clients (name, document, phone, city, notes) VALUES (?, ?, ?, ?, ?)",
            (name, document, phone, city, notes),
        )
        conn.commit()

    return RedirectResponse("/clientes", status_code=303)


@app.get("/colaboradores", response_class=HTMLResponse)
def employees_page(request: Request, user: sqlite3.Row = Depends(require_active_user)):
    with closing(get_conn()) as conn:
        employees = conn.execute("SELECT * FROM employees ORDER BY id DESC").fetchall()

    return templates.TemplateResponse(
        request=request,
        name="employees.html",
        context=context(request, "colaboradores", user=user, employees=employees),
    )


@app.post("/colaboradores")
def add_employee(
    request: Request,
    name: str = Form(...),
    role: str = Form(...),
    phone: str = Form(""),
    vehicle: str = Form(""),
    user: sqlite3.Row = Depends(require_active_user),
):
    with closing(get_conn()) as conn:
        conn.execute(
            "INSERT INTO employees (name, role, phone, vehicle) VALUES (?, ?, ?, ?)",
            (name, role, phone, vehicle),
        )
        conn.commit()

    return RedirectResponse("/colaboradores", status_code=303)


@app.get("/servicos", response_class=HTMLResponse)
def services_page(request: Request, user: sqlite3.Row = Depends(require_active_user)):
    with closing(get_conn()) as conn:
        services = conn.execute("SELECT * FROM services ORDER BY id DESC").fetchall()
        clients = conn.execute("SELECT name FROM clients ORDER BY name").fetchall()
        drivers = conn.execute(
            "SELECT name FROM employees WHERE role LIKE '%Motorista%' ORDER BY name"
        ).fetchall()

    return templates.TemplateResponse(
        request=request,
        name="services.html",
        context=context(
            request,
            "servicos",
            user=user,
            services=services,
            clients=clients,
            drivers=drivers,
        ),
    )


@app.post("/servicos")
def add_service(
    request: Request,
    service_code: str = Form(...),
    client_name: str = Form(...),
    origin: str = Form(...),
    destination: str = Form(...),
    driver_name: str = Form(""),
    status: str = Form(...),
    amount: float = Form(...),
    service_date: str = Form(...),
    notes: str = Form(""),
    user: sqlite3.Row = Depends(require_active_user),
):
    with closing(get_conn()) as conn:
        conn.execute(
            """
            INSERT INTO services
            (service_code, client_name, origin, destination, driver_name, status, amount, service_date, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                service_code,
                client_name,
                origin,
                destination,
                driver_name,
                status,
                amount,
                service_date,
                notes,
            ),
        )
        conn.commit()

    return RedirectResponse("/servicos", status_code=303)


@app.get("/financeiro", response_class=HTMLResponse)
def finance_page(request: Request, user: sqlite3.Row = Depends(require_active_user)):
    with closing(get_conn()) as conn:
        expenses = conn.execute("SELECT * FROM expenses ORDER BY id DESC").fetchall()
        total_expenses = conn.execute(
            "SELECT COALESCE(SUM(amount), 0) AS total FROM expenses"
        ).fetchone()["total"]
        total_revenue = conn.execute(
            "SELECT COALESCE(SUM(amount), 0) AS total FROM services WHERE status = 'Concluído'"
        ).fetchone()["total"]

    return templates.TemplateResponse(
        request=request,
        name="finance.html",
        context=context(
            request,
            "financeiro",
            user=user,
            expenses=expenses,
            total_expenses=total_expenses,
            total_revenue=total_revenue,
            total_profit=total_revenue - total_expenses,
        ),
    )


@app.post("/financeiro")
def add_expense(
    request: Request,
    description: str = Form(...),
    category: str = Form(...),
    amount: float = Form(...),
    expense_date: str = Form(...),
    user: sqlite3.Row = Depends(require_active_user),
):
    with closing(get_conn()) as conn:
        conn.execute(
            "INSERT INTO expenses (description, category, amount, expense_date) VALUES (?, ?, ?, ?)",
            (description, category, amount, expense_date),
        )
        conn.commit()

    return RedirectResponse("/financeiro", status_code=303)


@app.get("/assinatura", response_class=HTMLResponse)
def subscription_page(request: Request, user: sqlite3.Row = Depends(require_login)):
    return templates.TemplateResponse(
        request=request,
        name="subscription.html",
        context=context(
            request,
            "assinatura",
            user=user,
            due_date=user["due_date"],
            plan=user["plan"],
        ),
    )


@app.post("/assinatura/renovar")
def renew_subscription(request: Request, user: sqlite3.Row = Depends(require_login)):
    new_due_date = (date.today() + timedelta(days=30)).isoformat()

    with closing(get_conn()) as conn:
        conn.execute(
            "UPDATE users SET due_date = ?, status = 'ativo' WHERE id = ?",
            (new_due_date, user["id"]),
        )
        conn.commit()

    return RedirectResponse("/dashboard", status_code=303)


@app.get("/relatorios/servicos.pdf")
def services_pdf(request: Request, user: sqlite3.Row = Depends(require_active_user)):
    with closing(get_conn()) as conn:
        services = conn.execute(
            "SELECT * FROM services ORDER BY service_date DESC, id DESC LIMIT 30"
        ).fetchall()

    from io import BytesIO

    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    y = height - 50

    pdf.setTitle("Relatório de Serviços")
    pdf.setFont("Helvetica-Bold", 16)
    pdf.drawString(40, y, "Relatório de Serviços - Transportadora Control Pro")
    y -= 25

    pdf.setFont("Helvetica", 10)
    pdf.drawString(40, y, f"Gerado em: {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    y -= 30

    headers = ["Código", "Cliente", "Origem", "Destino", "Status", "Valor"]
    positions = [40, 100, 220, 320, 420, 500]

    pdf.setFont("Helvetica-Bold", 9)
    for pos, header in zip(positions, headers):
        pdf.drawString(pos, y, header)

    y -= 15
    pdf.setFont("Helvetica", 8)

    for s in services:
        if y < 60:
            pdf.showPage()
            y = height - 50
            pdf.setFont("Helvetica", 8)

        row = [
            s["service_code"][:10],
            s["client_name"][:22],
            s["origin"][:18],
            s["destination"][:18],
            s["status"][:12],
            f"R$ {s['amount']:.2f}",
        ]

        for pos, value in zip(positions, row):
            pdf.drawString(pos, y, str(value))

        y -= 14

    pdf.save()
    buffer.seek(0)

    headers = {"Content-Disposition": "inline; filename=relatorio_servicos.pdf"}
    return StreamingResponse(buffer, media_type="application/pdf", headers=headers)