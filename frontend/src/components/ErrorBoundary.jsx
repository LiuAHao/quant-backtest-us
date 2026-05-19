import React from "react";
import { AlertCircle, RefreshCw } from "lucide-react";

export class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, error };
  }

  componentDidCatch(error, errorInfo) {
    console.error("ErrorBoundary caught:", error, errorInfo);
  }

  render() {
    if (this.state.hasError) {
      const { fallbackLabel = "页面" } = this.props;
      return (
        <div className="view-stack page-enter">
          <div className="empty-state" style={{ padding: "2rem" }}>
            <AlertCircle size={32} />
            <p>{fallbackLabel}渲染出错：{this.state.error?.message || "未知错误"}</p>
            <button
              className="secondary-action"
              onClick={() => this.setState({ hasError: false, error: null })}
            >
              <RefreshCw size={16} />重试
            </button>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}

export default ErrorBoundary;
