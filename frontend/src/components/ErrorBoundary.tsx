import { Component } from "react";
import type { ErrorInfo, ReactNode } from "react";

/**
 * Last line of defence for a render crash (§5.1.5).
 *
 * Before this, one thrown hook or a malformed dataset took the whole page
 * white — no message, no way back, and the console was the only clue. The
 * boundary keeps the crash inside the region that broke, offers a reload and
 * a copy button so a bug report can include the actual stack.
 */
interface Props {
  /** shown in the fallback: 配置页 / 播放页 */
  region: string;
  children: ReactNode;
  /** extra action, e.g. "换一首歌" */
  onReset?: () => void;
}

interface State {
  error: Error | null;
  copied: boolean;
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null, copied: false };

  static getDerivedStateFromError(error: Error): Partial<State> {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    // console keeps the full component stack; the fallback keeps the message
    console.error("[uta] render failed", error, info.componentStack);
  }

  private reset = () => {
    this.setState({ error: null, copied: false });
    this.props.onReset?.();
  };

  private copy = async () => {
    const err = this.state.error;
    const text = [
      `${this.props.region} 渲染失败`,
      err?.name ?? "Error",
      err?.message ?? "",
      err?.stack ?? "",
      `版本 ${window.location.host}`,
    ].join("\n");
    try {
      await navigator.clipboard.writeText(text);
      this.setState({ copied: true });
    } catch {
      // clipboard API needs a secure context; selecting the text still works
      this.setState({ copied: false });
    }
  };

  render() {
    const { error } = this.state;
    if (!error) return this.props.children;
    return (
      <div className="crash" role="alert">
        <span className="crash-mark">唄</span>
        <h2>{this.props.region}出错了</h2>
        <p className="crash-msg">{error.message || "渲染时发生未知错误"}</p>
        <pre className="crash-stack">{(error.stack ?? "").split("\n").slice(0, 6).join("\n")}</pre>
        <div className="crash-actions">
          <button className="btn primary" onClick={() => window.location.reload()}>
            重新载入
          </button>
          <button className="btn" onClick={this.reset}>
            回到上一屏
          </button>
          <button className="btn" onClick={() => void this.copy()}>
            {this.state.copied ? "已复制" : "复制错误信息"}
          </button>
        </div>
      </div>
    );
  }
}
