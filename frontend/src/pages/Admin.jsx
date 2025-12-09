import {
    ArrowLeft,
    Cat,
    Check,
    ExternalLink,
    Key,
    Plus,
    RefreshCw,
    ScrollText,
    Settings,
    Trash2,
    Users,
    X
} from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import api from '../api'
import { useAuth } from '../App'
import { useWebSocket } from '../hooks/useWebSocket'

export default function Admin() {
  const { user } = useAuth()
  const [tab, setTab] = useState('users')
  const [users, setUsers] = useState([])
  const [credentials, setCredentials] = useState([])
  const [logs, setLogs] = useState([])
  const [loading, setLoading] = useState(true)

  // 添加凭证表单
  const [newCredName, setNewCredName] = useState('')
  const [newCredKey, setNewCredKey] = useState('')
  const [verifyingAll, setVerifyingAll] = useState(false)
  const [verifyResult, setVerifyResult] = useState(null)

  // WebSocket 实时更新
  const handleWsMessage = useCallback((data) => {
    console.log('WS:', data.type)
    if (data.type === 'user_update') {
      // 实时更新用户列表
      api.get('/api/admin/users').then(res => setUsers(res.data.users)).catch(() => {})
    } else if (data.type === 'credential_update') {
      // 实时更新凭证列表
      api.get('/api/admin/credentials').then(res => setCredentials(res.data.credentials)).catch(() => {})
    } else if (data.type === 'log_update' && data.data) {
      // 实时插入新日志
      setLogs(prev => [data.data, ...prev].slice(0, 100))
    }
  }, [])

  const { connected } = useWebSocket(handleWsMessage)

  const fetchData = async () => {
    setLoading(true)
    try {
      if (tab === 'users') {
        const res = await api.get('/api/admin/users')
        setUsers(res.data.users)
      } else if (tab === 'credentials') {
        const res = await api.get('/api/admin/credentials')
        setCredentials(res.data.credentials)
      } else if (tab === 'logs') {
        const res = await api.get('/api/admin/logs?limit=100')
        setLogs(res.data.logs)
      }
    } catch (err) {
      console.error('获取数据失败', err)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchData()
  }, [tab])

  // 用户操作
  const toggleUserActive = async (userId, isActive) => {
    try {
      await api.put(`/api/admin/users/${userId}`, { is_active: !isActive })
      fetchData()
    } catch (err) {
      alert('操作失败')
    }
  }

  const updateUserQuota = async (userId, quota) => {
    const newQuota = prompt('设置每日配额:', quota)
    if (newQuota && !isNaN(newQuota)) {
      try {
        await api.put(`/api/admin/users/${userId}`, { daily_quota: parseInt(newQuota) })
        fetchData()
      } catch (err) {
        alert('操作失败')
      }
    }
  }

  const deleteUser = async (userId) => {
    if (!confirm('确定删除此用户?')) return
    try {
      await api.delete(`/api/admin/users/${userId}`)
      fetchData()
    } catch (err) {
      alert(err.response?.data?.detail || '删除失败')
    }
  }

  // 凭证操作
  const addCredential = async () => {
    if (!newCredName.trim() || !newCredKey.trim()) return
    try {
      await api.post('/api/admin/credentials', { name: newCredName, api_key: newCredKey })
      setNewCredName('')
      setNewCredKey('')
      fetchData()
    } catch (err) {
      alert('添加失败')
    }
  }

  const toggleCredActive = async (credId, isActive) => {
    try {
      await api.put(`/api/admin/credentials/${credId}`, { is_active: !isActive })
      fetchData()
    } catch (err) {
      alert('操作失败')
    }
  }

  const deleteCredential = async (credId) => {
    if (!confirm('确定删除此凭证?')) return
    try {
      await api.delete(`/api/admin/credentials/${credId}`)
      fetchData()
    } catch (err) {
      alert('删除失败')
    }
  }

  const verifyAllCredentials = async () => {
    if (!confirm('确定要检测所有凭证？这可能需要一些时间。')) return
    setVerifyingAll(true)
    setVerifyResult(null)
    try {
      const res = await api.post('/api/manage/credentials/verify-all')
      setVerifyResult(res.data)
      fetchData()
    } catch (err) {
      alert('检测失败: ' + (err.response?.data?.detail || err.message))
    } finally {
      setVerifyingAll(false)
    }
  }

  const exportAllCredentials = async () => {
    try {
      const res = await api.get('/api/admin/credentials/export')
      const blob = new Blob([JSON.stringify(res.data, null, 2)], { type: 'application/json' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `all_credentials_${new Date().toISOString().slice(0, 10)}.json`
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      URL.revokeObjectURL(url)
      alert('导出成功!')
    } catch (err) {
      alert('导出失败: ' + (err.response?.data?.detail || err.message))
    }
  }

  const tabs = [
    { id: 'users', label: '用户管理', icon: Users },
    { id: 'credentials', label: '凭证池', icon: Key },
    { id: 'logs', label: '使用日志', icon: ScrollText },
    { id: 'settings', label: '配额设置', icon: Settings },
  ]

  // 用户管理：搜索、排序、翻页
  const [userSearch, setUserSearch] = useState('')
  const [userSort, setUserSort] = useState({ field: 'id', order: 'asc' })
  const [userPage, setUserPage] = useState(1)
  const usersPerPage = 20

  // 处理用户列表：搜索 -> 排序 -> 分页
  const processedUsers = (() => {
    let result = [...users]
    // 搜索
    if (userSearch.trim()) {
      const search = userSearch.toLowerCase()
      result = result.filter(u => 
        u.username?.toLowerCase().includes(search) ||
        u.discord_name?.toLowerCase().includes(search) ||
        u.discord_id?.includes(search) ||
        String(u.id).includes(search)
      )
    }
    // 排序
    result.sort((a, b) => {
      let aVal = a[userSort.field]
      let bVal = b[userSort.field]
      if (typeof aVal === 'string') aVal = aVal.toLowerCase()
      if (typeof bVal === 'string') bVal = bVal.toLowerCase()
      if (aVal < bVal) return userSort.order === 'asc' ? -1 : 1
      if (aVal > bVal) return userSort.order === 'asc' ? 1 : -1
      return 0
    })
    return result
  })()

  const totalUserPages = Math.ceil(processedUsers.length / usersPerPage)
  const paginatedUsers = processedUsers.slice((userPage - 1) * usersPerPage, userPage * usersPerPage)

  const handleUserSort = (field) => {
    setUserSort(prev => ({
      field,
      order: prev.field === field && prev.order === 'asc' ? 'desc' : 'asc'
    }))
  }

  // 配额设置相关
  const [defaultQuota, setDefaultQuota] = useState(100)
  const [batchQuota, setBatchQuota] = useState('')

  const updateDefaultQuota = async () => {
    try {
      await api.post('/api/admin/settings/default-quota', { quota: defaultQuota })
      alert('默认配额已更新')
    } catch (err) {
      alert('更新失败')
    }
  }

  const applyQuotaToAll = async () => {
    if (!batchQuota || !confirm(`确定将所有用户配额设为 ${batchQuota} 次/天？`)) return
    try {
      await api.post('/api/admin/settings/batch-quota', { quota: parseInt(batchQuota) })
      alert('批量更新成功')
      fetchData()
    } catch (err) {
      alert('更新失败')
    }
  }

  return (
    <div className="min-h-screen">
      {/* 导航栏 */}
      <nav className="bg-dark-900 border-b border-dark-700">
        <div className="max-w-7xl mx-auto px-4 py-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <Cat className="w-8 h-8 text-purple-400" />
            <span className="text-xl font-bold">Catiecli</span>
            <span className="text-sm text-gray-500 bg-dark-700 px-2 py-0.5 rounded">管理后台</span>
            {connected && (
              <span className="flex items-center gap-1 text-xs text-green-400">
                <span className="w-2 h-2 bg-green-400 rounded-full animate-pulse"></span>
                实时
              </span>
            )}
          </div>
          <Link to="/dashboard" className="text-gray-400 hover:text-white flex items-center gap-2">
            <ArrowLeft size={20} />
            返回
          </Link>
        </div>
      </nav>

      <div className="max-w-7xl mx-auto px-4 py-6">
        {/* Tab 导航 */}
        <div className="flex gap-2 mb-6 overflow-x-auto pb-2">
          {tabs.map(t => (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              className={`flex items-center gap-2 px-4 py-2 rounded-lg font-medium transition-colors whitespace-nowrap ${
                tab === t.id
                  ? 'bg-purple-600 text-white'
                  : 'bg-dark-800 text-gray-400 hover:text-white hover:bg-dark-700'
              }`}
            >
              <t.icon size={18} />
              {t.label}
            </button>
          ))}
          <button
            onClick={fetchData}
            className="ml-auto p-2 text-gray-400 hover:text-white hover:bg-dark-700 rounded-lg"
          >
            <RefreshCw size={20} />
          </button>
        </div>

        {loading ? (
          <div className="text-center py-12 text-gray-400">加载中...</div>
        ) : (
          <>
            {/* 用户管理 */}
            {tab === 'users' && (
              <div className="space-y-4">
                {/* 搜索和统计 */}
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-4">
                    <input
                      type="text"
                      placeholder="搜索用户名、Discord..."
                      value={userSearch}
                      onChange={(e) => { setUserSearch(e.target.value); setUserPage(1) }}
                      className="px-4 py-2 bg-dark-800 border border-dark-600 rounded-lg text-white placeholder-gray-500 w-64"
                    />
                    <span className="text-gray-400 text-sm">
                      共 {processedUsers.length} 个用户
                      {userSearch && ` (筛选自 ${users.length} 个)`}
                    </span>
                  </div>
                </div>

                <div className="table-container">
                  <table>
                    <thead>
                      <tr>
                        <th className="cursor-pointer hover:text-purple-400" onClick={() => handleUserSort('id')}>
                          ID {userSort.field === 'id' && (userSort.order === 'asc' ? '↑' : '↓')}
                        </th>
                        <th className="cursor-pointer hover:text-purple-400" onClick={() => handleUserSort('username')}>
                          用户名 {userSort.field === 'username' && (userSort.order === 'asc' ? '↑' : '↓')}
                        </th>
                        <th>Discord</th>
                        <th className="cursor-pointer hover:text-purple-400" onClick={() => handleUserSort('daily_quota')}>
                          配额 {userSort.field === 'daily_quota' && (userSort.order === 'asc' ? '↑' : '↓')}
                        </th>
                        <th className="cursor-pointer hover:text-purple-400" onClick={() => handleUserSort('today_usage')}>
                          今日使用 {userSort.field === 'today_usage' && (userSort.order === 'asc' ? '↑' : '↓')}
                        </th>
                        <th className="cursor-pointer hover:text-purple-400" onClick={() => handleUserSort('credential_count')}>
                          凭证数 {userSort.field === 'credential_count' && (userSort.order === 'asc' ? '↑' : '↓')}
                        </th>
                        <th>状态</th>
                        <th>操作</th>
                      </tr>
                    </thead>
                    <tbody>
                      {paginatedUsers.map(u => (
                      <tr key={u.id}>
                        <td className="text-gray-400">{u.id}</td>
                        <td>
                          {u.username}
                          {u.is_admin && (
                            <span className="ml-2 text-xs bg-purple-500/20 text-purple-400 px-1.5 py-0.5 rounded">
                              管理员
                            </span>
                          )}
                        </td>
                        <td className="text-gray-400 text-xs">
                          {u.discord_id ? (
                            <div>
                              <div className="text-blue-400">{u.discord_name || 'Unknown'}</div>
                              <div className="text-gray-500 font-mono">{u.discord_id}</div>
                            </div>
                          ) : '-'}
                        </td>
                        <td>
                          <button
                            onClick={() => updateUserQuota(u.id, u.daily_quota)}
                            className="text-purple-400 hover:underline"
                          >
                            {u.daily_quota}
                          </button>
                        </td>
                        <td>{u.today_usage}</td>
                        <td className={u.credential_count > 0 ? 'text-green-400' : 'text-gray-500'}>
                          {u.credential_count || 0}
                        </td>
                        <td>
                          {u.is_active ? (
                            <span className="text-green-400">活跃</span>
                          ) : (
                            <span className="text-red-400">禁用</span>
                          )}
                        </td>
                        <td>
                          <div className="flex gap-1">
                            <button
                              onClick={() => toggleUserActive(u.id, u.is_active)}
                              className={`p-1.5 rounded hover:bg-dark-700 ${
                                u.is_active ? 'text-red-400' : 'text-green-400'
                              }`}
                              title={u.is_active ? '禁用' : '启用'}
                            >
                              {u.is_active ? <X size={16} /> : <Check size={16} />}
                            </button>
                            <button
                              onClick={() => deleteUser(u.id)}
                              className="p-1.5 rounded hover:bg-dark-700 text-gray-400 hover:text-red-400"
                              title="删除"
                            >
                              <Trash2 size={16} />
                            </button>
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                </div>

                {/* 分页 */}
                {totalUserPages > 1 && (
                  <div className="flex items-center justify-center gap-2 mt-4">
                    <button
                      onClick={() => setUserPage(1)}
                      disabled={userPage === 1}
                      className="px-3 py-1 bg-dark-700 rounded disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                      首页
                    </button>
                    <button
                      onClick={() => setUserPage(p => Math.max(1, p - 1))}
                      disabled={userPage === 1}
                      className="px-3 py-1 bg-dark-700 rounded disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                      上一页
                    </button>
                    <span className="px-4 py-1 text-gray-400">
                      第 {userPage} / {totalUserPages} 页
                    </span>
                    <button
                      onClick={() => setUserPage(p => Math.min(totalUserPages, p + 1))}
                      disabled={userPage === totalUserPages}
                      className="px-3 py-1 bg-dark-700 rounded disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                      下一页
                    </button>
                    <button
                      onClick={() => setUserPage(totalUserPages)}
                      disabled={userPage === totalUserPages}
                      className="px-3 py-1 bg-dark-700 rounded disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                      末页
                    </button>
                  </div>
                )}
              </div>
            )}

            {/* 凭证池 */}
            {tab === 'credentials' && (
              <div className="space-y-4">
                {/* OAuth 认证入口 + 一键检测 */}
                <div className="flex gap-4">
                  <div className="flex-1 bg-gradient-to-r from-purple-600/20 to-blue-600/20 border border-purple-500/30 rounded-xl p-4">
                    <div className="flex items-center justify-between">
                      <div>
                        <div className="font-medium text-purple-400 mb-1">🔐 OAuth 认证获取凭证</div>
                        <p className="text-sm text-gray-400">通过 Google OAuth 自动获取 Gemini API 凭证</p>
                      </div>
                      <Link to="/oauth" className="btn btn-primary flex items-center gap-2">
                        <ExternalLink size={16} />
                        去认证
                      </Link>
                    </div>
                  </div>
                  
                  <div className="bg-cyan-600/20 border border-cyan-500/30 rounded-xl p-4">
                    <div className="font-medium text-cyan-400 mb-1">🔍 一键检测</div>
                    <p className="text-sm text-gray-400 mb-3">检测所有凭证有效性</p>
                    <button
                      onClick={verifyAllCredentials}
                      disabled={verifyingAll}
                      className="btn bg-cyan-600 hover:bg-cyan-500 text-white flex items-center gap-2 disabled:opacity-50"
                    >
                      {verifyingAll ? <RefreshCw size={16} className="animate-spin" /> : <Check size={16} />}
                      {verifyingAll ? '检测中...' : '开始检测'}
                    </button>
                  </div>
                  
                  <div className="bg-green-600/20 border border-green-500/30 rounded-xl p-4">
                    <div className="font-medium text-green-400 mb-1">📦 导出凭证</div>
                    <p className="text-sm text-gray-400 mb-3">导出所有凭证为JSON</p>
                    <button
                      onClick={exportAllCredentials}
                      className="btn bg-green-600 hover:bg-green-500 text-white flex items-center gap-2"
                    >
                      <Download size={16} />
                      导出全部
                    </button>
                  </div>
                </div>
                
                {/* 检测结果 */}
                {verifyResult && (
                  <div className="bg-dark-800 border border-dark-600 rounded-xl p-4">
                    <div className="flex items-center gap-4 mb-3">
                      <span className="text-gray-400">检测完成:</span>
                      <span className="text-green-400">✅ 有效 {verifyResult.valid}</span>
                      <span className="text-red-400">❌ 无效 {verifyResult.invalid}</span>
                      <span className="text-purple-400">⭐ Tier3 {verifyResult.tier3}</span>
                      <span className="text-gray-500">总计 {verifyResult.total}</span>
                    </div>
                  </div>
                )}

                <div className="card">
                  <h3 className="font-medium mb-3">手动添加凭证</h3>
                  <div className="flex gap-3">
                    <input
                      type="text"
                      value={newCredName}
                      onChange={(e) => setNewCredName(e.target.value)}
                      placeholder="凭证名称"
                      className="px-4 py-2 bg-dark-800 border border-dark-600 rounded-lg text-white placeholder-gray-500"
                    />
                    <input
                      type="text"
                      value={newCredKey}
                      onChange={(e) => setNewCredKey(e.target.value)}
                      placeholder="Gemini API Key"
                      className="flex-1 px-4 py-2 bg-dark-800 border border-dark-600 rounded-lg text-white placeholder-gray-500"
                    />
                    <button onClick={addCredential} className="btn btn-primary flex items-center gap-2">
                      <Plus size={18} />
                      添加
                    </button>
                  </div>
                </div>

                <div className="table-container">
                  <table>
                    <thead>
                      <tr>
                        <th>ID</th>
                        <th>名称</th>
                        <th>等级</th>
                        <th>API Key</th>
                        <th>请求数</th>
                        <th>失败数</th>
                        <th>状态</th>
                        <th>最后错误</th>
                        <th>操作</th>
                      </tr>
                    </thead>
                    <tbody>
                      {credentials.map(c => (
                        <tr key={c.id}>
                          <td className="text-gray-400">{c.id}</td>
                          <td>{c.name}</td>
                          <td>
                            {c.model_tier === '3' ? (
                              <span className="px-2 py-0.5 bg-yellow-500/20 text-yellow-400 rounded text-xs">⭐ 3.0</span>
                            ) : (
                              <span className="px-2 py-0.5 bg-gray-600/50 text-gray-400 rounded text-xs">2.5</span>
                            )}
                          </td>
                          <td className="font-mono text-sm text-gray-400">{c.api_key}</td>
                          <td>{c.total_requests}</td>
                          <td className={c.failed_requests > 0 ? 'text-red-400' : ''}>
                            {c.failed_requests}
                          </td>
                          <td>
                            {c.is_active ? (
                              <span className="text-green-400">活跃</span>
                            ) : (
                              <span className="text-red-400">禁用</span>
                            )}
                          </td>
                          <td className="text-xs text-gray-500 max-w-xs truncate">
                            {c.last_error || '-'}
                          </td>
                          <td>
                            <div className="flex gap-1">
                              <button
                                onClick={() => toggleCredActive(c.id, c.is_active)}
                                className={`p-1.5 rounded hover:bg-dark-700 ${
                                  c.is_active ? 'text-red-400' : 'text-green-400'
                                }`}
                              >
                                {c.is_active ? <X size={16} /> : <Check size={16} />}
                              </button>
                              <button
                                onClick={() => deleteCredential(c.id)}
                                className="p-1.5 rounded hover:bg-dark-700 text-gray-400 hover:text-red-400"
                              >
                                <Trash2 size={16} />
                              </button>
                            </div>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}

            {/* 使用日志 */}
            {tab === 'logs' && (
              <div className="table-container">
                <table>
                  <thead>
                    <tr>
                      <th>时间</th>
                      <th>用户</th>
                      <th>模型</th>
                      <th>端点</th>
                      <th>状态</th>
                      <th>延迟</th>
                    </tr>
                  </thead>
                  <tbody>
                    {logs.map(log => (
                      <tr key={log.id}>
                        <td className="text-gray-400 text-sm whitespace-nowrap">
                          {new Date(log.created_at).toLocaleString()}
                        </td>
                        <td>{log.username}</td>
                        <td className="font-mono text-sm">{log.model}</td>
                        <td className="text-gray-400 text-sm">{log.endpoint}</td>
                        <td>
                          <span className={log.status_code === 200 ? 'text-green-400' : 'text-red-400'}>
                            {log.status_code}
                          </span>
                        </td>
                        <td className="text-gray-400">{log.latency_ms?.toFixed(0)}ms</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            {/* 配额设置 */}
            {tab === 'settings' && (
              <div className="space-y-6">
                {/* 批量设置配额 */}
                <div className="card">
                  <h3 className="font-semibold mb-4">批量设置所有用户配额</h3>
                  <p className="text-gray-400 text-sm mb-4">
                    将所有现有用户的配额统一设置为指定值
                  </p>
                  <div className="flex gap-3">
                    <input
                      type="number"
                      value={batchQuota}
                      onChange={(e) => setBatchQuota(e.target.value)}
                      placeholder="输入配额值"
                      className="w-32 px-4 py-2 bg-dark-800 border border-dark-600 rounded-lg text-white placeholder-gray-500"
                    />
                    <button 
                      onClick={applyQuotaToAll} 
                      disabled={!batchQuota}
                      className="btn bg-amber-600 hover:bg-amber-700 text-white"
                    >
                      应用到所有用户
                    </button>
                  </div>
                </div>

                {/* 单独设置用户配额 */}
                <div className="card">
                  <h3 className="font-semibold mb-4">单独设置用户配额</h3>
                  <p className="text-gray-400 text-sm mb-4">
                    在「用户管理」页面点击用户的配额数值即可单独修改
                  </p>
                </div>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}
