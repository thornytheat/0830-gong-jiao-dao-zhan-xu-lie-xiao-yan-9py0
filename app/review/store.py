import json
import sqlite3
from contextlib import closing, contextmanager
from pathlib import Path

from app.business import DomainIssue

SCHEMA = '''CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY, report TEXT NOT NULL, created TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'PENDING', revision INTEGER NOT NULL DEFAULT 0,
    note TEXT NOT NULL DEFAULT '', reviewed TEXT
);
CREATE TABLE IF NOT EXISTS confirmations (
    id TEXT NOT NULL, run_id TEXT NOT NULL, case_id TEXT NOT NULL,
    station INTEGER NOT NULL, second INTEGER NOT NULL, created TEXT NOT NULL,
    PRIMARY KEY (run_id, id),
    FOREIGN KEY (run_id) REFERENCES runs (id)
);
CREATE INDEX IF NOT EXISTS confirmations_run ON confirmations (run_id);
CREATE TABLE IF NOT EXISTS sources (
    run_id TEXT PRIMARY KEY, data BLOB NOT NULL,
    FOREIGN KEY (run_id) REFERENCES runs (id)
);
'''


class Store:
    def __init__(self, path):
        self.path = Path(path)

    @contextmanager
    def connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=15)
        connection.row_factory = sqlite3.Row
        connection.executescript(SCHEMA)  # DDL 幂等；先于业务事务提交
        with closing(connection), connection:
            yield connection

    def register(self, run_id, report, data=None):
        with self.connect() as db:
            db.execute('INSERT INTO runs(id,report,created) VALUES (?,?,?) ON CONFLICT(id) DO NOTHING',
                       (run_id, json.dumps(report, ensure_ascii=False), report['manifest']['created']))
            if data is not None:
                db.execute('INSERT INTO sources(run_id,data) VALUES (?,?) ON CONFLICT(run_id) DO NOTHING',
                           (run_id, data))
        return self.load(run_id)

    def source(self, run_id):
        with self.connect() as db:
            row = db.execute('SELECT data FROM sources WHERE run_id=?', (run_id,)).fetchone()
        if row is None:
            raise DomainIssue('RUN_NOT_FOUND')
        return row['data']

    def load(self, run_id):
        with self.connect() as db:
            row = db.execute('SELECT * FROM runs WHERE id=?', (run_id,)).fetchone()
        if row is None:
            raise DomainIssue('RUN_NOT_FOUND')
        result = dict(row)
        result['report'] = json.loads(result['report'])
        return result

    def confirmations(self, run_id):
        with self.connect() as db:
            rows = db.execute('SELECT id, run_id AS run, case_id AS "case", station, second, created '
                              'FROM confirmations WHERE run_id=? ORDER BY created, id', (run_id,)).fetchall()
        return [dict(row) for row in rows]

    def list(self):
        with self.connect() as db:
            return [dict(r) for r in db.execute('SELECT id,created,status,revision,note FROM runs ORDER BY created DESC,id LIMIT 50')]

    def revise(self, run_id, revision, status, note, now):
        with self.connect() as db:
            cursor = db.execute('UPDATE runs SET status=?,note=?,reviewed=?,revision=revision+1 WHERE id=? AND revision=?',
                                (status, note, now, run_id, revision))
            if cursor.rowcount != 1:
                raise DomainIssue('STALE_REVIEW')
        return self.load(run_id)

    def replace_report(self, db, run_id, report):
        cursor = db.execute('UPDATE runs SET report=?, revision=revision+1 WHERE id=?',
                            (json.dumps(report, ensure_ascii=False), run_id))
        if cursor.rowcount != 1:
            raise DomainIssue('RUN_NOT_FOUND')

    def add_confirmation(self, run_id, revision, confirmation, report, now):
        """同一事务内登记确认点、替换复核报告并推进版本号。"""
        with self.connect() as db:
            row = db.execute('SELECT revision, status FROM runs WHERE id=?', (run_id,)).fetchone()
            if row is None:
                raise DomainIssue('RUN_NOT_FOUND')
            if row['revision'] != revision:
                raise DomainIssue('STALE_REVIEW')
            if row['status'] == 'APPROVED':
                raise DomainIssue('RUN_FINALIZED')
            exists = db.execute('SELECT 1 FROM confirmations WHERE run_id=? AND id=?',
                                (run_id, confirmation['id'])).fetchone()
            if exists:
                raise DomainIssue('CONFIRMATION_EXISTS')
            db.execute('INSERT INTO confirmations(id,run_id,case_id,station,second,created) VALUES (?,?,?,?,?,?)',
                       (confirmation['id'], run_id, confirmation['case'], confirmation['station'],
                        confirmation['second'], now))
            self.replace_report(db, run_id, report)
        return self.load(run_id)

    def remove_confirmation(self, run_id, revision, confirmation_id, report):
        """同一事务内撤回确认点、替换复核报告并推进版本号；旧版本号的并发签发随之失败。"""
        with self.connect() as db:
            row = db.execute('SELECT revision, status FROM runs WHERE id=?', (run_id,)).fetchone()
            if row is None:
                raise DomainIssue('RUN_NOT_FOUND')
            if row['revision'] != revision:
                raise DomainIssue('STALE_REVIEW')
            if row['status'] == 'APPROVED':
                raise DomainIssue('RUN_FINALIZED')
            cursor = db.execute('DELETE FROM confirmations WHERE run_id=? AND id=?', (run_id, confirmation_id))
            if cursor.rowcount != 1:
                raise DomainIssue('CONFIRMATION_NOT_FOUND')
            self.replace_report(db, run_id, report)
        return self.load(run_id)
