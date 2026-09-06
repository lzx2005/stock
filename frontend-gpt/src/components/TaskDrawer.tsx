import { useEffect, useRef, useState } from "react";
import { X, Code, ArrowUpRight } from "@phosphor-icons/react";
import { mutate, errorText } from "../api";
import type { Task, TaskInput } from "../types";
import { validateTask } from "../domain";
import { Button, Notice, Switch } from "./Common";
const blank: TaskInput = {
  name: "",
  symbol: "",
  interval_sec: 60,
  notify: 1,
  description: "",
  script: 'def check(ctx):\n    return {"on": False, "msg": ""}\n',
};
export default function TaskDrawer({
  task,
  close,
  saved,
}: {
  task: Task | null;
  close: () => void;
  saved: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [form, setForm] = useState<TaskInput>(
    task
      ? {
          name: task.name,
          symbol: task.symbol,
          interval_sec: task.interval_sec,
          notify: task.notify,
          description: task.description || "",
          script: task.script,
        }
      : { ...blank },
  );
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    const node = dialog.current;
    const focused = document.activeElement as HTMLElement;
    node?.showModal();
    return () => {
      node?.close();
      focused?.focus();
    };
  }, []);
  const update = <K extends keyof TaskInput>(key: K, value: TaskInput[K]) => {
    setForm((f) => ({ ...f, [key]: value }));
    setErrors((e) => ({ ...e, [key]: "" }));
  };
  async function save(e: React.FormEvent) {
    e.preventDefault();
    const invalid = validateTask(form);
    setErrors(invalid);
    if (Object.keys(invalid).length) {
      requestAnimationFrame(() =>
        dialog.current
          ?.querySelector<HTMLElement>('[aria-invalid="true"]')
          ?.focus(),
      );
      return;
    }
    setBusy(true);
    setError("");
    try {
      await mutate(
        task ? `monitor/tasks/${task.id}` : "monitor/tasks",
        task ? "PUT" : "POST",
        {
          ...form,
          name: form.name.trim(),
          symbol: form.symbol.trim().toUpperCase(),
        },
      );
      saved();
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }
  return (
    <dialog
      ref={dialog}
      className="task-dialog"
      aria-labelledby="task-dialog-title"
      onCancel={(e) => {
        e.preventDefault();
        if (!busy) close();
      }}
      onClick={(e) => {
        if (e.target === e.currentTarget && !busy) close();
      }}
    >
      <form className="drawer-inner" onSubmit={save} noValidate>
        <div className="drawer-head">
          <div>
            <span className="eyebrow">MONITOR RULE</span>
            <h2 id="task-dialog-title">{task ? "任务详情" : "新建盯盘任务"}</h2>
          </div>
          <Button
            type="button"
            aria-label="关闭抽屉"
            disabled={busy}
            onClick={close}
          >
            <X size={20} />
          </Button>
        </div>
        <div className="drawer-body">
          {error && <Notice message={error} />}
          <label className="field">
            任务名称 <span>*</span>
            <input
              autoFocus
              value={form.name}
              aria-invalid={Boolean(errors.name)}
              onChange={(e) => update("name", e.target.value)}
              placeholder="例如：浦发银行均线观察"
            />
            {errors.name && <small>{errors.name}</small>}
          </label>
          <div className="form-row">
            <label className="field">
              标的代码 <span>*</span>
              <input
                value={form.symbol}
                aria-invalid={Boolean(errors.symbol)}
                onChange={(e) => update("symbol", e.target.value)}
                placeholder="600000.SH"
              />
              {errors.symbol && <small>{errors.symbol}</small>}
            </label>
            <label className="field">
              轮询间隔（秒）
              <input
                type="number"
                min={60}
                step={1}
                value={Number.isNaN(form.interval_sec) ? "" : form.interval_sec}
                aria-invalid={Boolean(errors.interval_sec)}
                onChange={(e) => update("interval_sec", e.target.valueAsNumber)}
              />
              {errors.interval_sec && <small>{errors.interval_sec}</small>}
            </label>
          </div>
          <div className="notify-field">
            <div>
              <strong>信号通知</strong>
              <p>灯状态翻转时推送 Bark 通知</p>
            </div>
            <Switch
              label="信号通知"
              on={Boolean(form.notify)}
              change={() => update("notify", form.notify ? 0 : 1)}
            />
          </div>
          <label className="field">
            任务说明
            <textarea
              rows={3}
              value={form.description}
              onChange={(e) => update("description", e.target.value)}
              placeholder="记录条件原理、实现方式与回放结果"
            />
          </label>
          <label className="field script-field">
            <span>
              <Code size={18} /> 盯盘脚本 <b>*</b>
              <em>PYTHON</em>
            </span>
            <textarea
              spellCheck={false}
              rows={13}
              aria-label="盯盘脚本"
              aria-invalid={Boolean(errors.script)}
              value={form.script}
              onChange={(e) => update("script", e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Tab" && !e.shiftKey) {
                  e.preventDefault();
                  const el = e.currentTarget;
                  const start = el.selectionStart;
                  update(
                    "script",
                    form.script.slice(0, start) +
                      "    " +
                      form.script.slice(el.selectionEnd),
                  );
                  requestAnimationFrame(() => {
                    el.selectionStart = el.selectionEnd = start + 4;
                  });
                }
              }}
            />
            {errors.script && <small>{errors.script}</small>}
          </label>
          <p className="script-hint">
            定义 check(ctx)，返回 on 和 msg。保存时会校验 Python
            语法；新任务保存后默认启用。
          </p>
        </div>
        <div className="drawer-footer">
          <Button type="button" disabled={busy} onClick={close}>
            取消
          </Button>
          <Button tone="dark" disabled={busy} type="submit">
            {busy ? "正在保存…" : "保存任务"}
            <ArrowUpRight size={18} />
          </Button>
        </div>
      </form>
    </dialog>
  );
}
