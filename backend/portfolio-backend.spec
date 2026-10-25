# PyInstaller build of the backend for the Mac app: pyinstaller portfolio-backend.spec
# Produces dist/portfolio-backend/ (a folder: starts faster than a single-file build).
from PyInstaller.utils.hooks import collect_all, collect_submodules

datas, binaries, hiddenimports = [], [], []
# uvicorn imports its loops and protocols by name at runtime
hiddenimports += collect_submodules("uvicorn")
# pandas imports openpyxl only when reading an .xlsx (index holdings files, constituents.py)
hiddenimports += collect_submodules("openpyxl")
# yfinance's HTTP client ships native libraries and certificates
for package in ("curl_cffi", "certifi"):
    package_datas, package_binaries, package_hidden = collect_all(package)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_hidden
# Index members with sectors already looked up, so a fresh install only tops them up (constituents.py)
datas += [("seed/indices.json", "seed")]
# Boards of the US index members, read from their proxy statements (directors.py, #113)
datas += [("seed/directors.json", "seed")]
# What Wikipedia and Wikidata say about those people and the executives (person_data.py, #280)
datas += [("seed/persons.json", "seed")]
# Companies each supply chain theme starts with (supply_chain/themes.py, #121)
datas += [("seed/themes.json", "seed")]
# Common company names that differ from the legal name (supply_chain/resolver.py, #317)
datas += [("seed/aliases.json", "seed")]
# Build-time settings such as the SEC contact email (write_app_config.py; gitignored)
datas += [("app_config.json", ".")]

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
