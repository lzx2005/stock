import React from "react";
import ReactDOM from "react-dom/client";
import { ConfigProvider } from "antd";
import zhCN from "antd/locale/zh_CN";
import App from "./App";
import "./style.css";

// 终端风主题：红涨绿跌为语义色，主色用沉稳的墨蓝（不与涨跌抢注意力）
const THEME = {
  token: {
    colorPrimary: "#31456B",
    colorInfo: "#31456B",
    colorSuccess: "#0FA67C",
    colorError: "#E23B33",
    colorTextBase: "#1F2430",
    colorBgLayout: "#F4F6F9",
    borderRadius: 6,
    fontFamily:
      '-apple-system, BlinkMacSystemFont, "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", "Segoe UI", Roboto, Arial, sans-serif',
  },
};

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <ConfigProvider locale={zhCN} theme={THEME}>
      <App />
    </ConfigProvider>
  </React.StrictMode>
);
