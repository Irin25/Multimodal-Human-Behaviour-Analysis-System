import os, sys, ctypes, shutil, requests

FONT_DIR_NAME = "fonts"

FONT_FILES = {
    "Orbitron-Regular.ttf": "https://github.com/google/fonts/raw/main/ofl/orbitron/Orbitron%5Bwght%5D.ttf",
    "Orbitron-Bold.ttf": "https://github.com/google/fonts/raw/main/ofl/orbitron/Orbitron%5Bwght%5D.ttf",
    "Exo2-Regular.ttf": "https://github.com/google/fonts/raw/main/ofl/exo2/Exo2%5Bwght%5D.ttf",
    "Exo2-Bold.ttf": "https://github.com/google/fonts/raw/main/ofl/exo2/Exo2%5Bwght%5D.ttf",
    "ShareTechMono-Regular.ttf": "https://github.com/google/fonts/raw/main/ofl/sharetechmono/ShareTechMono-Regular.ttf",
}

WINDOWS_FONTS_DIR = r"C:\Windows\Fonts"
REG_KEY = r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts"


def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except:
        return False


def download_font(url, path):
    try:
        r = requests.get(url, timeout=30)
        r.raise_for_status()
        with open(path, "wb") as f:
            f.write(r.content)
        return True
    except Exception as e:
        print(f"[FAIL DOWNLOAD] {path}: {e}")
        return False


def register_font_runtime(font_path):
    try:
        ctypes.windll.gdi32.AddFontResourceExW(font_path, 0x10, 0)
    except Exception as e:
        print(f"[WARN] Runtime load failed: {e}")


def register_font_registry(name, file):
    import winreg
    try:
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, REG_KEY, 0, winreg.KEY_SET_VALUE)
        winreg.SetValueEx(key, name, 0, winreg.REG_SZ, file)
        winreg.CloseKey(key)
    except Exception as e:
        print(f"[WARN] Registry failed: {e}")


def install():
    if sys.platform != "win32":
        print("Windows only.")
        return

    if not is_admin():
        print("Run as Administrator.")
        sys.exit(1)

    base = os.path.dirname(os.path.abspath(__file__))
    font_dir = os.path.join(base, FONT_DIR_NAME)
    os.makedirs(font_dir, exist_ok=True)

    print("\nDownloading fonts...\n")

    # 1. DOWNLOAD PHASE
    for fname, url in FONT_FILES.items():
        path = os.path.join(font_dir, fname)
        if not os.path.exists(path):
            print(f"Downloading {fname} ...")
            download_font(url, path)
        else:
            print(f"[OK] Already downloaded: {fname}")

    print("\nInstalling fonts...\n")

    installed = 0
    failed = 0

    # 2. INSTALL PHASE
    for fname in os.listdir(font_dir):
        if not fname.lower().endswith((".ttf", ".otf")):
            continue

        src = os.path.join(font_dir, fname)
        dest = os.path.join(WINDOWS_FONTS_DIR, fname)

        try:
            if not os.path.exists(dest):
                shutil.copy2(src, dest)

            register_font_runtime(dest)

            reg_name = fname.replace(".ttf", "").replace("-", " ") + " (TrueType)"
            register_font_registry(reg_name, fname)

            print(f"[DONE] {fname}")
            installed += 1

        except Exception as e:
            print(f"[FAIL] {fname}: {e}")
            failed += 1

    print("\n====================")
    print(f"Installed: {installed}")
    print(f"Failed: {failed}")
    print("====================")


if __name__ == "__main__":
    print("=" * 55)
    print(" BehaviourAI — Auto Font Installer")
    print("=" * 55)
    install()
    input("\nPress Enter to exit...")