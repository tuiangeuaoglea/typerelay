"""Manual, local-only UI fixture. It never starts a typing run automatically."""

import argparse
import json
from pathlib import Path
import sys
import tkinter as tk

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import typerelay


SAMPLE = (
    '\n    def greet(name):\n'
    '\tvalue = {"path": "C:/tmp/a_b.py", "ok": True}\n'
    '        return f"Hello, {name}!"\n'
    '\n    # symbols: _-+[]{}()\\\"\'/:?<>|&$!\n'
)


def make_root(args):
    typerelay.configure_dpi_awareness()
    root = tk.Tk()
    if args.scale is not None:
        # Changes only this test process, never the Windows display settings.
        root.tk.call('tk', 'scaling', (96 / 72) * args.scale / 100)
    return root


def relay(args):
    root = make_root(args)
    app = typerelay.App(root=root)
    app.root.title('TypeRelay ' + typerelay.VERSION + ' — 本机样例')
    app.root.geometry(args.size)
    app.mode.set(args.mode)
    app.update_mode()
    app.text_area.insert('1.0', SAMPLE)
    app.text_area.edit_modified(False)
    app.refresh_stats()
    if args.settings:
        app.toggle_advanced()
    app.run()


def editor(args):
    root = make_root(args)
    root.title('TypeRelay — 本机临时编辑器')
    root.geometry(args.size)
    root.minsize(640, 400)
    root.configure(bg='#F5F6FC')
    tk.Label(root, text='仅本机临时测试 · 请先切到英文 / 半角', bg='#F5F6FC',
             fg='#252B45', font=('Microsoft YaHei UI', 12)).pack(pady=18)
    text = tk.Text(root, font=('Consolas', 12), wrap='none', undo=True,
                   padx=12, pady=12)
    text.pack(fill='both', expand=True, padx=20)
    result_label = tk.Label(root, text='点击文本框，等待 TypeRelay 输入样例。',
                            bg='#F5F6FC', fg='#7A819A', font=('Microsoft YaHei UI', 10))
    result_label.pack(pady=12)

    def verify():
        expected = typerelay.prepare_text(SAMPLE, typerelay.TypingOptions(mode=args.mode))
        received = text.get('1.0', 'end-1c')
        matches = received == expected
        result_label.config(text=('PASS：字符、换行与空白完全一致。' if matches
                                   else 'FAIL：不一致。请先核对输入模式和目标输入法。'),
                            fg='#177454' if matches else '#B42338')
        # Report counts only. Neither the application nor this fixture saves input text.
        print(json.dumps({'mode': args.mode, 'exact_match': matches,
                          'expected_length': len(expected), 'received_length': len(received)}), flush=True)

    tk.Button(root, text='核对样例', command=verify, padx=18, pady=7).pack(pady=(0, 16))
    root.mainloop()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('role', choices=('relay', 'editor'))
    parser.add_argument('--mode', choices=('command', 'file'), default='file')
    parser.add_argument('--scale', type=int, choices=(100, 125, 150), help='Test-process Tk font scaling only')
    parser.add_argument('--size', default='960x720', help='Window size, e.g. 780x600')
    parser.add_argument('--settings', action='store_true', help='Expand settings in the relay window')
    args = parser.parse_args()
    (relay if args.role == 'relay' else editor)(args)


if __name__ == '__main__':
    main()
