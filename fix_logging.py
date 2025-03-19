import os
import sys
import shutil
import subprocess

def create_patched_main():
    """创建一个修补后的main启动文件"""
    print("正在创建修补后的启动文件...")
    
    # 创建修补后的main_patched.py文件
    with open("main_patched.py", "w", encoding="utf-8") as f:
        f.write("""
# 修补后的启动文件，用于解决日志配置问题
import os
import sys

# 设置环境变量
os.environ["PYTHONUNBUFFERED"] = "1"
os.environ["PYTHONIOENCODING"] = "utf-8"

# 修补uvicorn日志配置
import uvicorn.config
import logging
original_configure_logging = uvicorn.config.Config.configure_logging

def patched_configure_logging(self):
    try:
        return original_configure_logging(self)
    except Exception as e:
        print(f"日志配置失败，使用基本配置: {e}")
        logging.basicConfig(
            level=getattr(logging, self.log_level.upper()),
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            handlers=[logging.StreamHandler()]
        )

uvicorn.config.Config.configure_logging = patched_configure_logging

# 导入原始main模块
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import main

# 如果main模块有app对象，则启动它
if hasattr(main, "app"):
    if __name__ == "__main__":
        uvicorn.run(
            "main:app", 
            host="127.0.0.1", 
            port=8000, 
            log_level="info",
            log_config=None
        )
""")
    
    print("修补后的启动文件创建成功！")
    return True

def create_patched_batch():
    """创建一个修补后的批处理文件"""
    print("正在创建修补后的批处理文件...")
    
    # 创建修补后的run_fixed.bat文件
    with open("run_fixed.bat", "w", encoding="utf-8") as f:
        f.write("""@echo off
echo 正在启动YouTube视频下载器（修补版）...
set PYTHONUNBUFFERED=1
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
if exist "dist\YouTube视频下载器.exe" (
    start "" "dist\YouTube视频下载器.exe"
) else (
    echo 错误: 找不到可执行文件
    pause
)
""")
    
    # 复制到dist目录
    if os.path.exists("dist"):
        shutil.copy("run_fixed.bat", "dist/run_fixed.bat")
    
    print("修补后的批处理文件创建成功！")
    return True

def rebuild_exe():
    """使用修补后的main_patched.py重新打包应用程序"""
    print("正在准备重新打包应用程序...")
    
    # 修改build_exe.py中的main.py为main_patched.py
    if os.path.exists("build_exe.py"):
        with open("build_exe.py", "r", encoding="utf-8") as f:
            content = f.read()
        
        # 替换main.py为main_patched.py
        if "main.py" in content:
            content = content.replace('"main.py"', '"main_patched.py"')
            
            # 保存修改后的build_exe.py
            with open("build_exe_patched.py", "w", encoding="utf-8") as f:
                f.write(content)
            
            print("已创建修补后的build_exe_patched.py")
            
            # 运行修补后的build_exe_patched.py
            try:
                print("正在重新打包应用程序...")
                subprocess.check_call([sys.executable, "build_exe_patched.py"])
                print("应用程序重新打包成功！")
                return True
            except subprocess.CalledProcessError as e:
                print(f"重新打包失败: {e}")
                return False
        else:
            print("警告: 在build_exe.py中找不到main.py引用")
            return False
    else:
        print("错误: 找不到build_exe.py文件")
        return False

def main():
    print("=" * 50)
    print("YouTube视频下载器修复工具")
    print("=" * 50)
    
    # 创建修补后的启动文件
    if create_patched_main():
        # 创建修补后的批处理文件
        create_patched_batch()
        
        # 询问是否重新打包
        choice = input("是否重新打包应用程序? (y/n): ")
        if choice.lower() == 'y':
            if rebuild_exe():
                print("\n修复和重新打包完成！")
                print("新的可执行文件位于dist目录中")
                print("请使用dist目录中的run_fixed.bat启动应用程序")
            else:
                print("\n重新打包失败，但您仍然可以使用run_fixed.bat启动原始可执行文件")
        else:
            print("\n跳过重新打包，您可以使用run_fixed.bat启动原始可执行文件")
    
    print("=" * 50)

if __name__ == "__main__":
    main() 