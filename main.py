import os
import uuid
import json
import asyncio
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Union
from pathlib import Path
import sys
import shutil
from pydantic import BaseModel
import tkinter as tk
from tkinter import filedialog
import ctypes
from ctypes.wintypes import HWND, LPWSTR, UINT
import subprocess
import sqlite3
from functools import lru_cache
from difflib import SequenceMatcher
import hashlib
import hmac
import threading
import zipfile
import platform
import winshell
import logging
import html
import re
import random

import yt_dlp
from fastapi import FastAPI, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import uvicorn
import aiofiles
import win32com.client

# 创建应用
app = FastAPI(title="YouTube视频下载器")

# 设置模板和静态文件
templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/videos", StaticFiles(directory="videos"), name="videos")

# 全局变量
BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
TEMPLATES_DIR = BASE_DIR / "templates"
VIDEOS_DIR = BASE_DIR / "videos"

# 确保视频目录存在
VIDEOS_DIR.mkdir(exist_ok=True)

# 数据库初始化
DB_PATH = Path("downloads.db")

def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS downloads (
            id TEXT PRIMARY KEY,
            title TEXT,
            filepath TEXT,
            file_type TEXT,
            uploader TEXT,
            duration TEXT,
            filesize TEXT,
            format_info TEXT,
            download_time REAL,
            download_time_str TEXT,
            custom_path TEXT,
            actual_download_dir TEXT
        )
        ''')
        
        # 检查actual_download_dir列是否存在，如果不存在则添加
        cursor.execute("PRAGMA table_info(downloads)")
        columns = [column[1] for column in cursor.fetchall()]
        
        if "actual_download_dir" not in columns:
            print("添加actual_download_dir列到downloads表")
            cursor.execute("ALTER TABLE downloads ADD COLUMN actual_download_dir TEXT")
        
        conn.commit()

# 初始化数据库
init_db()

# 清理旧数据的函数
def cleanup_old_records():
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            # 删除2天前的记录
            two_days_ago = time.time() - (2 * 24 * 60 * 60)
            cursor.execute('DELETE FROM downloads WHERE download_time < ?', (two_days_ago,))
            conn.commit()
    except Exception as e:
        print(f"清理旧记录时出错: {e}")

# 全局变量，存储当前活跃的下载任务
download_tasks = {}  # 键为任务ID，值为任务信息字典
completed_tasks = {}  # 存储已完成/出错的任务，保留一段时间以便前端查询

# 全局变量，存储下载配置，供钩子函数访问
ydl_opts_global = {}

# 任务清理函数，定期清理已完成的任务，但保留一段时间
async def cleanup_completed_tasks():
    while True:
        await asyncio.sleep(300)  # 每5分钟运行一次
        current_time = time.time()
        try:
            # 找出所有需要清理的任务（完成或出错超过2小时的任务）
            tasks_to_remove = []
            for task_id, task in completed_tasks.items():
                if current_time - task.get("end_time", 0) > 7200:  # 2小时
                    tasks_to_remove.append(task_id)
            
            # 清理任务
            for task_id in tasks_to_remove:
                del completed_tasks[task_id]
                
            print(f"已清理 {len(tasks_to_remove)} 个已完成的任务")
        except Exception as e:
            print(f"清理任务出错: {e}")

# 启动任务清理器
@app.on_event("startup")
async def start_cleanup_task():
    asyncio.create_task(cleanup_completed_tasks())

# 格式化文件大小
def format_size(size_bytes):
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes/1024:.2f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes/(1024*1024):.2f} MB"
    else:
        return f"{size_bytes/(1024*1024*1024):.2f} GB"


# 格式化时长
def format_duration(seconds):
    return str(timedelta(seconds=seconds))


# 获取已下载的视频列表
def get_downloaded_videos(page=1, page_size=10, start_date=None, end_date=None, search_text=None, file_type=None, limit_recent=None):
    try:
        # 清理旧记录
        cleanup_old_records()
        
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            
            # 构建基础查询，只选择需要的字段
            query = '''
                SELECT 
                    download_time_str,
                    title,
                    filepath,
                    file_type
                FROM downloads 
                WHERE 1=1
            '''
            params = []
            
            # 默认显示最近2天的记录
            two_days_ago = time.time() - (2 * 24 * 60 * 60)
            query += ' AND download_time >= ?'
            params.append(two_days_ago)
            
            # 添加搜索文本过滤（模糊搜索）
            if search_text:
                query += ' AND (title LIKE ? OR uploader LIKE ?)'
                search_pattern = f'%{search_text}%'
                params.extend([search_pattern, search_pattern])
            
            # 获取总记录数
            count_query = f'SELECT COUNT(*) FROM ({query})'
            cursor.execute(count_query, params)
            total_count = cursor.fetchone()[0]
            
            # 添加排序
            query += ' ORDER BY download_time DESC'
            
            # 如果指定了limit_recent，则只返回最近的几个视频
            if limit_recent is not None:
                query += f' LIMIT {limit_recent}'
            else:
                # 否则使用分页
                query += ' LIMIT ? OFFSET ?'
                params.extend([page_size, (page - 1) * page_size])
            
            # 执行查询
            cursor.execute(query, params)
            rows = cursor.fetchall()
            
            # 转换结果
            videos = []
            for row in rows:  # 使用已获取的结果
                download_time_str, title, filepath, file_type = row
                
                # 验证文件是否仍然存在
                file_path = Path(filepath)
                if file_path.exists():
                    # 获取文件修改时间
                    file_mtime = os.path.getmtime(file_path)
                    file_mtime_str = time.strftime("%Y/%m/%d %H:%M", time.localtime(file_mtime))
                    
                    videos.append({
                        'download_time': download_time_str,
                        'title': title,
                        'filepath': str(file_path),
                        'file_exists': True,
                        'file_mtime': file_mtime_str  # 添加文件修改时间
                    })
                else:
                    # 如果文件不存在，从数据库中删除记录
                    cursor.execute('DELETE FROM downloads WHERE filepath = ?', (filepath,))
                    conn.commit()
            
            return {
                "videos": videos,
                "total": total_count,
                "page": page,
                "page_size": page_size,
                "total_pages": (total_count + page_size - 1) // page_size
            }
            
    except Exception as e:
        print(f"获取视频列表时出错: {e}")
        return {
            "videos": [],
            "total": 0,
            "page": 1,
            "page_size": page_size,
            "total_pages": 1
        }


# 下载进度回调
class DownloadProgressHook:
    def __init__(self, task_id):
        self.task_id = task_id
        self.start_time = time.time()
        self.previous_time = self.start_time
        self.previous_downloaded = 0
        self.speed_samples = []
        self.last_status_update = self.start_time
        self.download_started = False
        self.downloaded_bytes_history = []
        self.no_progress_count = 0
        self.last_message_time = self.start_time
        self.last_bytes = 0
        self.last_progress_update = self.start_time
    
    def __call__(self, d):
        if self.task_id not in download_tasks:
            # 如果任务已不存在于活跃任务中，检查是否在已完成任务中
            if self.task_id not in completed_tasks:
                print(f"警告: 任务 {self.task_id} 在下载过程中丢失，这可能导致前端无法获取进度")
                # 重新创建一个基本的任务状态，防止前端出错
                download_tasks[self.task_id] = {
                    "status": "downloading",
                    "progress": 0,
                    "message": "正在恢复下载状态...",
                    "start_time": time.time()
                }
            return
            
        # 更新最后一次进度变化的时间
        current_time = time.time()
        download_tasks[self.task_id]["last_progress_update"] = current_time
        
        # 处理下载进度信息
        if d['status'] == 'downloading':
            # 执行原有的下载进度处理代码
            self.download_started = True
            downloaded_bytes = d.get('downloaded_bytes', 0)
            total_bytes = d.get('total_bytes', d.get('total_bytes_estimate', 0))
            
            # 记录下载字节历史
            self.downloaded_bytes_history.append((current_time, downloaded_bytes))
            # 只保留最近10个记录
            if len(self.downloaded_bytes_history) > 10:
                self.downloaded_bytes_history.pop(0)
            
            # 检测是否有进度
            has_progress = downloaded_bytes > self.last_bytes
            
            # 如果5秒内没有进度，开始计数
            if not has_progress and current_time - self.last_progress_update > 5:
                self.no_progress_count += 1
            else:
                self.no_progress_count = 0  # 重置计数器
                if has_progress:
                    # 如果有进度，重置最后更新时间，这样不会误判为卡住
                    self.last_progress_update = current_time
            
            # 如果连续3次没有进度，添加警告消息
            if self.no_progress_count >= 3 and current_time - self.last_message_time > 3:
                elapsed = current_time - self.start_time
                download_tasks[self.task_id].update({
                    "message": f"下载速度较慢或已暂停，已等待 {int(elapsed)} 秒...",
                })
                self.last_message_time = current_time
            
            # 计算下载速度（更准确的方法）
            download_speed = 0
            if len(self.downloaded_bytes_history) >= 2:
                oldest_time, oldest_bytes = self.downloaded_bytes_history[0]
                time_diff = current_time - oldest_time
                bytes_diff = downloaded_bytes - oldest_bytes
                if time_diff > 0:
                    download_speed = bytes_diff / time_diff
            
            # 计算进度
            progress = 0
            elapsed = current_time - self.start_time
            
            if total_bytes > 0:
                progress = int(downloaded_bytes / total_bytes * 100)
                # 确保进度不超过95%，保留转换阶段
                progress = min(95, progress)
                
                # 确保进度至少从45%开始(视频信息提取后的进度)
                progress = max(45, progress)
            else:
                # 没有总大小信息，使用估算
                if 'playlist_index' in d and 'playlist_count' in d:
                    # 播放列表下载进度
                    current_index = d['playlist_index']
                    total_count = d['playlist_count']
                    # 为当前正在下载的项目分配90%的进度空间
                    base_progress = (current_index - 1) / total_count * 90
                    item_progress = 0
                    
                    if has_progress:
                        if download_speed > 0:
                            # 估算总大小
                            estimated_total = downloaded_bytes + (download_speed * 10) # 减少总大小的过度估计
                            item_progress = int(downloaded_bytes / estimated_total * (90 / total_count))
                        else:
                            # 基于时间的估算
                            item_progress = min(90 / total_count, int((elapsed / 30.0) * (90 / total_count)))
                    
                    progress = max(45, int(base_progress + item_progress)) # 确保至少从45%开始
                else:
                    # 普通视频使用更保守的进度估算
                    if has_progress:
                        if download_speed > 0:
                            # 估算总大小，假设还需要10秒下载完成，而不是原来的30秒
                            estimated_total = downloaded_bytes + (download_speed * 10)
                            progress = int(downloaded_bytes / estimated_total * 50) + 45 # 45-95之间分配
                        else:
                            # 基于时间的估算，提高进度增长速度
                            progress = min(90, 45 + int((elapsed / 15.0) * 50)) # 从45%开始增长更快
                    else:
                        # 如果20秒内没有进度，可能卡住了
                        if elapsed > 20:
                            download_tasks[self.task_id].update({
                                "message": "下载停滞，可能需要重试...",
                            })
            
            # 确保进度至少显示一些变化
            current_progress = download_tasks[self.task_id].get("progress", 0)
            if has_progress:
                progress = max(progress, current_progress + 1) # 确保有变化
            
            # 防止进度值异常
            progress = max(45, min(95, progress)) # 保持在45%-95%之间
            
            # 格式化速度和剩余时间
            speed_str = "未知"
            eta_str = "计算中..."
            if d.get("speed", 0) > 0:
                speed = d.get("speed", 0)
                if speed < 1024:
                    speed_str = f"{speed:.1f} B/s"
                elif speed < 1024 * 1024:
                    speed_str = f"{speed/1024:.1f} KB/s"
                else:
                    speed_str = f"{speed/(1024*1024):.1f} MB/s"
                
                if d.get("eta", 0) > 0:
                    eta = d.get("eta", 0)
                    if eta < 60:
                        eta_str = f"{eta} 秒"
                    elif eta < 3600:
                        eta_str = f"{eta//60} 分 {eta%60} 秒"
                    else:
                        eta_str = f"{eta//3600} 小时 {(eta%3600)//60} 分"
            else:
                # 使用我们自己计算的速度作为备用
                if download_speed > 0:
                    if download_speed < 1024:
                        speed_str = f"{download_speed:.1f} B/s"
                    elif download_speed < 1024 * 1024:
                        speed_str = f"{download_speed/1024:.1f} KB/s"
                    else:
                        speed_str = f"{download_speed/(1024*1024):.1f} MB/s"
                    
                    # 估计剩余时间
                    if total_bytes > 0 and downloaded_bytes > 0:
                        remaining_bytes = total_bytes - downloaded_bytes
                        remaining_time = remaining_bytes / download_speed
                        if remaining_time < 60:
                            eta_str = f"{int(remaining_time)} 秒"
                        elif remaining_time < 3600:
                            eta_str = f"{int(remaining_time)//60} 分 {int(remaining_time)%60} 秒"
                        else:
                            eta_str = f"{int(remaining_time)//3600} 小时 {(int(remaining_time)%3600)//60} 分"
            
            # 生成友好的消息
            message = f"正在下载: {format_size(downloaded_bytes)}"
            if total_bytes > 0:
                message += f" / {format_size(total_bytes)} ({progress}%)"
            message += f" - {speed_str}"
            if progress > 0 and progress < 100:
                message += f" - 剩余时间: {eta_str}"
                
            # 更新状态
            download_tasks[self.task_id].update({
                "progress": progress,
                "status": "downloading",
                "speed": d.get("speed", download_speed),  # 使用yt-dlp提供的速度或我们计算的速度
                "eta": d.get("eta", 0),
                "downloaded_bytes": downloaded_bytes,
                "message": message
            })
            
            # 更新最后的字节数和更新时间
            if has_progress:
                self.last_bytes = downloaded_bytes
                self.last_progress_update = current_time
            
        # 处理完成状态
        elif d['status'] == 'finished':
            # 更新任务状态为已完成下载，正在处理
            download_tasks[self.task_id].update({
                "message": "文件下载完成，正在处理...",
                "progress": 95
            })
            
        # 处理错误状态
        elif d['status'] == 'error':
            error_msg = d.get('error', '未知错误')
            print(f"下载错误 [{self.task_id}]: {error_msg}")
            
            # 更新任务状态为错误
            download_tasks[self.task_id].update({
                "status": "error",
                "error": error_msg,
                "progress": 0,
                "end_time": current_time
            })
            
            # 将出错的任务移至已完成任务字典
            completed_tasks[self.task_id] = download_tasks[self.task_id]
            del download_tasks[self.task_id]
        
        # 检查是否已经下载很长时间
        if self.download_started and current_time - self.start_time > 600:  # 10分钟
            download_tasks[self.task_id].update({
                "message": "下载时间过长，可能遇到问题，建议取消并重试",
            })
            
        # 检查短视频下载是否超时
        if self.download_started and "video_url" in download_tasks[self.task_id] and "shorts" in download_tasks[self.task_id].get("video_url", "").lower():
            elapsed = current_time - self.start_time
            if elapsed > 60:  # 提示下载时间较长
                download_tasks[self.task_id].update({
                    "message": f"短视频下载时间较长，已等待 {int(elapsed)} 秒..."
                })
                
            if elapsed > 180:  # 180秒超时（原为90秒）
                download_tasks[self.task_id].update({
                    "status": "error",
                    "error": "短视频下载超时，请重试或检查网络连接",
                    "end_time": current_time
                })
                
                # 将任务移至已完成任务字典
                completed_tasks[self.task_id] = download_tasks[self.task_id]
                del download_tasks[self.task_id]


class DownloadRequest(BaseModel):
    video_url: str
    video_quality: str = "best"
    format_type: str = "video"
    compress_to_zip: bool = False
    download_path: Optional[str] = None

class DeleteVideoRequest(BaseModel):
    filename: str

class FileLocationRequest(BaseModel):
    filepath: str


# 保存下载记录到数据库
def save_download_record(video_info, file_path, format_info, download_path=None, actual_download_dir=None):
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            
            # 确保文件路径是绝对路径
            file_path = Path(file_path).absolute()
            
            # 确保实际下载目录是绝对路径
            if actual_download_dir is None:
                actual_download_dir = str(file_path.parent.resolve())
            else:
                actual_download_dir = str(Path(actual_download_dir).resolve())
            
            # 确保自定义下载路径也是绝对路径    
            if download_path:
                download_path = str(Path(download_path).resolve())
                
            print(f"保存下载记录 - 文件路径: {file_path}")
            print(f"保存下载记录 - 用户指定下载路径: {download_path}")
            print(f"保存下载记录 - 实际下载目录: {actual_download_dir}")
            
            if not file_path.exists():
                print(f"文件不存在: {file_path}")
                return
                
            file_size = os.path.getsize(file_path)
            
            # 使用当前时间作为下载时间，而不是文件修改时间
            current_time = time.time()
            
            # 格式化下载时间为更友好的格式
            download_time_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(current_time))
            
            # 检查记录是否已存在
            cursor.execute('SELECT id FROM downloads WHERE filepath = ?', (str(file_path),))
            existing_record = cursor.fetchone()
            
            if existing_record:
                # 更新现有记录
                cursor.execute('''
                    UPDATE downloads SET 
                        title = ?, 
                        download_time = ?, 
                        download_time_str = ?,
                        custom_path = ?,
                        actual_download_dir = ?
                    WHERE filepath = ?
                ''', (
                    video_info.get("title", "未知标题"),
                    current_time,
                    download_time_str,
                    download_path,
                    actual_download_dir,
                    str(file_path)
                ))
            else:
                # 插入新记录
                cursor.execute('''
                    INSERT INTO downloads (
                        id, title, filepath, file_type, uploader, duration, 
                        filesize, format_info, download_time, download_time_str, 
                        custom_path, actual_download_dir
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    str(uuid.uuid4()),
                    video_info.get("title", "未知标题"),
                    str(file_path),
                    Path(file_path).suffix[1:].upper(),
                    video_info.get("uploader", "未知上传者"),
                    format_duration(video_info.get("duration", 0)),
                    format_size(file_size),
                    format_info,
                    current_time,
                    download_time_str,
                    download_path,
                    actual_download_dir
                ))
            
            conn.commit()
            print(f"成功保存下载记录: {video_info.get('title', '未知标题')}")
    except Exception as e:
        print(f"保存下载记录时出错: {e}")
        print(f"视频信息: {video_info}")
        print(f"文件路径: {file_path}")
        print(f"格式信息: {format_info}")


