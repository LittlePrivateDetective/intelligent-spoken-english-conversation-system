"""支持 python -m spoken 运行（启动桌面 GUI）。

旧版命令行界面仍保留：python -m spoken.cli
"""

from .gui import main

if __name__ == "__main__":
    main()
