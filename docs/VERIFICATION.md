# TypeRelay 2.1 validation

2026-10-21 · Windows · Python 3.12.14

## Confirmed offline

- 51 unittest cases passed. Native input, foreground-window APIs, and Tk root creation are replaced with test doubles; no keystrokes are delivered by this suite.
- Command/file character streams, source boundaries, line endings, Tab conversion, optional autoindent handling, main-keyboard punctuation, Unicode input layout, Shift cleanup, cancellation, and focus rejection are covered.
- UI regressions cover frozen snapshots, source statistics, numeric queue progress, completed/stopped/error outcomes, cancelled callbacks, closed-window polling, collapsed settings, and disabled/keyboard/mouse behavior of the gradient action button.
- Gradient and rounded shapes use Tk Canvas. The runtime dependency remains `keyboard==0.13.5`.

Run:

```powershell
python -B -m unittest discover -s tests -v
```

## Pending manual desktop checks

The current interface has **not** been visually accepted. No screenshot of the redesigned interface or successful native-input result is claimed. Remote desktop forwarding remains unverified for this version.

1. Run `python tools/local_check.py relay --mode file` and, in another shell, `python tools/local_check.py editor --mode file`. Both windows are local test fixtures. No typing starts automatically.
2. Set the test target to English / half-width. In the relay window choose “开始输入 →”, then click the temporary editor during the countdown. After input, click “核对样例”. A PASS means the target text matches the synthetic sample after the selected mode's preparation.
3. Repeat with `--mode command` in **both** windows. The expected text contains spaces instead of line breaks and no Enter is sent.
4. Check empty state, both selected modes, hover, Tab/Space/Enter keyboard interaction, settings expansion/collapse, invalid numeric values, long text, and long error/status text.
5. Test `relay --size 780x600 --scale 100`, then `--scale 125` and `--scale 150`, including `--settings`. This adjusts only the test process's Tk font scaling; it does not change Windows display settings. Check actual system DPI separately if needed.
6. Cancel during countdown; finish countdown without switching targets; press Esc or change foreground windows mid-run. Confirm zero-send or partial-stop behavior as applicable, and no automatic resume. Close while waiting and while sending.
7. Save screenshots of the actual accepted windows. Verify the intended remote client/editor separately with a short temporary sample before operational use.

The sample checker reports only match status and character counts. It does not save or upload the input text.
