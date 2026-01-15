"""
实验二：双机通信实验（C/S模式） - 客户端
功能：作为客户端向服务器发送请求，并接收响应
"""

import serial
import serial.tools.list_ports
import threading
import time
import sys

class SerialClient:
    def __init__(self):
        self.ser = None
        self.receiving = False
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
            print(f"[客户端] 串口 {port_name} 打开成功")
            print(f"         波特率: {baudrate}, 数据位: 8, 停止位: 1, 校验: 无")
            
            # 自动启动接收线程
            self.receiving = True
            self.recv_thread = threading.Thread(target=self._receive_worker, daemon=True)
            self.recv_thread.start()
            return True
        except serial.SerialException as e:
            print(f"[错误] 无法打开串口: {e}")
            return False
    
    def close_port(self):
        """关闭串口"""
        self.receiving = False
        if self.recv_thread:
            self.recv_thread.join(timeout=2)
        if self.ser and self.ser.is_open:
            self.ser.close()
            print("[客户端] 串口已关闭")
    
    def send_request(self, request):
        """发送请求到服务器"""
        if self.ser and self.ser.is_open:
            try:
                if isinstance(request, str):
                    request = request.encode('utf-8')
                # 确保请求以换行符结尾，便于服务器读取
                if not request.endswith(b'\n'):
                    request += b'\n'
                self.ser.write(request)
                self._log('SEND', request.strip(b'\n'))
                return True
            except Exception as e:
                print(f"[错误] 发送失败: {e}")
                return False
        return False
    
    def _receive_worker(self):
        """接收数据的工作线程"""
        while self.receiving:
            try:
                if self.ser.in_waiting > 0:
                    data = self.ser.readline()
                    if data:
                        self._log('RECV', data)
                else:
                    time.sleep(0.01)
            except Exception as e:
                if self.receiving:
                    print(f"[错误] 接收数据异常: {e}")
                    time.sleep(0.1)


def main():
    client = SerialClient()
    
    # 显示可用串口
    ports = client.get_available_ports()
    print("=" * 60)
    print("实验二：双机通信实验 - 客户端（C/S模式）")
    print("=" * 60)
    print("\n可用串口:")
    for i, port in enumerate(ports, 1):
        print(f"  {i}. {port}")
    
    # 选择串口
    while True:
        try:
            choice = input("\n请选择客户端串口编号: ").strip()
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
    if not client.open_port(selected_port, baudrate):
        return
    
    print("\n" + "=" * 60)
    print("客户端命令说明:")
    print("  HELLO          - 向服务器发送问候")
    print("  TIME           - 请求服务器当前时间")
    print("  ECHO <msg>     - 回显消息")
    print("  CALC <expr>    - 计算表达式，例如: CALC 2+3*4")
    print("  QUIT           - 断开连接并退出")
    print("  help           - 显示帮助信息")
    print("=" * 60 + "\n")
    
    # 发送初始连接请求
    print("[客户端] 正在连接服务器...")
    time.sleep(0.5)  # 等待服务器就绪
    client.send_request("HELLO")
    
    # 主循环 - 发送请求
    try:
        while True:
            request = input("\n请输入命令: ").strip()
            
            if not request:
                continue
            
            if request.lower() == 'help':
                print("\n可用命令:")
                print("  HELLO          - 向服务器发送问候")
                print("  TIME           - 请求服务器当前时间")
                print("  ECHO <msg>     - 回显消息")
                print("  CALC <expr>    - 计算表达式")
                print("  QUIT           - 断开连接并退出")
                continue
            
            # 发送请求
            client.send_request(request)
            
            # 如果是退出命令，等待响应后退出
            if request.upper() == "QUIT":
                time.sleep(0.5)  # 等待接收服务器的响应
                break
            
            time.sleep(0.1)  # 短暂延迟
            
    except KeyboardInterrupt:
        print("\n[客户端] 检测到中断信号")
    finally:
        client.close_port()
        print("[客户端] 已退出")


if __name__ == "__main__":
    main()
