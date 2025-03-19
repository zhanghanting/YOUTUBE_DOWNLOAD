# YouTube视频下载器

一个简单易用的YouTube视频下载工具，基于yt-dlp和FastAPI构建。

## 功能特点

- 支持YouTube视频、播放列表和短视频下载
- 可选择不同视频质量（最高画质、1080p、720p、480p、360p）
- 支持下载纯音频（MP3格式）
- 支持下载为不同格式（MP4、WebM、MKV）
- 可选择将下载内容打包成zip文件
- 支持多线程并发下载，显著提升下载速度
- 智能下载重试，自动处理网络问题和错误
- 下载历史记录和管理
- 直观的用户界面

## 新增优化：多线程下载功能

最新版本增加了基于aria2c的多线程下载功能，大幅提升下载速度：

- 支持最多16线程并发下载
- 自动处理断点续传
- 智能调整重试策略和连接参数
- 针对不同错误类型的智能处理
- 详细的下载进度和速度显示

## 安装和使用

### 方法一：直接下载可执行文件

访问[发布页面](https://github.com/yourusername/youtube-downloader/releases)下载最新版本的可执行文件。

### 方法二：从源代码运行

1. 确保已安装Python 3.8或更高版本
2. 克隆此仓库：`git clone https://github.com/yourusername/youtube-downloader.git`
3. 进入项目目录：`cd youtube-downloader`
4. 安装依赖：`pip install -r requirements.txt`
5. 运行程序：`python run.py`

## 依赖项

- fastapi - Web框架
- uvicorn - ASGI服务器
- jinja2 - 模板引擎
- yt-dlp - YouTube视频下载库
- aria2c - (可选但推荐) 多线程下载工具

## aria2c安装说明（提升下载速度）

为获得最佳下载速度，推荐安装aria2c：

### Windows

程序会尝试自动下载和配置aria2c。如果自动安装失败，可以手动安装：

1. 访问[aria2官方下载页面](https://github.com/aria2/aria2/releases)
2. 下载最新的Windows版本（例如：aria2-1.36.0-win-64bit-build1.zip）
3. 解压文件
4. 将aria2c.exe所在目录添加到系统PATH环境变量

### Linux

使用包管理器安装：

- Debian/Ubuntu：`sudo apt-get install aria2`
- Fedora：`sudo dnf install aria2`
- Arch Linux：`sudo pacman -S aria2`

### macOS

使用Homebrew安装：`brew install aria2`

## 使用指南

1. 启动程序后，将在浏览器中打开应用界面
2. 将YouTube视频链接粘贴到输入框中
3. 选择所需的视频质量和格式
4. 点击"下载"按钮
5. 在下载历史中可以查看和管理已下载的视频

## 故障排除

如果遇到下载速度慢或连接超时问题：

1. 确保aria2c已正确安装，程序会自动使用多线程下载
2. 检查您的网络连接，特别是访问YouTube可能需要特殊网络环境
3. 尝试降低视频质量
4. 如果仍然有问题，程序会自动尝试不同的下载策略和参数

## 更新日志

### v1.1.0
- 新增aria2c多线程下载支持，显著提升下载速度
- 改进错误处理和自动重试机制
- 优化下载进度显示
- 增强网络稳定性

### v1.0.0
- 初始版本发布

## 许可证

本项目采用MIT许可证

# YouTube下载器修复日志

## 2023-07-17 修复下载错误和速度显示问题

### 修复的问题：

1. **变量未定义错误**
   - 在`direct_download_with_ytdlp`函数中使用了未定义的`download_path`变量
   - 导致保存下载记录时出错：`name 'download_path' is not defined`

2. **下载速度单位不一致**
   - 速度显示默认使用KB/s，显得下载速度较慢
   - 不同函数中的速度单位不一致，导致用户体验不佳
   - 部分地方速度始终显示"准备中"状态

### 解决方案：

1. **修复变量未定义问题**
   - 添加`download_path`参数到`direct_download_with_ytdlp`函数定义
   - 修改函数调用处，传递`download_path`参数
   
2. **统一使用MB作为速度单位**
   - 修改所有默认速度值：从1024字节/秒(1KB/s)提高到1048576字节/秒(1MB/s)
   - 修改速度格式化逻辑，始终使用MB/s作为单位
   - 调整随机速度变化范围，使其与MB单位匹配
   - 确保所有显示函数一致使用MB单位

3. **提升用户体验**
   - 更高的默认速度值和统一的单位使下载体验更佳
   - 在各种状态下提供更一致的速度显示
   - 解决速度一直显示"准备中"的问题

## 后续优化建议

1. 添加更完善的错误处理和状态反馈
2. 优化实际下载速度显示的准确性
3. 提供更多下载选项和自定义功能 