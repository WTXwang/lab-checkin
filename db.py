# -*- coding: utf-8 -*-
"""SQLite 数据库连接、建表与迁移（首次运行自动初始化，老库自动升级为课程结构）。"""
import hashlib
import os
import secrets
import shutil
import sqlite3
from contextlib import contextmanager
from datetime import datetime

import config

DB_PATH = os.environ.get("CHECKIN_DB") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data.db"
)

# ---------- 密码哈希（标准库 PBKDF2，零外部依赖） ----------

_PBKDF2_ITERATIONS = 200_000


def hash_password(password):
    """返回 "salt$hexdigest" 形式的哈希字符串。"""
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt), _PBKDF2_ITERATIONS
    )
    return f"{salt}${dk.hex()}"


def verify_password(password, stored):
    """校验密码与存储的哈希是否匹配；存储格式非法时返回 False。"""
    try:
        salt, digest = stored.split("$", 1)
        dk = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), bytes.fromhex(salt), _PBKDF2_ITERATIONS
        )
        return secrets.compare_digest(dk.hex(), digest)
    except Exception:
        return False


# 建表（课程结构）。老库已存在的表会被 IF NOT EXISTS 跳过，随后由迁移函数升级。
# 注意：依赖 course_id 的索引不写在这里（老库执行时该列还不存在），改在 _ensure_indexes 中创建。
_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    display_name TEXT,
    role TEXT NOT NULL DEFAULT 'user',   -- 'user' | 'super_admin'
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS courses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    owner_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    UNIQUE (owner_id, name)
);

CREATE TABLE IF NOT EXISTS course_members (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    course_id INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role TEXT NOT NULL,                  -- 'admin'（课程创建者）| 'assistant'（助教）
    joined_at TEXT NOT NULL,
    UNIQUE (course_id, user_id)
);

CREATE TABLE IF NOT EXISTS invitations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    course_id INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    code TEXT NOT NULL UNIQUE,
    created_by INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    used_at TEXT,
    used_by INTEGER
);

CREATE TABLE IF NOT EXISTS classes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    course_id INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    UNIQUE (course_id, name)
);

CREATE TABLE IF NOT EXISTS experiments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    course_id INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    UNIQUE (course_id, name)
);

