#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
daily_report_bot_gui.py
One-pane dashboard + weekly performance analytics
————————————————————————————————————————————
Designer : Eng. Ahmed M. Elsakka
Manager  : Eng. Walid S. Haddad
"""

import os, logging, sqlite3, threading, time, asyncio, tempfile, textwrap
from datetime import datetime, date, timedelta

import schedule
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

# Telegram
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardRemove
)
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, ConversationHandler,
    MessageHandler, ContextTypes, filters
)

# GUI
import tkinter as tk
from tkinter import ttk, messagebox
from PIL import Image, ImageTk  # thumbnail preview

# PDF
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# ========= settings =========

BOT_TOKEN = os.getenv("BOT_TOKEN",
                      "7981928739:AAHbGX19La0FBCgJkRr9yjKFf3vTxWoB5As")
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "ahmed.mm.elsakka@gmail.com")
SMTP_PASS = os.getenv("SMTP_PASS", "dodllqsu ffqjkqte")
EMAIL_TO = os.getenv("EMAIL_TO", "ahmed.m.elsaka@gmail.com")

DB_PATH = os.getenv("DB_PATH", "bot.db")
IMAGES_DIR = os.getenv("IMAGES_DIR", "images")
LOG_FILE = os.getenv("LOG_FILE", "bot.log")

# ========= logging =========
os.makedirs(os.path.dirname(LOG_FILE) or ".", exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler(LOG_FILE), logging.StreamHandler()],
)

EMPLOYEE, PROJECT, TASKS, PHOTOS = range(4)

os.makedirs(IMAGES_DIR, exist_ok=True)
os.makedirs("reports", exist_ok=True)


# ========= database =========
def get_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


db = get_db()


def init_db():
    with db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS employees(
            id INTEGER PRIMARY KEY, name TEXT, telegram_id TEXT);
        CREATE TABLE IF NOT EXISTS projects(
            id INTEGER PRIMARY KEY, project_name TEXT);
        CREATE TABLE IF NOT EXISTS reports(
            id INTEGER PRIMARY KEY,
            employee_id INTEGER REFERENCES employees(id),
            project_id  INTEGER REFERENCES projects(id),
            tasks TEXT, images TEXT, timestamp DATETIME);
        """)
    seed_employees = [("محمد رجب", "7009323275"),
                      ("سمر عادل", "6011223344"),
                      ("أحمد خالد", "9988776655")]
    seed_projects = [("إبداع الحياة",), ("القليبة",), ("منصة نور",)]
    with db:
        if db.execute("SELECT COUNT(*) FROM employees").fetchone()[0] == 0:
            db.executemany(
                "INSERT INTO employees(name,telegram_id) VALUES(?,?)",
                seed_employees)
        if db.execute("SELECT COUNT(*) FROM projects").fetchone()[0] == 0:
            db.executemany(
                "INSERT INTO projects(project_name) VALUES(?)", seed_projects)


init_db()


def list_employees(): return db.execute("SELECT id,name FROM employees").fetchall()


def list_projects():  return db.execute("SELECT id,project_name FROM projects").fetchall()


def employee_name(emp_id: int) -> str:
    row = db.execute("SELECT name FROM employees WHERE id=?", (emp_id,)).fetchone()
    return row["name"] if row else f"emp{emp_id}"


def save_report(emp_id, proj_id, tasks, imgs):
    with db:
        db.execute("""INSERT INTO reports(employee_id,project_id,tasks,images,timestamp)
                      VALUES(?,?,?,?,?)""",
                   (emp_id, proj_id, tasks, ",".join(imgs),
                    datetime.now().isoformat(" ", "seconds")))


