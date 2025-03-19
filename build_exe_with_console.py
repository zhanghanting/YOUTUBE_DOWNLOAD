import os
import sys
import subprocess
import shutil
import platform

def check_requirements():
    """检查并安装必要的依赖项"""
    print("检查并安装必要的依赖项...")
    
    # 安装PyInstaller和其他必要的包
    subprocess.check_call([sys.executable, "-m", "pip", "install", "--upgrade", "pip"])
    subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])
    
    # 安装必要的依赖，但跳过pyinstaller（因为我们已经安装了）
    if os.path.exists("requirements.txt"):
        try:
            # 读取requirements.txt文件
            with open("requirements.txt", "r") as f:
                requirements = f.readlines()
            
            # 过滤掉pyinstaller相关的行
            filtered_requirements = [req for req in requirements if "pyinstaller" not in req.lower()]
            
            # 创建临时requirements文件
            with open("temp_requirements.txt", "w") as f:
                f.writelines(filtered_requirements)
                
            # 安装过滤后的依赖
            subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", "temp_requirements.txt"])
            
            # 删除临时文件
            os.remove("temp_requirements.txt")
        except Exception as e:
            print(f"安装依赖时出错: {e}")
            print("尝试安装基本依赖...")
            subprocess.check_call([sys.executable, "-m", "pip", "install", "fastapi", "uvicorn", "yt-dlp", "jinja2", "aiofiles", "winshell", "pywin32"])
    else:
        # 如果没有requirements.txt，直接安装基本依赖
        subprocess.check_call([sys.executable, "-m", "pip", "install", "fastapi", "uvicorn", "yt-dlp", "jinja2", "aiofiles", "winshell", "pywin32"])
    
    print("依赖项安装完成！")

def create_patched_main():
    """创建main_patched.py文件"""
    with open("main_patched.py", "w", encoding="utf-8") as f:
        f.write('''
# 修补后的启动文件，用于解决日志配置问题并显示控制台窗口
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
        print("="*50)
        print("YouTube视频下载器已启动")
        print("请在浏览器中访问: http://127.0.0.1:8000")
        print("="*50)
        # 启动浏览器
        import webbrowser
        webbrowser.open("http://127.0.0.1:8000")
        
        uvicorn.run(
            "main:app", 
            host="127.0.0.1", 
            port=8000, 
            log_level="info",
            log_config=None
        )
''')
    print("已创建启动脚本 main_patched.py")

def build_exe():
    """构建可执行文件"""
    print("开始构建可执行文件...")
    
    # 创建修补后的main文件
    create_patched_main()
    
    # 确保目录存在
    if not os.path.exists("dist"):
        os.makedirs("dist")
    
    # 确保ffmpeg目录存在
    if not os.path.exists("ffmpeg"):
        print("警告: ffmpeg目录不存在，请确保您已下载ffmpeg并放置在正确的位置")
    
    # 构建命令
    cmd = [
        "pyinstaller",
        "--name=YouTube视频下载器",
        "--icon=static/favicon.ico" if os.path.exists("static/favicon.ico") else "",
        "--add-data=templates;templates",
        "--add-data=static;static",
        "--add-data=ffmpeg;ffmpeg",
        "--hidden-import=uvicorn.logging",
        "--hidden-import=uvicorn.lifespan",
        "--hidden-import=uvicorn.lifespan.on",
        "--hidden-import=uvicorn.lifespan.off",
        "--hidden-import=uvicorn.protocols",
        "--hidden-import=uvicorn.protocols.http",
        "--hidden-import=uvicorn.protocols.http.auto",
        "--hidden-import=uvicorn.protocols.websockets",
        "--hidden-import=uvicorn.protocols.websockets.auto",
        "--hidden-import=uvicorn.protocols.websockets.websockets_impl",
        "--hidden-import=uvicorn.protocols.websockets.wsproto_impl",
        "--hidden-import=email.mime.text",
        "--hidden-import=email.mime.multipart",
        "--hidden-import=email.mime.message",
        "--hidden-import=email.mime.image",
        "--hidden-import=email.mime.audio",
        "--hidden-import=email.mime.base",
        "--hidden-import=email.mime.nonmultipart",
        "--hidden-import=email.encoders",
        # "--noconsole",  # 移除此选项以显示控制台窗口
        "--onefile",
        "main_patched.py"
    ]
    
    # 过滤掉空字符串
    cmd = [item for item in cmd if item]
    
    # 执行PyInstaller命令
    subprocess.check_call(cmd)
    
    print("可执行文件构建完成！")
    print(f"可执行文件位于: {os.path.abspath('dist/YouTube视频下载器.exe')}")

def create_shortcut():
    """创建桌面快捷方式"""
    if platform.system() != "Windows":
        print("只有Windows系统支持创建桌面快捷方式")
        return
    
    try:
        import winshell
        from win32com.client import Dispatch
        
        desktop = winshell.desktop()
        path = os.path.join(desktop, "YouTube视频下载器.lnk")
        target = os.path.abspath("dist/YouTube视频下载器.exe")
        
        shell = Dispatch('WScript.Shell')
        shortcut = shell.CreateShortCut(path)
        shortcut.Targetpath = target
        shortcut.WorkingDirectory = os.path.dirname(target)
        shortcut.IconLocation = target
        shortcut.save()
        
        print(f"桌面快捷方式已创建: {path}")
    except ImportError:
        print("创建快捷方式需要安装winshell和pywin32")
        choice = input("是否安装这些依赖项? (y/n): ")
        if choice.lower() == 'y':
            subprocess.check_call([sys.executable, "-m", "pip", "install", "winshell", "pywin32"])
            create_shortcut()
        else:
            print("跳过创建快捷方式")

def main():
    print("=" * 50)
    print("YouTube视频下载器打包工具 (带控制台窗口)")
    print("=" * 50)
    
    # 检查并安装依赖项
    check_requirements()
    
    # 构建可执行文件
    build_exe()
    
    # 询问是否创建桌面快捷方式
    if platform.system() == "Windows":
        choice = input("是否创建桌面快捷方式? (y/n): ")
        if choice.lower() == 'y':
            create_shortcut()
    
    print("\n打包过程完成!")
    print("您可以在dist目录中找到可执行文件")
    print("=" * 50)

if __name__ == "__main__":
    main() 