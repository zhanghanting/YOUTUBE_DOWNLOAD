"""
测试文件路径打开功能
此脚本用于测试打开文件位置和目录功能，验证修复后的实现是否有效
"""
import os
import subprocess
import sqlite3
from pathlib import Path
import platform

def test_open_location():
    """测试打开文件位置功能"""
    print("===== 测试打开文件位置功能 =====")
    # 连接数据库
    conn = sqlite3.connect('downloads.db')
    cursor = conn.cursor()
    
    # 查询文件路径
    cursor.execute('SELECT id, filepath FROM downloads LIMIT 5')
    rows = cursor.fetchall()
    
    for row_id, filepath in rows:
        print(f"\n测试ID {row_id}的文件: {filepath}")
        # 检查文件是否存在
        if os.path.exists(filepath):
            print(f"原始文件存在")
            
            # 测试explorer /select方法
            try:
                print("尝试使用explorer /select方法...")
                # 注意:在PowerShell中，正确的分隔符是分号
                if platform.system() == "Windows":
                    cmd = f'explorer /select,"{filepath}"'
                    result = subprocess.run(cmd, shell=True)
                    if result.returncode == 0:
                        print("成功：explorer /select方法工作正常")
                    else:
                        print(f"失败：返回码 {result.returncode}")
            except Exception as e:
                print(f"错误：{e}")
                
            # 测试打开文件目录
            try:
                print("\n尝试打开文件目录...")
                directory = os.path.dirname(filepath)
                if os.path.exists(directory):
                    print(f"目录存在: {directory}")
                    os.startfile(directory)
                    print("成功：打开文件目录正常")
                else:
                    print(f"失败：目录不存在: {directory}")
            except Exception as e:
                print(f"错误：{e}")
        else:
            print(f"文件不存在，测试替代方案")
            # 提取文件名
            filename = os.path.basename(filepath)
            videos_dir = Path("videos")
            
            # 检查videos目录中是否有匹配的文件
            if videos_dir.exists():
                potential_files = list(videos_dir.glob(f"*{filename}*"))
                if potential_files:
                    test_path = potential_files[0]
                    print(f"找到替代文件: {test_path}")
                    
                    try:
                        if platform.system() == "Windows":
                            cmd = f'explorer /select,"{test_path}"'
                            result = subprocess.run(cmd, shell=True)
                            if result.returncode == 0:
                                print("成功：能够打开替代文件位置")
                            else:
                                print(f"失败：返回码 {result.returncode}")
                    except Exception as e:
                        print(f"错误：{e}")
                else:
                    print("未找到匹配的替代文件")
            else:
                print("videos目录不存在")
    
    conn.close()
    
def test_fallback_options():
    """测试后备选项"""
    print("\n===== 测试后备选项 =====")
    
    # 测试打开当前工作目录
    try:
        print("尝试打开当前工作目录...")
        current_dir = os.getcwd()
        print(f"当前目录: {current_dir}")
        os.startfile(current_dir)
        print("成功：打开当前工作目录正常")
    except Exception as e:
        print(f"错误：{e}")
    
    # 测试打开videos目录
    try:
        print("\n尝试打开videos目录...")
        videos_dir = os.path.join(os.getcwd(), "videos")
        if not os.path.exists(videos_dir):
            os.makedirs(videos_dir, exist_ok=True)
            print(f"创建了videos目录: {videos_dir}")
        
        os.startfile(videos_dir)
        print("成功：打开videos目录正常")
    except Exception as e:
        print(f"错误：{e}")

if __name__ == "__main__":
    print("文件路径测试工具\n")
    test_open_location()
    test_fallback_options()
    
    print("\n测试完成。请按任意键退出...")
    input() 