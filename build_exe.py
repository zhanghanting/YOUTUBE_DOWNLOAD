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
    subprocess.check_call([sys.executable, "-m", "pip", "install", "fastapi", "uvicorn", "yt-dlp", "jinja2"])
    
    print("依赖项安装完成！")

def build_exe():
    """构建可执行文件"""
    print("开始构建可执行文件...")
    
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
        "--noconsole",
        "--onefile",
        "main.py"
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
    print("YouTube视频下载器打包工具")
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