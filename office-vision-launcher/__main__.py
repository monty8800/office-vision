"""包级入口：供 PyInstaller 打包（保持包上下文，使相对导入可用）。"""

from launcher.main import main

if __name__ == "__main__":
    main()
