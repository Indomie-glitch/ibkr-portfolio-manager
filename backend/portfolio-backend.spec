# PyInstaller build of the backend for the Mac app: pyinstaller portfolio-backend.spec
# Produces dist/portfolio-backend/ (a folder: starts faster than a single-file build).
from PyInstaller.utils.hooks import collect_all, collect_submodules

datas, binaries, hiddenimports = [], [], []
# uvicorn imports its loops and protocols by name at runtime
hiddenimports += collect_submodules("uvicorn")
# yfinance's HTTP client ships native libraries and certificates
for package in ("curl_cffi", "certifi"):
    package_datas, package_binaries, package_hidden = collect_all(package)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_hidden

a = Analysis(
    ["app_main.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "matplotlib", "IPython", "pytest"],
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="portfolio-backend", console=True,
          target_arch="arm64")
coll = COLLECT(exe, a.binaries, a.datas, name="portfolio-backend")
