import { useCallback, useEffect, useState } from "react";
import { Input, message, Table } from "antd";
import type { ColumnsType } from "antd/es/table";
import dayjs from "dayjs";
import { api, FactorDir, FactorRow, FactorValuesResp, StoredCell } from "../api";

const PAGE_SIZE = 50;

export default function FactorBrowser() {
  const [q, setQ] = useState("");
  const [fPage, setFPage] = useState(1);
  const [factors, setFactors] = useState<{ total: number; items: FactorRow[] } | null>(null);
  const [fLoading, setFLoading] = useState(false);
  const [selFactor, setSelFactor] = useState<string | null>(null);

  const [dirs, setDirs] = useState<{ total: number; items: FactorDir[] } | null>(null);
  const [dLoading, setDLoading] = useState(false);
  const [dPage, setDPage] = useState(1);
  const [selDir, setSelDir] = useState<FactorDir | null>(null);

  const [selCell, setSelCell] = useState<StoredCell | null>(null);
  const [values, setValues] = useState<FactorValuesResp | null>(null);
  const [vLoading, setVLoading] = useState(false);
  const [vPage, setVPage] = useState(1);
  const [vSize, setVSize] = useState(PAGE_SIZE);

  const loadFactors = useCallback((page: number, qv: string) => {
    setFLoading(true);
    api.factors(qv, page, PAGE_SIZE)
      .then((r) => { setFactors(r); setFPage(page); })
      .catch((e) => message.error(String(e.message)))
      .finally(() => setFLoading(false));
  }, []);
  useEffect(() => { loadFactors(1, q); }, [q, loadFactors]);

  const loadDirs = useCallback((page: number, name: string) => {
    setDLoading(true);
    api.factorDirs(name, page, PAGE_SIZE)
      .then((r) => { setDirs(r); setDPage(page); })
      .catch((e) => message.error(String(e.message)))
      .finally(() => setDLoading(false));
  }, []);

  const loadValues = useCallback((d: FactorDir, cell: StoredCell, page: number, size: number) => {
    setVLoading(true);
    api.factorValues(d.fingerprint, cell.symbol, cell.period, page, size)
      .then((r) => { setValues(r); setVPage(page); setVSize(size); })
      .catch((e) => message.error(String(e.message)))
      .finally(() => setVLoading(false));
  }, []);

  const selectFactor = (name: string) => {
    setSelFactor(name);
    setSelDir(null);
    setSelCell(null);
    setValues(null);
    loadDirs(1, name);
  };

  const selectDir = (d: FactorDir) => {
    setSelDir(d);
    setSelCell(null);
    setValues(null);
  };

  const selectCell = (cell: StoredCell) => {
    setSelCell(cell);
    setValues(null);
    if (selDir) loadValues(selDir, cell, 1, PAGE_SIZE);
  };

  const fCols: ColumnsType<FactorRow> = [
    { title: "名称", dataIndex: "name" },
    { title: "参数", dataIndex: "default_params", render: (v) => JSON.stringify(v), className: "col-mono" },
    { title: "版本", dataIndex: "version", align: "right" },
    { title: "类别", dataIndex: "category" },
    { title: "说明/同花顺条件句", dataIndex: "doc", ellipsis: true },
    { title: "已存目录", dataIndex: "stored_dir_count", align: "right", className: "col-num" },
  ];

  const dCols: ColumnsType<FactorDir> = [
    { title: "指纹", dataIndex: "fingerprint", ellipsis: true, className: "col-mono" },
    { title: "参数", dataIndex: "params", render: (v) => JSON.stringify(v), className: "col-mono" },
    { title: "版本", dataIndex: "version", align: "right" },
    { title: "复权", dataIndex: "adjust" },
    { title: "组合数", dataIndex: "cells", render: (cells: StoredCell[]) => cells.length, align: "right", className: "col-num" },
    { title: "总行数", dataIndex: "total_rows", align: "right", className: "col-num" },
  ];

  const cellCols: ColumnsType<StoredCell> = [
    { title: "标的", dataIndex: "symbol", className: "col-mono" },
    { title: "周期", dataIndex: "period" },
    { title: "行数", dataIndex: "rows", align: "right", className: "col-num" },
  ];

  const vCols: ColumnsType<[number, number | null]> = [
    { title: "时间", render: (_, r) => dayjs(r[0]).format("YYYY-MM-DD"), className: "col-mono" },
    { title: "值", render: (_, r) => (r[1] === null ? "—" : r[1]), align: "right", className: "col-num" },
  ];

  return (
    <div className="fb">
      <div className="kb-toolbar">
        <Input.Search
          placeholder="搜索因子名/说明"
          allowClear
          onSearch={(v) => setQ(v.trim())}
          style={{ width: 280 }}
        />
      </div>

      <div className="panel">
        <Table
          rowKey={(r) => r.name}
          size="small"
          loading={fLoading}
          dataSource={factors?.items ?? []}
          columns={fCols}
          rowClassName={(r) => (selFactor === r.name ? "row-selected" : "")}
          onRow={(r) => ({ onClick: () => selectFactor(r.name), style: { cursor: "pointer" } })}
          pagination={{
            current: fPage,
            pageSize: PAGE_SIZE,
            total: factors?.total ?? 0,
            showSizeChanger: false,
            showTotal: (t) => `共 ${t} 个因子`,
            onChange: (p) => loadFactors(p, q),
          }}
        />
      </div>

      {selFactor && (
        <div className="panel">
          <div className="subhead">已存数据目录 · {selFactor}</div>
          <Table
            rowKey={(r) => r.fingerprint}
            size="small"
            loading={dLoading}
            dataSource={dirs?.items ?? []}
            columns={dCols}
            rowClassName={(r) => (selDir?.fingerprint === r.fingerprint ? "row-selected" : "")}
            onRow={(r) => ({ onClick: () => selectDir(r), style: { cursor: "pointer" } })}
            pagination={{
              current: dPage,
              pageSize: PAGE_SIZE,
              total: dirs?.total ?? 0,
              showSizeChanger: false,
              onChange: (p) => loadDirs(p, selFactor),
            }}
          />
        </div>
      )}

      {selDir && (
        <div className="panel">
          <div className="subhead">组合明细 · {selDir.fingerprint}</div>
          <Table
            rowKey={(c) => `${c.symbol}|${c.period}`}
            size="small"
            dataSource={selDir.cells}
            columns={cellCols}
            rowClassName={(c) =>
              selCell?.symbol === c.symbol && selCell?.period === c.period ? "row-selected" : ""
            }
            onRow={(c) => ({ onClick: () => selectCell(c), style: { cursor: "pointer" } })}
          />
        </div>
      )}

      {selCell && (
        <div className="panel">
          <div className="subhead">
            因子值 · {selDir!.name} {JSON.stringify(selDir!.params)} · {selCell.symbol} {selCell.period}
          </div>
          <Table
            rowKey={(r) => String(r[0])}
            size="small"
            loading={vLoading}
            dataSource={values?.rows ?? []}
            columns={vCols}
            pagination={{
              current: vPage,
              pageSize: vSize,
              total: values?.total ?? 0,
              showSizeChanger: true,
              pageSizeOptions: [20, 50, 100, 200],
              showTotal: (t) => `共 ${t} 条`,
              onChange: (p, ps) => { if (selDir && selCell) loadValues(selDir, selCell, p, ps); },
            }}
          />
        </div>
      )}
    </div>
  );
}