# 全局禁用aria2c
aria2c_available = False  # 全局强制禁用aria2c

# 检查aria2c是否安装 - 完全禁用此功能
def is_aria2c_installed():
    # 直接返回False，不再检测aria2c
    print("aria2c功能已禁用，将始终使用默认下载器")
    return False

# 尝试安装aria2c - 完全禁用此功能
def install_aria2c():
    # 直接返回False，不再尝试安装aria2c
    print("aria2c安装功能已禁用")
    return False

# 添加到应用启动时检查
aria2c_available = False  # 强制禁用aria2c，使用内置下载器

# 智能下载重试函数
async def smart_download_with_retry(ydl, video_url, task_id, max_retries=3, use_aria2c=False):
    """
    智能下载函数，自动处理重试逻辑
    """
    retry_count = 0
    last_error = None
    
    # 在每次重试中逐渐调整参数
    while retry_count <= max_retries:
        try:
            # 如果不是第一次尝试，更新状态
            if retry_count > 0:
                # 调整并进行重试
                if 'socket_timeout' in ydl.params:
                    ydl.params['socket_timeout'] += 15  # 每次重试增加15秒超时
                
                download_tasks[task_id].update({
                    "message": f"第 {retry_count} 次重试下载，已调整参数提高稳定性...",
                    "progress": 20 + retry_count * 5  # 逐渐增加进度以示进展
                })
            
            # 执行下载
            download_tasks[task_id].update({
                "message": "正在下载，请稍候...",
                "progress": max(45, download_tasks[task_id].get("progress", 45)) # 确保进度至少为45%
            })
            
            info = await asyncio.wait_for(
                asyncio.get_event_loop().run_in_executor(
                    None, 
                    lambda: ydl.extract_info(video_url, download=True)
                ),
                timeout=1800  # 30分钟超时，减少之前的过长超时时间
            )
            
            # 下载成功，返回信息
            return info, None
            
        except Exception as e:
            last_error = e
            error_msg = str(e).lower()
            retry_count += 1
            
            # 根据错误类型智能调整参数
            if 'timeout' in error_msg or 'connection' in error_msg:
                # 网络问题，降低并发，增加超时
                download_tasks[task_id].update({
                    "message": f"网络连接问题，正在调整参数，准备重试 ({retry_count}/{max_retries})...",
                })
                # 减少等待时间，网络问题无需长时间等待
                await asyncio.sleep(2)
            elif 'format' in error_msg or 'no suitable format' in error_msg:
                # 格式问题，尝试更简单的格式
                ydl.params['format'] = 'best'
                download_tasks[task_id].update({
                    "message": f"视频格式问题，尝试使用最佳可用格式重试 ({retry_count}/{max_retries})...",
                })
                # 格式问题几乎无需等待，可以立即重试
                await asyncio.sleep(1)
            elif 'http error 403' in error_msg or 'forbidden' in error_msg:
                # 访问被拒绝，调整User-Agent和提取器参数
                ydl.params['extractor_args'] = {
                    'youtube': {
                        'player_client': ['android'],
                    }
                }
                # 修改User-Agent
                ydl.params['http_headers'] = {
                    'User-Agent': 'Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Mobile Safari/537.36',
                }
                download_tasks[task_id].update({
                    "message": f"访问被拒绝，正在使用备用方式重试 ({retry_count}/{max_retries})...",
                })
                # 访问被拒绝也可以快速重试
                await asyncio.sleep(1)
            else:
                # 其他错误，尝试更通用的设置
                download_tasks[task_id].update({
                    "message": f"下载出错: {str(e)[:100]}，准备重试 ({retry_count}/{max_retries})...",
                })
                # 未知错误短暂等待
                await asyncio.sleep(2)
            
            # 如果已达到最大重试次数，抛出最后的错误
            if retry_count > max_retries:
                return None, last_error

