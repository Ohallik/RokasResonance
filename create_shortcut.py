"""
create_shortcut.py
Creates a desktop shortcut for Roka's Resonance.
Run via: python create_shortcut.py
Called automatically at the end of setup.bat.
"""

import os
import subprocess
import sys
import tempfile


def main():
    app_dir = os.path.dirname(os.path.abspath(__file__))
    ico_path = os.path.join(app_dir, "assets", "banner_logo.ico")
    if not os.path.isfile(ico_path):
        ico_path = ""

    # ── Locate pythonw so the shortcut launches without a console window ──────
    pythonw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    if not os.path.isfile(pythonw):
        pythonw = sys.executable  # fall back to python.exe

    main_py = os.path.join(app_dir, "main.py")

    # Escape backslashes for PowerShell double-quoted strings
    def ps(p):
        return p.replace("\\", "\\\\").replace('"', '`"')

    icon_line = f'$s.IconLocation = "{ps(ico_path)},0"' if ico_path else ""

    # Write a temporary .ps1 file so there are no command-line escaping issues.
    # [Environment]::GetFolderPath('Desktop') resolves the real Desktop even when
    # OneDrive redirects it (e.g. C:\Users\natem\OneDrive\Desktop).
    ps1_lines = [
        "$ws = New-Object -COM WScript.Shell",
        "$desktop = [Environment]::GetFolderPath('Desktop')",
        "$lnk = Join-Path $desktop \"Roka's Resonance.lnk\"",
        "$s = $ws.CreateShortcut($lnk)",
        f'$s.TargetPath = "{ps(pythonw)}"',
        f'$s.Arguments = "`"{ps(main_py)}`""',
        f'$s.WorkingDirectory = "{ps(app_dir)}"',
    ]
    if icon_line:
        ps1_lines.append(icon_line)
    ps1_lines += [
        "$s.Description = \"Roka's Resonance\"",
        "$s.WindowStyle = 1",
        "$s.Save()",
        'Write-Output ("Shortcut created: " + $lnk)',
    ]
    ps1_content = "\r\n".join(ps1_lines) + "\r\n"

    ps1_file = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".ps1", delete=False, encoding="utf-8"
        ) as f:
            f.write(ps1_content)
            ps1_file = f.name

        result = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy", "Bypass",
                "-File", ps1_file,
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            print(f"Failed to create shortcut: {result.stderr.strip()}")
            sys.exit(1)
        print(result.stdout.strip() or "Desktop shortcut created.")
    finally:
        if ps1_file and os.path.exists(ps1_file):
            os.unlink(ps1_file)


if __name__ == "__main__":
    main()
