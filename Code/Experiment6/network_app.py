"""
实验六：简单网络管理实验（应用层 Ping/Traceroute）
功能：
1. 继承实验四/五的动态路由与转发功能
2. 网络层增加 TTL (Time To Live) 处理
3. 实现 ICMP 协议逻辑 (Echo Request/Reply, Time Exceeded)
4. 实现 Ping 和 Traceroute 工具

使用方法：
python Code/Experiment6/network_app.py
命令：
- table: 查看路由表
- ping <TargetID>: 测试连通性
- tracert <TargetID>: 路由追踪
- send <TargetID> <Msg>: 发送普通可靠消息 (保留功能)
"""

import serial
import serial.tools.list_ports
import threading
import time
import json
import sys
import zlib

# === 协议常量 ===
TYPE_HELLO = 'HELLO'
TYPE_DV    = 'DV'
TYPE_DATA  = 'DATA'  
SEPARATOR  = '|'

# 内部子协议类型
PROTO_TRANSPORT = 'TRA' # 实验五的可靠传输
PROTO_ICMP      = 'ICMP' # 实验六的网络管理

# ICMP 类型
ICMP_ECHO_REQUEST = 'ECHO_REQ'
ICMP_ECHO_REPLY   = 'ECHO_REP'
ICMP_TIME_EXCEEDED = 'TIME_EXC'

# 配置
BAUDRATE = 9600
HELLO_INTERVAL = 3
DV_INTERVAL    = 5
NEIGHBOR_TIMEOUT = 10
DEFAULT_TTL = 64