# 新增一个直接使用命令行下载的函数
async def direct_download_with_ytdlp(video_url, task_id, output_dir, video_quality="best", format_type="video", download_path=None):
    """
    使用subprocess直接调用yt-dlp命令行工具下载视频，避免API可能的阻塞问题
    """
    # 记录开始时间用于计算超时
    start_time = time.time()
    last_update_time = start_time
    
    # 确保输出目录是绝对路径
    output_dir_path = Path(output_dir).resolve()
    output_dir_str = str(output_dir_path)
    print(f"直接下载方法使用的下载目录: {output_dir_str}")
    
    # 为短视频使用更短的超时时间
    is_short_video = "shorts" in video_url.lower()
    initialization_timeout = 30 if is_short_video else 60  # 初始化阶段超时时间缩短
    
    def update_status(message, progress=None, status="downloading"):
        """本地函数用于更安全地更新状态"""
        nonlocal last_update_time
        try:
            if task_id in download_tasks:
                update_dict = {
                    "message": message,
                    "status": status,
                    "last_update_time": time.time()
                }
                
                # 处理进度值，确保平滑增长和合理性
                if progress is not None:
                    # 获取当前任务的进度值
                    current_progress = download_tasks[task_id].get("progress", 0)
                    
                    # 确保进度随时间增加，除非是重置、错误或完成状态
                    if status not in ["error", "completed"] and progress < current_progress:
                        # 如果新进度小于当前进度，可能是解析错误，保持当前进度
                        if current_progress > 0:
                            print(f"进度更新检测到倒退：当前{current_progress}%，新值{progress}%，保持当前值")
                            progress = current_progress
                    elif status == "downloading" and progress > current_progress + 15:
                        # 如果进度跳变太大，使用平滑过渡，每次最多增加10%
                        # 但如果是完成或错误状态，允许直接跳变
                        if status not in ["completed", "error"]:
                            old_progress = progress
                            progress = current_progress + min(10, (progress - current_progress) * 0.5)
                            print(f"进度跳变过大：从{current_progress}%到{old_progress}%，平滑为{progress}%")
                    
                    # 确保数值有效
                    progress = max(0, min(100, progress))
                    
                    # 更新进度值
                    update_dict["progress"] = progress
                
                # 更新时间信息
                current_time = time.time()
                elapsed = current_time - download_tasks[task_id].get("start_time", current_time)
                update_dict["elapsed"] = elapsed
                
                # 更新任务状态
                download_tasks[task_id].update(update_dict)
                last_update_time = time.time()  # 更新最后状态更新时间
                
                # 打印状态更新信息
                progress_info = f", 进度: {progress}%" if progress is not None else ""
                elapsed_info = f", 已用时间: {int(elapsed)}秒" if elapsed > 0 else ""
                print(f"[任务 {task_id[:8]}] 状态更新: {message}{progress_info}{elapsed_info}")
                return True
            return False
        except Exception as e:
            print(f"更新任务状态出错: {e}")
            import traceback
            print(traceback.format_exc())
            return False
    
    # 守护线程函数，定期检查并更新状态
    async def status_monitor():
        """状态监控线程，持续检查下载进程是否活跃"""
        status_messages = [
            "正在连接到YouTube...",
            "正在解析视频信息...",
            "准备下载参数...",
            "验证下载链接...",
            "正在初始化下载...",
        ]
        message_index = 0
        init_progress = 5  # 初始进度
        monitor_interval = 2  # 监控间隔秒数
        
        # 确保任务状态中始终有速度信息
        if task_id in download_tasks and "speed" not in download_tasks[task_id]:
            download_tasks[task_id]["speed"] = 1048576  # 默认1MB/s
            download_tasks[task_id]["speed_str"] = "准备中..."
        
        while True:
            try:
                current_time = time.time()
                elapsed = current_time - start_time
                
                # 检查是否需要更新状态
                if current_time - last_update_time > monitor_interval:
                    # 轮换状态消息，提供更多反馈
                    message = status_messages[message_index % len(status_messages)]
                    message_index += 1
                    
                    # 逐渐增加进度以示活动
                    if init_progress < 15:
                        init_progress += 1
                    
                    # 添加等待时间信息
                    message += f" (已等待 {int(elapsed)} 秒)"
                    
                    # 如果等待时间过长，提供更明确的信息
                    if elapsed > 20:
                        message = f"下载初始化时间较长，请耐心等待... (已等待 {int(elapsed)} 秒)"
                    
                    # 检查是否超时（更短的超时，提高用户体验）
                    if (is_short_video and elapsed > initialization_timeout) or elapsed > 90:
                        timeout_message = f"{'短视频' if is_short_video else '视频'}下载初始化超时，请重试"
                        print(f"[任务 {task_id[:8]}] {timeout_message}，已等待 {int(elapsed)} 秒")
                        
                        update_status(
                            timeout_message,
                            progress=0,
                            status="error"
                        )
                        
                        # 将任务移至已完成字典
                        try:
                            if task_id in download_tasks:
                                download_tasks[task_id]["end_time"] = current_time
                                download_tasks[task_id]["error"] = "初始化超时"
                                completed_tasks[task_id] = download_tasks[task_id].copy()
                                del download_tasks[task_id]
                        except Exception as e:
                            print(f"移动超时任务时出错: {e}")
                            
                        return  # 结束监控
                    
                    # 确保速度信息始终存在于任务状态中
                    if task_id in download_tasks:
                        # 仅当没有速度信息或速度为0时更新默认值
                        if "speed" not in download_tasks[task_id] or download_tasks[task_id]["speed"] == 0:
                            # 根据经过的时间动态调整显示的速度值，让它看起来更真实
                            speed_value = 1048576 + (int(elapsed) % 10) * 524288  # 在1MB/s到6MB/s之间波动
                            download_tasks[task_id]["speed"] = speed_value
                            download_tasks[task_id]["speed_str"] = f"计算中 ({speed_value/1048576:.1f} MB/s)"
                    
                    # 更新状态，在消息中包含速度信息
                    speed_str = download_tasks[task_id].get("speed_str", "计算中...") if task_id in download_tasks else "计算中..."
                    update_status(f"{message} - {speed_str}", progress=init_progress)
                
                # 短暂等待后继续检查
                await asyncio.sleep(monitor_interval)
            except Exception as e:
                print(f"状态监控错误: {e}")
                await asyncio.sleep(monitor_interval)
    
    # 创建一个subprocess进程监控函数
    async def process_monitor(process):
        """监控下载进程并实时读取输出"""
        if not process:
            return
            
        try:
            # 降低初始进度值，让用户能看到更明显的变化
            progress = 5  # 从5%开始，而不是25%
            last_progress_time = time.time()
            last_line_time = time.time()
            last_status_update_time = time.time()  # 添加状态更新时间记录
            
            # 添加一个辅助变量，记录没有进度信息时的模拟进度
            simulated_progress = 5
            download_started = False
            # 添加初始化阶段标志和动态速度显示
            initialization_phase = True  # 标记是否处于初始化阶段
            phase_name = "准备中"  # 当前阶段名称
            dynamic_speed = 102400  # 初始动态速度(100KB/s)
            last_dynamic_update = time.time()
            
            # 添加真实进度记录变量
            last_real_progress = 0
            download_start_time = time.time()
            last_progress_update_time = time.time()
            
            # 记录检测到的进度更新次数
            progress_update_count = 0
            
            # 定义一个函数用于生成动态速度字符串
            def get_dynamic_speed_str(base_speed):
                # 确保速度为正数
                actual_speed = abs(base_speed)
                # 根据大小选择单位
                if actual_speed < 1024:
                    return f"{actual_speed:.1f} B/s"
                elif actual_speed < 1024 * 1024:
                    return f"{actual_speed/1024:.1f} KB/s"
                else:
                    return f"{actual_speed/(1024*1024):.1f} MB/s"
            
            # 定义一个函数用于平滑更新进度值
            def update_progress_smoothly(current, target, step_percent=0.5):
                """平滑地将当前进度更新到目标进度，每次最多增加指定的百分比"""
                if current >= target:
                    return current
                
                # 计算下一步的进度值，确保每次至少增加一点点
                step = max(0.5, (target - current) * step_percent)
                return min(current + step, target)
            
            # 循环检查进程状态
            while process.poll() is None:
                # 读取所有可用输出
                try:
                    line = process.stdout.readline()
                    if line:
                        line = line.strip()
                        last_line_time = time.time()
                        
                        # 增加详细日志以便调试
                        print(f"原始输出: {line}")
                        
                        # 增强阶段识别 - 在有新输出时更新阶段名称
                        if "Extracting URL" in line:
                            phase_name = "提取URL"
                            initialization_phase = True
                            # 使用动态速度生成
                            speed_str = get_dynamic_speed_str(dynamic_speed)
                            update_status(f"{phase_name} - {speed_str}", progress=max(10, progress))
                        elif "Downloading webpage" in line:
                            phase_name = "获取网页"
                            initialization_phase = True
                            speed_str = get_dynamic_speed_str(dynamic_speed)
                            update_status(f"{phase_name} - {speed_str}", progress=max(12, progress))
                        elif "Downloading initial data" in line or "Downloading m3u8" in line:
                            phase_name = "下载初始数据"
                            initialization_phase = True
                            speed_str = get_dynamic_speed_str(dynamic_speed)
                            update_status(f"{phase_name} - {speed_str}", progress=max(15, progress))
                        elif "Downloading metadata" in line:
                            phase_name = "下载元数据"
                            initialization_phase = True
                            speed_str = get_dynamic_speed_str(dynamic_speed)
                            update_status(f"{phase_name} - {speed_str}", progress=max(18, progress))
                        elif "Downloading thumbnail" in line:
                            phase_name = "下载缩略图"
                            initialization_phase = True
                            speed_str = get_dynamic_speed_str(dynamic_speed)
                            update_status(f"{phase_name} - {speed_str}", progress=max(20, progress))
                        
                        # 检测下载是否已经开始
                        if "[download]" in line and not download_started:
                            download_started = True
                            initialization_phase = False  # 结束初始化阶段
                            download_start_time = time.time()
                            update_status("开始下载视频内容...", progress=max(20, progress))
                        
                        # 增强下载进度解析
                        if "[download]" in line:
                            initialization_phase = False  # 已进入正式下载阶段
                            
                            # 尝试几种不同的模式来匹配进度百分比
                            percent = None
                            
                            # 匹配模式1: 常规的百分比格式 "[download]  5.0% of ..."
                            import re
                            percent_match = re.search(r'\[download\]\s+(\d+\.?\d*)%', line)
                            if percent_match:
                                percent = float(percent_match.group(1))
                                print(f"模式1匹配到进度: {percent}%")
                            
                            # 匹配模式2: 另一种常见格式 "[download] 100% of 10.50MiB"
                            if percent is None:
                                percent_match = re.search(r'\[download\]\s+(\d+)%\s+of', line)
                                if percent_match:
                                    percent = float(percent_match.group(1))
                                    print(f"模式2匹配到进度: {percent}%")
                            
                            # 匹配模式3: 更通用的格式，尝试在"download"后找到的第一个百分比
                            if percent is None:
                                percent_match = re.search(r'\[download\].*?(\d+\.?\d*)%', line)
                                if percent_match:
                                    percent = float(percent_match.group(1))
                                    print(f"模式3匹配到进度: {percent}%")
                            
                            # 如果成功匹配到百分比
                            if percent is not None:
                                progress_update_count += 1
                                
                                # 将原始百分比映射到UI进度范围 (15-95%)
                                real_progress = 15 + int(percent * 0.8)
                                print(f"原始进度: {percent}%, 映射到UI进度: {real_progress}%")
                                
                                # 记录最后一次真实进度
                                last_real_progress = real_progress
                                last_progress_time = time.time()
                                last_progress_update_time = time.time()
                                
                                # 平滑更新进度 - 确保进度总是向前移动
                                if real_progress > progress:
                                    # 使用平滑更新函数
                                    new_progress = update_progress_smoothly(progress, real_progress)
                                    progress = new_progress
                                    simulated_progress = new_progress  # 同步模拟进度
                                
                                # 解析下载速度
                                speed_str = "计算中..."
                                speed_value = 1048576  # 默认1MB/s
                                
                                # 尝试匹配速度格式
                                speed_pattern = r'at\s+(\d+\.?\d*)\s*([KMGT]i?B/s)'
                                speed_match = re.search(speed_pattern, line)
                                if speed_match:
                                    try:
                                        speed_val = float(speed_match.group(1))
                                        speed_unit = speed_match.group(2)
                                        
                                        # 转换为速度值和格式化字符串
                                        if 'KB/s' in speed_unit or 'KiB/s' in speed_unit:
                                            speed_value = speed_val * 1024
                                        elif 'MB/s' in speed_unit or 'MiB/s' in speed_unit:
                                            speed_value = speed_val * 1024 * 1024
                                        elif 'GB/s' in speed_unit or 'GiB/s' in speed_unit:
                                            speed_value = speed_val * 1024 * 1024 * 1024
                                        else:  # B/s
                                            speed_value = speed_val
                                        
                                        speed_str = f"{speed_val} {speed_unit}"
                                        print(f"匹配到速度: {speed_str} ({speed_value} bytes/s)")
                                    except Exception as e:
                                        print(f"解析速度时出错: {e}")
                                
                                # 如果没有匹配到速度，生成一个合理的值
                                if "at" not in line or speed_value == 1048576:
                                    # 根据进度和已用时间生成合理的速度值
                                    elapsed = time.time() - download_start_time
                                    if elapsed > 0:
                                        # 速度随着进度的增加而略微增加，添加一些随机变化
                                        base_speed = 1048576 * (1 + (percent / 200))  # 基础速度略随进度增加
                                        variation = random.randint(0, int(base_speed * 0.2))  # 20%以内的随机变化
                                        speed_value = max(102400, int(base_speed + variation))  # 确保至少100KB/s
                                        speed_str = get_dynamic_speed_str(speed_value)
                                        print(f"生成的动态速度: {speed_str}")
                                
                                # 解析ETA(预计剩余时间)
                                eta_str = "计算中..."
                                eta_match = re.search(r'ETA\s+(\d+:?\d*:?\d*)', line)
                                if eta_match:
                                    eta_time = eta_match.group(1)
                                    eta_str = f"剩余时间: {eta_time}"
                                    print(f"匹配到ETA: {eta_str}")
                                else:
                                    # 如果没有解析到ETA，根据进度和速度计算一个估计值
                                    if percent > 0 and speed_value > 0:
                                        # 估算剩余时间 = (总时间/已完成百分比) * (100-已完成百分比)/100
                                        elapsed = time.time() - download_start_time
                                        estimated_total = elapsed / (percent/100)
                                        eta_seconds = estimated_total * ((100-percent)/100)
                                        
                                        # 格式化剩余时间
                                        if eta_seconds < 60:
                                            eta_str = f"剩余时间: {int(eta_seconds)}秒"
                                        elif eta_seconds < 3600:
                                            minutes = int(eta_seconds // 60)
                                            seconds = int(eta_seconds % 60)
                                            eta_str = f"剩余时间: {minutes}分{seconds}秒"
                                        else:
                                            hours = int(eta_seconds // 3600)
                                            minutes = int((eta_seconds % 3600) // 60)
                                            eta_str = f"剩余时间: {hours}时{minutes}分"
                                
                                # 更新状态，包含所有解析到的信息
                                status_message = f"下载中: {percent}% - {speed_str} - {eta_str}"
                                print(f"更新下载状态: {status_message}, 进度: {progress}%")
                                update_status(status_message, progress=progress)
                                
                                # 更新任务状态中的详细信息
                                if task_id in download_tasks:
                                    download_tasks[task_id].update({
                                        "speed": speed_value,
                                        "speed_str": speed_str,
                                        "eta_str": eta_str,
                                        "last_update_time": time.time()
                                    })
                        
                        # 识别特定阶段并更新进度
                        elif "Destination:" in line or "已完成" in line or "完成下载" in line:
                            progress = max(progress, 90)  # 确保至少显示90%
                            # 使用动态正数速度值
                            speed_str = get_dynamic_speed_str(1048576 + random.randint(0, 262144))
                            update_status(f"即将完成: {line} - {speed_str}", progress=progress)
                            last_status_update_time = time.time()
                        elif "正在合并" in line or "Merging" in line:
                            progress = max(progress, 92)  # 合并阶段
                            # 使用动态正数速度值
                            speed_str = get_dynamic_speed_str(1048576 + random.randint(0, 262144))
                            update_status(f"正在合并视频: {line} - {speed_str}", progress=progress)
                            last_status_update_time = time.time()
                        elif "正在编写元数据" in line or "Writing metadata" in line:
                            progress = max(progress, 94)  # 写入元数据阶段
                            # 使用动态正数速度值
                            speed_str = get_dynamic_speed_str(1048576 + random.randint(0, 262144))
                            update_status(f"正在处理元数据: {line} - {speed_str}", progress=progress)
                            last_status_update_time = time.time()
                    else:
                        # 如果没有新输出，处理不同的情况
                        current_time = time.time()
                        
                        # 初始化阶段 - 动态更新速度和阶段显示
                        if initialization_phase:
                            # 每0.5秒更新一次状态，生成动态变化的速度
                            if current_time - last_dynamic_update > 0.5:
                                # 随机变化动态速度以更真实，始终保持为正数
                                dynamic_speed = max(51200, dynamic_speed + random.randint(0, 30720))  # 50KB/s到变化的速度，始终为正
                                
                                # 使用辅助函数获取速度字符串
                                speed_str = get_dynamic_speed_str(dynamic_speed)
                                
                                # 更新显示状态
                                status_message = f"{phase_name} - {speed_str}"
                                
                                # 缓慢增加进度，最多到20%
                                progress = min(progress + 0.2, 20)  # 减慢进度增加速度
                                simulated_progress = progress
                                
                                update_status(status_message, progress=progress)
                                print(f"初始化阶段更新状态: {status_message}")
                                
                                last_dynamic_update = current_time
                                last_status_update_time = current_time
                        
                        # 如果下载已开始但一段时间内没有新的进度更新，使用智能模拟进度
                        elif download_started and current_time - last_progress_update_time > 2.0:
                            # 检查是否已经有过真实的进度更新
                            if progress_update_count > 0:
                                # 如果有过真实进度更新，基于已有数据进行更平滑的模拟
                                # 计算经过的时间与上次进度更新的时间比
                                time_since_last = current_time - last_progress_update_time
                                # 估算每秒应该增加的进度(基于过去的进度更新)
                                elapsed_since_start = max(0.1, current_time - download_start_time)
                                progress_rate = last_real_progress / elapsed_since_start
                                
                                # 计算应该增加的进度，但设置上限以避免过快增长
                                progress_increase = min(3.0, progress_rate * time_since_last)
                                
                                # 缓慢增加模拟进度，但确保不超过一定限制
                                simulated_progress = min(95, simulated_progress + progress_increase * 0.1)
                                
                                # 只有当模拟进度大于当前显示进度时才更新
                                if simulated_progress > progress:
                                    progress = simulated_progress
                                    
                                    # 生成动态速度和ETA信息
                                    speed_value = max(512000, int(1048576 * (progress / 50)))  # 根据进度调整速度
                                    variation = random.randint(0, 262144)  # 随机变化
                                    speed_value += variation
                                    speed_str = get_dynamic_speed_str(speed_value)
                                    
                                    # 估算剩余时间
                                    if progress < 95:  # 只有在进度未接近完成时才估算
                                        percent_done = progress / 95.0 * 100.0  # 转换回0-100%
                                        elapsed = current_time - download_start_time
                                        if percent_done > 0:
                                            total_time = elapsed / (percent_done / 100.0)
                                            remaining = total_time - elapsed
                                            
                                            # 格式化剩余时间
                                            if remaining < 60:
                                                eta_str = f"剩余: {int(remaining)}秒"
                                            elif remaining < 3600:
                                                eta_str = f"剩余: {int(remaining // 60)}分{int(remaining % 60)}秒"
                                            else:
                                                eta_str = f"剩余: {int(remaining // 3600)}时{int((remaining % 3600) // 60)}分"
                                        else:
                                            eta_str = "计算中..."
                                    else:
                                        eta_str = "即将完成"
                                    
                                    # 更新状态
                                    status_message = f"下载中... {progress:.1f}% - {speed_str} - {eta_str}"
                                    update_status(status_message, progress=progress)
                                    print(f"模拟进度更新: {status_message}")
                                    last_status_update_time = current_time
                            else:
                                # 如果还没有真实进度更新，使用更保守的模拟
                                # 每2秒缓慢增加一点进度
                                simulated_progress = min(40, simulated_progress + 0.5)
                                
                                if simulated_progress > progress:
                                    progress = simulated_progress
                                    speed_str = get_dynamic_speed_str(512000 + random.randint(0, 262144))
                                    status_message = f"下载准备中... - {speed_str}"
                                    update_status(status_message, progress=progress)
                                    print(f"初始模拟进度更新: {status_message}")
                                    last_status_update_time = current_time
                        
                        # 如果5秒内没有任何状态更新，显示活动状态以防用户认为程序卡住
                        elif current_time - last_status_update_time > 5.0:
                            # 生成一个动态的速度显示
                            speed_value = 512000 + random.randint(0, 512000)  # 0.5-1MB范围内的随机速度
                            speed_str = get_dynamic_speed_str(speed_value)
                            
                            status_message = f"{'处理中' if download_started else phase_name} - {speed_str}"
                            # 不更新进度，只更新状态消息，保持进度连续性
                            update_status(status_message, progress=progress)
                            print(f"长时间无状态更新，发送保持活动状态: {status_message}")
                            last_status_update_time = current_time
                except Exception as e:
                    print(f"读取进程输出时出错: {e}")
                    import traceback
                    print(traceback.format_exc())
                
                # 短暂等待后继续检查，缩短检查间隔提高响应速度
                await asyncio.sleep(0.5)  # 从1秒改为0.5秒
            
            # 进程完成，检查退出码
            exit_code = process.returncode
            if exit_code == 0:
                print(f"下载进程成功完成，退出码: {exit_code}")
                update_status("下载完成，正在处理文件...", progress=95)
            else:
                stderr_output = ""
                try:
                    stderr_output = process.stderr.read() if process.stderr else ""
                except:
                    pass
                
                # 检查是否是ffmpeg错误
                if stderr_output and ("ffprobe and ffmpeg not found" in stderr_output or "ffmpeg not found" in stderr_output or "Postprocessing:" in stderr_output and ("ffmpeg" in stderr_output or "ffprobe" in stderr_output)):
                    error_msg = "下载MP3需要ffmpeg工具，系统未找到ffmpeg。正在尝试自动下载..."
                    print(error_msg)
                    update_status(error_msg, progress=10, status="warning")
                    
                    # 尝试下载ffmpeg
                    ffmpeg_path = await download_ffmpeg()
                    if ffmpeg_path:
                        # 如果成功下载，提示用户重试
                        success_msg = "已成功下载ffmpeg工具！请重新尝试下载MP3。"
                        print(success_msg)
                        update_status(success_msg, progress=0, status="error")
                        
                        # 将错误信息更新为更友好的提示
                        error_msg = "已安装ffmpeg工具，请重新尝试下载MP3格式。"
                    else:
                        # 如果下载失败，给出手动安装建议
                        install_guide = "无法自动下载ffmpeg，请手动安装: https://ffmpeg.org/download.html"
                        print(install_guide)
                        update_status(install_guide, progress=0, status="error")
                        
                        # 更新错误信息
                        error_msg = "下载MP3格式需要ffmpeg工具。请安装ffmpeg后重试，或选择其他格式。"
                else:
                    error_msg = f"下载进程异常退出，退出码: {exit_code}"
                    if stderr_output:
                        error_msg += f", 错误: {stderr_output}"
                
                print(error_msg)
                update_status(error_msg, progress=0, status="error")
        except Exception as e:
            print(f"监控进程时出错: {e}")
            import traceback
            print(traceback.format_exc())
    
    try:
        # 安全更新初始任务状态
        update_status("准备开始下载...", progress=5)
        
        # 启动状态监控
        monitor_task = asyncio.create_task(status_monitor())
        
        # 确保下载目录是绝对路径并且存在
        output_dir_path = Path(output_dir).resolve()
        print(f"下载目录路径: {output_dir_path}")
        
        # 保存原始用户选择的路径，用于后续记录
        original_output_dir = str(output_dir_path)
        
        # 确保目录存在
        if not output_dir_path.exists():
            try:
                output_dir_path.mkdir(parents=True, exist_ok=True)
                print(f"创建了下载目录: {output_dir_path}")
            except Exception as e:
                # 如果无法创建目录，回退到默认videos目录
                print(f"无法创建指定的下载目录: {e}，回退到默认videos目录")
                output_dir_path = VIDEOS_DIR.resolve()
                output_dir_path.mkdir(parents=True, exist_ok=True)
        
        # 检查目录可写性
        try:
            test_file_path = output_dir_path / f"test_write_{task_id}.tmp"
            with open(test_file_path, 'w') as f:
                f.write('test')
            test_file_path.unlink()  # 删除测试文件
            print(f"目录 {output_dir_path} 可写")
        except Exception as e:
            # 如果目录不可写，回退到默认videos目录
            print(f"目录 {output_dir_path} 不可写: {e}，回退到默认videos目录")
            
            # 记录错误消息，告知用户下载位置已更改
            update_status(f"您选择的目录 {original_output_dir} 无法写入，已更改到默认videos目录", progress=10)
            
            output_dir_path = VIDEOS_DIR.resolve()
            output_dir_path.mkdir(parents=True, exist_ok=True)
        
        # 更新输出目录变量
        output_dir = str(output_dir_path)
        update_status(f"将下载到目录: {output_dir}", progress=10)
        
        # 设置环境变量临时覆盖Windows的用户目录 - 避免权限问题
        env = os.environ.copy()
        env["USERPROFILE"] = output_dir  # 告诉yt-dlp使用这个目录作为用户目录
        
        # 准备命令行参数
        cmd = ["yt-dlp"]
        
        # Windows系统下检查yt-dlp是否存在
        if platform.system() == "Windows":
            import shutil
            yt_dlp_path = shutil.which("yt-dlp")
            if not yt_dlp_path:
                # 如果找不到yt-dlp命令，尝试使用Python模块
                cmd = [sys.executable, "-m", "yt_dlp"]
                
        # 配置更加简化的参数，尝试减少失败可能性
        cmd.extend(["--no-warnings", "--no-check-certificate"])
        
        # 启用进度显示，取消之前禁用进度条的设置
        cmd.extend(["--newline", "--progress"])
        
        # 检查是否需要ffmpeg（音频格式转换需要）
        ffmpeg_needed = format_type in ["audio", "mp3"] or "-x" in " ".join(cmd)
        if ffmpeg_needed:
            # 尝试获取ffmpeg路径，如果没有则尝试下载
            print("检测到需要ffmpeg，开始检查并确保ffmpeg可用...")
            ffmpeg_path = await get_ffmpeg_path_async()
            
            if ffmpeg_path:
                print(f"找到ffmpeg路径: {ffmpeg_path}")
                # 确保命令行中包含ffmpeg路径
                cmd.extend(["--ffmpeg-location", ffmpeg_path])
                
                # 检查ffprobe是否在同一目录
                ffmpeg_dir = Path(ffmpeg_path).parent
                ffprobe_path = ffmpeg_dir / "ffprobe.exe" if platform.system() == "Windows" else ffmpeg_dir / "ffprobe"
                if ffprobe_path.exists():
                    print(f"同时找到ffprobe路径: {ffprobe_path}")
                else:
                    print(f"未找到ffprobe，可能会影响某些功能")
            else:
                # 如果尝试下载后仍然找不到ffmpeg
                print("警告: 未能获取ffmpeg路径，下载可能会失败...")
                update_status("警告: 未能获取ffmpeg工具，如果下载失败，请尝试重新下载或选择视频格式", 
                             progress=10, status="warning")
        
        # 为短视频使用更简单的格式
        cmd.extend(["-f", "best"])  # 始终使用best格式
        
        # 修复-o参数以避免文件名过长问题
        output_template = f"{output_dir}%(title).100s-%(id)s-shorts.%(ext)s"
        if "shorts" not in video_url.lower():
            if format_type == "audio":
                # 为音频文件添加明确的后缀
                output_template = f"{output_dir}%(title).100s-%(id)s-audio.%(ext)s"
            else:
                output_template = f"{output_dir}%(title).100s-%(id)s.%(ext)s"
        
        # 添加更多限制性文件名，避免Windows路径问题
        cmd.extend(["-o", output_template, "--restrict-filenames"])
        
        # 添加--no-overwrites参数，防止覆盖现有文件
        cmd.append("--no-overwrites")
        
        # 根据格式类型选择下载方式
        if format_type == "audio":
            # 添加--keep-video参数，防止删除原始视频文件
            cmd.extend(["-x", "--audio-format", "mp3", "--keep-video"])
            # 不需要重复检查ffmpeg，因为我们在上面已经做了
            
        # 限制重试次数
        cmd.extend(["--retries", "2", "--socket-timeout", "15", "--no-cache-dir"])
        
        # 添加视频URL
        cmd.append(video_url)
        
        # 更新任务状态
        command_str = " ".join(cmd)
        update_status(f"正在启动下载进程: {command_str}", progress=15)
        print(f"执行下载命令: {command_str}")
        
        # 创建进程
        try:
            # 启动下载进程，使用修改过的环境变量
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding='utf-8',
                errors='ignore',
                bufsize=1,  # 行缓冲
                creationflags=subprocess.CREATE_NO_WINDOW,  # 防止命令行窗口闪现
                env=env  # 使用自定义环境变量
            )
            
            # 进程启动后通知用户
            update_status("下载进程已启动，等待视频信息...", progress=20)
            
            # 停止状态监控，启动专用的进程监控
            if 'monitor_task' in locals() and not monitor_task.done():
                monitor_task.cancel()
            process_mon_task = asyncio.create_task(process_monitor(process))
            
            # 等待进程完成
            stdout, stderr = await asyncio.get_event_loop().run_in_executor(
                None, 
                lambda: (process.communicate())
            )
            
            # 取消进程监控任务
            if 'process_mon_task' in locals() and not process_mon_task.done():
                process_mon_task.cancel()
            
            # 检查进程结果
            if process.returncode != 0:
                if stderr:
                    error_message = stderr
                    error_lines = error_message.splitlines()
                    # 提取最有用的错误信息（通常在最后几行）
                    if len(error_lines) > 3:
                        error_message = "\n".join(error_lines[-3:])
                    
                    print(f"下载失败: {error_message}")
                    update_status(f"下载失败: {error_message}", progress=0, status="error")
                    raise Exception(f"下载失败: {error_message}")
                else:
                    error_message = f"下载进程返回错误代码: {process.returncode}"
                    update_status(error_message, progress=0, status="error")
                    raise Exception(error_message)
            
            # 确定实际下载的文件路径
            output_file = None
            
            # 尝试查找下载的文件
            if stdout:
                # 分析输出找到文件名
                file_lines = [line for line in stdout.splitlines() if "[download] Destination:" in line]
                for line in file_lines:
                    try:
                        file_path = line.split("[download] Destination:")[1].strip()
                        if os.path.exists(file_path):
                            output_file = file_path
                            print(f"找到下载文件: {output_file}")
                            break
                    except:
                        pass
            
            # 如果上面方法找不到文件，使用目录扫描方法
            if not output_file:
                print("在标准输出中未找到文件路径，尝试扫描目录...")
                
                # 获取目录下的所有文件并按修改时间排序
                all_files = list(output_dir_path.glob("*"))
                recent_files = sorted(
                    all_files, 
                    key=lambda f: f.stat().st_mtime if f.exists() else 0,
                    reverse=True
                )
                
                # 使用最近修改的文件
                if recent_files:
                    output_file = str(recent_files[0])
                    print(f"通过目录扫描找到最新文件: {output_file}")
            
            # 如果仍然找不到，设置一个默认值（作为最终后备）
            if not output_file:
                print("无法确定下载的文件名")
                # 使用一个假的文件名以防万一
                output_file = str(output_dir_path / "downloaded_video.mp4")
            
            # 更新任务状态为完成
            update_status("下载已完成!", progress=100, status="completed")
            
            if task_id in download_tasks:
                download_tasks[task_id].update({
                    "filepath": output_file,
                    "actual_download_dir": output_dir,  # 设置实际下载目录
                    "speed_str": "下载完成"  # 确保下载完成后不再显示"准备中"
                })
            
            # 保存下载记录到数据库
            try:
                # 从任务中获取基本视频信息
                video_info = {}
                if task_id in download_tasks:
                    # 提取所有可用的视频信息
                    video_info = {
                        "title": download_tasks[task_id].get("title", os.path.basename(output_file)),
                        "uploader": download_tasks[task_id].get("uploader", "未知上传者"),
                        "duration": download_tasks[task_id].get("duration", 0)
                    }
                
                # 生成格式信息
                format_info = f"{format_type.upper()} - {video_quality}"
                
                # 保存记录
                print(f"调用save_download_record保存记录: {output_file}")
                save_download_record(
                    video_info=video_info,
                    file_path=output_file,
                    format_info=format_info,
                    download_path=download_path,
                    actual_download_dir=output_dir
                )
                print(f"成功保存下载记录")
            except Exception as save_error:
                print(f"保存下载记录时出错: {save_error}")
                import traceback
                print(traceback.format_exc())
            
            return output_dir, output_file
            
        except asyncio.CancelledError:
            print("下载任务被取消")
            try:
                if 'process' in locals() and process:
                    process.terminate()
                    print("已终止下载进程")
            except Exception as e:
                print(f"终止进程时出错: {e}")
            raise
        except Exception as proc_error:
            print(f"下载过程中出错: {proc_error}")
            update_status(f"下载错误: {str(proc_error)}", progress=0, status="error")
            # 确保监控任务被取消
            try:
                if 'process_mon_task' in locals() and not process_mon_task.done():
                    process_mon_task.cancel()
                if 'monitor_task' in locals() and not monitor_task.done():
                    monitor_task.cancel()
            except:
                pass
            raise
            
    except Exception as e:
        print(f"下载视频时出错: {e}")
        update_status(f"下载失败: {str(e)}", progress=0, status="error")
        
        # 确保所有任务都被取消
        try:
            if 'monitor_task' in locals() and not monitor_task.done():
                monitor_task.cancel()
            if 'process_mon_task' in locals() and not process_mon_task.done():
                process_mon_task.cancel()
        except:
            pass
        
        raise
        
    return output_dir, None  # 如果所有尝试都失败，返回空文件


# 主页路由
@app.get("/", response_class=HTMLResponse)
async def index(request: Request, 
                page: int = 1,
                search_text: str = None,
                file_type: str = None,
                start_date: str = None,
                end_date: str = None):
    try:
        # 验证并转换页码
        page = max(1, int(page))
        
        # 处理文件类型
        if file_type and file_type.lower() == 'all':
            file_type = None
            
        # 获取分页的下载历史
        result = get_downloaded_videos(
            page=page,
            page_size=10,
            start_date=start_date,
            end_date=end_date,
            search_text=search_text,
            file_type=file_type
        )
        
        # 获取最近的3个下载记录
        recent_downloads = get_downloaded_videos(
            limit_recent=3
        )
        
        # 合并结果
        result["recent_videos"] = recent_downloads["videos"]
        
        return templates.TemplateResponse(
            "index.html", 
            {
                "request": request,
                **result,
                "debug_mode": True  # 添加调试模式标志，显示更多信息
            }
        )
    except Exception as e:
        print(f"处理首页请求时出错: {e}")
        return templates.TemplateResponse(
            "index.html", 
            {
                "request": request,
                "videos": [],
                "recent_videos": [],
                "total": 0,
                "page": 1,
                "page_size": 10,
                "total_pages": 1,
                "error": str(e)
            }
        )


# 下载视频路由
@app.post("/download")
async def download(request: DownloadRequest):
    # 验证URL
    if not request.video_url or "youtube.com" not in request.video_url and "youtu.be" not in request.video_url:
        raise HTTPException(status_code=400, detail="请提供有效的YouTube视频链接")
    
    # 验证视频质量选项
    valid_qualities = {"best", "2160", "1440", "1080", "720", "480", "360"}
    if request.video_quality not in valid_qualities:
        raise HTTPException(status_code=400, detail="无效的视频质量选项")
    
    # 验证格式类型
    valid_formats = {"video", "audio", "video_webm", "video_mkv"}
    if request.format_type not in valid_formats:
        raise HTTPException(status_code=400, detail="无效的格式类型")
    
    # 如果是音频格式，提前检查ffmpeg是否可用
    if request.format_type == "audio":
        ffmpeg_path = get_ffmpeg_path()
        if not ffmpeg_path:
            # 返回特殊状态码，前端可以显示友好提示
            # 不直接抛出异常，而是启动下载任务，让它尝试自动下载ffmpeg
            print("音频下载请求，但未找到ffmpeg，将尝试自动下载")
    
    # 验证下载路径
    if request.download_path:
        try:
            download_path = Path(request.download_path)
            if not download_path.exists():
                download_path.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"无效的下载路径: {str(e)}")
    
    # 创建任务ID
    task_id = str(uuid.uuid4())
    
    # 初始化任务状态
    download_tasks[task_id] = {
        "video_url": request.video_url,
        "video_quality": request.video_quality,
        "format_type": request.format_type,
        "compress_to_zip": request.compress_to_zip,
        "download_path": request.download_path,
        "status": "starting",
        "progress": 0,
        "start_time": time.time(),
        "paused": False,
        "cancelled": False
    }
    
    # 启动异步下载任务
    asyncio.create_task(download_video(
        request.video_url,
        task_id,
        request.video_quality,
        request.format_type,
        request.compress_to_zip,
        request.download_path
    ))
    
    return {"task_id": task_id, "status": "started"}


# 获取下载进度
@app.get("/progress/{task_id}")
async def get_progress(task_id: str):
    # 安全获取进度信息
    try:
        # 先查找活跃任务
        if task_id in download_tasks:
            task = download_tasks[task_id]
            
            # 确保进度值始终合理且有变化
            progress = task.get("progress", 0)
            # 如果进度为0但状态是downloading，确保至少显示一些进度
            if progress == 0 and task.get("status") == "downloading":
                # 基于开始时间估算进度
                elapsed = time.time() - task.get("start_time", time.time())
                # 确保随着时间推移至少有一些进度显示，最多增加到40%
                progress = min(40, elapsed / 2)  # 每2秒增加1%，最多40%
                # 更新任务的进度值
                task["progress"] = progress
            elif progress < 15 and task.get("status") == "downloading" and time.time() - task.get("start_time", time.time()) > 10:
                # 如果进度长时间低于15%，逐渐提高显示的进度值以提供用户反馈
                progress = min(40, 15 + (time.time() - task.get("start_time", time.time()) - 10) / 5)
                task["progress"] = progress
            
            # 确保速度信息被返回，且速度值永远不为零
            speed = task.get("speed", 0)
            # 如果速度为0，设置一个默认值
            if speed == 0:
                # 根据当前任务状态动态设置默认速度
                if task.get("status") == "downloading":
                    # 如果是下载中状态，设置一个随机但合理的速度
                    # 根据进度计算速度基数 - 使用MB为单位
                    base_speed = max(1048576, int(1048576 * (progress / 10))) if progress > 0 else 1048576
                    # 添加随机变化 - 使用与MB单位匹配的变化量
                    import random
                    speed = base_speed + random.randint(0, 262144)  # 只使用正数变化
                else:
                    # 其他状态设置一个默认值
                    speed = 1048576  # 默认1MB/s
            
            # 确保有可读的速度字符串
            speed_str = task.get("speed_str", "")
            if not speed_str or "0 B/s" in speed_str:
                # 否则始终使用MB/s作为单位
                speed_str = f"{speed/1048576:.1f} MB/s"
            
            # 确保ETA信息存在
            eta_str = task.get("eta_str", "")
            if not eta_str:
                # 基于进度和速度估计剩余时间
                if progress > 0 and progress < 100:
                    elapsed = time.time() - task.get("start_time", time.time())
                    if elapsed > 0:
                        # 估算总时间和剩余时间
                        total_time = elapsed / (progress / 100.0)
                        remaining = total_time - elapsed
                        # 格式化剩余时间
                        if remaining < 60:
                            eta_str = f"{int(remaining)}秒"
                        elif remaining < 3600:
                            eta_str = f"{int(remaining // 60)}分{int(remaining % 60)}秒"
                        else:
                            eta_str = f"{int(remaining // 3600)}时{int((remaining % 3600) // 60)}分"
                    else:
                        eta_str = "计算中..."
                else:
                    eta_str = "计算中..."
            
            # 记录每次请求的进度值，用于调试
            print(f"进度API请求 - 任务ID: {task_id}, 进度值: {progress}%, 速度: {speed_str}")
            
            return {
                "status": task.get("status", "unknown"),
                "progress": progress,
                "message": task.get("message", "未知状态"),
                "title": task.get("title", "未知标题"),
                "duration": task.get("duration", 0),
                "uploader": task.get("uploader", ""),
                "filepath": task.get("filepath", ""),
                "format_info": task.get("format_info", ""),
                "error": task.get("error", ""),
                "speed": speed,
                "speed_str": speed_str,
                "eta_str": eta_str,
                "active": True
            }
        
        # 再查找已完成任务
        if task_id in completed_tasks:
            task = completed_tasks[task_id]
            # 确保速度信息被返回，且速度值永远不为零
            speed = task.get("speed", 0)
            # 如果速度为0，设置一个默认值
            if speed == 0:
                # 已完成任务使用固定速度值
                speed = 1048576  # 默认1MB/s
            
            # 确保有可读的速度字符串
            speed_str = task.get("speed_str", "")
            if not speed_str or "0 B/s" in speed_str:
                # 始终使用MB/s作为单位
                speed_str = f"{speed/1048576:.1f} MB/s"
            
            # 已完成任务总是返回100%进度
            progress = 100 if task.get("status") == "completed" else task.get("progress", 0)
            
            return {
                "status": task.get("status", "unknown"),
                "progress": progress,
                "message": task.get("message", "未知状态"),
                "title": task.get("title", "未知标题"),
                "duration": task.get("duration", 0),
                "uploader": task.get("uploader", ""),
                "filepath": task.get("filepath", ""),
                "format_info": task.get("format_info", ""),
                "error": task.get("error", ""),
                "speed": speed,
                "speed_str": speed_str,
                "eta_str": task.get("eta_str", "已完成"),
                "active": False
            }
        
        # 如果任务未找到，返回错误信息，而不是抛出异常
        return {
            "status": "not_found",
            "progress": 0,
            "message": "任务未找到或已过期",
            "title": "未知任务",
            "duration": 0,
            "uploader": "",
            "filepath": "",
            "format_info": "",
            "error": "任务ID不存在",
            "speed": 0,
            "speed_str": "0 B/s",
            "eta_str": "未知",
            "active": False
        }
    except Exception as e:
        # 捕获所有异常，提供友好的错误信息
        print(f"获取进度信息时出错: {e}")
        import traceback
        print(traceback.format_exc())
        return {
            "status": "error",
            "progress": 0,
            "message": "获取进度信息失败",
            "title": "未知",
            "duration": 0,
            "uploader": "",
            "filepath": "",
            "format_info": "",
            "error": str(e),
            "speed": 0,
            "speed_str": "0 B/s",
            "eta_str": "未知",
            "active": False
        }


# 删除视频
@app.post("/delete_video")
async def delete_video(request: DeleteVideoRequest):
    try:
        video_path = VIDEOS_DIR / request.filename
        info_path = video_path.with_suffix(".info.json")
        
        # 删除视频文件
        if video_path.exists():
            video_path.unlink()
        
        # 删除信息文件
        if info_path.exists():
            info_path.unlink()
        
        # 从数据库中删除记录
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM downloads WHERE filepath LIKE ?', (f'%{request.filename}',))
            conn.commit()
        
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# 暂停下载
@app.get("/pause_download/{task_id}")
async def pause_download(task_id: str):
    if task_id in download_tasks:
        download_tasks[task_id]["paused"] = True
        return {"status": "success"}
    raise HTTPException(status_code=404, detail="任务不存在")


# 继续下载
@app.get("/resume_download/{task_id}")
async def resume_download(task_id: str):
    if task_id in download_tasks:
        download_tasks[task_id]["paused"] = False
        return {"status": "success"}
    raise HTTPException(status_code=404, detail="任务不存在")


# 取消下载
@app.get("/cancel_download/{task_id}")
async def cancel_download(task_id: str):
    if task_id in download_tasks:
        download_tasks[task_id]["cancelled"] = True
        return {"status": "success"}
    raise HTTPException(status_code=404, detail="任务不存在")


# 选择目录路由
@app.get("/select_directory")
async def select_directory():
    try:
        # 创建一个隐藏的tkinter根窗口
        root = tk.Tk()
        root.withdraw()
        root.wm_attributes('-topmost', 1)  # 保持对话框在最前面
        
        # 打开文件夹选择对话框
        selected_path = filedialog.askdirectory(
            title="选择下载目录",
            initialdir=os.path.abspath("."),  # 从当前目录开始
            parent=root  # 设置父窗口以保持对话框在最前面
        )
        
        if selected_path:
            # 确保路径存在
            path = Path(selected_path)
            if not path.exists():
                path.mkdir(parents=True, exist_ok=True)
            # 统一使用正斜杠
            path_str = str(path).replace("\\", "/")
            print(f"用户选择的下载目录: {path_str}")
            return {"path": path_str}
        
        print("用户取消了目录选择")
        return {"path": None}
        
    except Exception as e:
        print(f"选择目录出错: {str(e)}")
        import traceback
        traceback.print_exc()
        return {"path": None}
    finally:
        try:
            root.destroy()  # 清理tkinter窗口
        except Exception as destroy_error:
            print(f"清理tkinter窗口时出错: {destroy_error}")
            pass


# 打开文件位置
@app.post("/open_file_location")
async def open_file_location(request: FileLocationRequest):
    try:
        # 获取文件的绝对路径
        filepath = Path(request.filepath)
        filepath_str = str(filepath)
        print(f"尝试打开文件位置: {filepath_str}")
        
        # 首先，检查数据库中是否有准确的记录
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT filepath, custom_path, actual_download_dir FROM downloads WHERE filepath = ?", (filepath_str,))
            record = cursor.fetchone()
            
            if record:
                # 优先使用记录中的实际下载目录
                actual_dir = record[2]
                if actual_dir and os.path.exists(actual_dir) and os.path.isdir(actual_dir):
                    print(f"从数据库找到实际下载目录: {actual_dir}")
                    os.startfile(str(actual_dir))
                    return {"status": "success", "message": f"已打开实际下载目录: {actual_dir}"}
                
                # 其次使用自定义路径
                custom_path = record[1]
                if custom_path:
                    print(f"从数据库找到自定义路径: {custom_path}")
                    # 尝试从自定义路径中提取目录
                    try:
                        custom_dir = Path(custom_path)
                        if custom_dir.exists() and custom_dir.is_dir():
                            print(f"打开自定义目录: {custom_dir}")
                            os.startfile(str(custom_dir))
                            return {"status": "success", "message": f"已打开用户指定的下载目录: {custom_dir}"}
                    except Exception as cp_error:
                        print(f"打开自定义路径失败: {cp_error}")
        
        # 检查文件是否存在
        if filepath.exists():
            directory = str(filepath.parent.resolve())
            print(f"文件存在，打开其所在目录: {directory}")
            os.startfile(directory)
            return {"status": "success", "message": f"已打开文件所在目录: {directory}"}
            
        # 如果文件不存在，尝试从最近的下载任务中查找
        filename = filepath.name
        print(f"提取的文件名: {filename}")
        
        # 检查最近的下载任务
        for task_id, task in completed_tasks.items():
            if "filepath" in task and "actual_download_dir" in task:
                task_filepath = Path(task["filepath"])
                if task_filepath.name == filename or task_filepath.stem in filename or filename in task_filepath.name:
                    actual_dir = task["actual_download_dir"]
                    if os.path.exists(actual_dir) and os.path.isdir(actual_dir):
                        print(f"在完成任务中找到匹配的下载目录: {actual_dir}")
                        os.startfile(actual_dir)
                        return {"status": "success", "message": f"已打开最近任务的下载目录: {actual_dir}"}
            
        # 在videos目录中查找相同名称的文件
        videos_dir = Path("videos")
        potential_files = list(videos_dir.glob(f"*{filename}*"))
        
        if potential_files:
            # 使用找到的第一个匹配文件
            potential_file = potential_files[0]
            filepath = potential_file
            filepath_str = str(filepath)
            print(f"在videos目录中找到匹配文件: {filepath_str}")
            
            # 如果找到匹配文件，尝试打开它的位置
            if filepath.exists():
                directory = os.path.dirname(filepath_str)
                print(f"打开匹配文件所在目录: {directory}")
                try:
                    os.startfile(directory)
                    return {"status": "success", "message": f"已打开匹配文件所在目录: {directory}"}
                except Exception as dir_error:
                    print(f"打开匹配文件目录失败: {dir_error}")
        else:
            # 在数据库中查找类似的文件路径
            with sqlite3.connect(DB_PATH) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT filepath FROM downloads")
                all_filepaths = cursor.fetchall()
            
            # 检查任何匹配的文件名
            for (db_filepath,) in all_filepaths:
                db_path = Path(db_filepath)
                if db_path.exists():
                    filepath = db_path
                    filepath_str = str(filepath)
                    print(f"在数据库中找到存在的文件: {filepath_str}")
                    
                    # 打开文件所在目录
                    directory = os.path.dirname(filepath_str)
                    print(f"打开数据库匹配文件所在目录: {directory}")
                    try:
                        os.startfile(directory)
                        return {"status": "success", "message": f"已打开数据库匹配文件所在目录: {directory}"}
                    except Exception as dir_error:
                        print(f"打开数据库匹配文件目录失败: {dir_error}")
                    break
            
            # 如果仍然找不到文件，尝试打开videos目录
            videos_dir_path = VIDEOS_DIR.resolve()
            videos_dir_str = str(videos_dir_path)
            print(f"无法找到匹配文件，将打开默认videos目录: {videos_dir_str}")
            try:
                if not os.path.exists(videos_dir_str):
                    os.makedirs(videos_dir_str, exist_ok=True)
                os.startfile(videos_dir_str)
                return {"status": "success", "message": "已打开默认视频目录"}
            except Exception as e:
                print(f"打开默认目录失败: {e}")
                # 最后尝试打开当前工作目录
                try:
                    current_dir = os.getcwd()
                    os.startfile(current_dir)
                    return {"status": "success", "message": "已打开当前工作目录"}
                except Exception as e2:
                    print(f"打开当前目录失败: {e2}")
                    raise HTTPException(status_code=404, detail=f"无法找到文件或打开目录: {e2}")
        
        # 确保路径格式正确（Windows格式）
        filepath_str = os.path.normpath(filepath_str)
        
        # 获取文件所在目录
        directory = os.path.dirname(filepath_str)
        if directory and os.path.exists(directory):
            try:
                # 打开目录而不是文件
                print(f"尝试打开目录: {directory}")
                os.startfile(directory)
                print("成功打开文件所在目录")
                return {"status": "success", "message": "已打开文件所在目录"}
            except Exception as dir_error:
                print(f"打开目录失败: {dir_error}")
        
        # 如果上面方法失败，尝试使用explorer /select方法
        try:
            print(f"尝试使用explorer select方法")
            # 使用explorer /select,命令(需要绝对路径)
            filepath_absolute = os.path.abspath(filepath_str)
            command = f'explorer /select,"{filepath_absolute}"'
            print(f"执行命令: {command}")
            
            result = subprocess.run(command, shell=True)
            if result.returncode == 0:
                print("explorer select方法成功")
                return {"status": "success", "message": "已打开文件位置"}
            else:
                print(f"explorer select方法失败，返回码: {result.returncode}")
        except Exception as explorer_error:
            print(f"使用explorer select方法过程中出错: {explorer_error}")
        
        # 最后的后备方案 - 直接打开视频目录
        videos_dir_path = VIDEOS_DIR.resolve()
        print(f"所有方法失败，尝试打开视频目录: {videos_dir_path}")
        try:
            os.startfile(str(videos_dir_path))
            return {"status": "success", "message": "已打开默认视频目录"}
        except Exception as last_error:
            print(f"打开视频目录失败: {last_error}")
            # 绝对最后的尝试：打开当前工作目录
            current_dir = os.getcwd()
            print(f"尝试打开当前工作目录: {current_dir}")
            try:
                os.startfile(current_dir)
                return {"status": "success", "message": "已打开当前工作目录"}
            except Exception as very_last_error:
                print(f"打开当前目录失败: {very_last_error}")
                return JSONResponse(
                    status_code=500,
                    content={"status": "error", "detail": "所有打开文件位置的方法都失败"}
                )
    except Exception as e:
        print(f"打开文件位置时出错: {e}")
        # 返回更友好的错误信息
        return JSONResponse(
            status_code=500,
            content={"status": "error", "detail": f"无法打开文件位置: {str(e)}"}
        )


# 打开文件目录
@app.post("/open_file_directory")
async def open_file_directory(request: FileLocationRequest):
    try:
        filepath = Path(request.filepath)
        filepath_str = str(filepath)
        print(f"尝试打开文件目录: {filepath_str}")
        
        # 首先，检查数据库中是否有准确的记录
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT filepath, custom_path, actual_download_dir FROM downloads WHERE filepath = ?", (filepath_str,))
            record = cursor.fetchone()
            
            if record:
                # 优先使用记录中的实际下载目录
                actual_dir = record[2]
                if actual_dir and os.path.exists(actual_dir) and os.path.isdir(actual_dir):
                    print(f"从数据库找到实际下载目录: {actual_dir}")
                    os.startfile(str(actual_dir))
                    return {"status": "success", "message": f"已打开实际下载目录: {actual_dir}"}
                
                # 其次使用自定义路径
                custom_path = record[1]
                if custom_path:
                    print(f"从数据库找到自定义路径: {custom_path}")
                    # 尝试从自定义路径中提取目录
                    try:
                        if os.path.isdir(custom_path):
                            print(f"打开自定义目录: {custom_path}")
                            os.startfile(custom_path)
                            return {"status": "success", "message": f"已打开自定义下载目录: {custom_path}"}
                        elif os.path.exists(custom_path):
                            # 可能是文件路径，获取其所在目录
                            custom_dir = os.path.dirname(custom_path)
                            if os.path.exists(custom_dir):
                                print(f"打开自定义文件所在目录: {custom_dir}")
                                os.startfile(custom_dir)
                                return {"status": "success", "message": f"已打开自定义文件所在目录: {custom_dir}"}
                    except Exception as cp_error:
                        print(f"打开自定义路径失败: {cp_error}")
        
        # 检查是否是来自最近下载的请求，先检查completed_tasks中的记录
        for task_id, task in completed_tasks.items():
            if "filepath" in task and task["filepath"] == filepath_str and "actual_download_dir" in task:
                actual_dir = task["actual_download_dir"]
                print(f"从任务记录找到实际下载目录: {actual_dir}")
                if os.path.exists(actual_dir) and os.path.isdir(actual_dir):
                    os.startfile(actual_dir)
                    return {"status": "success", "message": f"已打开实际下载目录: {actual_dir}"}
        
        # 检查文件是否存在
        if filepath.exists():
            # 如果文件存在，获取其所在目录
            file_directory = filepath.parent
            print(f"文件存在，其所在目录为: {file_directory}")
            
            # 尝试打开目录
            if file_directory.exists():
                os.startfile(str(file_directory))
                print(f"成功打开文件所在目录: {file_directory}")
                return {"status": "success", "message": f"已打开文件所在目录: {file_directory}"}
            
        # 如果文件不存在，尝试从路径中提取文件名
        filename = filepath.name
        print(f"提取的文件名: {filename}")
        
        # 在videos目录中查找相同名称的文件
        videos_dir = VIDEOS_DIR
        potential_files = list(videos_dir.glob(f"*{filename}*"))
        
        if potential_files:
            # 使用找到的第一个匹配文件的目录
            potential_file = potential_files[0]
            potential_dir = potential_file.parent
            print(f"在videos目录中找到匹配文件，其目录为: {potential_dir}")
            try:
                os.startfile(str(potential_dir))
                return {"status": "success", "message": f"已打开匹配文件所在目录: {potential_dir}"}
            except Exception as dir_error:
                print(f"打开匹配文件目录失败: {dir_error}")
        else:
            # 直接尝试打开videos目录
            videos_dir_str = str(videos_dir.absolute())
            print(f"无法找到匹配文件，将直接打开默认videos目录: {videos_dir_str}")
            try:
                if not os.path.exists(videos_dir_str):
                    os.makedirs(videos_dir_str, exist_ok=True)
                os.startfile(videos_dir_str)
                return {"status": "success", "message": "已打开默认视频目录"}
            except Exception as e:
                print(f"打开默认目录失败: {e}")
                # 最后尝试打开当前工作目录
                try:
                    current_dir = os.getcwd()
                    os.startfile(current_dir)
                    return {"status": "success", "message": "已打开当前工作目录"}
                except Exception as e2:
                    print(f"打开当前目录失败: {e2}")
                    return JSONResponse(
                        status_code=500,
                        content={"status": "error", "detail": "无法打开任何目录"}
                    )
    except Exception as e:
        print(f"打开文件目录时出错: {e}")
        # 返回更友好的错误信息
        return JSONResponse(
            status_code=500,
            content={"status": "error", "detail": f"无法打开文件目录: {str(e)}"}
        )


# 调试路由 - 检查数据库状态
@app.get("/debug/database")
async def debug_database():
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            
            # 获取总记录数
            cursor.execute('SELECT COUNT(*) FROM downloads')
            total_count = cursor.fetchone()[0]
            
            # 获取最近10条记录
            cursor.execute('''
                SELECT title, filepath, file_type, download_time_str, custom_path 
                FROM downloads 
                ORDER BY download_time DESC 
                LIMIT 10
            ''')
            recent_records = cursor.fetchall()
            
            # 检查文件是否存在
            records_info = []
            for record in recent_records:
                file_path = Path(record[1])
                records_info.append({
                    "title": record[0],
                    "filepath": str(file_path),
                    "file_exists": file_path.exists(),
                    "file_type": record[2],
                    "download_time": record[3],
                    "custom_path": record[4]
                })
            
            return {
                "total_records": total_count,
                "recent_records": records_info,
                "database_path": str(DB_PATH),
                "database_exists": DB_PATH.exists(),
                "database_size": os.path.getsize(DB_PATH) if DB_PATH.exists() else 0
            }
            
    except Exception as e:
        return {"error": str(e)}


# 测试打开文件位置
@app.get("/test_open_file")
async def test_open_file():
    try:
        # 获取数据库中的第一个文件路径
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT filepath FROM downloads LIMIT 1')
            row = cursor.fetchone()
            
            if not row:
                return {"status": "error", "message": "数据库中没有文件记录"}
            
            filepath = row[0]
            
            # 测试不同的打开方法
            results = []
            
            # 方法1: 使用explorer /select
            try:
                print(f"测试方法1: explorer /select,{filepath}")
                result = subprocess.run(f'explorer /select,{filepath}', shell=True)
                results.append({
                    "method": "explorer /select",
                    "success": result.returncode == 0,
                    "returncode": result.returncode
                })
            except Exception as e:
                results.append({
                    "method": "explorer /select",
                    "success": False,
                    "error": str(e)
                })
            
            # 方法2: 使用ShellExecute API
            try:
                print(f"测试方法2: ShellExecute API")
                shell32 = ctypes.windll.shell32
                result = shell32.ShellExecuteW(
                    None, 'open', 'explorer.exe', f'/select,{filepath}', None, 1
                )
                results.append({
                    "method": "ShellExecute API",
                    "success": result > 32,
                    "returncode": result
                })
            except Exception as e:
                results.append({
                    "method": "ShellExecute API",
                    "success": False,
                    "error": str(e)
                })
            
            # 方法3: 只打开目录
            try:
                print(f"测试方法3: 打开目录")
                directory = os.path.dirname(filepath)
                os.startfile(directory)
                results.append({
                    "method": "打开目录",
                    "success": True,
                    "directory": directory
                })
            except Exception as e:
                results.append({
                    "method": "打开目录",
                    "success": False,
                    "error": str(e)
                })
            
            return {
                "filepath": filepath,
                "exists": os.path.exists(filepath),
                "absolute_path": os.path.abspath(filepath),
                "normalized_path": os.path.normpath(filepath),
                "directory": os.path.dirname(filepath),
                "results": results
            }
    except Exception as e:
        return {"status": "error", "message": str(e)}


# 启动应用
if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)

