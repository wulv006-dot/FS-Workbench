"""Interactive local credential entry; no .ps1 execution or policy changes."""
import getpass
import os
from pathlib import Path
import subprocess
import tempfile
import warnings


def save_token(directory, token):
    token = token.strip()
    if len(token) < 30 or any(c.isspace() for c in token):
        raise ValueError('Invalid token format; nothing saved.')
    directory = Path(directory).absolute()
    if directory.is_symlink() or directory.is_junction():
        raise ValueError('Secret directory must not be a link.')
    directory.mkdir(exist_ok=True)
    if os.name == 'nt':
        # Only filesystem ACL commands; token never goes to PowerShell or argv.
        command = '''$ErrorActionPreference='Stop'
$sid=[System.Security.Principal.WindowsIdentity]::GetCurrent().User
$acl=New-Object System.Security.AccessControl.DirectorySecurity
$acl.SetOwner($sid)
$acl.SetAccessRuleProtection($true,$false)
$rule=New-Object System.Security.AccessControl.FileSystemAccessRule($sid,'FullControl','ContainerInherit,ObjectInherit','None','Allow')
$acl.AddAccessRule($rule)
[System.IO.Directory]::SetAccessControl($env:MMOEXP_SECRET_DIR,$acl)
'''
        env = dict(os.environ, MMOEXP_SECRET_DIR=str(directory))
        subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', command],
                       env=env, check=True, capture_output=True)
    else:
        directory.chmod(0o700)
    fd, name = tempfile.mkstemp(prefix='token-', dir=directory)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as file:
            file.write('FC_ENABLE_LIVE=1\nDISCORD_BOT_TOKEN=' + token + '\n')
        os.replace(name, directory / 'discord.env')
    finally:
        if os.path.exists(name):
            os.unlink(name)


def gui_main():
    import tkinter as tk
    root = tk.Tk()
    root.title('MMOEXP FC Assistant - Save Token')
    root.geometry('620x210')
    tk.Label(root, text='Paste the NEW Bot Token below (Ctrl+V). It stays on this computer.').pack(pady=(18, 8))
    entry = tk.Entry(root, show='*', width=68)
    entry.pack(padx=20, pady=5)
    status = tk.Label(root, text='Token input is hidden. Do not send it in chat.', wraplength=580)
    status.pack(pady=8)

    def paste():
        try:
            value = root.clipboard_get()
            entry.delete(0, tk.END)
            entry.insert(0, value.strip())
            status.config(text='Pasted. Click Save locally.')
        except tk.TclError:
            status.config(text='Clipboard has no text. Copy the token again.')

    def save():
        try:
            save_token(Path(__file__).resolve().parents[1] / '.secrets', entry.get())
        except Exception:
            status.config(text='Not saved. Check the token and try again.')
            return
        entry.delete(0, tk.END)
        status.config(text='Saved locally. You can close this window and tell Codex: saved.')

    buttons = tk.Frame(root)
    buttons.pack(pady=5)
    tk.Button(buttons, text='Paste from clipboard', command=paste).pack(side=tk.LEFT, padx=8)
    tk.Button(buttons, text='Save locally', command=save).pack(side=tk.LEFT, padx=8)
    tk.Button(buttons, text='Close', command=root.destroy).pack(side=tk.LEFT, padx=8)
    entry.focus_set()
    root.mainloop()
    return 0


def main():
    if os.name == 'nt':
        return gui_main()
    print('MMOEXP FC Assistant: paste the NEW Bot Token below. Input is hidden.')
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', getpass.GetPassWarning)
            token = getpass.getpass('Token: ')
        save_token(Path(__file__).resolve().parents[1] / '.secrets', token)
        print('Saved locally. Do not send the token in chat.')
        return 0
    except (Exception, KeyboardInterrupt):
        print('Not saved. Use an interactive terminal; do not paste the token into chat.')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
