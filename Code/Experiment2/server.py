"""
实验二：双机通信实验（C/S模式） - 服务器端
功能：作为服务器接收客户端请求，处理后返回响应
"""

import serial
import serial.tools.list_ports
import threading
import time
import sys

class SerialServer:
    def __init__(self):
        self.ser = None
        self.running = False
        self.recv_thread = None
        self.debug = True

    def _log(self, direction, payload):
        """调试输出，带时间戳和方向"""
        if not self.debug:
            return
        ts = time.strftime('%H:%M:%S')
        if isinstance(payload, bytes):
            safe = payload.decode('utf-8', errors='ignore')
        else:
            safe = "==" + str(payload) + "=="
        print(f"[DEBUG {ts}] {direction}: {safe}")
        
    def get_available_ports(self):
        """获取可用串口列表"""
        ports = serial.tools.list_ports.comports()
        return [p.device for p in ports]
    
    def open_port(self, port_name, baudrate=9600):
        """打开串口"""
        try:
            self.ser = serial.Serial(
                port=port_name,
                baudrate=baudrate,
                bytesize=serial.EIGHTBITS,
                stopbits=serial.STOPBITS_ONE,
                parity=serial.PARITY_NONE,
                timeout=1
            )
            print(f"[服务器] 串口 {port_name} 打开成功")
            print(f"         波特率: {baudrate}, 数据位: 8, 停止位: 1, 校验: 无")
            return True
        except serial.SerialException as e:
            print(f"[错误] 无法打开串口: {e}")
            return False
    
    def close_port(self):
        """关闭串口"""
        self.running = False
        if self.recv_thread:
            self.recv_thread.join(timeout=2)
        if self.ser and self.ser.is_open:
            self.ser.close()
            print("[服务器] 串口已关闭")
    
    def send_data(self, data):
        """发送数据"""
        if self.ser and self.ser.is_open:
            try:
                if isinstance(data, str):
                    data = data.encode('utf-8')
                self.ser.write(data)
                self._log('SEND', data)
                return True
            except Exception as e:
                print(f"[错误] 发送失败: {e}")
                return False
        return False
    
    def process_request(self, request):
        """处理客户端请求"""
        request_str = request.decode('utf-8', errors='ignore').strip()
        
        # 根据不同的请求类型返回不同的响应
        if request_str.upper().startswith("HELLO"):
            response = "SERVER: Hello, Client! Connection established."
        elif request_str.upper().startswith("TIME"):
            response = f"SERVER: Current time is {time.strftime('%Y-%m-%d %H:%M:%S')}"
        elif request_str.upper().startswith("ECHO"):
            # Echo 服务，返回客户端发送的内容
            echo_content = request_str[5:].strip()
            response = f"SERVER: ECHO - {echo_content}"
        elif request_str.upper().startswith("CALC"):
            # 简单计算服务
            try:
                expr = request_str[5:].strip()
                result = eval(expr)
                response = f"SERVER: CALC - {expr} = {result}"
            except:
                response = "SERVER: ERROR - Invalid calculation expression"
        elif request_str.upper().startswith("QUIT"):
            response = "SERVER: Goodbye!"
            return response, True  # 返回退出标志
        else:
            response = f"SERVER: Unknown command '{request_str}'. Available: HELLO, TIME, ECHO <msg>, CALC <expr>, QUIT"
        
        return response, False
    
    def receive_worker(self):
        """接收数据的工作线程"""
        print("[服务器] 开始监听客户端请求...")
        while self.running:
            try:
                if self.ser.in_waiting > 0:
                    data = self.ser.readline()
                    if data:
                        self._log('RECV', data)
                        
                        # 处理请求并返回响应
                        response, should_quit = self.process_request(data)
                        time.sleep(0.1)  # 短暂延迟，确保客户端准备好接收
                        self.send_data(response + "\n")
                        
                        if should_quit:
                            print("[服务器] 收到退出请求，准备关闭...")
                            self.running = False
                            break
                else:
                    time.sleep(0.01)
            except Exception as e:
                if self.running:
                    print(f"[错误] 接收数据异常: {e}")
                    time.sleep(0.1)
    
    def start_server(self):
        """启动服务器"""
        if not self.ser or not self.ser.is_open:
            print("[错误] 请先打开串口")
            return False
        
        self.running = True
        self.recv_thread = threading.Thread(target=self.receive_worker, daemon=True)
        self.recv_thread.start()
        print("[服务器] 服务已启动，等待客户端连接...")
        return True


def main():
    server = SerialServer()
    
    # 显示可用串口
    ports = server.get_available_ports()
    print("=" * 60)
    print("实验二：双机通信实验 - 服务器端（C/S模式）")
    print("=" * 60)
    print("\n可用串口:")
    for i, port in enumerate(ports, 1):
        print(f"  {i}. {port}")
    
    # 选择串口
    while True:
        try:
            choice = input("\n请选择服务器串口编号: ").strip()
            port_idx = int(choice) - 1
            if 0 <= port_idx < len(ports):
                selected_port = ports[port_idx]
                break
            else:
                print("[错误] 无效的编号，请重新选择")
        except ValueError:
            print("[错误] 请输入数字")
    
    # 设置波特率
    while True:
        try:
            baudrate = input("请输入波特率 (默认9600): ").strip()
            baudrate = int(baudrate) if baudrate else 9600
            break
        except ValueError:
            print("[错误] 请输入有效的波特率")
    
    # 打开串口
    if not server.open_port(selected_port, baudrate):
        return
    
    # 启动服务器
    if not server.start_server():
        server.close_port()
        return
    
    print("\n" + "=" * 60)
    print("服务器命令说明:")
    print("  - 自动处理客户端请求")
    print("  - 支持的客户端命令: HELLO, TIME, ECHO <msg>, CALC <expr>, QUIT")
    print("  - 输入 'quit' 退出服务器")
    print("=" * 60 + "\n")
    
    # 主循环
    try:
        while server.running:
            cmd = input()
            if cmd.strip().lower() == 'quit':
                print("[服务器] 正在关闭服务器...")
                break
            time.sleep(0.1)
    except KeyboardInterrupt:
        print("\n[服务器] 检测到中断信号")
    finally:
        server.close_port()
        print("[服务器] 已退出")


if __name__ == "__main__":
    main()