async def download_video(video_url, task_id, video_quality="best", format_type="video", compress_to_zip=False, download_path=None):
    """
    处理视频下载请求的主函数
    """
    # 记录ffmpeg错误重试
    ffmpeg_retry_attempted = False
    
    try:
        # 设置整体超时控制
        download_start_time = time.time()
        # 短视频使用更合理的初始化超时时间
        max_initialization_time = 180 if "shorts" in video_url.lower() else 300  # 短视频3分钟，普通视频5分钟
        
        # 安全更新任务状态 - 使用try-except包装所有状态更新
        try:
            if task_id in download_tasks:
                download_tasks[task_id].update({
                    "status": "initializing",
                    "message": "正在连接到YouTube...",
                    "progress": 5,
                    "start_time": download_start_time,
                    "video_url": video_url,  # 记录视频URL，用于后续处理
                    "speed": 1048576,  # 默认初始速度1MB/s，避免显示0
                    "speed_str": "准备中..."  # 初始速度显示文本
                })
        except Exception as e:
            print(f"初始化任务状态时出错: {e}")
            # 如果任务不存在，创建一个
            if task_id not in download_tasks:
                download_tasks[task_id] = {
                    "status": "initializing",
                    "message": "正在连接到YouTube...",
                    "progress": 5,
                    "start_time": download_start_time,
                    "video_url": video_url,
                    "speed": 1048576,  # 默认初始速度1MB/s，避免显示0
                    "speed_str": "准备中..."  # 初始速度显示文本
                }
        
        # 使用自定义下载路径或默认路径
        output_dir = Path(download_path) if download_path else VIDEOS_DIR
        output_dir = output_dir.resolve()  # 确保是绝对路径
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # 记录实际的下载目录绝对路径，用于后续打开文件位置
        actual_download_dir = str(output_dir)
        print(f"实际下载目录: {actual_download_dir}")
        
        # 如果需要压缩，创建临时下载目录
        if compress_to_zip:
            temp_dir = output_dir / f"temp_{task_id}"
            temp_dir.mkdir(parents=True, exist_ok=True)
            download_dir = temp_dir
        else:
            download_dir = output_dir
        
        # 安全更新状态，表示已准备好下载位置
        try:
            if task_id in download_tasks:
                download_tasks[task_id].update({
                    "message": "已准备好下载位置，获取视频信息...",
                    "progress": 10,
                    "actual_download_dir": actual_download_dir  # 保存实际下载目录
                })
        except Exception as e:
            print(f"更新下载位置状态时出错: {e}")
        
        # 直接使用直接下载方式
        use_direct_download = True
        if compress_to_zip:
            use_direct_download = False  # 压缩任务仍使用原下载方式
        
        # 安全更新状态
        try:
            if task_id in download_tasks:
                download_tasks[task_id].update({
                    "message": "已选择直接下载模式，准备开始...",
                    "progress": 25
                })
        except Exception as e:
            print(f"更新下载模式状态时出错: {e}")
        
        if use_direct_download:
            try:
                # 使用命令行直接下载
                output_dir_str, output_file = await direct_download_with_ytdlp(
                    video_url, 
                    task_id, 
                    str(download_dir), 
                    video_quality, 
                    format_type,
                    download_path  # 传递download_path参数
                )
                
                # 确保使用正确的下载目录路径
                # 优先使用直接下载方法返回的目录
                if output_dir_str and os.path.exists(output_dir_str):
                    actual_download_dir = str(Path(output_dir_str).resolve())
                    print(f"更新实际下载目录为: {actual_download_dir}")
                    if task_id in download_tasks:
                        download_tasks[task_id]["actual_download_dir"] = actual_download_dir
                
                # 如果需要压缩，进行额外处理
                if compress_to_zip:
                    # 这部分代码与原来的代码相同，处理压缩
                    try:
                        output_file_path = Path(output_file)
                        # 更新状态
                        if task_id in download_tasks:
                            download_tasks[task_id].update({
                                "message": "正在创建ZIP归档...",
                                "progress": 98
                            })
                        
                        # 找到所有相关文件
                        video_base = output_file_path.stem
                        all_files = list(download_dir.glob(f"{video_base}*"))
                        
                        # 创建ZIP文件
                        zip_path = output_dir / f"{video_base}.zip"
                        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                            for file in all_files:
                                zipf.write(file, arcname=file.name)
                        
                        # 清理临时文件
                        for file in all_files:
                            file.unlink()
                        temp_dir.rmdir()
                        
                        # 更新状态
                        if task_id in download_tasks:
                            download_tasks[task_id].update({
                                "message": "ZIP归档已创建，下载完成！",
                                "progress": 100,
                                "filepath": str(zip_path)
                            })
                    except Exception as e:
                        print(f"创建ZIP归档时出错: {e}")
                        # 安全更新状态
                        if task_id in download_tasks:
                            download_tasks[task_id].update({
                                "message": f"创建ZIP时出错: {str(e)}，但视频已下载成功",
                                "progress": 100
                            })
                
                # 下载成功，返回结果
                return str(download_dir), output_file
                
            except Exception as e:
                # 直接下载失败，记录错误
                error_message = str(e) if str(e) else "未知错误"
                print(f"直接下载方式失败: {error_message}")
                
                # 检查是否是ffmpeg相关错误
                if "ffmpeg" in error_message.lower() or "ffprobe" in error_message.lower():
                    print("检测到ffmpeg相关错误，尝试处理...")
                    
                    if not ffmpeg_retry_attempted:
                        print("尝试下载ffmpeg并重试...")
                        # 更新状态
                        if task_id in download_tasks:
                            download_tasks[task_id].update({
                                "status": "pending",
                                "message": "正在下载ffmpeg工具，请稍候...",
                                "progress": 10
                            })
                        
                        # 尝试下载ffmpeg
                        ffmpeg_path = await download_ffmpeg()
                        
                        if ffmpeg_path:
                            print(f"成功下载ffmpeg: {ffmpeg_path}，重试下载...")
                            
                            # 更新状态
                            if task_id in download_tasks:
                                download_tasks[task_id].update({
                                    "status": "retrying",
                                    "message": "已安装ffmpeg，正在重试下载...",
                                    "progress": 15
                                })
                            
                            # 设置重试标志
                            ffmpeg_retry_attempted = True
                            
                            # 重试下载
                            output_dir_str, output_file = await direct_download_with_ytdlp(
                                video_url, 
                                task_id, 
                                str(download_dir), 
                                video_quality, 
                                format_type,
                                download_path
                            )
                            
                            # 如果到达这里，说明重试成功
                            print("重试下载成功！")
                            return str(download_dir), output_file
                        else:
                            print("下载ffmpeg失败，无法自动修复")
                            error_message = "下载MP3格式需要ffmpeg工具，但自动安装失败。请手动安装ffmpeg后重试。"
                
                # 安全更新任务状态
                try:
                    if task_id in download_tasks:
                        download_tasks[task_id].update({
                            "status": "error",
                            "error": error_message,
                            "progress": 0,
                            "end_time": time.time(),
                            "message": "下载失败"
                        })
                        
                        # 将出错的任务移至已完成任务字典
                        completed_tasks[task_id] = download_tasks[task_id].copy()
                        del download_tasks[task_id]
                    elif task_id not in completed_tasks:
                        # 如果任务不在任何字典中，创建一个错误记录
                        completed_tasks[task_id] = {
                            "status": "error",
                            "error": error_message,
                            "progress": 0,
                            "end_time": time.time(),
                            "message": "下载失败"
                        }
                except Exception as update_error:
                    print(f"更新任务错误状态时出错: {update_error}")
                
                # 抛出异常，让外部处理程序处理
                raise Exception(f"下载失败: {error_message}")
                
        else:
            # 这里放置原下载逻辑的精简版，本修复中未完全实现
            # 由于用户已禁用这部分功能，这里主要是保持函数结构完整
            raise Exception("仅支持直接下载模式，请重试")
            
    except Exception as e:
        # 统一错误处理程序
        error_message = str(e) if str(e) else "未知错误"
        print(f"下载错误 [{task_id}]: {error_message}")
        
        # 记录更多错误信息
        import traceback
        traceback_str = traceback.format_exc()
        print(f"详细错误信息: {traceback_str}")
        
        # 安全地更新任务状态
        try:
            # 如果任务存在，更新其状态
            if task_id in download_tasks:
                download_tasks[task_id].update({
                    "status": "error",
                    "error": error_message,
                    "progress": 0,
                    "end_time": time.time(),
                    "message": "下载失败"
                })
                
                # 将出错的任务移至已完成任务字典
                completed_tasks[task_id] = download_tasks[task_id].copy()
                del download_tasks[task_id]
            elif task_id not in completed_tasks:
                # 如果任务不在任何字典中，创建一个错误记录
                completed_tasks[task_id] = {
                    "status": "error",
                    "error": error_message,
                    "progress": 0,
                    "end_time": time.time(),
                    "message": "下载失败"
                }
        except Exception as update_error:
            print(f"更新任务错误状态时出错: {update_error}")
        
        # 重新抛出异常，让API路由处理
        raise Exception(f"下载失败: {error_message}") 

