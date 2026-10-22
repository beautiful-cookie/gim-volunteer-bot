"""Хранение в SQLite: состояние диалогов, анкеты, решения кураторов, опросы волонтёров и версии модели.

Таблица sessions — где кандидат сейчас в анкете (переживает перезапуск бота).
Таблица applications — отправленные анкеты; status: new → scored (или error).
Таблица decisions — решения кураторов из дашборда.
Таблица surveys — опрос через четыре месяца для тех, кого взяли в команду (bot/survey.py).
Таблица model_versions — версии модели успеха, дообученные на опросах (bot/retrain.py).
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
            -- Опрос через четыре месяца. status: sent → completed / declined / expired / undelivered.
            -- alert — почему волонтёр, похоже, недоволен (пусто — всё хорошо); notified — кураторам уже написали.
            CREATE TABLE IF NOT EXISTS surveys (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                app_id       INTEGER NOT NULL UNIQUE,
                user_id      INTEGER NOT NULL,
                sent_at      TEXT NOT NULL,
                status       TEXT NOT NULL DEFAULT 'sent',
                reminded     INTEGER NOT NULL DEFAULT 0,
                completed_at TEXT,
                answers      TEXT NOT NULL DEFAULT '{}',
                alert        TEXT NOT NULL DEFAULT '',
                notified     INTEGER NOT NULL DEFAULT 0
            );
            -- Версии модели успеха. Действующая — последняя принятая (accepted = 1).
            CREATE TABLE IF NOT EXISTS model_versions (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                n_history  INTEGER NOT NULL,
                n_survey   INTEGER NOT NULL,
                auc_new    REAL,
                auc_old    REAL,
                accepted   INTEGER NOT NULL,
                model      TEXT NOT NULL,
                note       TEXT NOT NULL DEFAULT ''
            );
        """)
        # decided_at — когда решение стало таким, как сейчас. Правка комментария его не сдвигает,
        # поэтому четыре месяца до опроса считаются от дня, когда волонтёра взяли в команду.
        columns = [row[1] for row in self.db.execute("PRAGMA table_info(decisions)")]
        if "decided_at" not in columns:
            self.db.execute("ALTER TABLE decisions ADD COLUMN decided_at TEXT")
            self.db.execute("UPDATE decisions SET decided_at = updated_at")
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
        moment = now()
        self.db.execute(
            "INSERT INTO decisions (app_key, decision, note, updated_at, decided_at) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(app_key) DO UPDATE SET note = excluded.note, updated_at = excluded.updated_at, "
            "decided_at = CASE WHEN decisions.decision = excluded.decision THEN decisions.decided_at "
            "ELSE excluded.decided_at END, decision = excluded.decision",
            (app_key, decision, note, moment, moment))
        self.db.commit()

    def decisions(self):
        """{app_key: (решение, комментарий)}"""
        rows = self.db.execute("SELECT app_key, decision, note FROM decisions").fetchall()
        return {key: (decision, note) for key, decision, note in rows}

    def all_applications(self):
        rows = self.db.execute("SELECT id, user_id, submitted_at, status, answers, result FROM applications").fetchall()
        return [dict(id=r[0], user_id=r[1], submitted_at=r[2], status=r[3], answers=json.loads(r[4]),
                     result=json.loads(r[5]) if r[5] else None) for r in rows]

    # ------------------------------------------------------------ опрос через четыре месяца

    def applications_due_for_survey(self, after_days, decision="Взят в команду"):
        """Анкеты из бота, чьих авторов взяли в команду не меньше after_days дней назад, а опроса ещё не было."""
        border = (datetime.datetime.now() - datetime.timedelta(days=after_days)).isoformat(timespec="seconds")
        rows = self.db.execute(
            "SELECT a.id, a.user_id, a.answers FROM applications a "
            "JOIN decisions d ON d.app_key = 'bot:' || a.id "
            "WHERE d.decision = ? AND d.decided_at <= ? AND a.id NOT IN (SELECT app_id FROM surveys)",
            (decision, border)).fetchall()
        return [(app_id, user_id, json.loads(answers)) for app_id, user_id, answers in rows]

    def create_survey(self, app_id, user_id):
        cursor = self.db.execute("INSERT INTO surveys (app_id, user_id, sent_at) VALUES (?, ?, ?)",
                                 (app_id, user_id, now()))
        self.db.commit()
        return cursor.lastrowid

    def finish_survey(self, survey_id, answers, status="completed", alert=""):
        self.db.execute("UPDATE surveys SET status = ?, answers = ?, alert = ?, completed_at = ? WHERE id = ?",
                        (status, json.dumps(answers, ensure_ascii=False), alert, now(), survey_id))
        self.db.commit()

    def surveys_to_remind(self, days=3):
        """Опросы без ответа дольше days дней, по которым ещё не напоминали: [(id опроса, user_id)]."""
        border = (datetime.datetime.now() - datetime.timedelta(days=days)).isoformat(timespec="seconds")
        return self.db.execute("SELECT id, user_id FROM surveys WHERE status = 'sent' AND reminded = 0 "
                               "AND sent_at < ?", (border,)).fetchall()

    def mark_survey_reminded(self, survey_id):
        self.db.execute("UPDATE surveys SET reminded = 1 WHERE id = ?", (survey_id,))
        self.db.commit()

    def expire_surveys(self, days=14):
        """Опросы без ответа дольше days дней закрываем. Возвращает user_id, чтобы убрать опрос из диалога."""
        border = (datetime.datetime.now() - datetime.timedelta(days=days)).isoformat(timespec="seconds")
        rows = self.db.execute("SELECT id, user_id FROM surveys WHERE status = 'sent' AND sent_at < ?",
                               (border,)).fetchall()
        for survey_id, _ in rows:
            self.db.execute("UPDATE surveys SET status = 'expired' WHERE id = ?", (survey_id,))
        self.db.commit()
        return [user_id for _, user_id in rows]

    def surveys_to_notify(self):
        """Пройденные опросы с сигналом «недоволен», о которых кураторам ещё не написали."""
        rows = self.db.execute(
            "SELECT s.id, s.app_id, s.user_id, s.answers, s.alert, a.answers FROM surveys s "
            "JOIN applications a ON a.id = s.app_id "
            "WHERE s.status = 'completed' AND s.alert != '' AND s.notified = 0").fetchall()
        return [dict(id=r[0], app_id=r[1], user_id=r[2], answers=json.loads(r[3]), alert=r[4],
                     application=json.loads(r[5])) for r in rows]

    def mark_survey_notified(self, survey_id):
        self.db.execute("UPDATE surveys SET notified = 1 WHERE id = ?", (survey_id,))
        self.db.commit()

    def all_surveys(self):
        rows = self.db.execute("SELECT id, app_id, user_id, sent_at, status, completed_at, answers, alert "
                               "FROM surveys").fetchall()
        return [dict(id=r[0], app_id=r[1], user_id=r[2], sent_at=r[3], status=r[4], completed_at=r[5],
                     answers=json.loads(r[6]), alert=r[7]) for r in rows]

    # ------------------------------------------------------------ версии модели

    def add_model_version(self, n_history, n_survey, auc_new, auc_old, accepted, model, note=""):
        cursor = self.db.execute(
            "INSERT INTO model_versions (created_at, n_history, n_survey, auc_new, auc_old, accepted, model, note) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (now(), n_history, n_survey, auc_new, auc_old, int(accepted), json.dumps(model, ensure_ascii=False),
             note))
        self.db.commit()
        return cursor.lastrowid

    def active_model(self):
        """Коэффициенты действующей модели или None, если модель ещё ни разу не дообучалась."""
        row = self.db.execute("SELECT model FROM model_versions WHERE accepted = 1 "
                              "ORDER BY id DESC LIMIT 1").fetchone()
        return json.loads(row[0]) if row else None

    def model_versions(self):
        rows = self.db.execute("SELECT id, created_at, n_history, n_survey, auc_new, auc_old, accepted, note "
                               "FROM model_versions ORDER BY id").fetchall()
        return [dict(id=r[0], created_at=r[1], n_history=r[2], n_survey=r[3], auc_new=r[4], auc_old=r[5],
                     accepted=bool(r[6]), note=r[7]) for r in rows]
