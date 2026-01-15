"""
实验三：简单拓扑的多机通信实验（链路层） - 叶子节点 (Leaf)
功能：作为树形拓扑的叶子节点，连接到根节点
核心逻辑：
1. 仅通过一个串口连接到根节点
2. 发送数据时封装帧头 (SRC|DST|DATA)
3. 接收数据时检查 DST 是否匹配本机ID
"""

import serial
import serial.tools.list_ports
import threading
import time
import sys

# 数据帧分隔符
SEPARATOR = '|'

class LeafNode:
    def __init__(self):
        self.ser = None
        self.running = False
        self.my_id = None
        self.recv_thread = None

    def get_available_ports(self):
        return [p.device for p in serial.tools.list_ports.comports()]

    def connect(self, port, baudrate, my_id):
        try:
            self.ser = serial.Serial(port, baudrate, timeout=0.1)
            self.my_id = my_id
            self.running = True
            
            # 启动接收线程
            self.recv_thread = threading.Thread(target=self._receive_loop)
            self.recv_thread.daemon = True
            self.recv_thread.start()
            
            print(f"成功连接至 {port}，本机ID设置为: {self.my_id}")
            return True
        except Exception as e:
            print(f"连接失败: {e}")
            return False

    def _receive_loop(self):
        print(f"开始监听来自端口的数据...")
        while self.running and self.ser and self.ser.is_open:
            try:
                if self.ser.in_waiting:
                    line = self.ser.readline().decode('utf-8', errors='ignore').strip()
                    if line:
                        self._process_frame(line)
                time.sleep(0.01)
            except Exception as e:
                print(f"[错误] 接收线程异常: {e}")
                break

    def _process_frame(self, raw_data):
        """
        处理接收到的帧
        格式: SRC_ID|DST_ID|PAYLOAD
        """
        parts = raw_data.split(SEPARATOR, 2)
        if len(parts) != 3:
            # 格式不符，可能是干扰数据或者非标准帧
            # 也可以选择打印出来调试
            # print(f"[Debug] 忽略非标准帧: {raw_data}")
            return

        src_id, dst_id, payload = parts

        if dst_id == self.my_id:
            print(f"\n[收到消息] 来自 {src_id}: {payload}")
            print(f"> ", end="", flush=True) # 恢复提示符
        elif dst_id == "BROADCAST": # 可选：支持广播
             print(f"\n[收到广播] 来自 {src_id}: {payload}")
             print(f"> ", end="", flush=True)
        else:
            # 目标不是自己，忽略（链路层基本行为）
            pass

    def send_message(self, target_id, message):
        if not self.ser or not self.ser.is_open:
            print("串口未连接")
            return

        # 封装帧
        # 格式: SRC|DST|MSG
        frame = f"{self.my_id}{SEPARATOR}{target_id}{SEPARATOR}{message}\n"
        try:
            self.ser.write(frame.encode('utf-8'))
            print(f"[发送成功] -> {target_id}: {message}")
        except Exception as e:
            print(f"[发送失败] {e}")

    def stop(self):
        self.running = False
        if self.ser and self.ser.is_open:
            self.ser.close()

def main():
    leaf = LeafNode()
    print("="*60)
    print("实验三：简单拓扑的多机通信实验 - 叶子节点 (Leaf)")
    print("="*60)
    
    ports = leaf.get_available_ports()
    if not ports:
        print("未检测到串口，请检查连接")
        return

    print("\n可用串口列表:")
    for i, p in enumerate(ports):
        print(f"  {i+1}. {p}")
    
    # 配置环节
    while True:
        try:
            choice = input(f"\n请选择连接根节点的串口序号 (1-{len(ports)}): ").strip()
            
            if not choice.isdigit():
                print("请输入数字序号")
                continue

            idx = int(choice) - 1
            if idx < 0 or idx >= len(ports):
                print(f"无效序号，请输入 1 到 {len(ports)} 之间的数字")
                continue
                
            selected_port = ports[idx]
            
            my_id = input("请输入本机识别ID (例如 ID2): ").strip()
            if not my_id:
                print("ID不能为空")
                continue
                
            if leaf.connect(selected_port, 9600, my_id):
                break
        except KeyboardInterrupt:
            return
        except Exception as e:
            print(f"配置错误，请重试: {e}")

    print("\n" + "="*60)
    print("操作说明:")
    print("  格式: 目标ID 消息内容")
    print("  例如: ID3 Hello World")
    print("  输入 'exit' 或 'quit' 退出")
    print("="*60)

    try:
        while True:
            cmd = input("> ").strip()
            if not cmd:
                continue
                
            if cmd.lower() in ('exit', 'quit'):
                break

            # 解析输入 "TARGET_ID MESSAGE"
            parts = cmd.split(None, 1)
            if len(parts) < 2:
                print("格式错误。请使用: 目标ID 消息内容")
                continue
            
            target_id, msg = parts
            leaf.send_message(target_id, msg)
            
    except KeyboardInterrupt:
        pass
    finally:
        leaf.stop()
        print("\n程序已退出")

if __name__ == '__main__':
    main()