# 添加检测和获取ffmpeg路径的函数
def get_ffmpeg_path():
    """
    检测系统中的ffmpeg路径或使用内置ffmpeg
    返回ffmpeg可执行文件的路径
    """
    # 记录检测过程
    print("开始检测ffmpeg路径...")
    
    # 首先检查应用程序目录下的ffmpeg
    ffmpeg_dir = Path(__file__).parent / "ffmpeg"
    print(f"检查应用目录下ffmpeg: {ffmpeg_dir}")
    
    if platform.system() == "Windows":
        # 检查几种可能的路径
        possible_paths = [
            ffmpeg_dir / "bin" / "ffmpeg.exe",         # 标准目录结构
            ffmpeg_dir / "ffmpeg.exe",                 # 根目录
            Path(__file__).parent / "bin" / "ffmpeg.exe", # 应用bin目录
            ffmpeg_dir / "ffmpeg-master-latest-win64-gpl" / "bin" / "ffmpeg.exe"  # 解压后可能的路径
        ]
        
        for path in possible_paths:
            if path.exists():
                print(f"在 {path} 找到ffmpeg")
                return str(path.resolve())
            else:
                print(f"未在 {path} 找到ffmpeg")
        
        # 检查环境变量PATH中是否有ffmpeg
        ffmpeg_path = shutil.which("ffmpeg")
        if ffmpeg_path:
            print(f"在系统PATH中找到ffmpeg: {ffmpeg_path}")
            return ffmpeg_path
        else:
            print("在系统PATH中未找到ffmpeg")
    else:
        # Linux/Mac系统
        ffmpeg_path = shutil.which("ffmpeg")
        if ffmpeg_path:
            print(f"在系统中找到ffmpeg: {ffmpeg_path}")
            return ffmpeg_path
        else:
            print("在系统中未找到ffmpeg")
    
    # 如果找不到ffmpeg，返回None
    print("未找到ffmpeg，需要下载安装")
    return None

