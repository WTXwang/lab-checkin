# -*- coding: utf-8 -*-
"""冒烟测试：课程权限模型的核心流程与权限矩阵。

用法：python test_smoke.py（使用临时数据库，不影响真实 data.db；也兼容 pytest 收集）。
"""
import glob
import os
import re
import sqlite3
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config
import db
from fastapi.testclient import TestClient
import app as app_module

TMPDIR = tempfile.mkdtemp(prefix="checkin_smoke_")
PASS = []
FAIL = []


def check(name, cond, detail=""):
    if cond:
        PASS.append(name)
        print("OK   " + name)
    else:
        FAIL.append(name)
        print("FAIL " + name + ((" | " + str(detail)) if detail else ""))


def use_db(path, keep=False):
    if not keep and os.path.exists(path):
        os.remove(path)
    os.environ["CHECKIN_DB"] = path
    db.DB_PATH = path


# ---------- 1. 全新库：完整流程 + 权限矩阵 ----------

def test_fresh_flow():
    path = os.path.join(TMPDIR, "fresh.db")
    use_db(path)

    # --- admin（超管 + 课程管理员） ---
    with TestClient(app_module.app) as c:
        r = c.get("/api/courses")
        check("未登录访问课程列表 401", r.status_code == 401, r.status_code)

        r = c.post("/api/login", json={"username": config.ADMIN_USERNAME, "password": config.ADMIN_PASSWORD})
        check("admin 登录 role=super_admin", r.status_code == 200 and r.json()["role"] == "super_admin", r.text)

        me = c.get("/api/me").json()
        check("/api/me 返回 id 与 is_super_admin", me["authed"] and me["id"] and me["is_super_admin"] is True, me)

        r = c.post("/api/courses", json={"name": "物理实验"})
        check("admin 创建课程", r.status_code == 200, r.text)
        cid = r.json()["id"]

        r = c.get("/api/courses").json()
        check("课程列表角色为 admin", len(r["courses"]) == 1 and r["courses"][0]["role"] == "admin", r)

        r = c.post(f"/api/courses/{cid}/classes", json={"name": "一班"})
        check("admin 添加班级", r.status_code == 200, r.text)
        class_id = r.json()["id"]
        r = c.post(f"/api/courses/{cid}/experiments", json={"name": "实验一"})
        check("admin 添加实验", r.status_code == 200, r.text)
        exp_id = r.json()["id"]
        r = c.post(f"/api/courses/{cid}/students", json={"class_id": class_id, "student_no": "20210001", "name": "张三"})
        check("admin 添加学生", r.status_code == 200, r.text)
        student_id = r.json()["id"]

        r = c.post(f"/api/courses/{cid}/students", json={"class_id": class_id, "student_no": "20210001", "name": "李四"})
        check("同学号学生被拒 400（学号课程内唯一）", r.status_code == 400, r.text)

        r = c.post(f"/api/courses/{cid}/completions", json={"student_id": student_id, "experiment_id": exp_id})
        check("admin 登记完成", r.status_code == 200, r.text)
        r = c.put(f"/api/courses/{cid}/completions", json={"student_id": student_id, "experiment_id": exp_id, "completed_at": "2026-10-07T10:00:00"})
        check("admin 修改完成时间", r.status_code == 200, r.text)
        r = c.delete(f"/api/courses/{cid}/completions?student_id={student_id}&experiment_id={exp_id}")
        check("admin 撤销完成", r.status_code == 200, r.text)

        r = c.post(f"/api/courses/{cid}/invites", json={})
        check("生成邀请码", r.status_code == 200, r.text)
        code = r.json()["code"]
        check("邀请码格式 ^[0-9A-F]{8}$", bool(re.match(r"^[0-9A-F]{8}$", code)), code)

        r = c.get("/api/admin/users")
        check("超管访问用户列表 200", r.status_code == 200, r.text)
        r = c.get("/api/admin/courses")
        check("超管访问课程列表 200", r.status_code == 200, r.text)
        r = c.delete(f"/api/admin/users/{me['id']}")
        check("超管删除自己 400", r.status_code == 400, r.text)
        r = c.get("/api/courses/99999/classes")
        check("不存在课程 404", r.status_code == 404, r.text)

    # --- u2：注册 → 邀请码加入 → 助教权限 ---
    with TestClient(app_module.app) as c2:
        r = c2.post("/api/register", json={"username": "u2", "password": "pass123", "display_name": "助教二"})
        check("u2 注册 role=user", r.status_code == 200 and r.json()["role"] == "user", r.text)

        r = c2.get(f"/api/courses/{cid}/classes")
        check("u2 非成员访问 403", r.status_code == 403, r.text)

        r = c2.get(f"/api/invites/{code}")
        check("u2 预览邀请码", r.status_code == 200 and r.json()["course_name"] == "物理实验" and r.json()["role"] == "assistant", r.text)

        r = c2.post("/api/invites/accept", json={"code": code})
        check("u2 接受邀请", r.status_code == 200, r.text)
        r = c2.post("/api/invites/accept", json={"code": code})
        check("u2 同码再接受 404", r.status_code == 404, r.text)

        r = c2.get("/api/courses").json()
        check("u2 课程列表角色为 assistant", any(x["id"] == cid and x["role"] == "assistant" for x in r["courses"]), r)

        r = c2.get(f"/api/courses/{cid}/classes")
        check("u2 成员读取班级 200", r.status_code == 200, r.text)
        r = c2.get(f"/api/courses/{cid}/students?class_id={class_id}")
        check("u2 成员读取学生 200", r.status_code == 200, r.text)
        r = c2.get(f"/api/courses/{cid}/overview?class_id={class_id}")
        check("u2 查看总览 403（仅管理员）", r.status_code == 403, r.text)
        r = c2.get(f"/api/courses/{cid}/export?class_id={class_id}")
        check("u2 导出总览 403（仅管理员）", r.status_code == 403, r.text)
        r = c2.get(f"/api/courses/{cid}/student_lookup?student_no=20210001")
        check("u2 按学号查找 200", r.status_code == 200, r.text)
        r = c2.post(f"/api/courses/{cid}/completions", json={"student_id": student_id, "experiment_id": exp_id})
        check("u2 登记完成 200", r.status_code == 200, r.text)
        r = c2.put(f"/api/courses/{cid}/completions", json={"student_id": student_id, "experiment_id": exp_id, "completed_at": "2026-10-07T11:00:00"})
        check("u2 修改时间 403（仅管理员）", r.status_code == 403, r.text)
        r = c2.delete(f"/api/courses/{cid}/completions?student_id={student_id}&experiment_id={exp_id}")
        check("u2 撤销 200", r.status_code == 200, r.text)

        r = c2.post(f"/api/courses/{cid}/classes", json={"name": "二班"})
        check("u2 写班级 403", r.status_code == 403, r.text)
        r = c2.delete(f"/api/courses/{cid}/classes/{class_id}")
        check("u2 删班级 403", r.status_code == 403, r.text)
        r = c2.post(f"/api/courses/{cid}/experiments", json={"name": "实验二"})
        check("u2 加实验 403", r.status_code == 403, r.text)
        r = c2.post(f"/api/courses/{cid}/students", json={"class_id": class_id, "student_no": "x", "name": "y"})
        check("u2 加学生 403", r.status_code == 403, r.text)
        r = c2.get(f"/api/courses/{cid}/members")
        check("u2 看成员列表 403", r.status_code == 403, r.text)
        r = c2.post(f"/api/courses/{cid}/invites", json={})
        check("u2 生成邀请码 403", r.status_code == 403, r.text)
        r = c2.delete(f"/api/courses/{cid}")
        check("u2 删课程 403", r.status_code == 403, r.text)
        r = c2.get("/api/admin/users")
        check("u2 访问全局管理 403", r.status_code == 403, r.text)

    # --- u3：无关用户 ---
    with TestClient(app_module.app) as c3:
        r = c3.post("/api/register", json={"username": "u3", "password": "pass123"})
        check("u3 注册", r.status_code == 200, r.text)
        r = c3.get(f"/api/courses/{cid}/classes")
        check("u3 无关用户访问 403", r.status_code == 403, r.text)
        r = c3.post("/api/invites/accept", json={"code": code})
        check("u3 用已使用邀请码 404", r.status_code == 404, r.text)

    # --- admin：成员管理 ---
    with TestClient(app_module.app) as c:
        r = c.post("/api/login", json={"username": config.ADMIN_USERNAME, "password": config.ADMIN_PASSWORD})
        assert r.status_code == 200
        users = c.get("/api/admin/users").json()["users"]
        u2_id = next(u["id"] for u in users if u["username"] == "u2")
        u3_id = next(u["id"] for u in users if u["username"] == "u3")

        r = c.get(f"/api/courses/{cid}/members")
        check("admin 查看成员列表", r.status_code == 200, r.text)
        r = c.delete(f"/api/courses/{cid}/members/{me['id']}")
        check("admin 移除创建者 400", r.status_code == 400, r.text)
        r = c.delete(f"/api/courses/{cid}/members/{u2_id}")
        check("admin 移除助教 u2", r.status_code == 200, r.text)

        # 被移除的 u2 立即验证（此时课程仍存在，应 403 而非 404）
        with TestClient(app_module.app) as c2:
            r = c2.post("/api/login", json={"username": "u2", "password": "pass123"})
            assert r.status_code == 200
            r = c2.get(f"/api/courses/{cid}/classes")
            check("被移除的 u2 访问 403", r.status_code == 403, r.text)

        # 全局管理：删 u3、删课程
        r = c.delete(f"/api/admin/users/{u3_id}")
        check("超管删除 u3", r.status_code == 200, r.text)
        r = c.delete(f"/api/admin/courses/{cid}")
        check("超管删除课程", r.status_code == 200, r.text)
        r = c.get("/api/courses").json()
        check("admin 课程列表已空", len(r["courses"]) == 0, r)
        r = c.get(f"/api/courses/{cid}/classes")
        check("删除后访问课程 404", r.status_code == 404, r.text)


