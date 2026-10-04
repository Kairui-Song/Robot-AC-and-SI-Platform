#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import serial
import serial.tools.list_ports
import struct
import binascii
import time

class SerialController:
    def __init__(self, port=None, baudrate=115200, timeout=0.1):
        """
        串口控制器
        :param port: 串口端口号，如果为None则自动查找
        :param baudrate: 波特率
        :param timeout: 超时时间
        """
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.ser = None
        
    def find_port(self):
        """自动查找可用的串口"""
        ports = list(serial.tools.list_ports.comports())
        
        print("可用串口列表:")
        for i, port in enumerate(ports):
            print(f"  [{i}] {port.device} - {port.description}")
        
        if not ports:
            print("❌ 没有找到可用的串口")
            return None
        
        # 如果有多个，让用户选择
        if len(ports) > 1:
            try:
                choice = int(input("请选择串口编号: "))
                if 0 <= choice < len(ports):
                    return ports[choice].device
            except:
                pass
        
        return ports[0].device
    
    def connect(self):
        """连接串口"""
        if self.port is None:
            self.port = self.find_port()
            if self.port is None:
                return False
        
        try:
            self.ser = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                timeout=self.timeout,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                bytesize=serial.EIGHTBITS
            )
            print(f"✔ 串口连接成功: {self.port} @ {self.baudrate}bps")
            return True
        except Exception as e:
            print(f"❌ 串口连接失败: {e}")
            return False
    
    def send(self, data):
        """发送数据"""
        if self.ser and self.ser.is_open:
            self.ser.write(data)
            return True
        return False
    
    def receive(self, size=1024):
        """接收数据"""
        if self.ser and self.ser.is_open:
            return self.ser.read(size)
        return None
    
    def close(self):
        """关闭串口"""
        if self.ser and self.ser.is_open:
            self.ser.close()
            print("✔ 串口已关闭")


# 电机控制协议定义
MOTOR_CMD_FMT = '<B B B f'  # 电机ID, 命令类型, 命令值, 参数
MOTOR_CMD_HEADER = 0xAA
MOTOR_CMD_SET_POSITION = 0x01
MOTOR_CMD_SET_SPEED = 0x02
MOTOR_CMD_SET_TORQUE = 0x03
MOTOR_CMD_ENABLE = 0x04
MOTOR_CMD_DISABLE = 0x05
MOTOR_CMD_READ_STATUS = 0x06

def pack_motor_command(motor_id, cmd_type, cmd_value, param=0.0):
    """
    打包电机控制命令
    :param motor_id: 电机ID (1-255)
    :param cmd_type: 命令类型
    :param cmd_value: 命令值 (通常为角度或速度)
    :param param: 额外参数
    :return: 打包后的字节数据
    """
    data = struct.pack(MOTOR_CMD_FMT, 
                      MOTOR_CMD_HEADER,
                      motor_id,
                      cmd_type,
                      cmd_value,
                      param)
    
    # 简单校验和
    checksum = 0
    for byte in data:
        checksum ^= byte
    
    return data + struct.pack('<B', checksum)

def pack_multi_motor_command(motor_ids, positions):
    """
    打包多电机位置命令
    :param motor_ids: 电机ID列表
    :param positions: 位置列表（弧度）
    :return: 打包后的字节数据
    """
    # 命令格式: 0xAA, 命令类型(0x10), 电机数量, [电机ID, 位置(float)], ..., 校验和
    cmd_type = 0x10  # 多电机位置命令
    
    data = bytearray()
    data.append(MOTOR_CMD_HEADER)
    data.append(cmd_type)
    data.append(len(motor_ids))
    
    for motor_id, pos in zip(motor_ids, positions):
        data.extend(struct.pack('<B f', motor_id, pos))
    
    # 计算校验和
    checksum = 0
    for byte in data:
        checksum ^= byte
    
    data.append(checksum)
    return bytes(data)