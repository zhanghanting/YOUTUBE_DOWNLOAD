import uvicorn

if __name__ == "__main__":
    print("启动YouTube视频下载器...")
    print("请在浏览器中访问: http://localhost:8000")
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True) 