class NetworkNode:
    def __init__(self):
        self.my_id = ""
        self.running = False
        
        self.active_ports = {}
        self.port_locks = {}
        self.neighbors = {} 
        self.neighbors_lock = threading.Lock()

        self.routing_table = {}
        self.rt_lock = threading.Lock()

    def log(self, *args, **kwargs):
        print(*args, **kwargs)

        # Ping/Tracert 状态管理
        # events: {seq: threading.Event}
        # results: {seq: params}
        self.icmp_events = {}
        self.icmp_results = {}
        self.icmp_lock = threading.Lock()
        self.seq_counter = 0

    def start(self):
        print("="*60)
        print("实验六：网络管理工具 (Ping / Traceroute)")
        # 简化启动流程，自动选择所有串口 (也可保留交互式)
        # 这里为了方便保留交互式
        available = [p.device for p in serial.tools.list_ports.comports()]
        if not available:
            print("警告: 未检测到串口")
        
        while not self.my_id:
            self.my_id = input("本机ID: ").strip()
        
        sel = input(f"选择串口 (检测到 {available}, 输入 all 或 COMx): ").strip()
        ports = []
        if sel == 'all': ports = available
        else: ports = [x.strip() for x in sel.replace(',',' ').split()]

        self.routing_table[self.my_id] = {'cost': 0, 'next_hop_port': 'LOCAL', 'next_hop_id': self.my_id}
        self.running = True

        for p in ports:
            try:
                # 兼容部分输入不带COM的情况
                if p.isdigit(): p = 'COM' + p
                ser = serial.Serial(p, BAUDRATE, timeout=0.1)
                self.active_ports[p] = ser
                self.port_locks[p] = threading.Lock()
                threading.Thread(target=self._listen_port, args=(p,), daemon=True).start()
                print(f"[{p}] 监听中...")
            except Exception as e:
                print(f"[{p}] 失败: {e}")

        # 启动后台任务
        threading.Thread(target=self._task_hello, daemon=True).start()
        threading.Thread(target=self._task_broadcast_dv, daemon=True).start()
        threading.Thread(target=self._task_check_timeout, daemon=True).start()

        print("\n系统就绪。可用命令: ping, tracert, table, send, exit")
        self._input_loop()

    # === 基础通信 ===
    def _listen_port(self, port):
        ser = self.active_ports[port]
        while self.running and ser.is_open:
            try:
                if ser.in_waiting:
                    line = ser.readline().decode('utf-8', errors='ignore').strip()
                    if line: self._handle_packet(line, port)
                else:
                    time.sleep(0.01)
            except:
                break

    def _send_bytes(self, port, data_str):
        if port not in self.active_ports: return
        with self.port_locks[port]:
            try:
                self.active_ports[port].write((data_str + '\n').encode('utf-8'))
            except Exception as e:
                print(f"Send Error on {port}: {e}")

    # === 核心处理 ===
    def _handle_packet(self, raw, port_src):
        try:
            parts = raw.split(SEPARATOR, 4) # DATA|Src|Dst|TTL|Payload
            # 为了兼容 Hello/DV (只有2-3段)，这里逻辑需要调整
            # 协议设计：
            # HELLO|ID
            # DV|ID|JSON
            # DATA|Src|Dst|TTL|Type|Content (这里将Data细分)
            
            # 简单起见，先按最少分割，再根据类型细分
            base_parts = raw.split(SEPARATOR)
            p_type = base_parts[0]
            
            if p_type == TYPE_HELLO:
                self._on_recv_hello(base_parts[1], port_src)
            elif p_type == TYPE_DV:
                self._on_recv_dv(base_parts[1], base_parts[2], port_src)
            elif p_type == TYPE_DATA:
                # DATA|Src|Dst|TTL|Payload(Type|Body)
                # Payload 内部再解析
                if len(base_parts) < 5: return
                src, dst, ttl_str, payload = base_parts[1], base_parts[2], base_parts[3], SEPARATOR.join(base_parts[4:])
                self._process_network_packet(src, dst, int(ttl_str), payload)
                
        except Exception as e:
            # print(f"Parse Error: {e} raw={raw}")
            pass

    def _process_network_packet(self, src_id, dst_id, ttl, payload):
        """网络层处理：转发、或者是给我的"""
        
        # 1. 如果是发给我的
        if dst_id == self.my_id:
            self._handle_application_payload(src_id, payload)
            return

        # 2. 也是关键点：TTL处理与转发
        # TTL减1
        ttl -= 1
        if ttl <= 0:
            # TTL耗尽，发送 ICMP Time Exceeded 给 Source
            # print(f"[TTL Exceeded] Drop packet from {src_id} to {dst_id}")
            self._send_icmp_time_exceeded(src_id, payload)
            return

        # 查找路由转发
        with self.rt_lock:
            route = self.routing_table.get(dst_id)
            if route and route['cost'] < 999:
                next_port = route['next_hop_port']
                # 重新打包
                packet = f"{TYPE_DATA}{SEPARATOR}{src_id}{SEPARATOR}{dst_id}{SEPARATOR}{ttl}{SEPARATOR}{payload}"
                self._send_bytes(next_port, packet)
            else:
                pass # 无法送达 (也可回送 ICMP Destination Unreachable)

    def _handle_application_payload(self, src_id, payload):
        """应用层/传输层分发"""
        # Payload 格式: Proto|Content
        try:
            sub_parts = payload.split(SEPARATOR, 1)
            proto = sub_parts[0]
            content = sub_parts[1]
            
            if proto == PROTO_ICMP:
                self._handle_icmp(src_id, content)
            elif proto == PROTO_TRANSPORT:
                print(f"[ReliableMsg] From {src_id}: {content}")
        except:
            pass

    # === ICMP 实现 ===
    # Format: Type|Seq|Timestamp
    
    def _send_icmp_echo_request(self, target, seq, ttl=DEFAULT_TTL):
        ts = time.time()
        # Payload: ICMP|ECHO_REQ|Seq|Ts
        payload = f"{PROTO_ICMP}{SEPARATOR}{ICMP_ECHO_REQUEST}{SEPARATOR}{seq}{SEPARATOR}{ts}"
        self._network_send(target, payload, ttl)

    def _send_icmp_echo_reply(self, target, seq, orig_ts):
        # Payload: ICMP|ECHO_REP|Seq|OrigTs|RecvTs
        recv_ts = time.time()
        payload = f"{PROTO_ICMP}{SEPARATOR}{ICMP_ECHO_REPLY}{SEPARATOR}{seq}{SEPARATOR}{orig_ts}{SEPARATOR}{recv_ts}"
        self._network_send(target, payload, DEFAULT_TTL)

    def _send_icmp_time_exceeded(self, target, orig_payload):
        # Payload: ICMP|TIME_EXC|OrigPayload(Partial)
        # 这里不仅要告诉发件人TTL过期，通常还要把原始包的一部分带回去，以便识别是哪个包
        # 这里简化，假设 seq 在 orig_payload 里能解析出来，或者仅仅作为 Traceroute 触发器
        # 为了 Traceroute，我们需要提取出原始的 Seq。
        # 尝试解析原始 payload 里的 Seq
        # Assumption: Orig Payload starts with ICMP|ECHO_REQ|Seq|...
        try:
            parts = orig_payload.split(SEPARATOR)
            if parts[0] == PROTO_ICMP and parts[1] == ICMP_ECHO_REQUEST:
                seq = parts[2]
                payload = f"{PROTO_ICMP}{SEPARATOR}{ICMP_TIME_EXCEEDED}{SEPARATOR}{seq}{SEPARATOR}{self.my_id}"
                self._network_send(target, payload, DEFAULT_TTL)
        except:
            pass

    def _handle_icmp(self, src_id, content):
        parts = content.split(SEPARATOR)
        icmp_type = parts[0]

        if icmp_type == ICMP_ECHO_REQUEST:
            # PONG
            seq = parts[1]
            ts = parts[2]
            # print(f"[Ping] Received Request from {src_id} Seq={seq}")
            self._send_icmp_echo_reply(src_id, seq, ts)

        elif icmp_type == ICMP_ECHO_REPLY:
            # 收到回显
            seq = int(parts[1])
            orig_ts = float(parts[2])
            recv_ts = float(parts[3]) # 对端接收时间，可选使用
            
            rtt = (time.time() - orig_ts) * 1000 # ms
            # 通知等待线程
            with self.icmp_lock:
                if seq in self.icmp_events:
                    self.icmp_results[seq] = {'type': 'REPLY', 'src': src_id, 'rtt': rtt}
                    self.icmp_events[seq].set()

        elif icmp_type == ICMP_TIME_EXCEEDED:
            # TTL 过期
            seq = int(parts[1])
            router_id = parts[2]
            
            with self.icmp_lock:
                if seq in self.icmp_events:
                    self.icmp_results[seq] = {'type': 'EXPIRED', 'src': router_id}
                    self.icmp_events[seq].set()

    def _network_send(self, dst_id, payload, ttl):
        packet = f"{TYPE_DATA}{SEPARATOR}{self.my_id}{SEPARATOR}{dst_id}{SEPARATOR}{ttl}{SEPARATOR}{payload}"
        
        # 路由查找
        with self.rt_lock:
            route = self.routing_table.get(dst_id)
            if not route or route['cost'] >= 999:
                return False
            port = route['next_hop_port']
            self._send_bytes(port, packet)
            return True

    # === API Ping/Traceroute ===
    
    def do_ping(self, target_id, count=4):
        print(f"\nPing {target_id} with 32 bytes of data:")
        lost = 0
        rtts = []
        
        for i in range(count):
            seq = self.seq_counter
            self.seq_counter += 1
            
            evt = threading.Event()
            with self.icmp_lock:
                self.icmp_events[seq] = evt
            
            self._send_icmp_echo_request(target_id, seq)
            
            # Wait
            if evt.wait(2.0): # 2s timeout
                res = self.icmp_results.get(seq)
                if res and res['type'] == 'REPLY':
                    rtt = res['rtt']
                    rtts.append(rtt)
                    self.log(f"来自 {res['src']} 的回复: time={rtt:.1f}ms")
                else:
                    self.log("请求超时 (异常回复).")
                    lost += 1
            else:
                self.log("请求超时.")
                lost += 1
                
            # Cleanup
            with self.icmp_lock:
                self.icmp_events.pop(seq, None)
                self.icmp_results.pop(seq, None)
                
            time.sleep(1)

        self.log(f"\nPing statistics for {target_id}:")
        loss_rate = (lost/count)*100
        self.log(f"    Packets: Sent = {count}, Received = {count-lost}, Lost = {lost} ({loss_rate:.0f}% loss)")
        if rtts:
            avg = sum(rtts)/len(rtts)
            self.log(f"Approximate round trip times in milli-seconds:")
            self.log(f"    Minimum = {min(rtts):.1f}ms, Maximum = {max(rtts):.1f}ms, Average = {avg:.1f}ms")

    def do_traceroute(self, target_id, max_hops=15):
        self.log(f"\nTracing route to {target_id} over a maximum of {max_hops} hops:\n")
        
        for ttl in range(1, max_hops + 1):
            seq = self.seq_counter
            self.seq_counter += 1
            
            evt = threading.Event()
            with self.icmp_lock:
                self.icmp_events[seq] = evt
            
            start_t = time.time()
            # 发送 TTL=ttl 的 Echo Request
            self._send_icmp_echo_request(target_id, seq, ttl=ttl)
            
            self.log(f"{ttl:2d}  ", end='', flush=True)
            
            if evt.wait(3.0):
                rtt = (time.time() - start_t) * 1000
                res = self.icmp_results.get(seq)
                
                if not res:
                    self.log(f"    *     Error")
                elif res['type'] == 'EXPIRED':
                    self.log(f"  {rtt:6.1f} ms    {res['src']}")
                elif res['type'] == 'REPLY':
                    # 到达目的地
                    self.log(f"  {rtt:6.1f} ms    {res['src']}")
                    self.log("\nTrace complete.")
                    with self.icmp_lock:
                        self.icmp_events.pop(seq, None)
                        self.icmp_results.pop(seq, None)
                    return
            else:
                self.log(f"    *        Request timed out.")
                
            with self.icmp_lock:
                self.icmp_events.pop(seq, None)
                self.icmp_results.pop(seq, None)

    # === Helper (Hello/DV/Routing) Copied & Simplified ===
    def _on_recv_hello(self, sender_id, port):
        with self.neighbors_lock:
            self.neighbors[port] = {'id': sender_id, 'last_seen': time.time()}
        with self.rt_lock:
            cur = self.routing_table.get(sender_id)
            if not cur or cur['cost'] > 1:
                self.routing_table[sender_id] = {'cost': 1, 'next_hop_port': port, 'next_hop_id': sender_id}

    def _send_dv_updates(self):
        """发送路由更新（支持毒性逆转）"""
        with self.rt_lock:
            snapshot = {k:v.copy() for k,v in self.routing_table.items()}
        
        current_ports = list(self.active_ports.keys())
        for port_out in current_ports:
            # Poison Reverse Logic
            custom_dv = {}
            for dest, info in snapshot.items():
                cost = info['cost']
                if info.get('next_hop_port') == port_out:
                    cost = 999 
                custom_dv[dest] = {'cost': cost}
            
            pkt = f"{TYPE_DV}{SEPARATOR}{self.my_id}{SEPARATOR}{json.dumps(custom_dv)}"
            self._send_bytes(port_out, pkt)

    def _on_recv_dv(self, sender_id, dv_json, port):
        """优化的 DV 处理 (Triggered Updates + Poison Reverse Support)"""
        try: neighbors_dv = json.loads(dv_json)
        except: return
        updated = False
        with self.rt_lock:
            # 1. Update from neighbor
            for dst, info in neighbors_dv.items():
                if dst == self.my_id: continue
                cost_neighbor = info.get('cost', 999)
                new_cost = 1 + cost_neighbor
                if new_cost > 999: new_cost = 999
                
                cur = self.routing_table.get(dst)
                
                if not cur:
                    # New route found
                    if new_cost < 999:
                        self.routing_table[dst] = {'cost': new_cost, 'next_hop_port': port, 'next_hop_id': sender_id}
                        updated = True
                
                elif cur['next_hop_id'] == sender_id:
                    # Route from same neighbor: must update
                    if cur['cost'] != new_cost:
                        cur['cost'] = new_cost
                        updated = True
                
                elif new_cost < cur['cost']:
                    # Better route found
                    self.routing_table[dst] = {'cost': new_cost, 'next_hop_port': port, 'next_hop_id': sender_id}
                    updated = True

            # 2. Poison Logic for missing routes from next hop
            for dst in list(self.routing_table.keys()):
                if dst == self.my_id: continue
                route = self.routing_table[dst]
                if route['next_hop_id'] == sender_id and dst not in neighbors_dv:
                    if route['cost'] != 999:
                        route['cost'] = 999
                        updated = True
        
        if updated:
            self._send_dv_updates()

    def _task_hello(self):
        while self.running:
            for p in list(self.active_ports.keys()): self._send_bytes(p, f"{TYPE_HELLO}{SEPARATOR}{self.my_id}")
            time.sleep(HELLO_INTERVAL)

    def _task_broadcast_dv(self):
        while self.running:
            self._send_dv_updates()
            time.sleep(DV_INTERVAL)

    def _task_check_timeout(self):
        while self.running:
            now = time.time()
            drops = []
            with self.neighbors_lock:
                for k,v in self.neighbors.items():
                    if now - v['last_seen'] > NEIGHBOR_TIMEOUT: drops.append(k)
                for k in drops: del self.neighbors[k]
            if drops:
                with self.rt_lock:
                    for d,i in self.routing_table.items():
                        if i['next_hop_port'] in drops and d!=self.my_id: i['cost']=999
            time.sleep(1)

    def _input_loop(self):
        while self.running:
            try:
                cmd = input("> ").strip().split()
                if not cmd: continue
                op = cmd[0].lower()
                if op == 'ping':
                    if len(cmd)<2: print("Usage: ping <ID>")
                    else: self.do_ping(cmd[1])
                elif op == 'tracert':
                    if len(cmd)<2: print("Usage: tracert <ID>")
                    else: self.do_traceroute(cmd[1])
                elif op == 'table':
                    print(json.dumps(self.routing_table, indent=2))
                elif op == 'send': # 简单的不可靠发送示例
                    if len(cmd)<3: print("Usage: send <ID> <Msg>")
                    else:
                        payload = f"{PROTO_TRANSPORT}{SEPARATOR}{' '.join(cmd[2:])}"
                        self._network_send(cmd[1], payload, DEFAULT_TTL)
                elif op == 'exit':
                    self.running=False
                    sys.exit()
            except KeyboardInterrupt:
                self.running=False
            except Exception as e:
                print(f"Err: {e}")

if __name__ == "__main__":
    NetworkNode().start()
