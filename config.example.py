# -*- coding: utf-8 -*-
"""系统配置（示例）。

部署时请把本文件复制为 config.py，并修改下面几项：
1. ADMIN_USERNAME / ADMIN_PASSWORD —— 全局超级管理员账号（首次启动时自动创建，
   之后每次启动都会确保该账号是超管）。超管可进入「全局管理」查看/删除任何用户和课程；
   课程内部事务（班级、实验、学生）由各课程的管理员负责。
2. SECRET_KEY —— 会话签名密钥，改成任意一长串随机字符，不要泄露。

其他用户通过登录页「注册」自行创建账号：可创建课程（成为该课程管理员），
或通过课程管理员发放的邀请码加入课程成为助教。
"""

# 初始全局超管账号（仅在首次启动时用于创建该账号；之后改密码需另想办法）
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "请改成你自己的密码"
# 会话签名密钥（用于 Cookie 签名；泄露则任何人都能伪造登录会话，务必保密。
# 用 python -c "import secrets; print(secrets.token_hex(32))" 生成一个随机值填在这里）
SECRET_KEY = "please-change-this-to-a-long-random-string"

# 部署 HTTPS 后设为 True（会话 Cookie 只在加密连接下传输；本地 HTTP 调试保持 False）
HTTPS_ONLY = False