# ========= daily + weekly data =========
def get_daily_data(target: date | None = None):
    target = target or date.today()
    start = datetime.combine(target, datetime.min.time())
    end = start + timedelta(days=1)
    rows = db.execute("""
        SELECT e.name emp,p.project_name proj,r.tasks,r.images
        FROM reports r
        JOIN employees e ON r.employee_id=e.id
        JOIN projects  p ON r.project_id=p.id
        WHERE timestamp BETWEEN ? AND ?""",
                      (start.isoformat(" "), end.isoformat(" "))).fetchall()
    active = [{"emp": r["emp"], "proj": r["proj"], "tasks": r["tasks"],
               "imgs": bool(r["images"]), "img_list": r["images"].split(",") if r["images"] else []}
              for r in rows]
    inactive = sorted({e["name"] for e in list_employees()} -
                      {r["emp"] for r in rows})
    untouched = sorted({p["project_name"] for p in list_projects()} -
                       {r["proj"] for r in rows})
    return active, inactive, untouched


def get_weekly_stats(today: date | None = None):
    today = today or date.today()
    start = datetime.combine(today - timedelta(days=6), datetime.min.time())
    end = datetime.combine(today + timedelta(days=1), datetime.min.time())
    rows = db.execute("""
        SELECT e.name emp,p.project_name proj
        FROM reports r
        JOIN employees e ON r.employee_id=e.id
        JOIN projects  p ON r.project_id=p.id
        WHERE timestamp BETWEEN ? AND ?""",
                      (start.isoformat(" "), end.isoformat(" "))).fetchall()

    emp_count, proj_count = {}, {}
    for r in rows:
        emp_count[r["emp"]] = emp_count.get(r["emp"], 0) + 1
        proj_count[r["proj"]] = proj_count.get(r["proj"], 0) + 1
    for e in list_employees():  emp_count.setdefault(e["name"], 0)
    for p in list_projects():   proj_count.setdefault(p["project_name"], 0)

    most_emp = sorted(emp_count.items(), key=lambda x: (-x[1], x[0]))[:3]
    least_emp = sorted(emp_count.items(), key=lambda x: (x[1], x[0]))[:3]
    most_proj = sorted(proj_count.items(), key=lambda x: (-x[1], x[0]))[:3]
    least_proj = sorted(proj_count.items(), key=lambda x: (x[1], x[0]))[:3]
    fmt = lambda lst: [f"{n} ({c})" if c else f"{n} (0)" for n, c in lst]
    return fmt(most_emp), fmt(least_emp), fmt(most_proj), fmt(least_proj)


# ========= report for email / pdf =========
def generate_daily_report(for_date: date | None = None) -> str:
    active, inactive, untouched = get_daily_data(for_date)
    t = for_date or date.today()
    report = [f"Daily Report - {t}"]
    report += ["", "✅ Active staff:"]
    report += [f"- {r['emp']} ({r['proj']}) — {r['tasks']}"
               + (" [images]" if r["imgs"] else "")
               for r in active] or ["- None"]
    report += ["", "❌ Inactive staff:"]
    report += ([f"- {n}" for n in inactive] or ["- None"])
    report += ["", "🚫 Unvisited projects:"]
    report += ([f"- {p}" for p in untouched] or ["- None"])
    return "\n".join(report)


# ========= email =========
def send_email(body: str):
    msg = MIMEMultipart()
    msg["Subject"] = f"Daily Report - {date.today()}"
    msg["From"] = SMTP_USER
    msg["To"] = EMAIL_TO
    msg.attach(MIMEText(body, "plain", "utf-8"))
    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as s:
            s.starttls();
            s.login(SMTP_USER, SMTP_PASS);
            s.send_message(msg)
        logging.info("Email sent")
    except Exception as e:
        logging.error("Mail error: %s", e)


# ========= pdf =========
def create_pdf(text: str) -> str:
    fd, path = tempfile.mkstemp(suffix=".pdf", dir="reports");
    os.close(fd)
    try:
        pdfmetrics.registerFont(TTFont('Arial', 'arial.ttf'));
        f = 'Arial'
    except:
        f = 'Helvetica'
    c = canvas.Canvas(path, pagesize=A4)
    t = c.beginText(40, 820);
    t.setFont(f, 12)
    for ln in text.splitlines(): t.textLine(ln)
    c.drawText(t);
    c.showPage();
    c.save()
    return path


