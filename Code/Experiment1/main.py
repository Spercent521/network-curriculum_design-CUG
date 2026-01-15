import serial
import serial.tools.list_ports
import threading
import time
import sys

class SerialAssistant:
    def __init__(self):
        self.ser = None
        self.receiving = False
        self.recv_thread = None
        self.lock = threading.Lock()
        
        # Statistics for rate testing
        self.bytes_received = 0
        self.test_mode = False  # If True, suppress print and just count

    def get_available_ports(self):
        """List available COM ports"""
        ports = serial.tools.list_ports.comports()
        return [p.device for p in ports]

    def open_port(self, port_name, baudrate=9600, timeout=1):
        """Open serial port with default parameters as per Experiment 1 Req 3"""
        try:
            self.ser = serial.Serial(
                port=port_name,
                baudrate=baudrate,
                bytesize=serial.EIGHTBITS,
                stopbits=serial.STOPBITS_ONE,
                parity=serial.PARITY_NONE,
                timeout=timeout
            )
            print(f"[System] Serial port {port_name} opened successfully.")
            print(f"         Baud: {baudrate}, Data: 8, Stop: 1, Parity: None")
            
            # Start receive thread automatically
            self.receiving = True
            self.recv_thread = threading.Thread(target=self._receive_worker, daemon=True)
            self.recv_thread.start()
            return True
        except serial.SerialException as e:
            print(f"[Error] Failed to open port: {e}")
            return False

    def close_port(self):
        """Close serial port"""
        self.receiving = False
        if self.recv_thread and self.recv_thread.is_alive():
            self.recv_thread.join(timeout=1)
        
        if self.ser and self.ser.is_open:
            self.ser.close()
            print("[System] Serial port closed.")

    def send_data(self, data):
        """Send data properly encoded"""
        if not self.ser or not self.ser.is_open:
            print("[Error] Port not open.")
            return False

        try:
            if isinstance(data, str):
                data = data.encode('utf-8')
            
            self.ser.write(data)
            # Experiment 1 Req 3: Specific feedback on send success
            if not self.test_mode:
                print(f"[Sent] {len(data)} bytes sent successfully.")
            return True
        except Exception as e:
            print(f"[Error] Send failed: {e}")
            return False

    def _receive_worker(self):
        """
        Background thread for receiving data.
        Experiment 1 Req 4: Real-time detection (using in_waiting).
        """
        while self.receiving and self.ser and self.ser.is_open:
            try:
                # Check buffer size
                if self.ser.in_waiting > 0:
                    # Read all available
                    data = self.ser.read(self.ser.in_waiting)
                    self.bytes_received += len(data)
                    
                    if not self.test_mode:
                        try:
                            decoded = data.decode('utf-8')
                            print(f"\n[Received] {decoded}")
                        except UnicodeDecodeError:
                            print(f"\n[Received Raw] {data}")
                            
                time.sleep(0.01) # Small sleep to reduce CPU usage
            except Exception as e:
                if self.receiving:
                    print(f"[Error] Receive error: {e}")
                break

def run_basic_mode(assistant):
    print("\n--- Basic Chat Mode (Type 'exit' to quit) ---")
    print("Enter text to send loopback:")
    while True:
        msg = input(">> ")
        if msg.lower() == 'exit':
            break
        assistant.send_data(msg)
        time.sleep(0.1) # Wait briefly for loopback response

def run_rate_test(assistant):
    """Experiment 1 Req 4: Max send rate test"""
    print("\n--- Max Send Rate Test ---")
    print("Sending continuous data stream for 5 seconds...")
    
    assistant.test_mode = True # Suppress printing
    assistant.bytes_received = 0
    
    start_time = time.time()
    payload = b'X' * 1024 # 1KB packets
    sent_bytes = 0
    
    try:
        while time.time() - start_time < 5:
            if assistant.send_data(payload):
                sent_bytes += len(payload)
    except KeyboardInterrupt:
        pass
        
    duration = time.time() - start_time
    assistant.test_mode = False
    
    # Since it's loopback, we check receiving speed too
    # Wait a moment for buffer to clear
    time.sleep(1) 
    
    print("-" * 30)
    print(f"Duration: {duration:.2f} s")
    print(f"Total Sent: {sent_bytes} bytes")
    print(f"Total Received: {assistant.bytes_received} bytes")
    print(f"Speed: {sent_bytes / duration / 1024:.2f} KB/s")
    print("Note: If 'Received' < 'Sent', data loss occurred due to buffer overflow.")

def run_long_message_test(assistant):
    """Experiment 1 Req 4: Long message test"""
    print("\n--- Long Message (Fragmentation) Test ---")
    length = 100000 # 100KB message
    print(f"Generatng {length} bytes of text data...")
    
    # Create a long identifiable string
    long_msg = "START" + "1234567890" * (length // 10) + "END"
    
    assistant.test_mode = True # Use clean output mode
    assistant.bytes_received = 0
    
    print("Sending...")
    start_time = time.time()
    assistant.send_data(long_msg)
    
    print("Waiting for reception to complete...")
    # Wait until we receive approximately the right amount or timeout
    timeout = 10 
    while assistant.bytes_received < len(long_msg) and timeout > 0:
        time.sleep(0.5)
        timeout -= 0.5
        print(f"Received: {assistant.bytes_received}/{len(long_msg)}...", end='\r')
        
    print(f"\nDone. Bytes Received: {assistant.bytes_received}")
    
    if assistant.bytes_received == len(long_msg):
        print("[Success] Full message received intact.")
    else:
        print(f"[Warning] Data mismatch. Lost {len(long_msg) - assistant.bytes_received} bytes.")
    
    assistant.test_mode = False

if __name__ == "__main__":
    assist = SerialAssistant()
    
    # 1. Port Selection
    avail_ports = assist.get_available_ports()
    if not avail_ports:
        # Fallback if no ports found (for testing without hardware)
        print("No COM ports found. Please connect your USB-Serial adapter.")
        manual_port = input("Enter port name manually (e.g. COM3): ")
        if not manual_port: sys.exit()
        current_port = manual_port
    else:
        print("Available Ports:", avail_ports)
        current_port = input(f"Select Port [Default {avail_ports[0]}]: ") or avail_ports[0]

    if not assist.open_port(current_port):
        sys.exit()

    try:
        while True:
            print("\n" + "="*30)
            print(f"Experiment 1: Loopback Test ({current_port})")
            print("1. Basic Send/Receive (Section 3)")
            print("2. Rate Performance Test (Section 4 - Extension)")
            print("3. Long Message Test (Section 4 - Extension)")
            print("0. Exit")
            
            choice = input("Select option: ")
            
            if choice == '1':
                run_basic_mode(assist)
            elif choice == '2':
                run_rate_test(assist)
            elif choice == '3':
                run_long_message_test(assist)
            elif choice == '0':
                break
            else:
                print("Invalid option")
                
    except KeyboardInterrupt:
        print("\nForce Exit")
    finally:
        assist.close_port()
