# 计算机网络课程设计：多机通信网络系统 (Computer Network Project)

本项目为一个基于串行通信接口 (Serial Port) 构建的多机通信网络系统。该项目由浅入深，从基础的单机串口测试出发，逐步实现了一套包含物理层连接、数据链路层转发、网络层动态路由以及运输层可靠传输的完整协议栈，并最终提供了 Ping 和 Traceroute 等网络管理工具。

目前，本项目正在开发基于 **React** 框架的可视化前端界面，以提供更直观的网络拓扑监控和数据包跟踪功能。

## 实验概览

本项目共包含六个循序渐进的实验模块：

| 实验编号 | 名称 | 核心功能 | 对应目录 |
| :--- | :--- | :--- | :--- |
| **Experiment 1** | 单机串口实验 | 自环测试、基准性能测试、长文本传输 | `Code/Experiment1/` |
| **Experiment 2** | 双机通信实验 | C/S 架构简单的请求/响应模型 | `Code/Experiment2/` |
| **Experiment 3** | 简单拓扑通信 | 链路层转发、树状拓扑 (Star Topology) | `Code/Experiment3/` |
| **Experiment 4** | 动态路由网络 | **网络层 DV 算法**、网状拓扑、自动邻居发现 | `Code/Experiment4/` |
| **Experiment 5** | 可靠传输协议 | **运输层停等协议**、CRC校验、超时重传 | `Code/Experiment5/` |
| **Experiment 6** | 网络管理工具 | **ICMP协议实现**、Ping、Traceroute、TTL处理 | `Code/Experiment6/` |

## 开发环境与依赖

- **操作系统**: Windows (推荐), Linux, macOS
- **编程语言**: Python 3.11+
- **核心依赖**:
  ```bash
  pip install pyserial
  ```

## Web 可视化界面 (New!)

为了更直观地展示网络路由收敛过程及数据包流向，现在已支持基于 React 的可视化控制台。

### 1. 启动后端 (Backend)
该后端服务作为一个中间件，桥接底层的网络节点逻辑与 WebSocket 接口。

```bash
cd Web-Interface/Backend
pip install -r requirements.txt
python main.py
```

### 2. 启动前端 (Frontend)
前端界面提供了网络拓扑图实时绘制和命令控制台。

```bash
cd Web-Interface/Frontend
npm install
npm run dev
```

### 3. 使用方法
1.  浏览器打开 `http://localhost:5173`。
2.  在右侧控制台输入 CLI 命令（如 `ping B`），操作方式与命令行版本一致。
3.  左侧将实时展示当前节点的路由表拓扑。

*   **技术栈**:
    *   **Frontend**: React.js, Vite, React-Force-Graph
    *   **Backend**: Python FastAPI (WebSocket)

## 快速开始

1.  **克隆项目**:
    ```bash
    git clone <your-repo-url>
    cd Project-Network
    ```
2.  **环境配置**:
    确保已安装 Python 和 `pyserial`。
3.  **运行实验**:
    进入相应实验目录查看具体的 `README.md` 指引。例如运行最新的网络节点：
    ```bash
    python Code/Experiment6/network_app.py
    ```

## 目录结构
```text
Project-Network/
├── README.md               # 项目主文档
├── Report/                 # 实验报告 LaTeX 源码
├── Code/
│   ├── Experiment1/        # 基础串口测试
│   ├── Experiment2/        # 双机 C/S 通信
│   ├── Experiment3/        # 简单转发 (链路层)
│   ├── Experiment4/        # 动态路由 (网络层 DV算法)
│   ├── Experiment5/        # 可靠传输 (运输层)
│   └── Experiment6/        # 网络管理 (Ping/Traceroute)
└── README_pic/             # 文档图片资源
```