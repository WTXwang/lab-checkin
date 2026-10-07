# -*- coding: utf-8 -*-
"""学生名单导入解析。

支持 .xlsx（openpyxl）、.xls（xlrd）和 .csv。按文件内容嗅探真实格式
（不依赖扩展名），自动识别表头行，按列名映射「学号 / 姓名 / 班级」三列，
返回 [(班级, 学号, 姓名), ...]。
"""
import csv
import io


# 列名别名（匹配时已做归一化：去空格、转小写）
_NO_KEYS = ("学号", "学生学号", "studentno", "studentid", "编号", "账号")
_NAME_KEYS = ("姓名", "名字", "学生姓名", "name")
_CLASS_KEYS = ("班级", "班", "class", "班级名称", "行政班", "专业班级")

_DEFAULT_CLASS = "默认班级"


def _norm(s):
    return "".join(str(s or "").strip().lower().split())


def _match(cell, keys):
    c = _norm(cell)
    if not c:
        return False
    return any(k in c or c in k for k in keys)


def _clean(v):
    if v is None:
        return ""
    if isinstance(v, float):
        if v.is_integer():
            v = int(v)
        else:
            v = str(v)
    return str(v).strip()


def _parse_xlsx(data):
    from openpyxl import load_workbook
    try:
        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception:
        raise ValueError("无法读取该 Excel 文件（文件可能已损坏）。请用 Excel 打开后另存为 .xlsx 再导入。")
    ws = wb.active
    return [list(row) for row in ws.iter_rows(values_only=True)]


def _parse_xls(data):
    try:
        import xlrd
    except ImportError:
        raise ValueError(
            "检测到旧版 Excel(.xls) 文件，但缺少解析库。请把文件用 Excel 另存为 .xlsx 或 .csv 后重试。"
        )
    book = xlrd.open_workbook(file_contents=data)
    sheet = book.sheet_by_index(0)
    return [[sheet.cell_value(r, c) for c in range(sheet.ncols)] for r in range(sheet.nrows)]


def _parse_csv(data):
    text = None
    for enc in ("utf-8-sig", "gbk", "utf-8"):
        try:
            text = data.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        text = data.decode("utf-8", errors="replace")
    return list(csv.reader(io.StringIO(text)))


def parse_file(filename, data):
    """解析上传文件，返回 [(班级, 学号, 姓名), ...]。失败抛 ValueError。"""
    name = (filename or "").lower()
    head = data[:8]

    # .csv / .txt 直接按文本解析
    if name.endswith((".csv", ".txt")):
        return _extract(_parse_csv(data))

    # 按文件内容嗅探真实格式（扩展名可能被改名，例如 .xls 被存成 .xlsx）
    if head[:4] == b"PK\x03\x04":
        return _extract(_parse_xlsx(data))
    if head[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
        return _extract(_parse_xls(data))

    # 其余情况（改名成 xls/xlsx 的文本，或未知格式）按文本兜底解析
    return _extract(_parse_csv(data))


def _extract(rows):
    col_no = col_name = col_class = None
    header_idx = None

    for i, row in enumerate(rows):
        no_i = name_i = class_i = None
        for j, cell in enumerate(row):
            if no_i is None and _match(cell, _NO_KEYS):
                no_i = j
            if name_i is None and _match(cell, _NAME_KEYS):
                name_i = j
            if class_i is None and _match(cell, _CLASS_KEYS):
                class_i = j
        if no_i is not None and name_i is not None:
            header_idx = i
            col_no, col_name, col_class = no_i, name_i, class_i
            break

    if header_idx is None:
        raise ValueError("未找到表头行，请确保文件包含「学号」和「姓名」两列")

    result = []
    for row in rows[header_idx + 1:]:
        student_no = _clean(row[col_no]) if col_no < len(row) else ""
        name = _clean(row[col_name]) if col_name < len(row) else ""
        class_name = _clean(row[col_class]) if (col_class is not None and col_class < len(row)) else ""
        if not student_no and not name:
            continue
        if not class_name:
            class_name = _DEFAULT_CLASS
        result.append((class_name, student_no, name))
    return result
