w#!/usr/bin/env python
"""
78HAM Client 启动器
可以选择使用原版Tkinter或新版CustomTkinter GUI
"""

import sys
import os
import argparse

def main():
    parser = argparse.ArgumentParser(description='78HAM Client 启动器')
    parser.add_argument('--gui', choices=['tk', 'ctk'], default='ctk',
                       help='选择GUI类型: tk (传统Tkinter) 或 ctk (现代CustomTkinter)')
    
    args = parser.parse_args()
    
    # 添加当前目录到Python路径
    current_dir = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, current_dir)
    
    if args.gui == 'tk':
        print("启动传统Tkinter GUI...")
        from gui_client import main as tk_main
        tk_main()
    else:
        print("启动现代化CustomTkinter GUI...")
        from gui_client_ctk import main as ctk_main
        ctk_main()

if __name__ == "__main__":
    main()