# ========= GUI =========
class DashboardGUI:
    weekday_short = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
    month_short = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

    def __init__(self, root: tk.Tk):
        self.root = root
        self.current_date = date.today()

        root.title("Daily Report Dashboard")
        root.geometry("1280x720")

        # ---------- header ----------
        header = tk.Frame(root)
        header.pack(fill="x", pady=(6, 0), padx=8)
        tk.Label(header, text="Designer: Eng. Ahmed M. Elsakka",
                 font=("Tahoma", 10)).pack(side="left")
        tk.Label(header, text="Program Manager: Eng. Walid S. Haddad",
                 font=("Tahoma", 10)).pack(side="left", padx=12)
        self.lbl_date = tk.Label(header, font=("Tahoma", 16, "bold"))
        self.lbl_date.pack(side="right")

        # ---------- control bar ----------
        ctrl = tk.Frame(root);
        ctrl.pack(fill="x", padx=8, pady=4)
        # navigation buttons
        ttk.Button(ctrl, text="◀ Previous", width=12,
                   command=self.nav_prev).pack(side="left")
        ttk.Button(ctrl, text="Today", width=8,
                   command=self.nav_today).pack(side="left", padx=2)
        ttk.Button(ctrl, text="Next ▶", width=12,
                   command=self.nav_next).pack(side="left")
        ttk.Separator(ctrl, orient="vertical").pack(side="left", fill="y", padx=6)
        ttk.Button(ctrl, text="⟳ Refresh", width=12,
                   command=self.refresh).pack(side="left")
        ttk.Button(ctrl, text="💾 Save PDF", width=12,
                   command=self.save_pdf).pack(side="left", padx=6)

        # ---------- main layout ----------
        main = tk.Frame(root);
        main.pack(fill="both", expand=True, padx=8, pady=4)

        # left  : tables (expand)
        left = tk.Frame(main);
        left.pack(side="left", fill="both", expand=True)

        canv = tk.Canvas(left, highlightthickness=0)
        vsb = ttk.Scrollbar(left, orient="vertical", command=canv.yview)
        self.left_inner = ttk.Frame(canv)
        self.left_inner.bind("<Configure>",
                             lambda e: canv.configure(scrollregion=canv.bbox("all")))
        canv.create_window((0, 0), window=self.left_inner, anchor="nw")
        canv.configure(yscrollcommand=vsb.set)
        canv.pack(side="right", fill="both", expand=True)
        vsb.pack(side="left", fill="y")

        # middle : full-height image preview
        mid = tk.Frame(main, width=420)
        mid.pack(side="left", fill="both")
        self.preview_lbl = tk.Label(mid, text="(double-click a row)\n\n— image preview —",
                                    relief="sunken", anchor="center")
        self.preview_lbl.pack(fill="both", expand=True)
        mid.pack_propagate(False)

        # right : weekly analytics (narrow)
        right_width = 220
        right = tk.Frame(main, width=right_width)
        right.pack(side="left", fill="y", padx=(6, 0))
        right.pack_propagate(False)
        ttk.Label(right, text="Weekly Analytics",
                  font=("Tahoma", 14, "bold")).pack()
        self.lbl_most_emp = self._stat_block(right, "Most active staff")
        self.lbl_least_emp = self._stat_block(right, "Least active staff")
        self.lbl_most_proj = self._stat_block(right, "Top visited projects")
        self.lbl_least_proj = self._stat_block(right, "Least visited projects")

        # Treeview row-height style (larger to show wrapped text)
        style = ttk.Style()
        style.configure("Multiline.Treeview", rowheight=60)

        # tables
        self.tree_active = self._make_table("Daily Activity",
                                            ("Staff", "Project", "Tasks", "Imgs"),
                                            rows=12, style="Multiline.Treeview")
        self.tree_inactive = self._make_table("Inactive staff", ("Staff",),
                                              rows=4)
        self.tree_projects = self._make_table("Unvisited projects", ("Project",),
                                              rows=4)

        # events
        self.tree_active.bind("<Double-1>", self._show_images)
        root.bind("<Configure>", self._refresh_preview_on_resize)

        self._current_img_path = None
        self.refresh()
        self.root.after(60000, self.auto_refresh)

    # ----- navigation -----
    def nav_prev(self):
        self.current_date -= timedelta(days=1)
        self.refresh()

    def nav_next(self):
        if self.current_date < date.today():
            self.current_date += timedelta(days=1)
            self.refresh()

    def nav_today(self):
        self.current_date = date.today()
        self.refresh()

    # ----- helpers -----
    def _stat_block(self, parent, title):
        frm = ttk.LabelFrame(parent, text=title)
        frm.pack(fill="x", padx=4, pady=4)
        lbl = tk.Label(frm, text="—", justify="left", font=("Tahoma", 10))
        lbl.pack(anchor="w", padx=4, pady=2)
        return lbl

    def _make_table(self, title, columns, rows=7, style="Treeview"):
        ttk.Label(self.left_inner, text=title,
                  font=("Tahoma", 13, "bold")).pack(anchor="w", pady=(8, 0))
        frame = ttk.Frame(self.left_inner);
        frame.pack(fill="x", expand=True)
        tree = ttk.Treeview(frame, columns=columns, show="headings",
                            height=rows, style=style)
        vsb = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=vsb.set)
        for col in columns:
            tree.heading(col, text=col, anchor="center")
            width = 140 if col in ("Imgs", "Staff") else 240 if col == "Tasks" else 160
            tree.column(col, anchor="center", width=width, minwidth=80, stretch=True)
        tree.pack(side="right", fill="x", expand=True)
        vsb.pack(side="left", fill="y")
        return tree

    def _english_date(self):
        d = self.current_date
        return f"{self.weekday_short[d.weekday()]}, {d.day} {self.month_short[d.month - 1]} {d.year}"

    # text wrapper for tasks column
    @staticmethod
    def _wrap(text, width=40):
        return "\n".join(textwrap.wrap(text, width)) if text else ""

    # ----- refresh -----
    def refresh(self):
        self.lbl_date.config(text=self._english_date())
        active, inactive, untouched = get_daily_data(self.current_date)
        most_emp, least_emp, most_proj, least_proj = get_weekly_stats(self.current_date)

        # populate tables
        t = self.tree_active;
        t.delete(*t.get_children())
        for r in active:
            tasks_multiline = self._wrap(r["tasks"])
            iid = t.insert("", "end",
                           values=(r["emp"], r["proj"], tasks_multiline,
                                   "Yes" if r["imgs"] else "—"))
            t.set(iid, "Imgs", ",".join(r["img_list"]))  # hidden path list
        t = self.tree_inactive;
        t.delete(*t.get_children())
        for name in inactive: t.insert("", "end", values=(name,))
        t = self.tree_projects;
        t.delete(*t.get_children())
        for proj in untouched: t.insert("", "end", values=(proj,))

        # weekly labels
        self.lbl_most_emp.config(text="\n".join(most_emp) if most_emp else "—")
        self.lbl_least_emp.config(text="\n".join(least_emp) if least_emp else "—")
        self.lbl_most_proj.config(text="\n".join(most_proj) if most_proj else "—")
        self.lbl_least_proj.config(text="\n".join(least_proj) if least_proj else "—")
        self.report_text = generate_daily_report(self.current_date)

    def auto_refresh(self):
        self.refresh()
        self.root.after(60000, self.auto_refresh)

    # ----- image preview -----
    def _show_images(self, event):
        item = self.tree_active.identify_row(event.y)
        if not item: return
        paths = self.tree_active.set(item, "Imgs").split(",")
        if not paths or paths == ['']:
            messagebox.showinfo("No images", "No images attached for this entry.")
            return
        self._current_img_path = paths[0]
        self._display_image()

    def _display_image(self):
        if not self._current_img_path: return
        try:
            w = self.preview_lbl.winfo_width() or 400
            h = self.preview_lbl.winfo_height() or 300
            img = Image.open(self._current_img_path)
            img.thumbnail((w, h))
            self._imgtk = ImageTk.PhotoImage(img)
            self.preview_lbl.configure(image=self._imgtk, text="")
        except Exception as e:
            messagebox.showerror("Error", f"Can't load image:\n{e}")

    def _refresh_preview_on_resize(self, _):
        if self._current_img_path:
            self._display_image()

    def save_pdf(self):
        try:
            path = create_pdf(self.report_text)
            os.startfile(path)
        except Exception as e:
            messagebox.showerror("Error", f"Couldn't create PDF:\n{e}")


