import sqlite3
import os
from pathlib import Path

# 连接数据库
conn = sqlite3.connect('downloads.db')
cursor = conn.cursor()

# 查询文件路径
cursor.execute('SELECT filepath FROM downloads LIMIT 5')
rows = cursor.fetchall()

print('数据库中的文件路径:')
for row in rows:
    filepath = row[0]
    print(f"路径: {filepath}")
    print(f"是否存在: {os.path.exists(filepath)}")
    print(f"绝对路径: {os.path.abspath(filepath)}")
    print(f"规范路径: {os.path.normpath(filepath)}")
    print(f"目录: {os.path.dirname(filepath)}")
    print("---")

conn.close() 