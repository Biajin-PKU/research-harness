#!/bin/bash

# Research Hub Web Dashboard 启动脚本

echo "========================================"
echo "启动 Research Hub Web Dashboard"
echo "========================================"

# 检查并安装依赖
if ! python3 -c "import flask" 2>/dev/null; then
    echo "正在安装 Flask..."
    pip install flask
fi

# 启动应用
echo ""
echo "🌐 服务器地址: http://localhost:5000"
echo "📱 如果你在Mac上通过SSH连接，请在Mac浏览器访问:"
echo "   http://<服务器IP>:5000"
echo ""
echo "按 Ctrl+C 停止服务器"
echo "========================================"

python3 app.py