# ---------- 2. 旧库（多账号 owner_id 结构）迁移 ----------

def make_legacy_db(path):
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE COLLATE NOCASE,
            password_hash TEXT NOT NULL,
            display_name TEXT,
            role TEXT NOT NULL DEFAULT 'teacher',
            created_at TEXT NOT NULL
        );
        CREATE TABLE classes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            owner_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            UNIQUE (owner_id, name)
        );
        CREATE TABLE students (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            class_id INTEGER NOT NULL REFERENCES classes(id) ON DELETE CASCADE,
            student_no TEXT NOT NULL,
            name TEXT NOT NULL,
            owner_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE
        );
        CREATE TABLE experiments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            owner_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            UNIQUE (owner_id, name)
        );
        CREATE TABLE completions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
            experiment_id INTEGER NOT NULL REFERENCES experiments(id) ON DELETE CASCADE,
            completed_at TEXT NOT NULL,
            operator TEXT,
            UNIQUE (student_id, experiment_id)
        );
        CREATE UNIQUE INDEX idx_students_owner_student_no ON students(owner_id, student_no);
        """
    )
    now = "2026-01-01T00:00:00+08:00"
    conn.execute(
        "INSERT INTO users(id, username, password_hash, display_name, role, created_at) VALUES (1, ?, 'h', ?, 'admin', ?)",
        (config.ADMIN_USERNAME, config.ADMIN_USERNAME, now),
    )
    conn.execute("INSERT INTO users(id, username, password_hash, display_name, role, created_at) VALUES (2, 'ww', 'h', 'ww', 'teacher', ?)", (now,))
    # 班级：admin 1班/2班；ww 1班(重名)/3班
    conn.execute("INSERT INTO classes(id, name, owner_id) VALUES (1, '1班', 1)")
    conn.execute("INSERT INTO classes(id, name, owner_id) VALUES (2, '2班', 1)")
    conn.execute("INSERT INTO classes(id, name, owner_id) VALUES (3, '1班', 2)")
    conn.execute("INSERT INTO classes(id, name, owner_id) VALUES (4, '3班', 2)")
    # 实验：admin 实验一/实验二；ww 实验一(重名)/实验三
    conn.execute("INSERT INTO experiments(id, name, owner_id) VALUES (1, '实验一', 1)")
    conn.execute("INSERT INTO experiments(id, name, owner_id) VALUES (2, '实验二', 1)")
    conn.execute("INSERT INTO experiments(id, name, owner_id) VALUES (3, '实验一', 2)")
    conn.execute("INSERT INTO experiments(id, name, owner_id) VALUES (4, '实验三', 2)")
    # 学生：admin S001/S002；ww S003(班级3→1班)、S002(学号与 admin 冲突，应被跳过)
    conn.execute("INSERT INTO students(id, class_id, student_no, name, owner_id) VALUES (1, 1, 'S001', '甲', 1)")
    conn.execute("INSERT INTO students(id, class_id, student_no, name, owner_id) VALUES (2, 2, 'S002', '乙', 1)")
    conn.execute("INSERT INTO students(id, class_id, student_no, name, owner_id) VALUES (3, 3, 'S003', '丙', 2)")
    conn.execute("INSERT INTO students(id, class_id, student_no, name, owner_id) VALUES (4, 4, 'S002', '丁', 2)")
    # 完成记录：admin 学生1×实验1；ww 学生3×实验3(→实验一)、学生4×实验4(学生被跳过，记录应删除)
    conn.execute("INSERT INTO completions(id, student_id, experiment_id, completed_at) VALUES (1, 1, 1, ?)", (now,))
    conn.execute("INSERT INTO completions(id, student_id, experiment_id, completed_at) VALUES (2, 3, 3, ?)", (now,))
    conn.execute("INSERT INTO completions(id, student_id, experiment_id, completed_at) VALUES (3, 4, 4, ?)", (now,))
    conn.commit()
    conn.close()


def test_legacy_migration():
    path = os.path.join(TMPDIR, "legacy.db")
    make_legacy_db(path)
    baks_before = glob.glob(os.path.join(TMPDIR, "data.db.bak-*"))
    use_db(path, keep=True)
    db.init_db()

    baks_after = glob.glob(os.path.join(TMPDIR, "data.db.bak-*"))
    check("迁移前自动备份生成", len(baks_after) == len(baks_before) + 1, baks_after)

    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row

    users = conn.execute("SELECT username, role FROM users ORDER BY id").fetchall()
    check("users 角色迁移", users[0]["role"] == "super_admin" and users[1]["role"] == "user",
          [dict(u) for u in users])

    courses = conn.execute("SELECT id, name, owner_id FROM courses").fetchall()
    check("courses=1 且为实验课 owner=1",
          len(courses) == 1 and courses[0]["name"] == "实验课" and courses[0]["owner_id"] == 1,
          [dict(c) for c in courses])

    members = conn.execute("SELECT course_id, user_id, role FROM course_members").fetchall()
    check("course_members=1 (课程, admin, admin)",
          len(members) == 1 and members[0]["user_id"] == 1 and members[0]["role"] == "admin",
          [dict(m) for m in members])

    classes = conn.execute("SELECT id, name, course_id FROM classes ORDER BY name").fetchall()
    check("classes 4→3（同名合并）", len(classes) == 3, [dict(c) for c in classes])

    experiments = conn.execute("SELECT id, name FROM experiments ORDER BY id").fetchall()
    check("experiments 4→3（同名合并）",
          len(experiments) == 3 and {e["name"] for e in experiments} == {"实验一", "实验二", "实验三"},
          [dict(e) for e in experiments])

    students = conn.execute("SELECT id, student_no, class_id FROM students ORDER BY id").fetchall()
    check("students 4→3（S002 冲突跳过）", len(students) == 3, [dict(s) for s in students])
    stu3 = next(s for s in students if s["id"] == 3)
    check("ww 学生 S003 班级重映射到 1班(id=1)", stu3["class_id"] == 1, dict(stu3))

    comps = conn.execute("SELECT id, student_id, experiment_id FROM completions ORDER BY id").fetchall()
    check("completions 3→2（跳过的学生记录被清理，实验重映射）",
          len(comps) == 2 and
          all(c["student_id"] in (1, 3) for c in comps) and
          any(c["student_id"] == 3 and c["experiment_id"] == 1 for c in comps),
          [dict(c) for c in comps])

    fk = conn.execute("PRAGMA foreign_key_check").fetchall()
    check("foreign_key_check 为空", len(fk) == 0, [dict(f) for f in fk])

    conn.close()

    # 幂等：再跑一次，计数不变
    db.init_db()
    conn = sqlite3.connect(path)
    counts = {
        "courses": conn.execute("SELECT COUNT(*) FROM courses").fetchone()[0],
        "classes": conn.execute("SELECT COUNT(*) FROM classes").fetchone()[0],
        "experiments": conn.execute("SELECT COUNT(*) FROM experiments").fetchone()[0],
        "students": conn.execute("SELECT COUNT(*) FROM students").fetchone()[0],
        "completions": conn.execute("SELECT COUNT(*) FROM completions").fetchone()[0],
    }
    conn.close()
    check("幂等：重跑 init_db 计数不变",
          counts == {"courses": 1, "classes": 3, "experiments": 3, "students": 3, "completions": 2},
          counts)


def main():
    test_fresh_flow()
    test_legacy_migration()
    print()
    print("=" * 52)
    print(f"  通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
    if FAIL:
        print("  失败项：")
        for name in FAIL:
            print("    - " + name)
    print("=" * 52)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
