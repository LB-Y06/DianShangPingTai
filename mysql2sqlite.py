# mysql2sqlite.py - 自动转换MySQL备份为SQLite数据库
import sqlite3
import re

# 连接SQLite（自动创建ecommerce.db）
conn = sqlite3.connect("ecommerce.db")
cursor = conn.cursor()

# 读取MySQL备份文件
with open("db_backup.sql", "r", encoding="utf8") as f:
    sql_content = f.read()

# 清理MySQL特有语法，适配SQLite
sql_content = re.sub(r"SET FOREIGN_KEY_CHECKS = \d+;", "", sql_content)
sql_content = re.sub(r"TRUNCATE TABLE \w+;", "", sql_content)
sql_content = re.sub(r"DEFAULT CHARSET=utf8mb4", "", sql_content)
sql_content = re.sub(r"AUTO_INCREMENT", "AUTOINCREMENT", sql_content)
sql_content = re.sub(r"INT\(\d+\)", "INTEGER", sql_content)
sql_content = re.sub(r"BIGINT\(\d+\)", "INTEGER", sql_content)
sql_content = re.sub(r"VARCHAR\(\d+\)", "TEXT", sql_content)
sql_content = re.sub(r"FLOAT", "REAL", sql_content)
sql_content = re.sub(r"DOUBLE", "REAL", sql_content)

# 拆分SQL语句并执行
sql_statements = [stmt.strip() for stmt in sql_content.split(";") if stmt.strip()]
for stmt in sql_statements:
    try:
        cursor.execute(stmt)
    except Exception as e:
        # 忽略无关的MySQL特有语句（不影响数据）
        if "near 'PRIMARY'" not in str(e) and "near 'KEY'" not in str(e):
            print(f"忽略语句：{stmt}，错误：{e}")

conn.commit()
cursor.close()
conn.close()
print("转换完成！生成ecommerce.db文件")