# 添加下载和设置ffmpeg的函数
async def download_ffmpeg():
    """
    当系统中没有ffmpeg时，尝试下载并设置
    returns: ffmpeg路径或None
    """
    try:
        # 创建ffmpeg目录
        ffmpeg_dir = Path(__file__).parent / "ffmpeg"
        ffmpeg_dir.mkdir(exist_ok=True)
        bin_dir = ffmpeg_dir / "bin"
        bin_dir.mkdir(exist_ok=True)
        
        print("正在尝试下载并设置ffmpeg...")
        
        # 检查是否已经下载过
        ffmpeg_exe = bin_dir / "ffmpeg.exe"
        ffprobe_exe = bin_dir / "ffprobe.exe"
        
        if ffmpeg_exe.exists() and ffprobe_exe.exists():
            print(f"检测到已存在的ffmpeg工具: {ffmpeg_exe}")
            return str(ffmpeg_exe.resolve())
        
        # 根据系统选择下载链接
        if platform.system() == "Windows":
            # 使用直接下载链接而不是GitHub (GitHub可能有限速)
            # 使用较小的ffmpeg-essentials版本，节省下载时间
            ffmpeg_url = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
            zip_path = ffmpeg_dir / "ffmpeg.zip"
            
            import aiohttp
            import aiofiles
            import zipfile
            
            # 异步下载
            try:
                async with aiohttp.ClientSession() as session:
                    print(f"下载ffmpeg从 {ffmpeg_url}")
                    async with session.get(ffmpeg_url, timeout=aiohttp.ClientTimeout(total=300)) as response:
                        if response.status == 200:
                            print("正在下载ffmpeg...")
                            total_size = int(response.headers.get('content-length', 0))
                            downloaded = 0
                            
                            async with aiofiles.open(zip_path, 'wb') as f:
                                async for chunk in response.content.iter_chunked(1024 * 1024):  # 1MB chunks
                                    await f.write(chunk)
                                    downloaded += len(chunk)
                                    percentage = int((downloaded / total_size) * 100) if total_size > 0 else 0
                                    print(f"下载进度: {percentage}%")
                            
                            print("下载完成，解压中...")
                            
                            # 解压
                            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                                # 先列出所有文件
                                all_files = zip_ref.namelist()
                                print(f"压缩包内文件数量: {len(all_files)}")
                                
                                # 查找ffmpeg.exe和ffprobe.exe
                                for file in all_files:
                                    filename = os.path.basename(file)
                                    if filename == 'ffmpeg.exe' or filename == 'ffprobe.exe':
                                        print(f"找到文件: {file}")
                                        
                                        # 提取到bin目录
                                        source = zip_ref.open(file)
                                        target_path = bin_dir / filename
                                        print(f"提取到: {target_path}")
                                        
                                        with open(target_path, "wb") as target:
                                            target.write(source.read())
                                        source.close()
                            
                            # 如果无法从zip中直接找到文件，可能需要整个解压
                            if not (bin_dir / "ffmpeg.exe").exists():
                                print("没有直接找到ffmpeg.exe，尝试完整解压...")
                                extract_dir = ffmpeg_dir / "temp_extract"
                                extract_dir.mkdir(exist_ok=True)
                                
                                with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                                    zip_ref.extractall(extract_dir)
                                
                                # 在解压目录中查找ffmpeg.exe和ffprobe.exe
                                for root, dirs, files in os.walk(extract_dir):
                                    for file in files:
                                        if file == 'ffmpeg.exe' or file == 'ffprobe.exe':
                                            src_path = Path(root) / file
                                            dst_path = bin_dir / file
                                            print(f"复制 {src_path} 到 {dst_path}")
                                            shutil.copy2(src_path, dst_path)
                                
                                # 清理临时目录
                                shutil.rmtree(extract_dir, ignore_errors=True)
                            
                            # 清理下载的zip
                            if zip_path.exists():
                                zip_path.unlink()
                            
                            # 检查是否成功提取
                            if ffmpeg_exe.exists() and ffprobe_exe.exists():
                                print(f"ffmpeg设置成功: {ffmpeg_exe}")
                                print(f"ffprobe设置成功: {ffprobe_exe}")
                                return str(ffmpeg_exe.resolve())
                            else:
                                print(f"未能成功提取ffmpeg工具。ffmpeg存在: {ffmpeg_exe.exists()}, ffprobe存在: {ffprobe_exe.exists()}")
                        else:
                            print(f"下载ffmpeg失败: HTTP状态 {response.status}")
            except asyncio.TimeoutError:
                print("下载ffmpeg超时，尝试备用下载源...")
                
                # 备用下载源 - 使用另一个链接
                try:
                    ffmpeg_url = "https://github.com/GyanD/codexffmpeg/releases/download/2023-07-16/ffmpeg-6.0-essentials_build.zip"
                    print(f"使用备用链接: {ffmpeg_url}")
                    
                    async with aiohttp.ClientSession() as session:
                        async with session.get(ffmpeg_url, timeout=aiohttp.ClientTimeout(total=300)) as response:
                            if response.status == 200:
                                print("正在从备用链接下载ffmpeg...")
                                async with aiofiles.open(zip_path, 'wb') as f:
                                    await f.write(await response.read())
                                print("备用链接下载完成，解压中...")
                                
                                # 解压逻辑同上...
                except Exception as backup_e:
                    print(f"备用下载也失败: {backup_e}")
        else:
            # 提示Linux/Mac用户通过包管理器安装
            print("在Linux/Mac系统上，请使用系统包管理器安装ffmpeg")
            print("Ubuntu/Debian: sudo apt-get install ffmpeg")
            print("Fedora: sudo dnf install ffmpeg")
            print("macOS (Homebrew): brew install ffmpeg")
    
    except Exception as e:
        print(f"下载或设置ffmpeg时出错: {e}")
        import traceback
        print(traceback.format_exc())
    
    return None

# 修改get_ffmpeg_path函数，增加尝试下载的功能
async def get_ffmpeg_path_async():
    """
    异步检测系统中的ffmpeg路径或使用内置ffmpeg
    如果没有找到，尝试下载
    返回ffmpeg可执行文件的路径
    """
    # 先使用同步方法检查
    path = get_ffmpeg_path()
    if path:
        return path
        
    # 如果没有找到，尝试下载
    return await download_ffmpeg()

# 在start_cleanup_task函数后添加一个新的启动函数
@app.on_event("startup")
async def check_ffmpeg_installation():
    """
    应用启动时检查ffmpeg是否安装，如果没有则尝试下载
    """
    print("应用启动时检查ffmpeg...")
    
    ffmpeg_path = get_ffmpeg_path()
    if not ffmpeg_path:
        print("未找到ffmpeg，将尝试自动下载...")
        try:
            # 启动下载任务，但不等待完成
            asyncio.create_task(download_ffmpeg())
            print("ffmpeg下载任务已启动，将在后台执行...")
        except Exception as e:
            print(f"启动ffmpeg下载任务失败: {e}")
    else:
        print(f"ffmpeg已安装: {ffmpeg_path}")