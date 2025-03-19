# 修补后的启动文件，用于解决日志配置问题并显示控制台窗口
import os
import sys
import socket
import time
import webbrowser
from http.client import HTTPConnection
import subprocess

# 设置环境变量
os.environ["PYTHONUNBUFFERED"] = "1"
os.environ["PYTHONIOENCODING"] = "utf-8"

# 单实例检测函数
def is_port_in_use(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('127.0.0.1', port)) == 0

def check_server_running(port):
    """检查服务器是否已在运行并响应"""
    try:
        conn = HTTPConnection('127.0.0.1', port, timeout=1)
        conn.request('HEAD', '/')
        response = conn.getresponse()
        conn.close()
        return response.status < 400
    except:
        return False

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

# 主程序
if __name__ == "__main__":
    # 定义端口号
    PORT = 8000
    
    # 检查是否已有实例在运行
    if is_port_in_use(PORT):
        print("="*50)
        print("检测到YouTube视频下载器已在运行")
        print(f"正在打开浏览器访问: http://127.0.0.1:{PORT}")
        print("="*50)
        
        # 尝试等待服务器完全启动
        for _ in range(3):
            if check_server_running(PORT):
                break
            time.sleep(1)
        
        # 打开浏览器访问已运行的实例
        webbrowser.open(f"http://127.0.0.1:{PORT}")
        
        # 退出当前实例
        sys.exit(0)
    
    # 没有运行中的实例，继续启动新实例
    print("="*50)
    print("YouTube视频下载器已启动")
    print(f"请在浏览器中访问: http://127.0.0.1:{PORT}")
    print("="*50)
    
    # 导入原始main模块
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import main
    
    # 启动浏览器
    webbrowser.open(f"http://127.0.0.1:{PORT}")
    
    # 如果main模块有app对象，则启动它
    if hasattr(main, "app"):
        uvicorn.run(
            "main:app", 
            host="127.0.0.1", 
            port=PORT, 
            log_level="info",
            log_config=None
        )
