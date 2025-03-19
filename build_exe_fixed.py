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

def create_readme():
    """创建README文件"""
    readme_content = """===== YouTube视频下载器使用说明 =====

== 软件简介 ==

这是一个简单易用的YouTube视频下载工具，可以帮助您下载YouTube上的视频和音频。
软件采用网页界面操作，无需安装任何额外软件，打开即用。

== 使用方法 ==

1. 启动软件：双击"YouTube视频下载器.exe"文件启动程序
   - 启动后会自动弹出命令行窗口（显示后台日志）
   - 同时会自动在默认浏览器中打开操作界面

2. 下载视频：
   - 在网页界面中粘贴YouTube视频链接
   - 选择所需的视频质量和格式
   - 点击下载按钮开始下载
   - 可以在界面中查看下载进度和状态

3. 查找下载文件：
   - 下载完成的文件默认保存在软件同目录下的"videos"文件夹中
   - 也可以在下载前设置自定义保存路径

== 目录结构说明 ==

运行软件时，请确保以下文件和目录保持完整：
- YouTube视频下载器.exe：主程序文件
- videos文件夹：默认的下载存储位置（首次运行会自动创建）

== 常见问题解答 ==

1. 软件无法启动
   - 请确保您的电脑已安装必要的Windows组件
   - 如遇到杀毒软件拦截，请将软件添加到安全例外中
   - 确保以管理员身份运行该程序

2. 下载失败
   - 检查网络连接是否正常
   - 确认提供的YouTube链接是否有效
   - 查看命令行窗口中的错误日志了解详细原因

3. 视频格式问题
   - 不同格式的视频可能需要选择不同的下载选项

4. 浏览器未自动打开
   - 手动访问网址：http://127.0.0.1:8000
   - 确保您的电脑已设置默认浏览器

5. 程序启动时提示端口冲突
   - 程序会自动处理，如果发现已有实例在运行，将会直接打开浏览器访问现有实例
   - 如果持续出现问题，请检查任务管理器并关闭所有相关进程后重试

== 程序特性 ==

- 支持多种视频质量和格式下载
- 支持仅下载音频
- 下载历史记录查询
- 自定义下载目录
- 批量下载功能
- 显示下载进度和状态
- 防止多实例运行，避免端口冲突

== 注意事项 ==

- 本软件仅供个人学习和研究使用
- 请尊重内容创作者的版权，不要违反YouTube的使用条款
- 对于受版权保护的内容，需获得版权所有者的授权后才能下载使用
- 软件会在后台生成临时文件，占用一定磁盘空间

祝您使用愉快！
"""
    
    # 确保dist目录存在
    if not os.path.exists("dist"):
        os.makedirs("dist")
        
    # 创建README.txt
    with open("dist/README.txt", "w", encoding="utf-8") as f:
        f.write(readme_content)
    
    print("已创建README.txt文件")

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
    
    # 创建README文件
    create_readme()

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
    print("YouTube视频下载器打包工具 (修复版)")
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
    print("您可以在dist目录中找到可执行文件和README.txt")
    print("=" * 50)

if __name__ == "__main__":
    main() 