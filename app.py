import os
import sqlite3
from datetime import datetime
from pathlib import Path

from flask import Flask, g, redirect, render_template, request, session, url_for, flash

APP_DIR = Path(__file__).parent
DB_PATH = APP_DIR / "db.sqlite3"

app = Flask(__name__)
app.secret_key = "zad-alwafa-dev-secret"


# ---------------------------------------------------------------- database

def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(exception=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    fresh = not DB_PATH.exists()
    db = sqlite3.connect(DB_PATH)
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS families (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            area TEXT NOT NULL,
            rating REAL NOT NULL,
            reviews INTEGER NOT NULL,
            lunch_cutoff INTEGER NOT NULL,
            dinner_cutoff INTEGER NOT NULL,
            lunch_window TEXT NOT NULL,
            dinner_window TEXT NOT NULL,
            verified INTEGER NOT NULL DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS dishes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            family_id INTEGER NOT NULL REFERENCES families(id),
            name TEXT NOT NULL,
            category TEXT NOT NULL,
            price INTEGER NOT NULL,
            active INTEGER NOT NULL DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS addons (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            dish_id INTEGER NOT NULL REFERENCES dishes(id),
            name TEXT NOT NULL,
            price INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_name TEXT NOT NULL,
            family_id INTEGER NOT NULL REFERENCES families(id),
            dish_id INTEGER NOT NULL REFERENCES dishes(id),
            addon_id INTEGER,
            meal TEXT NOT NULL,
            total INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT NOT NULL
        );
        """
    )
    db.commit()

    if fresh:
        seed(db)
    db.close()


def seed(db):
    families = [
        ("بيت أم سعود", "حي الفيصلية، بريدة", 4.8, 132, 8, 14, "12:00 – 1:00 ظهرًا", "7:00 – 8:00 مساءً"),
        ("مطبخ الجواهر", "حي النهضة، بريدة", 4.6, 74, 9, 15, "12:30 – 1:30 ظهرًا", "7:30 – 8:30 مساءً"),
        ("سفرة الحي", "حي الصفراء، بريدة", 4.9, 201, 7, 13, "12:00 – 1:00 ظهرًا", "6:30 – 7:30 مساءً"),
    ]
    fids = []
    for f in families:
        cur = db.execute(
            "INSERT INTO families (name, area, rating, reviews, lunch_cutoff, dinner_cutoff, lunch_window, dinner_window) "
            "VALUES (?,?,?,?,?,?,?,?)",
            f,
        )
        fids.append(cur.lastrowid)

    catalog = {
        fids[0]: {
            "main": [("كبسة دجاج", 28, 1), ("مندي لحم", 38, 1), ("مظبي دجاج", 30, 0), ("مجبوس ربيان", 42, 0)],
            "side": [("سلطة خضراء", 8, 1), ("شوربة عدس", 10, 1), ("حمص", 9, 0), ("تبولة", 10, 0)],
        },
        fids[1]: {
            "main": [("برياني دجاج", 26, 1), ("كبسة لحم", 35, 1), ("جريش", 24, 1), ("مقلوبة", 30, 0)],
            "side": [("فتوش", 9, 1), ("شوربة خضار", 9, 0), ("سلطة كول سلو", 8, 0), ("رز أبيض", 6, 1)],
        },
        fids[2]: {
            "main": [("مندي دجاج", 27, 1), ("مضغوط لحم", 40, 1), ("كبسة دجاج", 26, 1), ("سليق", 25, 0)],
            "side": [("سلطة عربية", 8, 1), ("شوربة دجاج", 10, 1), ("مقبلات مشكلة", 14, 0), ("لبن", 5, 1)],
        },
    }
    addon_bank = [("أرز إضافي", 6), ("خبز", 3), ("مشروب غازي", 5), ("حصة بروتين إضافية", 12)]

    for fid, cats in catalog.items():
        for cat, items in cats.items():
            for name, price, active in items:
                cur = db.execute(
                    "INSERT INTO dishes (family_id, name, category, price, active) VALUES (?,?,?,?,?)",
                    (fid, name, cat, price, active),
                )
                if cat == "main":
                    dish_id = cur.lastrowid
                    for aname, aprice in addon_bank[:3]:
                        db.execute(
                            "INSERT INTO addons (dish_id, name, price) VALUES (?,?,?)",
                            (dish_id, aname, aprice),
                        )
    db.commit()


# ---------------------------------------------------------------- helpers

def meal_status(family):
    hour = datetime.now().hour
    lunch_open = hour < family["lunch_cutoff"]
    dinner_open = hour < family["dinner_cutoff"]
    return {
        "lunch": {"open": lunch_open, "cutoff": family["lunch_cutoff"], "window": family["lunch_window"]},
        "dinner": {"open": dinner_open, "cutoff": family["dinner_cutoff"], "window": family["dinner_window"]},
    }


STATUS_LABELS = {
    "pending": ("بانتظار قبول الأسرة", "future"),
    "accepted": ("مقبول — قيد التحضير", "accent"),
    "rejected": ("مرفوض", "penalty"),
    "ready": ("جاهزة", "verified"),
}


@app.context_processor
def inject_globals():
    return {
        "customer_name": session.get("customer_name"),
        "family_id": session.get("family_id"),
        "status_labels": STATUS_LABELS,
    }


# ---------------------------------------------------------------- customer routes

@app.route("/")
def home():
    return render_template("home.html")


@app.route("/start", methods=["GET", "POST"])
def start():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        if not name:
            flash("اكتب اسمك أول عشان نكمل.", "error")
            return redirect(url_for("start"))
        session["customer_name"] = name
        return redirect(url_for("families"))
    return render_template("start.html")


@app.route("/families")
def families():
    if not session.get("customer_name"):
        return redirect(url_for("start"))
    db = get_db()
    rows = db.execute("SELECT * FROM families ORDER BY rating DESC").fetchall()
    data = [{"row": r, "meals": meal_status(r)} for r in rows]
    return render_template("families.html", families=data)


@app.route("/families/<int:family_id>")
def family_detail(family_id):
    if not session.get("customer_name"):
        return redirect(url_for("start"))
    db = get_db()
    family = db.execute("SELECT * FROM families WHERE id=?", (family_id,)).fetchone()
    mains = db.execute(
        "SELECT * FROM dishes WHERE family_id=? AND category='main' AND active=1", (family_id,)
    ).fetchall()
    sides = db.execute(
        "SELECT * FROM dishes WHERE family_id=? AND category='side' AND active=1", (family_id,)
    ).fetchall()
    catalog_count = db.execute(
        "SELECT category, COUNT(*) as n FROM dishes WHERE family_id=? GROUP BY category", (family_id,)
    ).fetchall()
    addons_by_dish = {}
    for d in list(mains):
        addons_by_dish[d["id"]] = db.execute(
            "SELECT * FROM addons WHERE dish_id=?", (d["id"],)
        ).fetchall()
    meals = meal_status(family)
    return render_template(
        "family_detail.html",
        family=family,
        mains=mains,
        sides=sides,
        addons_by_dish=addons_by_dish,
        meals=meals,
        catalog_count={r["category"]: r["n"] for r in catalog_count},
    )


@app.route("/order", methods=["POST"])
def place_order():
    if not session.get("customer_name"):
        return redirect(url_for("start"))
    db = get_db()
    family_id = int(request.form["family_id"])
    dish_id = int(request.form["dish_id"])
    meal = request.form["meal"]
    addon_id = request.form.get("addon_id") or None

    family = db.execute("SELECT * FROM families WHERE id=?", (family_id,)).fetchone()
    meals = meal_status(family)
    if not meals[meal]["open"]:
        flash("عذرًا، انتهى موعد القطع لهذه الوجبة اليوم.", "error")
        return redirect(url_for("family_detail", family_id=family_id))

    dish = db.execute("SELECT * FROM dishes WHERE id=?", (dish_id,)).fetchone()
    total = dish["price"]
    if addon_id:
        addon = db.execute("SELECT * FROM addons WHERE id=?", (addon_id,)).fetchone()
        total += addon["price"]

    db.execute(
        "INSERT INTO orders (customer_name, family_id, dish_id, addon_id, meal, total, status, created_at) "
        "VALUES (?,?,?,?,?,?, 'pending', ?)",
        (session["customer_name"], family_id, dish_id, addon_id, meal, total, datetime.now().strftime("%d/%m %H:%M")),
    )
    db.commit()
    flash("تم إرسال طلبك وخصم قيمته إلكترونيًا — بانتظار قبول الأسرة.", "success")
    return redirect(url_for("orders"))


@app.route("/orders")
def orders():
    if not session.get("customer_name"):
        return redirect(url_for("start"))
    db = get_db()
    rows = db.execute(
        """
        SELECT o.*, f.name AS family_name, d.name AS dish_name, a.name AS addon_name
        FROM orders o
        JOIN families f ON f.id = o.family_id
        JOIN dishes d ON d.id = o.dish_id
        LEFT JOIN addons a ON a.id = o.addon_id
        WHERE o.customer_name = ?
        ORDER BY o.id DESC
        """,
        (session["customer_name"],),
    ).fetchall()
    return render_template("orders.html", orders=rows)


@app.route("/logout")
def logout():
    session.pop("customer_name", None)
    return redirect(url_for("home"))


# ---------------------------------------------------------------- family routes

@app.route("/family/login")
def family_login():
    db = get_db()
    rows = db.execute("SELECT * FROM families ORDER BY name").fetchall()
    return render_template("family_login.html", families=rows)


@app.route("/family/login/<int:family_id>")
def family_login_as(family_id):
    session["family_id"] = family_id
    return redirect(url_for("family_dashboard"))


@app.route("/family/dashboard")
def family_dashboard():
    fid = session.get("family_id")
    if not fid:
        return redirect(url_for("family_login"))
    db = get_db()
    family = db.execute("SELECT * FROM families WHERE id=?", (fid,)).fetchone()
    rows = db.execute(
        """
        SELECT o.*, d.name AS dish_name, a.name AS addon_name
        FROM orders o
        JOIN dishes d ON d.id = o.dish_id
        LEFT JOIN addons a ON a.id = o.addon_id
        WHERE o.family_id = ?
        ORDER BY o.id DESC
        """,
        (fid,),
    ).fetchall()
    pending = [r for r in rows if r["status"] == "pending"]
    active = [r for r in rows if r["status"] == "accepted"]
    ready = [r for r in rows if r["status"] == "ready"]
    rejected = [r for r in rows if r["status"] == "rejected"]

    shopping_list = {}
    for r in pending + active:
        key = r["dish_name"]
        shopping_list[key] = shopping_list.get(key, 0) + 1

    return render_template(
        "family_dashboard.html",
        family=family,
        pending=pending,
        active=active,
        ready=ready,
        rejected=rejected,
        shopping_list=shopping_list,
    )


@app.route("/family/order/<int:order_id>/<action>", methods=["POST"])
def family_order_action(order_id, action):
    fid = session.get("family_id")
    if not fid:
        return redirect(url_for("family_login"))
    db = get_db()
    new_status = {"accept": "accepted", "reject": "rejected", "ready": "ready"}.get(action)
    if new_status:
        db.execute(
            "UPDATE orders SET status=? WHERE id=? AND family_id=?", (new_status, order_id, fid)
        )
        db.commit()
    return redirect(url_for("family_dashboard"))


@app.route("/family/menu")
def family_menu():
    fid = session.get("family_id")
    if not fid:
        return redirect(url_for("family_login"))
    db = get_db()
    family = db.execute("SELECT * FROM families WHERE id=?", (fid,)).fetchone()
    mains = db.execute("SELECT * FROM dishes WHERE family_id=? AND category='main'", (fid,)).fetchall()
    sides = db.execute("SELECT * FROM dishes WHERE family_id=? AND category='side'", (fid,)).fetchall()
    return render_template("family_menu.html", family=family, mains=mains, sides=sides)


@app.route("/family/dish/<int:dish_id>/toggle", methods=["POST"])
def toggle_dish(dish_id):
    fid = session.get("family_id")
    if not fid:
        return redirect(url_for("family_login"))
    db = get_db()
    db.execute(
        "UPDATE dishes SET active = 1 - active WHERE id=? AND family_id=?", (dish_id, fid)
    )
    db.commit()
    return redirect(url_for("family_menu"))


@app.route("/family/logout")
def family_logout():
    session.pop("family_id", None)
    return redirect(url_for("home"))


init_db()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port, debug=True)
