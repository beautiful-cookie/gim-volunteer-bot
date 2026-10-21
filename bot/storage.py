"""Хранение в SQLite: состояние диалогов и отправленные анкеты.

Таблица sessions — где кандидат сейчас в анкете (переживает перезапуск бота).
Таблица applications — отправленные анкеты; status: new → scored (или error).
"""
import datetime
import json
import sqlite3
from pathlib import Path


def now():
    return datetime.datetime.now().isoformat(timespec="seconds")


class Storage:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        # check_same_thread=False: бот обращается к базе из потоков (скоринг идёт в фоне).
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS sessions (
                user_id    INTEGER PRIMARY KEY,
                state      TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                reminded   INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS applications (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id      INTEGER NOT NULL,
                submitted_at TEXT NOT NULL,
                answers      TEXT NOT NULL,
                status       TEXT NOT NULL DEFAULT 'new',
                result       TEXT
            );
            -- Решения кураторов из дашборда. app_key — «bot:12» или «hist:O24-001».
            -- Через год к ним добавятся часы активности, и модель дообучится на этих решениях.
            CREATE TABLE IF NOT EXISTS decisions (
                app_key    TEXT PRIMARY KEY,
                decision   TEXT NOT NULL,
                note       TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL
            );
        """)
        self.db.commit()

    # ------------------------------------------------------------ диалоги

    def load_state(self, user_id):
        row = self.db.execute("SELECT state FROM sessions WHERE user_id = ?", (user_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def save_state(self, user_id, state):
        self.db.execute(
            "INSERT INTO sessions (user_id, state, updated_at, reminded) VALUES (?, ?, ?, 0) "
            "ON CONFLICT(user_id) DO UPDATE SET state = excluded.state, updated_at = excluded.updated_at, reminded = 0",
            (user_id, json.dumps(state, ensure_ascii=False), now()))
        self.db.commit()

    def sessions_to_remind(self, hours=24):
        """Кандидаты, которые бросили анкету больше суток назад и ещё не получали напоминание."""
        border = (datetime.datetime.now() - datetime.timedelta(hours=hours)).isoformat(timespec="seconds")
        rows = self.db.execute("SELECT user_id, state FROM sessions WHERE reminded = 0 AND updated_at < ?",
                               (border,)).fetchall()
        result = []
        for user_id, state_json in rows:
            step = json.loads(state_json)["step"]
            if step not in ("intro", "done", "stopped"):
                result.append(user_id)
        return result

    def mark_reminded(self, user_id):
        self.db.execute("UPDATE sessions SET reminded = 1 WHERE user_id = ?", (user_id,))
        self.db.commit()

    # ------------------------------------------------------------ анкеты

    def add_application(self, user_id, answers):
        cursor = self.db.execute("INSERT INTO applications (user_id, submitted_at, answers) VALUES (?, ?, ?)",
                                 (user_id, now(), json.dumps(answers, ensure_ascii=False)))
        self.db.commit()
        return cursor.lastrowid

    def new_applications(self):
        rows = self.db.execute("SELECT id, user_id, answers FROM applications WHERE status = 'new'").fetchall()
        return [(app_id, user_id, json.loads(answers)) for app_id, user_id, answers in rows]

    def save_result(self, app_id, result, status="scored"):
        self.db.execute("UPDATE applications SET status = ?, result = ? WHERE id = ?",
                        (status, json.dumps(result, ensure_ascii=False, default=str), app_id))
        self.db.commit()

    # ------------------------------------------------------------ решения кураторов

    def set_decision(self, app_key, decision, note=""):
        self.db.execute(
            "INSERT INTO decisions (app_key, decision, note, updated_at) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(app_key) DO UPDATE SET decision = excluded.decision, note = excluded.note, "
            "updated_at = excluded.updated_at",
            (app_key, decision, note, now()))
        self.db.commit()

    def decisions(self):
        """{app_key: (решение, комментарий)}"""
        rows = self.db.execute("SELECT app_key, decision, note FROM decisions").fetchall()
        return {key: (decision, note) for key, decision, note in rows}

    def all_applications(self):
        rows = self.db.execute("SELECT id, user_id, submitted_at, status, answers, result FROM applications").fetchall()
        return [dict(id=r[0], user_id=r[1], submitted_at=r[2], status=r[3], answers=json.loads(r[4]),
                     result=json.loads(r[5]) if r[5] else None) for r in rows]
