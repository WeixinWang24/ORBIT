# PTY Input Debug

To record raw and parsed PTY input events while using the runtime-first CLI, set:

```bash
export ORBIT_PTY_INPUT_DEBUG=1
```

Then launch the CLI normally. A log file will be written under:

```text
ORBIT/logs/pty-input-YYYYMMDD-HHMMSS.log
```

Each entry records:
- timestamp
- stage (`raw` or `parsed`)
- current CLI mode
- selected session index
- Python repr of the captured event/sequence

This is useful when diagnosing:
- focus-switch garbage input
- mouse/focus escape sequence leaks
- bad parser behavior in `parse_sequence()`