# ========= Telegram handlers (Arabic) =========
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "مرحبًا 👋\nاستخدم الأمر /report لبدء إعداد تقريرك اليومي.")


async def report_entry(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    kb = [[InlineKeyboardButton(e["name"], callback_data=str(e["id"]))]
          for e in list_employees()]
    await update.message.reply_text(
        "اختر اسمك:", reply_markup=InlineKeyboardMarkup(kb))
    return EMPLOYEE


async def emp_chosen(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query;
    await q.answer()
    ctx.user_data["emp"] = int(q.data)
    kb = [[InlineKeyboardButton(p["project_name"], callback_data=str(p["id"]))]
          for p in list_projects()]
    await q.edit_message_text(
        "اختر المشروع:", reply_markup=InlineKeyboardMarkup(kb))
    return PROJECT


async def proj_chosen(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query;
    await q.answer()
    ctx.user_data["proj"] = int(q.data)
    await q.edit_message_text("اكتب مهام اليوم:")
    ctx.user_data["imgs"] = []
    return TASKS


async def tasks_recv(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["tasks"] = update.message.text.strip()
    await update.message.reply_text(
        "يمكنك إرسال صور (اختياري)، ثم اضغط /done عند الانتهاء.")
    return PHOTOS


async def photo_recv(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    p = update.message.photo[-1];
    f = await p.get_file()
    emp_id = ctx.user_data["emp"]
    emp_name = employee_name(emp_id).replace(" ", "_")
    folder = os.path.join(IMAGES_DIR, emp_name)
    os.makedirs(folder, exist_ok=True)
    filename = f"{datetime.now():%Y%m%d_%H%M%S}.jpg"
    path = os.path.join(folder, filename)
    await f.download_to_drive(path)
    ctx.user_data["imgs"].append(path)
    await update.message.reply_text("✔️ تم حفظ الصورة")


async def done(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    save_report(ctx.user_data["emp"], ctx.user_data["proj"],
                ctx.user_data["tasks"], ctx.user_data["imgs"])
    await update.message.reply_text(
        "✅ تم حفظ تقريرك بنجاح.",
        reply_markup=ReplyKeyboardRemove())
    await asyncio.to_thread(send_email, generate_daily_report())
    await update.message.reply_text(
        "يمكنك البدء بتقرير جديد في أي وقت باستخدام الأمر /report.\n\n— انتهى —")
    return ConversationHandler.END


async def cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("تم الإلغاء.",
                                    reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END


# ========= scheduler =========
def daily_job():
    send_email(generate_daily_report())


def run_scheduler():
    schedule.every().day.at("20:00").do(daily_job)
    while True:
        schedule.run_pending();
        time.sleep(30)


# ========= Telegram bot thread =========
def run_bot():
    asyncio.set_event_loop(asyncio.new_event_loop())
    app = Application.builder().token(BOT_TOKEN).build()
    conv = ConversationHandler(
        entry_points=[CommandHandler("report", report_entry)],
        states={
            EMPLOYEE: [CallbackQueryHandler(emp_chosen)],
            PROJECT: [CallbackQueryHandler(proj_chosen)],
            TASKS: [MessageHandler(filters.TEXT & ~filters.COMMAND, tasks_recv)],
            PHOTOS: [MessageHandler(filters.PHOTO, photo_recv),
                     CommandHandler("done", done)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    app.add_handler(CommandHandler("start", start))
    app.add_handler(conv)
    logging.info("Telegram bot running …")
    app.run_polling(stop_signals=None)


# ========= main =========
def main():
    threading.Thread(target=run_scheduler, daemon=True).start()
    threading.Thread(target=run_bot, daemon=True).start()
    root = tk.Tk()
    DashboardGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
