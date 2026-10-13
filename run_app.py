"""spoken exe 打包入口（供 PyInstaller 使用）。

用根级脚本导入 spoken 包，保证包内相对导入在冻结态正常工作；
不要直接以 spoken/gui.py 为打包入口（相对导入会失败）。
"""

from spoken.gui import main

if __name__ == "__main__":
    main()