CREATE TABLE IF NOT EXISTS students (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    class_id INTEGER NOT NULL REFERENCES classes(id) ON DELETE CASCADE,
    student_no TEXT NOT NULL,
    name TEXT NOT NULL,
    course_id INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS completions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    experiment_id INTEGER NOT NULL REFERENCES experiments(id) ON DELETE CASCADE,
    completed_at TEXT NOT NULL,
    operator TEXT,
    UNIQUE (student_id, experiment_id)
);
"""


def _column_exists(conn, table, column):
    return any(r[1] == column for r in conn.execute(f"PRAGMA table_info({table})"))


def _table_count(conn, table):
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


# ---------- 迁移：v0（无 owner）→ 多账号（owner_id） ----------

def _rebuild_with_owner(conn, table, admin_id):
    """重建 classes / experiments：加 owner_id，并把「全局唯一 name」改为「按老师唯一」。"""
    conn.executescript(
        f"""
        CREATE TABLE {table}_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            owner_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            UNIQUE (owner_id, name)
        );
        INSERT INTO {table}_new (id, name, owner_id) SELECT id, name, {admin_id} FROM {table};
        DROP TABLE {table};
        ALTER TABLE {table}_new RENAME TO {table};
        """
    )


def _rebuild_students(conn, admin_id):
    """重建 students：加 owner_id（老数据全部归管理员）。"""
    conn.executescript(
        f"""
        CREATE TABLE students_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            class_id INTEGER NOT NULL REFERENCES classes(id) ON DELETE CASCADE,
            student_no TEXT NOT NULL,
            name TEXT NOT NULL,
            owner_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE
        );
        INSERT INTO students_new (id, class_id, student_no, name, owner_id)
            SELECT id, class_id, student_no, name, {admin_id} FROM students;
        DROP TABLE students;
        ALTER TABLE students_new RENAME TO students;
        """
    )


def _migrate_legacy(conn):
    """幂等迁移（v0 → 多账号）：老库补 owner_id 列，数据归管理员。已课程化的库跳过。"""
    admin_id = conn.execute(
        "SELECT id FROM users WHERE username = ?", (config.ADMIN_USERNAME,)
    ).fetchone()["id"]

    if not _column_exists(conn, "classes", "course_id") and not _column_exists(conn, "classes", "owner_id"):
        _rebuild_with_owner(conn, "classes", admin_id)
    if not _column_exists(conn, "experiments", "course_id") and not _column_exists(conn, "experiments", "owner_id"):
        _rebuild_with_owner(conn, "experiments", admin_id)
    if not _column_exists(conn, "students", "course_id") and not _column_exists(conn, "students", "owner_id"):
        _rebuild_students(conn, admin_id)

    # 过渡结构下的学号唯一索引（课程化迁移重建表时会随旧表一起删除）
    if not _column_exists(conn, "students", "course_id"):
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_students_owner_student_no "
            "ON students(owner_id, student_no)"
        )


# ---------- 迁移：多账号（owner_id）→ 课程结构（course_id） ----------

def _migrate_to_courses(conn):
    """多账号 → 课程结构：全部数据并入一个课程（归 config 管理员所有）。
    幂等触发条件：classes 缺 course_id 列（迁移完成后该列存在，重复启动永不重跑）。
    返回迁移摘要 dict；无需迁移时返回 None。"""
    if _column_exists(conn, "classes", "course_id"):
        return None

    admin_id = conn.execute(
        "SELECT id FROM users WHERE username = ?", (config.ADMIN_USERNAME,)
    ).fetchone()["id"]
    now = datetime.now().astimezone().isoformat(timespec="seconds")

    before = {
        "classes": _table_count(conn, "classes"),
        "experiments": _table_count(conn, "experiments"),
        "students": _table_count(conn, "students"),
        "completions": _table_count(conn, "completions"),
    }

    # 1. 全局角色迁移：config 管理员 → super_admin，其余 → user
    conn.execute(
        "UPDATE users SET role = 'super_admin' WHERE username = ?", (config.ADMIN_USERNAME,)
    )
    conn.execute("UPDATE users SET role = 'user' WHERE role NOT IN ('super_admin', 'user')")

    # 2. 建合并课程（admin 所有，成为课程管理员）
    cur = conn.execute(
        "INSERT INTO courses(name, owner_id, created_at) VALUES ('实验课', ?, ?)",
        (admin_id, now),
    )
    cid = cur.lastrowid

    # 3. 班级：保留原 id、按名合并（admin 优先）
    conn.execute(
        """
        CREATE TABLE classes_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            course_id INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
            UNIQUE (course_id, name)
        )"""
    )
    conn.execute(
        "INSERT INTO classes_new (id, name, course_id) SELECT id, name, ? FROM classes WHERE owner_id = ?",
        (cid, admin_id),
    )
    conn.execute(
        """
        INSERT INTO classes_new (id, name, course_id)
        SELECT c.id, c.name, ? FROM classes c
        WHERE c.owner_id <> ?
          AND NOT EXISTS (SELECT 1 FROM classes_new n WHERE n.course_id = ? AND n.name = c.name)
        """,
        (cid, admin_id, cid),
    )
    # 非 admin 学生的班级按名重映射到合并后的班级
    conn.execute(
        """
        UPDATE students
        SET class_id = (
            SELECT n.id FROM classes_new n
            JOIN classes o ON o.id = students.class_id AND n.name = o.name AND n.course_id = ?
        )
        WHERE owner_id <> ?
        """,
        (cid, admin_id),
    )

    # 4. 实验：保留原 id、按名合并（admin 优先）
    conn.execute(
        """
        CREATE TABLE experiments_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            course_id INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
            UNIQUE (course_id, name)
        )"""
    )
    conn.execute(
        "INSERT INTO experiments_new (id, name, course_id) SELECT id, name, ? FROM experiments WHERE owner_id = ?",
        (cid, admin_id),
    )
    conn.execute(
        """
        INSERT INTO experiments_new (id, name, course_id)
        SELECT e.id, e.name, ? FROM experiments e
        WHERE e.owner_id <> ?
          AND NOT EXISTS (SELECT 1 FROM experiments_new n WHERE n.course_id = ? AND n.name = e.name)
        """,
        (cid, admin_id, cid),
    )
    # 4a. 完成记录按名重映射 experiment_id（必须在 DROP 旧表之前）
    conn.execute(
        """
        UPDATE completions
        SET experiment_id = (
            SELECT n.id FROM experiments_new n
            JOIN experiments o ON o.id = completions.experiment_id AND n.name = o.name AND n.course_id = ?
        )
        WHERE experiment_id IN (SELECT id FROM experiments WHERE owner_id <> ?)
        """,
        (cid, admin_id),
    )

    # 5. 学生：保留原 id、学号冲突 admin 优先（非 admin 冲突学生跳过）
    conn.execute(
        """
        CREATE TABLE students_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            class_id INTEGER NOT NULL REFERENCES classes(id) ON DELETE CASCADE,
            student_no TEXT NOT NULL,
            name TEXT NOT NULL,
            course_id INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE
        )"""
    )
    conn.execute(
        "INSERT INTO students_new (id, class_id, student_no, name, course_id) "
        "SELECT id, class_id, student_no, name, ? FROM students WHERE owner_id = ?",
        (cid, admin_id),
    )
    other_count = conn.execute(
        "SELECT COUNT(*) FROM students WHERE owner_id <> ?", (admin_id,)
    ).fetchone()[0]
    conn.execute(
        """
        INSERT INTO students_new (id, class_id, student_no, name, course_id)
        SELECT s.id, s.class_id, s.student_no, s.name, ? FROM students s
        WHERE s.owner_id <> ?
          AND NOT EXISTS (SELECT 1 FROM students_new n WHERE n.course_id = ? AND n.student_no = s.student_no)
        """,
        (cid, admin_id, cid),
    )
    skipped_students = other_count - (
        _table_count(conn, "students_new") - (before["students"] - other_count)
    )

    # 5a. 被跳过（学号冲突）的非 admin 学生，其完成记录一并删除（否则换表后悬空引用）
    conn.execute(
        """
        DELETE FROM completions
        WHERE student_id IN (
            SELECT s.id FROM students s WHERE s.owner_id <> ?
              AND NOT EXISTS (SELECT 1 FROM students_new n WHERE n.id = s.id)
        )
        """,
        (admin_id,),
    )

    # 6. 换表（SQLite 默认 legacy_alter_table=OFF：RENAME 会同步更新其他表的外键引用）
    conn.execute("DROP TABLE classes")
    conn.execute("ALTER TABLE classes_new RENAME TO classes")
    conn.execute("DROP TABLE experiments")
    conn.execute("ALTER TABLE experiments_new RENAME TO experiments")
    conn.execute("DROP TABLE students")
    conn.execute("ALTER TABLE students_new RENAME TO students")

    # 7. 管理员入课程成员表
    conn.execute(
        "INSERT OR IGNORE INTO course_members(course_id, user_id, role, joined_at) "
        "VALUES (?, ?, 'admin', ?)",
        (cid, admin_id, now),
    )

    return {
        "course_id": cid,
        "before": before,
        "after": {
            "classes": _table_count(conn, "classes"),
            "experiments": _table_count(conn, "experiments"),
            "students": _table_count(conn, "students"),
            "completions": _table_count(conn, "completions"),
        },
        "skipped_students": skipped_students,
    }


# ---------- 索引 ----------

def _ensure_indexes(conn):
    """课程结构下的索引（幂等）。"""
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_students_course_student_no "
        "ON students(course_id, student_no)"
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_students_class ON students(class_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_students_course ON students(course_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_classes_course ON classes(course_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_experiments_course ON experiments(course_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_completions_student ON completions(student_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_completions_experiment ON completions(experiment_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_members_course ON course_members(course_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_members_user ON course_members(user_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_invitations_course ON invitations(course_id)")


# ---------- 初始管理员 / 备份 / 初始化 ----------

def _ensure_admin(conn):
    """创建初始全局超管（幂等），并每次启动确保 config 管理员是超管。"""
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    conn.execute(
        "INSERT OR IGNORE INTO users(username, password_hash, display_name, role, created_at) "
        "VALUES (?, ?, ?, 'super_admin', ?)",
        (config.ADMIN_USERNAME, hash_password(config.ADMIN_PASSWORD), config.ADMIN_USERNAME, now),
    )
    conn.execute(
        "UPDATE users SET role = 'super_admin' WHERE username = ?", (config.ADMIN_USERNAME,)
    )


def _needs_course_migration(path):
    """旧库（classes 缺 course_id 列）需要课程化迁移时返回 True。"""
    if not os.path.exists(path):
        return False
    conn = sqlite3.connect(path)
    try:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(classes)")]
        return "course_id" not in cols
    finally:
        conn.close()


def _backup_db():
    target = os.path.join(
        os.path.dirname(DB_PATH), f"data.db.bak-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    )
    shutil.copy2(DB_PATH, target)
    print(f"已备份数据库 → {target}")


def _print_migration_summary(s):
    b, a = s["before"], s["after"]
    print()
    print("=" * 52)
    print("  已完成数据库迁移：多账号结构 → 课程结构")
    print(f"  新建课程「实验课」(id={s['course_id']})，归属管理员")
    print(f"  班级 {b['classes']} → {a['classes']}（同名合并）")
    print(f"  实验 {b['experiments']} → {a['experiments']}（同名合并）")
    print(f"  学生 {b['students']} → {a['students']}（学号冲突跳过 {s['skipped_students']} 人）")
    print(f"  完成记录 {b['completions']} → {a['completions']}")
    print("=" * 52)
    print()


def init_db():
    # 迁移阶段需要临时关闭外键（SQLite 重建被引用表时不能开启外键）
    if _needs_course_migration(DB_PATH):
        _backup_db()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.executescript(_SCHEMA)
        _ensure_admin(conn)
        _migrate_legacy(conn)
        summary = _migrate_to_courses(conn)
        _ensure_indexes(conn)
        conn.execute("PRAGMA user_version = 2")
        conn.commit()
    finally:
        conn.close()
    if summary:
        _print_migration_summary(summary)


@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
