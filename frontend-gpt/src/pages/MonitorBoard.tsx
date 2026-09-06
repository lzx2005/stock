import { useEffect, useRef, useState } from "react";
import {
  ArrowClockwise,
  Plus,
  Pulse,
  Trash,
  X,
  ArrowUpRight,
} from "@phosphor-icons/react";
import { api, mutate, errorText } from "../api";
import type { Signal, Task } from "../types";
import { dateLabel, number, relative } from "../domain";
import {
  Busy,
  Button,
  Empty,
  Lamp,
  Notice,
  Pagination,
  Switch,
  TableWrap,
} from "../components/Common";
import TaskDrawer from "../components/TaskDrawer";
const eventNames: Record<string, string> = { on: "灯亮", off: "灯灭" };
export default function MonitorBoard({ active }: { active: boolean }) {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [signals, setSignals] = useState<Signal[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [auto, setAuto] = useState(true);
  const [visible, setVisible] = useState(!document.hidden);
  const [reload, setReload] = useState(0);
  const [selected, setSelected] = useState<number | null>(null);
  const [page, setPage] = useState(1);
  const [more, setMore] = useState(false);
  const [drawer, setDrawer] = useState<{ task: Task | null } | null>(null);
  const [deleting, setDeleting] = useState<Task | null>(null);
  const [mutation, setMutation] = useState<number | null>(null);
  const [feedback, setFeedback] = useState("");
  const confirm = useRef<HTMLDialogElement>(null);
  const readVersion = useRef(0);
  const changing = useRef(false);
  useEffect(() => {
    const change = () => setVisible(!document.hidden);
    document.addEventListener("visibilitychange", change);
    return () => document.removeEventListener("visibilitychange", change);
  }, []);
  useEffect(() => {
    if (!active || !visible) return;
    let controller: AbortController | null = null;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let live = true;
    async function fetchData() {
      if (changing.current) {
        if (auto) timer = setTimeout(fetchData, 10000);
        return;
      }
      const version = readVersion.current;
      controller = new AbortController();
      setError("");
      try {
        const [taskData, signalData] = await Promise.all([
          api<{ items: Task[] }>("monitor/tasks", {}, controller.signal),
          api<{ items: Signal[] }>(
            "monitor/signals",
            { task_id: selected ?? undefined, limit: page * 50 + 1 },
            controller.signal,
          ),
        ]);
        if (live && version === readVersion.current) {
          setTasks(taskData.items);
          setSignals(signalData.items);
          setMore(signalData.items.length > page * 50);
        }
      } catch (e) {
        if (live && !controller.signal.aborted) setError(errorText(e));
      } finally {
        if (live) {
          setLoading(false);
          if (auto) timer = setTimeout(fetchData, 10000);
        }
      }
    }
    void fetchData();
    return () => {
      live = false;
      controller?.abort();
      clearTimeout(timer);
    };
  }, [active, visible, auto, reload, selected, page]);
  useEffect(() => {
    if (deleting) confirm.current?.showModal();
  }, [deleting]);
  async function toggle(task: Task) {
    readVersion.current++;
    changing.current = true;
    setMutation(task.id);
    setFeedback("");
    try {
      const result = await mutate<{ enabled: number }>(
        `monitor/tasks/${task.id}/toggle`,
        "POST",
      );
      setTasks((ts) =>
        ts.map((t) =>
          t.id === task.id ? { ...t, enabled: result.enabled } : t,
        ),
      );
    } catch (e) {
      setFeedback(errorText(e));
    } finally {
      changing.current = false;
      setMutation(null);
      setReload((n) => n + 1);
    }
  }
  async function remove() {
    if (!deleting) return;
    readVersion.current++;
    changing.current = true;
    setMutation(deleting.id);
    try {
      await mutate(`monitor/tasks/${deleting.id}`, "DELETE");
      if (selected === deleting.id) {
        setSelected(null);
        setPage(1);
      }
      setDeleting(null);
      setReload((n) => n + 1);
    } catch (e) {
      setFeedback(errorText(e));
      setDeleting(null);
    } finally {
      changing.current = false;
      setMutation(null);
      setReload((n) => n + 1);
    }
  }
  const lastRun = Math.max(0, ...tasks.map((t) => t.last_run_at || 0));
  const selectedTask = tasks.find((t) => t.id === selected);
  const stats = [
    ["全部任务", tasks.length],
    ["启用中", tasks.filter((t) => t.enabled).length],
    ["亮灯数", tasks.filter((t) => t.lamp_on).length],
    ["出错任务", tasks.filter((t) => t.error_count > 0).length],
  ];
  return (
    <div className="monitor-page">
      <div className="section-top">
        <div>
          <span className="eyebrow">SIGNAL MONITOR</span>
          <h2>
            重要的时刻，不错过<span className="heading-dot">.</span>
          </h2>
        </div>
        <Button tone="dark" onClick={() => setDrawer({ task: null })}>
          <Plus size={18} /> 新建任务
        </Button>
      </div>
      <div className="monitor-stats">
        {stats.map(([label, count], i) => (
          <div key={label}>
            <span>
              {i === 2 ? <i className="lamp lit" /> : null}
              {label}
            </span>
            <strong className={i === 3 && Number(count) > 0 ? "up" : ""}>
              {Number(count).toString().padStart(2, "0")}
            </strong>
          </div>
        ))}
        <div className="last-run">
          <Pulse size={22} />
          <span>最近运行</span>
          <strong title={dateLabel(lastRun, true)}>
            {relative(lastRun || null)}
          </strong>
        </div>
      </div>
      <div className="monitor-tools">
        <span className="quiet">琥珀灯表示条件成立 · 状态翻转时通知</span>
        <div>
          <Switch
            label="自动刷新 10s"
            on={auto}
            change={() => setAuto(!auto)}
          />
          <span>自动刷新 10s</span>
          <Button onClick={() => setReload((n) => n + 1)}>
            <ArrowClockwise size={16} />
            刷新
          </Button>
        </div>
      </div>
      {error && (
        <Notice message={error} retry={() => setReload((n) => n + 1)} />
      )}
      {feedback && <Notice message={feedback} />}
      <div className="data-block monitor-table">
        {loading ? (
          <Busy />
        ) : tasks.length ? (
          <TableWrap>
            <table className="clickable-table">
              <thead>
                <tr>
                  {[
                    "任务 / 标的",
                    "信号灯",
                    "启用",
                    "轮询",
                    "轮询次数",
                    "信号",
                    "错误",
                    "最近运行",
                    "最近错误",
                    "操作",
                  ].map((h) => (
                    <th key={h}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {tasks.map((task) => (
                  <tr
                    key={task.id}
                    className={selected === task.id ? "selected-row" : ""}
                    tabIndex={0}
                    onKeyDown={(e) => {
                      if (e.target === e.currentTarget && e.key === "Enter") {
                        setSelected(selected === task.id ? null : task.id);
                        setPage(1);
                      }
                    }}
                    onClick={() => {
                      setSelected(selected === task.id ? null : task.id);
                      setPage(1);
                    }}
                  >
                    <td className="task-name">
                      <strong>{task.name}</strong>
                      <small>{task.symbol}</small>
                      <p title={task.description}>
                        {task.description || "暂无说明"}
                      </p>
                    </td>
                    <td>
                      <Lamp on={Boolean(task.lamp_on)} />
                    </td>
                    <td onClick={(e) => e.stopPropagation()}>
                      <Switch
                        label={`启用 ${task.name}`}
                        on={Boolean(task.enabled)}
                        disabled={mutation !== null}
                        change={() => void toggle(task)}
                      />
                    </td>
                    <td>{task.interval_sec}s</td>
                    <td>{task.poll_count}</td>
                    <td>{task.signal_count}</td>
                    <td className={task.error_count ? "up" : ""}>
                      {task.error_count}
                    </td>
                    <td title={dateLabel(task.last_run_at, true)}>
                      {relative(task.last_run_at)}
                    </td>
                    <td className="last-error" title={task.last_error || ""}>
                      {task.last_error || "—"}
                    </td>
                    <td onClick={(e) => e.stopPropagation()}>
                      <div className="table-actions">
                        <button onClick={() => setDrawer({ task })}>
                          详情 <ArrowUpRight size={14} />
                        </button>
                        <button
                          className="delete-button"
                          disabled={mutation !== null}
                          aria-label={`删除 ${task.name}`}
                          onClick={() => setDeleting(task)}
                        >
                          <Trash size={17} />
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </TableWrap>
        ) : (
          <Empty title="把下一次机会，交给盯盘">
            创建第一条规则，在交易时段持续观察条件变化。
            <br />
            <Button tone="dark" onClick={() => setDrawer({ task: null })}>
              新建任务 <Plus size={16} />
            </Button>
          </Empty>
        )}
      </div>
      <div className="data-block signal-block">
        <div className="block-title">
          <h3>
            信号历史 <span>EVENT LOG</span>
          </h3>
          {selected !== null ? (
            <Button
              onClick={() => {
                setSelected(null);
                setPage(1);
              }}
            >
              {selectedTask?.name || `任务 ${selected}`} · 查看全部{" "}
              <X size={14} />
            </Button>
          ) : (
            <span className="quiet">全部任务 · 最近优先</span>
          )}
        </div>
        {signals.length ? (
          <TableWrap>
            <table>
              <thead>
                <tr>
                  <th>时间</th>
                  <th>事件</th>
                  <th>触发价</th>
                  <th>信息</th>
                </tr>
              </thead>
              <tbody>
                {signals.slice((page - 1) * 50, page * 50).map((s, index) => (
                  <tr
                    key={s.id}
                    className={index === 0 && page === 1 ? "latest-signal" : ""}
                  >
                    <td>{dateLabel(s.ts, true)}</td>
                    <td>
                      <span
                        className={`event-chip ${s.kind === "on" ? "event-on" : ""}`}
                      >
                        <i className={`lamp ${s.kind === "on" ? "lit" : ""}`} />
                        {eventNames[s.kind] || s.kind}
                      </span>
                    </td>
                    <td>{number(s.price)}</td>
                    <td className="signal-message">{s.message || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </TableWrap>
        ) : (
          <Empty title="暂无信号记录">
            灯状态发生变化后，信号会出现在这里。
          </Empty>
        )}
        <div className="signal-pagination">
          <span className="quiet">
            已读取最近 {signals.length} 条{more ? "，后续记录可翻页" : ""}
          </span>
          <Pagination
            page={page}
            size={50}
            total={signals.length}
            change={setPage}
          />
        </div>
      </div>
      {drawer && (
        <TaskDrawer
          task={drawer.task}
          close={() => setDrawer(null)}
          saved={() => {
            readVersion.current++;
            setDrawer(null);
            setReload((n) => n + 1);
          }}
        />
      )}
      {deleting && (
        <dialog
          ref={confirm}
          className="confirm-dialog"
          aria-labelledby="confirm-title"
          onCancel={() => setDeleting(null)}
        >
          <div className="confirm-icon">
            <Trash size={26} />
          </div>
          <h3 id="confirm-title">删除这条盯盘任务？</h3>
          <p>
            「{deleting.name}
            」将被移除。关联的信号历史也会删除，此操作无法撤销。
          </p>
          <div>
            <Button
              disabled={mutation !== null}
              onClick={() => setDeleting(null)}
            >
              取消
            </Button>
            <Button
              tone="danger"
              disabled={mutation !== null}
              onClick={() => void remove()}
            >
              {mutation !== null ? "正在删除…" : "确认删除"}
            </Button>
          </div>
        </dialog>
      )}
    </div>
  );
}
