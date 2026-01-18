import {
    AlertTriangle,
    Check,
    ChevronDown,
    ChevronUp,
    Copy,
    RefreshCw,
    X,
} from "lucide-react";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import api from "../api";

export default function Stats() {
  const navigate = useNavigate();
  const [overview, setOverview] = useState(null);
  const [globalStats, setGlobalStats] = useState(null);
  const [byModel, setByModel] = useState([]);
  const [modelPage, setModelPage] = useState(1);
  const [modelTotalPages, setModelTotalPages] = useState(1);
  const [modelTotal, setModelTotal] = useState(0);
  const [byUser, setByUser] = useState([]);
  const [daily, setDaily] = useState([]);
  const [loading, setLoading] = useState(true);
  const [days, setDays] = useState(7);
  const [apiType, setApiType] = useState("all"); // all, cli, antigravity

  // 报错统计相关状态
  const [errorStats, setErrorStats] = useState(null);
  const [errorPage, setErrorPage] = useState(1);
  const [errorLoading, setErrorLoading] = useState(false);
  const [expandedCodes, setExpandedCodes] = useState({});
  const [selectedLog, setSelectedLog] = useState(null);
  const [logDetailLoading, setLogDetailLoading] = useState(false);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    fetchStats();
  }, [days, modelPage, apiType]);

  const fetchStats = async () => {
    setLoading(true);
    // 独立请求每个API，避免一个失败导致全部为空
    const results = await Promise.allSettled([
      api.get("/api/manage/stats/overview"),
      api.get(`/api/manage/stats/global?api_type=${apiType}`),
      api.get(
        `/api/manage/stats/by-model?days=${days}&page=${modelPage}&page_size=10&api_type=${apiType}`,
      ),
      api.get(`/api/manage/stats/by-user?days=${days}`),
      api.get(`/api/manage/stats/daily?days=${days}`),
    ]);

    // 检查是否有权限错误
    const authError = results.find(
      (r) =>
        r.status === "rejected" &&
        (r.reason?.response?.status === 401 ||
          r.reason?.response?.status === 403),
    );
    if (authError) {
      navigate("/login");
      return;
    }

    // 分别处理每个结果
    if (results[0].status === "fulfilled") setOverview(results[0].value.data);
    if (results[1].status === "fulfilled")
      setGlobalStats(results[1].value.data);
    if (results[2].status === "fulfilled") {
      const data = results[2].value.data;
      setByModel(data.models || []);
      setModelTotalPages(data.total_pages || 1);
      setModelTotal(data.total || 0);
    }
    if (results[3].status === "fulfilled")
      setByUser(results[3].value.data.users || []);
    if (results[4].status === "fulfilled")
      setDaily(results[4].value.data.daily || []);

    setLoading(false);
  };

  const poolModeLabel = {
    private: "🔒 私有模式",
    tier3_shared: "⚡ 3.0共享",
    full_shared: "🍲 大锅饭",
  };

  // 获取报错统计
  const fetchErrorStats = async (page = 1) => {
    setErrorLoading(true);
    try {
      const res = await api.get(
        `/api/manage/stats/errors?page=${page}&page_size=50`,
      );
      setErrorStats(res.data);
      setErrorPage(page);
    } catch (err) {
      console.error("获取报错统计失败", err);
    } finally {
      setErrorLoading(false);
    }
  };

  // 获取日志详情
  const fetchLogDetail = async (logId) => {
    setLogDetailLoading(true);
    try {
      const res = await api.get(`/api/manage/logs/${logId}`);
      setSelectedLog(res.data);
    } catch (err) {
      console.error("获取日志详情失败", err);
    } finally {
      setLogDetailLoading(false);
    }
  };

  // 切换展开/折叠
  const toggleExpand = (code) => {
    setExpandedCodes((prev) => ({ ...prev, [code]: !prev[code] }));
  };

  // 复制到剪贴板
  const copyToClipboard = async (text) => {
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      const textarea = document.createElement("textarea");
      textarea.value = text;
      document.body.appendChild(textarea);
      textarea.select();
      document.execCommand("copy");
      document.body.removeChild(textarea);
    }
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  // 错误码颜色
  const getStatusCodeColor = (code) => {
    if (code >= 500) return "text-red-400 bg-red-500/20";
    if (code === 429) return "text-orange-400 bg-orange-500/20";
    if (code >= 400) return "text-yellow-400 bg-yellow-500/20";
    return "text-gray-400 bg-gray-500/20";
  };

  if (loading) {
    return (
      <div className="min-h-screen bg-gray-900 flex items-center justify-center">
        <div className="text-white">加载中...</div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-900 text-white p-6">
      <div className="max-w-7xl mx-auto">
        <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4 mb-8">
          <h1 className="text-2xl sm:text-3xl font-bold whitespace-nowrap">
            📊 使用统计
          </h1>
          <div className="flex gap-2 sm:gap-4 items-center flex-wrap">
            <select
              value={days}
              onChange={(e) => setDays(Number(e.target.value))}
              className="bg-gray-800 text-white px-3 py-2 rounded-lg text-sm"
            >
              <option value={7}>最近 7 天</option>
              <option value={14}>最近 14 天</option>
              <option value={30}>最近 30 天</option>
            </select>
            <button
              onClick={() => navigate("/dashboard")}
              className="px-3 sm:px-4 py-2 bg-gray-700 rounded-lg hover:bg-gray-600 text-sm"
            >
              返回仪表盘
            </button>
          </div>
        </div>

        {/* 全站实时统计 */}
        {globalStats && (
          <div className="bg-gray-800 rounded-xl p-6 mb-8">
            <div className="flex items-center justify-between mb-4 flex-wrap gap-3">
              <h2 className="text-xl font-semibold">🌐 全站实时统计</h2>
              <div className="flex items-center gap-3">
                {/* API类型切换 */}
                <div className="flex bg-gray-700 rounded-lg p-1 text-sm">
                  <button
                    onClick={() => setApiType("all")}
                    className={`px-3 py-1 rounded-md transition-colors ${apiType === "all" ? "bg-blue-600 text-white" : "text-gray-400 hover:text-white"}`}
                  >
                    全部
                  </button>
                  <button
                    onClick={() => setApiType("cli")}
                    className={`px-3 py-1 rounded-md transition-colors ${apiType === "cli" ? "bg-cyan-600 text-white" : "text-gray-400 hover:text-white"}`}
                  >
                    CLI
                  </button>
                  <button
                    onClick={() => setApiType("antigravity")}
                    className={`px-3 py-1 rounded-md transition-colors ${apiType === "antigravity" ? "bg-green-600 text-white" : "text-gray-400 hover:text-white"}`}
                  >
                    Antigravity
                  </button>
                </div>
                <span className="px-3 py-1 bg-purple-600/30 text-purple-400 rounded-full text-sm">
                  {poolModeLabel[globalStats.pool_mode] ||
                    globalStats.pool_mode}
                </span>
              </div>
            </div>

            <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
              <div className="bg-gray-700/50 rounded-lg p-4">
                <div className="text-2xl font-bold text-yellow-400">
                  {globalStats.requests.last_hour}
                </div>
                <div className="text-sm text-gray-400">最近1小时</div>
              </div>
              <div className="bg-gray-700/50 rounded-lg p-4">
                <div className="text-2xl font-bold text-blue-400">
                  {globalStats.requests.today}
                </div>
                <div className="text-sm text-gray-400">今日请求</div>
              </div>
              <div className="bg-gray-700/50 rounded-lg p-4">
                <div className="text-2xl font-bold text-green-400">
                  {globalStats.users.active_24h}
                </div>
                <div className="text-sm text-gray-400">活跃用户(24h)</div>
              </div>
              <div className="bg-gray-700/50 rounded-lg p-4">
                <div className="text-2xl font-bold text-purple-400">
                  {globalStats.credentials.tier_3}
                </div>
                <div className="text-sm text-gray-400">3.0凭证</div>
              </div>
            </div>

            {/* 按模型分类 - 请求数/总额度 */}
            {apiType !== "antigravity" ? (
              <div className="grid grid-cols-3 gap-4 mb-4">
                <div className="bg-cyan-600/20 border border-cyan-600/30 rounded-lg p-4 text-center">
                  <div className="text-2xl font-bold text-cyan-400">
                    {globalStats.requests.by_category.flash}
                    <span className="text-lg text-cyan-300">
                      /{globalStats.total_quota?.flash ?? "-"}
                    </span>
                  </div>
                  <div className="text-sm text-cyan-300">Flash 请求</div>
                </div>
                <div className="bg-orange-600/20 border border-orange-600/30 rounded-lg p-4 text-center">
                  <div className="text-2xl font-bold text-orange-400">
                    {globalStats.requests.by_category["pro_2.5"]}
                    <span className="text-lg text-orange-300">
                      /{globalStats.total_quota?.["pro_2.5"] ?? "-"}
                    </span>
                  </div>
                  <div className="text-sm text-orange-300">2.5 Pro 请求</div>
                </div>
                <div className="bg-pink-600/20 border border-pink-600/30 rounded-lg p-4 text-center">
                  <div className="text-2xl font-bold text-pink-400">
                    {globalStats.requests.by_category.tier_3}
                    <span className="text-lg text-pink-300">
                      /{globalStats.total_quota?.tier_3 ?? "-"}
                    </span>
                  </div>
                  <div className="text-sm text-pink-300">3.0 请求</div>
                </div>
              </div>
            ) : (
              <div className="grid grid-cols-3 gap-4 mb-4">
                <div className="bg-purple-600/20 border border-purple-600/30 rounded-lg p-4 text-center">
                  <div className="text-2xl font-bold text-purple-400">
                    {globalStats.requests.by_category.flash}
                  </div>
                  <div className="text-sm text-purple-300">Claude 请求</div>
                </div>
                <div className="bg-blue-600/20 border border-blue-600/30 rounded-lg p-4 text-center">
                  <div className="text-2xl font-bold text-blue-400">
                    {globalStats.requests.by_category["pro_2.5"]}
                  </div>
                  <div className="text-sm text-blue-300">Gemini 请求</div>
                </div>
                <div className="bg-gray-600/20 border border-gray-600/30 rounded-lg p-4 text-center">
                  <div className="text-2xl font-bold text-gray-400">
                    {globalStats.requests.by_category.tier_3}
                  </div>
                  <div className="text-sm text-gray-300">其他 请求</div>
                </div>
              </div>
            )}

            {/* 按用户类型的配额分解 - 只在非Antigravity模式显示 */}
            {apiType !== "antigravity" && globalStats.quota_breakdown && (
              <div className="bg-gray-700/30 rounded-lg p-4 mb-4">
                <div className="text-sm text-gray-400 mb-3">
                  📊 按用户类型配额分解
                </div>
                <div className="grid grid-cols-3 gap-3 text-sm mb-3">
                  <div className="bg-gray-600/30 rounded p-2">
                    <div className="text-gray-400 text-xs mb-1">
                      🔒 无凭证用户 ({globalStats.user_counts?.no_cred ?? 0}人)
                    </div>
                    <div className="flex justify-between">
                      <span className="text-cyan-300">
                        {globalStats.quota_breakdown?.no_cred?.flash ?? 0}
                      </span>
                      <span className="text-orange-300">
                        {globalStats.quota_breakdown?.no_cred?.["pro_2.5"] ?? 0}
                      </span>
                      <span className="text-pink-300">
                        {globalStats.quota_breakdown?.no_cred?.tier_3 ?? 0}
                      </span>
                    </div>
                  </div>
                  <div className="bg-gray-600/30 rounded p-2">
                    <div className="text-gray-400 text-xs mb-1">
                      📘 2.5凭证用户 (
                      {globalStats.user_counts?.cred_25_only ?? 0}人)
                    </div>
                    <div className="flex justify-between">
                      <span className="text-cyan-300">
                        {globalStats.quota_breakdown?.cred_25?.flash ?? 0}
                      </span>
                      <span className="text-orange-300">
                        {globalStats.quota_breakdown?.cred_25?.["pro_2.5"] ?? 0}
                      </span>
                      <span className="text-pink-300">
                        {globalStats.quota_breakdown?.cred_25?.tier_3 ?? 0}
                      </span>
                    </div>
                  </div>
                  <div className="bg-gray-600/30 rounded p-2">
                    <div className="text-gray-400 text-xs mb-1">
                      💎 3.0凭证用户 ({globalStats.user_counts?.cred_30 ?? 0}人)
                    </div>
                    <div className="flex justify-between">
                      <span className="text-cyan-300">
                        {globalStats.quota_breakdown?.cred_30?.flash ?? 0}
                      </span>
                      <span className="text-orange-300">
                        {globalStats.quota_breakdown?.cred_30?.["pro_2.5"] ?? 0}
                      </span>
                      <span className="text-pink-300">
                        {globalStats.quota_breakdown?.cred_30?.tier_3 ?? 0}
                      </span>
                    </div>
                  </div>
                </div>
                <div className="text-center border-t border-gray-600 pt-3">
                  <span className="text-gray-400">总配额: </span>
                  <span className="text-cyan-400">
                    {globalStats.total_quota?.flash ?? 0}
                  </span>
                  <span className="text-gray-500"> + </span>
                  <span className="text-orange-400">
                    {globalStats.total_quota?.["pro_2.5"] ?? 0}
                  </span>
                  <span className="text-gray-500"> + </span>
                  <span className="text-pink-400">
                    {globalStats.total_quota?.tier_3 ?? 0}
                  </span>
                  <span className="text-gray-500"> = </span>
                  <span className="text-xl font-bold text-green-400">
                    {(globalStats.total_quota?.flash ?? 0) +
                      (globalStats.total_quota?.["pro_2.5"] ?? 0) +
                      (globalStats.total_quota?.tier_3 ?? 0)}
                  </span>
                </div>
              </div>
            )}

            {/* 凭证状态 */}
            <div className="flex items-center gap-4 text-sm text-gray-400">
              <span>用户: {globalStats.user_counts?.total ?? 0}</span>
              <span>•</span>
              <span>
                凭证: {globalStats.credentials.active}/
                {globalStats.credentials.total} 活跃
              </span>
              <span>•</span>
              <span>公共池: {globalStats.credentials.public}</span>
              <span>•</span>
              <span>3.0: {globalStats.credentials.tier_3}</span>
            </div>
          </div>
        )}

        {/* 概览卡片 */}
        {overview && (
          <div className="grid grid-cols-1 md:grid-cols-4 gap-6 mb-8">
            <div className="bg-gradient-to-br from-blue-600 to-blue-800 p-6 rounded-xl">
              <h3 className="text-sm text-blue-200 mb-2">今日请求</h3>
              <p className="text-3xl font-bold">{overview.requests.today}</p>
            </div>
            <div className="bg-gradient-to-br from-green-600 to-green-800 p-6 rounded-xl">
              <h3 className="text-sm text-green-200 mb-2">本周请求</h3>
              <p className="text-3xl font-bold">{overview.requests.week}</p>
            </div>
            <div className="bg-gradient-to-br from-purple-600 to-purple-800 p-6 rounded-xl">
              <h3 className="text-sm text-purple-200 mb-2">本月请求</h3>
              <p className="text-3xl font-bold">{overview.requests.month}</p>
            </div>
            <div className="bg-gradient-to-br from-orange-600 to-orange-800 p-6 rounded-xl">
              <h3 className="text-sm text-orange-200 mb-2">活跃凭证</h3>
              <p className="text-3xl font-bold">
                {overview.credentials.active}/{overview.credentials.total}
              </p>
            </div>
          </div>
        )}

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
          {/* 按模型统计 */}
          <div className="bg-gray-800 rounded-xl p-6">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-xl font-semibold">🤖 按模型统计</h2>
              {modelTotal > 0 && (
                <span className="text-sm text-gray-400">
                  共 {modelTotal} 个模型
                </span>
              )}
            </div>
            <div className="space-y-3">
              {byModel.length === 0 ? (
                <p className="text-gray-400">暂无数据</p>
              ) : (
                byModel.map((item, idx) => (
                  <div key={idx} className="flex justify-between items-center">
                    <span className="text-gray-300 truncate flex-1">
                      {item.model}
                    </span>
                    <div className="flex items-center gap-2">
                      <div className="w-32 bg-gray-700 rounded-full h-2">
                        <div
                          className="bg-blue-500 h-2 rounded-full"
                          style={{
                            width: `${Math.min(100, (item.count / (byModel[0]?.count || 1)) * 100)}%`,
                          }}
                        />
                      </div>
                      <span className="text-white font-medium w-16 text-right">
                        {item.count}
                      </span>
                    </div>
                  </div>
                ))
              )}
            </div>
            {/* 分页 */}
            {modelTotalPages > 1 && (
              <div className="flex items-center justify-center gap-2 mt-4 pt-4 border-t border-gray-700">
                <button
                  onClick={() => setModelPage((p) => Math.max(1, p - 1))}
                  disabled={modelPage <= 1}
                  className="px-3 py-1 bg-gray-700 rounded hover:bg-gray-600 disabled:opacity-50 disabled:cursor-not-allowed text-sm"
                >
                  上一页
                </button>
                <span className="text-gray-400 text-sm">
                  {modelPage} / {modelTotalPages}
                </span>
                <button
                  onClick={() =>
                    setModelPage((p) => Math.min(modelTotalPages, p + 1))
                  }
                  disabled={modelPage >= modelTotalPages}
                  className="px-3 py-1 bg-gray-700 rounded hover:bg-gray-600 disabled:opacity-50 disabled:cursor-not-allowed text-sm"
                >
                  下一页
                </button>
              </div>
            )}
          </div>

          {/* 按用户统计 */}
          <div className="bg-gray-800 rounded-xl p-6">
            <h2 className="text-xl font-semibold mb-4">
              👥 按用户统计 (Top 20)
            </h2>
            <div className="space-y-3">
              {byUser.length === 0 ? (
                <p className="text-gray-400">暂无数据</p>
              ) : (
                byUser.map((item, idx) => (
                  <div key={idx} className="flex justify-between items-center">
                    <span className="text-gray-300">{item.username}</span>
                    <div className="flex items-center gap-2">
                      <div className="w-32 bg-gray-700 rounded-full h-2">
                        <div
                          className="bg-green-500 h-2 rounded-full"
                          style={{
                            width: `${Math.min(100, (item.count / (byUser[0]?.count || 1)) * 100)}%`,
                          }}
                        />
                      </div>
                      <span className="text-white font-medium w-16 text-right">
                        {item.count}
                      </span>
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>
        </div>

        {/* 每日趋势 */}
        <div className="bg-gray-800 rounded-xl p-6 mt-8">
          <h2 className="text-xl font-semibold mb-4">📈 每日请求趋势</h2>
          <div className="h-64 flex items-end gap-1">
            {daily.length === 0 ? (
              <p className="text-gray-400">暂无数据</p>
            ) : (
              daily.map((item, idx) => {
                const maxCount = Math.max(...daily.map((d) => d.count));
                const height = maxCount > 0 ? (item.count / maxCount) * 100 : 0;
                return (
                  <div
                    key={idx}
                    className="flex-1 bg-blue-500 rounded-t hover:bg-blue-400 transition-colors relative group"
                    style={{ height: `${Math.max(height, 2)}%` }}
                  >
                    <div className="absolute bottom-full left-1/2 -translate-x-1/2 mb-2 bg-black px-2 py-1 rounded text-xs opacity-0 group-hover:opacity-100 whitespace-nowrap">
                      {item.date}: {item.count}
                    </div>
                  </div>
                );
              })
            )}
          </div>
          <div className="flex justify-between mt-2 text-xs text-gray-500">
            <span>{daily[0]?.date || ""}</span>
            <span>{daily[daily.length - 1]?.date || ""}</span>
          </div>
        </div>

        {/* 报错统计面板 */}
        <div className="bg-gray-800 rounded-xl p-6 mt-8">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-xl font-semibold flex items-center gap-2">
              <AlertTriangle className="w-5 h-5 text-yellow-400" />
              今日报错统计
            </h2>
            <button
              onClick={() => fetchErrorStats(1)}
              disabled={errorLoading}
              className="px-3 py-1.5 bg-gray-700 hover:bg-gray-600 rounded-lg text-sm flex items-center gap-2"
            >
              <RefreshCw
                size={14}
                className={errorLoading ? "animate-spin" : ""}
              />
              {errorStats ? "刷新" : "加载报错统计"}
            </button>
          </div>

          {errorStats && (
            <>
              {/* 按错误码分类 - 可展开 */}
              {errorStats.error_by_code?.length > 0 && (
                <div className="space-y-2 mb-6">
                  {errorStats.error_by_code.map((item, idx) => (
                    <div
                      key={idx}
                      className="border border-gray-700 rounded-lg overflow-hidden"
                    >
                      <button
                        onClick={() => toggleExpand(item.status_code)}
                        className="w-full flex items-center justify-between p-3 bg-gray-700/50 hover:bg-gray-700 transition-colors"
                      >
                        <div className="flex items-center gap-3">
                          <span className="text-gray-400 font-mono">
                            {idx + 1}
                          </span>
                          <span
                            className={`px-2 py-0.5 rounded text-sm font-medium ${getStatusCodeColor(item.status_code)}`}
                          >
                            {item.status_code === 429
                              ? "速率限制"
                              : item.status_code >= 500
                                ? "服务器错误"
                                : "错误"}{" "}
                            ({item.status_code})
                          </span>
                        </div>
                        <div className="flex items-center gap-2">
                          <span className="text-gray-400 text-sm">
                            {item.count} 次
                          </span>
                          {expandedCodes[item.status_code] ? (
                            <ChevronUp size={16} />
                          ) : (
                            <ChevronDown size={16} />
                          )}
                        </div>
                      </button>
                      {expandedCodes[item.status_code] && (
                        <div className="p-3 bg-gray-800/50 border-t border-gray-700">
                          <div className="space-y-1 text-sm">
                            {item.details?.map((detail, dIdx) => (
                              <div
                                key={dIdx}
                                className="flex items-center justify-between text-gray-400 hover:text-white hover:bg-gray-700/50 px-2 py-1 rounded cursor-pointer"
                                onClick={() => fetchLogDetail(detail.id)}
                              >
                                <span className="text-purple-400">
                                  {detail.username}
                                </span>
                                <span className="text-cyan-400 font-mono text-xs">
                                  {detail.model}
                                </span>
                                <span className="text-gray-500 text-xs">
                                  {new Date(
                                    detail.created_at,
                                  ).toLocaleTimeString()}
                                </span>
                              </div>
                            ))}
                          </div>
                        </div>
                      )}
                    </div>
                  ))}
                  <div className="text-xs text-gray-500 mt-2">
                    总计: {errorStats.total} 次报错（点击展开详情）
                  </div>
                </div>
              )}

              {/* 最近报错详情表格 */}
              <h3 className="text-lg font-semibold mb-3">最近报错详情</h3>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-left text-gray-400 border-b border-gray-700">
                      <th className="pb-2 pr-4">时间</th>
                      <th className="pb-2 pr-4">用户</th>
                      <th className="pb-2 pr-4">模型</th>
                      <th className="pb-2 pr-4">状态码</th>
                      <th className="pb-2 pr-4">CD</th>
                      <th className="pb-2">操作</th>
                    </tr>
                  </thead>
                  <tbody>
                    {errorStats.errors?.map((err) => (
                      <tr
                        key={err.id}
                        className="border-b border-gray-700/50 hover:bg-gray-700/30"
                      >
                        <td className="py-2 pr-4 text-gray-400">
                          {new Date(err.created_at).toLocaleString()}
                        </td>
                        <td className="py-2 pr-4 text-purple-400">
                          {err.username}
                        </td>
                        <td className="py-2 pr-4 text-cyan-400 font-mono text-xs">
                          {err.model}
                        </td>
                        <td className="py-2 pr-4">
                          <span
                            className={`px-2 py-0.5 rounded text-xs ${getStatusCodeColor(err.status_code)}`}
                          >
                            {err.status_code}
                          </span>
                        </td>
                        <td className="py-2 pr-4 text-orange-400">
                          {err.cd_seconds ? `${err.cd_seconds}s` : "-"}
                        </td>
                        <td className="py-2">
                          <button
                            onClick={() => fetchLogDetail(err.id)}
                            className="text-blue-400 hover:text-blue-300 text-xs"
                          >
                            详情
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              {/* 分页 */}
              {errorStats.total_pages > 1 && (
                <div className="flex items-center justify-center gap-2 mt-4">
                  <button
                    onClick={() => fetchErrorStats(errorPage - 1)}
                    disabled={errorPage <= 1 || errorLoading}
                    className="px-3 py-1 bg-gray-700 rounded hover:bg-gray-600 disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    上一页
                  </button>
                  <span className="text-gray-400 text-sm">
                    {errorPage} / {errorStats.total_pages}
                  </span>
                  <button
                    onClick={() => fetchErrorStats(errorPage + 1)}
                    disabled={
                      errorPage >= errorStats.total_pages || errorLoading
                    }
                    className="px-3 py-1 bg-gray-700 rounded hover:bg-gray-600 disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    下一页
                  </button>
                </div>
              )}
            </>
          )}

          {!errorStats && !errorLoading && (
            <div className="text-center text-gray-500 py-8">
              点击上方按钮加载报错统计
            </div>
          )}
        </div>

        {/* 请求详情弹窗 */}
        {selectedLog && (
          <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50 p-4">
            <div className="bg-gray-800 rounded-xl max-w-3xl w-full max-h-[90vh] overflow-y-auto">
              <div className="sticky top-0 bg-gray-800 border-b border-gray-700 p-4 flex items-center justify-between">
                <h3 className="text-lg font-semibold">请求详情</h3>
                <button
                  onClick={() => setSelectedLog(null)}
                  className="text-gray-400 hover:text-white"
                >
                  <X size={20} />
                </button>
              </div>

              {logDetailLoading ? (
                <div className="p-8 text-center text-gray-400">
                  <RefreshCw className="w-6 h-6 animate-spin mx-auto mb-2" />
                  加载中...
                </div>
              ) : (
                <div className="p-4 space-y-4">
                  {/* 基本信息 */}
                  <div className="bg-gray-700/50 rounded-lg p-4">
                    <h4 className="text-sm font-medium text-gray-300 mb-3">
                      基本信息
                    </h4>
                    <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-sm">
                      <div>
                        <span className="text-gray-500">时间</span>
                        <div className="text-white">
                          {selectedLog.created_at
                            ? new Date(selectedLog.created_at).toLocaleString()
                            : "-"}
                        </div>
                      </div>
                      <div>
                        <span className="text-gray-500">状态</span>
                        <div
                          className={`${getStatusCodeColor(selectedLog.status_code)} px-2 py-0.5 rounded inline-block`}
                        >
                          错误 - {selectedLog.status_code}
                        </div>
                      </div>
                      <div>
                        <span className="text-gray-500">耗时(ms)</span>
                        <div className="text-white">
                          {selectedLog.latency_ms?.toFixed(0) || "-"}
                        </div>
                      </div>
                      <div>
                        <span className="text-gray-500">分组</span>
                        <div className="text-white">
                          {selectedLog.username || "-"}
                        </div>
                      </div>
                      <div>
                        <span className="text-gray-500">模型</span>
                        <div className="text-cyan-400 font-mono text-xs">
                          {selectedLog.model || "-"}
                        </div>
                      </div>
                      <div>
                        <span className="text-gray-500">源IP</span>
                        <div className="text-white font-mono text-xs">
                          {selectedLog.client_ip || "-"}
                        </div>
                      </div>
                      <div className="col-span-2">
                        <span className="text-gray-500">凭证</span>
                        <div className="text-white text-xs">
                          {selectedLog.credential_email || "-"}
                        </div>
                      </div>
                    </div>
                  </div>

                  {/* 请求信息 */}
                  <div className="bg-gray-700/50 rounded-lg p-4">
                    <h4 className="text-sm font-medium text-gray-300 mb-3">
                      请求信息
                    </h4>
                    <div className="space-y-3">
                      <div className="bg-gray-800 rounded p-3 relative group">
                        <div className="text-gray-500 text-xs mb-1">
                          请求路径
                        </div>
                        <div className="text-white font-mono text-sm break-all">
                          {selectedLog.endpoint || "-"}
                        </div>
                        <button
                          onClick={() =>
                            copyToClipboard(selectedLog.endpoint || "")
                          }
                          className="absolute top-2 right-2 opacity-0 group-hover:opacity-100 text-gray-400 hover:text-white"
                        >
                          {copied ? <Check size={14} /> : <Copy size={14} />}
                        </button>
                      </div>
                      <div className="bg-gray-800 rounded p-3 relative group">
                        <div className="text-gray-500 text-xs mb-1">
                          User Agent
                        </div>
                        <div className="text-white font-mono text-xs break-all">
                          {selectedLog.user_agent || "-"}
                        </div>
                      </div>
                      {selectedLog.request_body && (
                        <div className="bg-gray-800 rounded p-3 relative group">
                          <div className="text-gray-500 text-xs mb-1">
                            请求内容
                          </div>
                          <pre className="text-white font-mono text-xs overflow-x-auto max-h-40 whitespace-pre-wrap">
                            {(() => {
                              try {
                                return JSON.stringify(
                                  JSON.parse(selectedLog.request_body),
                                  null,
                                  2,
                                );
                              } catch {
                                return selectedLog.request_body;
                              }
                            })()}
                          </pre>
                          <button
                            onClick={() =>
                              copyToClipboard(selectedLog.request_body || "")
                            }
                            className="absolute top-2 right-2 opacity-0 group-hover:opacity-100 text-gray-400 hover:text-white"
                          >
                            {copied ? <Check size={14} /> : <Copy size={14} />}
                          </button>
                        </div>
                      )}
                    </div>
                  </div>

                  {/* 错误信息 */}
                  {selectedLog.error_message && (
                    <div className="bg-red-900/30 border border-red-500/30 rounded-lg p-4">
                      <h4 className="text-sm font-medium text-red-400 mb-3">
                        错误信息
                      </h4>
                      <div className="bg-gray-900 rounded p-3 relative group">
                        <pre className="text-red-300 font-mono text-xs overflow-x-auto max-h-60 whitespace-pre-wrap">
                          {selectedLog.error_message}
                        </pre>
                        <button
                          onClick={() =>
                            copyToClipboard(selectedLog.error_message || "")
                          }
                          className="absolute top-2 right-2 opacity-0 group-hover:opacity-100 text-gray-400 hover:text-white"
                        >
                          {copied ? <Check size={14} /> : <Copy size={14} />}
                        </button>
                      </div>
                    </div>
                  )}
                </div>
              )}

              <div className="border-t border-gray-700 p-4 flex justify-end">
                <button
                  onClick={() => setSelectedLog(null)}
                  className="px-4 py-2 bg-gray-700 hover:bg-gray-600 rounded-lg"
                >
                  关闭
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
