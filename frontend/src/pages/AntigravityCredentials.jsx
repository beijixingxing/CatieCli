import {
    ArrowLeft,
    Cat,
    CheckCircle,
    Download,
    ExternalLink,
    Gift,
    RefreshCw,
    Rocket,
    Shield,
    Trash2,
    Upload,
    X
} from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import api from '../api'
import { useAuth } from '../App'

export default function AntigravityCredentials() {
  const { user } = useAuth()
  const [credentials, setCredentials] = useState([])
  const [loading, setLoading] = useState(true)
  const [uploadFiles, setUploadFiles] = useState([])
  const [uploadPublic, setUploadPublic] = useState(true)
  const [uploading, setUploading] = useState(false)
  const [message, setMessage] = useState({ type: '', text: '' })
  const [dragOver, setDragOver] = useState(false)
  const [verifyResult, setVerifyResult] = useState(null)
  const [quotaResult, setQuotaResult] = useState(null)
  const [loadingQuota, setLoadingQuota] = useState(null)
  const [stats, setStats] = useState(null)

  useEffect(() => {
    fetchCredentials()
    fetchStats()
  }, [])

  const fetchCredentials = async () => {
    setLoading(true)
    try {
      const res = await api.get('/api/antigravity/credentials')
      setCredentials(res.data)
    } catch (err) {
      setMessage({ type: 'error', text: '获取凭证失败' })
    } finally {
      setLoading(false)
    }
  }

  const fetchStats = async () => {
    try {
      const res = await api.get('/api/antigravity/stats')
      setStats(res.data)
    } catch (err) {
      console.error('获取统计失败', err)
    }
  }

  const uploadCredential = async () => {
    if (uploadFiles.length === 0) return
    setUploading(true)
    setMessage({ type: '', text: '' })
    try {
      const formData = new FormData()
      uploadFiles.forEach(file => formData.append('files', file))
      formData.append('is_public', uploadPublic)
      
      const res = await api.post('/api/antigravity/credentials/upload', formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
        timeout: 600000
      })
      setMessage({ 
        type: 'success', 
        text: `上传完成: 成功 ${res.data.uploaded_count}/${res.data.total_count} 个` 
      })
      setUploadFiles([])
      document.getElementById('antigravity-file-input').value = ''
      fetchCredentials()
      fetchStats()
    } catch (err) {
      setMessage({ type: 'error', text: err.response?.data?.detail || '上传失败' })
    } finally {
      setUploading(false)
    }
  }

  const togglePublic = async (id, currentPublic) => {
    try {
      await api.patch(`/api/antigravity/credentials/${id}`, null, {
        params: { is_public: !currentPublic }
      })
      fetchCredentials()
    } catch (err) {
      setMessage({ type: 'error', text: err.response?.data?.detail || '操作失败' })
    }
  }

  const toggleActive = async (id, currentActive) => {
    try {
      await api.patch(`/api/antigravity/credentials/${id}`, null, {
        params: { is_active: !currentActive }
      })
      fetchCredentials()
    } catch (err) {
      setMessage({ type: 'error', text: '操作失败' })
    }
  }

  const deleteCred = async (id) => {
    if (!confirm('确定删除此凭证？此操作不可恢复！')) return
    try {
      await api.delete(`/api/antigravity/credentials/${id}`)
      setMessage({ type: 'success', text: '删除成功' })
      fetchCredentials()
      fetchStats()
    } catch (err) {
      setMessage({ type: 'error', text: '删除失败' })
    }
  }

  const [verifying, setVerifying] = useState(null)
  
  const exportCred = async (id, email) => {
    try {
      const res = await api.get(`/api/antigravity/credentials/${id}/export`)
      const blob = new Blob([JSON.stringify(res.data, null, 2)], { type: 'application/json' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `antigravity_${email || id}.json`
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      URL.revokeObjectURL(url)
      setMessage({ type: 'success', text: '凭证已导出！' })
    } catch (err) {
      setMessage({ type: 'error', text: '导出失败: ' + (err.response?.data?.detail || err.message) })
    }
  }
  
  const verifyCred = async (id, email) => {
    setVerifying(id)
    try {
      const res = await api.post(`/api/antigravity/credentials/${id}/verify`)
      setVerifyResult({ ...res.data, email })
      fetchCredentials()
    } catch (err) {
      setVerifyResult({ error: err.response?.data?.detail || err.message, is_valid: false, email })
    } finally {
      setVerifying(null)
    }
  }

  const refreshProjectId = async (id, email) => {
    setVerifying(id)
    try {
      const res = await api.post(`/api/antigravity/credentials/${id}/refresh-project-id`)
      setVerifyResult({ ...res.data, email, is_project_id_refresh: true, is_valid: res.data.success })
      if (res.data.success) {
        fetchCredentials()
      }
    } catch (err) {
      setVerifyResult({ error: err.response?.data?.detail || err.message, is_valid: false, email, is_project_id_refresh: true })
    } finally {
      setVerifying(null)
    }
  }

  const fetchQuota = async (id, email) => {
    setLoadingQuota(id)
    try {
      const res = await api.get(`/api/antigravity/credentials/${id}/quota`)
      setQuotaResult({ ...res.data, email })
    } catch (err) {
      setQuotaResult({ success: false, error: err.response?.data?.detail || err.message, email })
    } finally {
      setLoadingQuota(null)
    }
  }

  const deleteAllInactive = async () => {
    if (!confirm('确定删除所有失效的 Antigravity 凭证？此操作不可恢复！')) return
    try {
      const res = await api.delete('/api/antigravity/credentials/inactive/batch')
      setMessage({ type: 'success', text: res.data.message })
      fetchCredentials()
      fetchStats()
    } catch (err) {
      setMessage({ type: 'error', text: err.response?.data?.detail || '删除失败' })
    }
  }

  return (
    <div className="min-h-screen">
      {/* 导航栏 */}
      <nav className="bg-dark-900 border-b border-dark-700">
        <div className="max-w-4xl mx-auto px-4 py-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <Cat className="w-8 h-8 text-purple-400" />
            <span className="text-xl font-bold">Catiecli</span>
            <span className="text-sm text-orange-400 bg-orange-500/20 px-2 py-0.5 rounded flex items-center gap-1">
              <Rocket size={14} />
              Antigravity 凭证
            </span>
          </div>
          <Link to="/dashboard" className="text-gray-400 hover:text-white flex items-center gap-2">
            <ArrowLeft size={20} />
            返回
          </Link>
        </div>
      </nav>

      <div className="max-w-4xl mx-auto px-4 py-8">
        {/* 统计信息 */}
        {stats && (
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
            <div className="card p-4">
              <div className="text-2xl font-bold text-orange-400">{stats.total}</div>
              <div className="text-xs text-gray-400">总凭证</div>
            </div>
            <div className="card p-4">
              <div className="text-2xl font-bold text-green-400">{stats.active}</div>
              <div className="text-xs text-gray-400">活跃凭证</div>
            </div>
            <div className="card p-4">
              <div className="text-2xl font-bold text-purple-400">{stats.public}</div>
              <div className="text-xs text-gray-400">公开凭证</div>
            </div>
            <div className="card p-4">
              <div className="text-2xl font-bold text-cyan-400">{stats.user_active}</div>
              <div className="text-xs text-gray-400">我的活跃</div>
            </div>
          </div>
        )}

        {/* 消息提示 */}
        {message.text && (
          <div className={`mb-6 p-4 rounded-xl border ${
            message.type === 'success' 
              ? 'bg-green-500/10 border-green-500/30 text-green-400' 
              : 'bg-red-500/10 border-red-500/30 text-red-400'
          }`}>
            {message.text}
          </div>
        )}

        {/* 上传区域 */}
        <div className="card p-6 mb-6">
          <h2 className="text-lg font-semibold mb-4 flex items-center gap-2">
            <Upload className="text-orange-400" />
            上传 Antigravity 凭证
          </h2>
          
          <div className="space-y-4">
            <div 
              className={`border-2 border-dashed rounded-lg p-6 text-center transition-colors ${
                dragOver ? 'border-orange-500 bg-orange-500/10' : 'border-dark-600 hover:border-orange-500'
              }`}
              onDragOver={(e) => { e.preventDefault(); setDragOver(true) }}
              onDragLeave={() => setDragOver(false)}
              onDrop={(e) => {
                e.preventDefault()
                setDragOver(false)
                const files = Array.from(e.dataTransfer.files).filter(f => f.name.endsWith('.json') || f.name.endsWith('.zip'))
                if (files.length > 0) setUploadFiles(prev => [...prev, ...files])
              }}
            >
              <input
                type="file"
                accept=".json,.zip"
                multiple
                onChange={(e) => setUploadFiles(prev => [...prev, ...Array.from(e.target.files)])}
                className="hidden"
                id="antigravity-file-input"
              />
              <label htmlFor="antigravity-file-input" className="cursor-pointer block">
                <Rocket size={32} className="mx-auto mb-3 text-orange-400" />
                <div className="text-gray-300 mb-1">
                  {uploadFiles.length > 0 
                    ? `已选择 ${uploadFiles.length} 个文件` 
                    : '点击或拖拽 JSON/ZIP 文件'}
                </div>
                <div className="text-xs text-gray-500">Antigravity 凭证会自动获取 project_id</div>
              </label>
            </div>
            
            {/* 已选文件列表 */}
            {uploadFiles.length > 0 && (
              <div className="bg-dark-800 rounded-lg p-3 space-y-2">
                <div className="text-xs text-gray-400 mb-2">已选择的文件：</div>
                {uploadFiles.map((file, idx) => (
                  <div key={idx} className="flex items-center justify-between text-sm bg-dark-700 rounded px-3 py-2">
                    <span className="truncate">{file.name}</span>
                    <button 
                      onClick={() => setUploadFiles(prev => prev.filter((_, i) => i !== idx))}
                      className="text-red-400 hover:text-red-300 ml-2"
                    >
                      ✕
                    </button>
                  </div>
                ))}
                <button 
                  onClick={() => { setUploadFiles([]); document.getElementById('antigravity-file-input').value = '' }}
                  className="text-xs text-gray-500 hover:text-gray-400"
                >
                  清空全部
                </button>
              </div>
            )}

            <div className="flex items-center justify-between">
              <label className="flex items-center gap-3 cursor-pointer p-3 bg-orange-500/10 border border-orange-500/30 rounded-lg hover:bg-orange-500/20 transition-colors">
                <input
                  type="checkbox"
                  checked={uploadPublic}
                  onChange={(e) => setUploadPublic(e.target.checked)}
                  className="w-5 h-5 rounded"
                />
                <div>
                  <div className="text-orange-400 font-medium flex items-center gap-2">
                    <Gift size={16} />
                    上传到公共池
                  </div>
                  <div className="text-xs text-orange-300/70">分享凭证，共同使用</div>
                </div>
              </label>

              <button
                onClick={uploadCredential}
                disabled={uploading || uploadFiles.length === 0}
                className="px-6 py-3 bg-orange-600 hover:bg-orange-700 disabled:opacity-50 text-white rounded-lg flex items-center gap-2 font-medium"
              >
                {uploading ? <RefreshCw className="animate-spin" size={18} /> : <Upload size={18} />}
                {uploading ? '上传中...' : '上传凭证'}
              </button>
            </div>
          </div>
        </div>

        {/* 凭证列表 */}
        <div className="card p-6">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-lg font-semibold flex items-center gap-2">
              <Shield className="text-orange-400" />
              我的 Antigravity 凭证 ({credentials.length})
            </h2>
            <div className="flex items-center gap-2">
              {credentials.some(c => !c.is_active) && (
                <button
                  onClick={deleteAllInactive}
                  className="text-red-400 hover:text-red-300 text-xs px-2 py-1 border border-red-500/30 rounded hover:bg-red-500/10"
                  title="删除所有失效凭证"
                >
                  清理失效
                </button>
              )}
              <Link
                to="/antigravity-oauth"
                className="px-3 py-1.5 bg-orange-600 hover:bg-orange-500 text-white rounded text-xs font-medium flex items-center gap-1"
              >
                <ExternalLink size={14} />
                获取新凭证
              </Link>
              <button
                onClick={() => { fetchCredentials(); fetchStats() }}
                className="text-gray-400 hover:text-white p-2"
                title="刷新"
              >
                <RefreshCw size={18} />
              </button>
            </div>
          </div>

          {loading ? (
            <div className="text-center py-8 text-gray-400">
              <RefreshCw className="animate-spin mx-auto mb-2" />
              加载中...
            </div>
          ) : credentials.length === 0 ? (
            <div className="text-center py-12 text-gray-500">
              <Rocket size={48} className="mx-auto mb-4 opacity-30" />
              <p>暂无 Antigravity 凭证</p>
              <p className="text-sm mt-2">上传 JSON 文件或通过 OAuth 获取凭证</p>
              <Link
                to="/antigravity-oauth"
                className="inline-flex items-center gap-2 px-6 py-3 mt-4 bg-orange-600 hover:bg-orange-500 text-white rounded-lg"
              >
                <ExternalLink size={18} />
                获取 Antigravity 凭证
              </Link>
            </div>
          ) : (
            <div className="space-y-3">
              {credentials.map(cred => (
                <div 
                  key={cred.id} 
                  className={`p-4 rounded-lg border transition-colors ${
                    cred.is_active 
                      ? 'bg-dark-800 border-dark-600' 
                      : 'bg-dark-900 border-dark-700 opacity-60'
                  }`}
                >
                  <div className="flex items-center justify-between">
                    <div className="flex-1 min-w-0">
                      {/* 凭证名称 */}
                      <div className="text-gray-400 italic mb-2 truncate">
                        {cred.email || cred.name}
                      </div>
                      
                      {/* 状态标签行 */}
                      <div className="flex items-center gap-2 mb-2 flex-wrap">
                        {/* 启用状态 */}
                        {cred.is_active ? (
                          <span className="text-xs px-2.5 py-1 bg-green-600 text-white rounded font-medium">
                            有效
                          </span>
                        ) : (
                          <span className="text-xs px-2.5 py-1 bg-red-600 text-white rounded font-medium">
                            ❌ 已失效
                          </span>
                        )}
                        
                        {/* Antigravity 标签 */}
                        <span className="text-xs px-2.5 py-1 bg-orange-500/20 text-orange-400 rounded font-medium">
                          🚀 Antigravity
                        </span>
                        
                        {/* 公开状态 */}
                        {cred.is_public && (
                          <span className="text-xs px-2.5 py-1 border border-purple-500 text-purple-400 rounded font-medium">
                            已公开
                          </span>
                        )}
                      </div>
                      
                      {/* Project ID */}
                      {cred.project_id && (
                        <div className="text-xs text-gray-500 truncate mb-1">
                          Project: {cred.project_id}
                        </div>
                      )}
                      
                      {/* 信息行 */}
                      <div className="text-xs text-gray-500">
                        最后使用: {cred.last_used_at ? new Date(cred.last_used_at).toLocaleString() : '从未使用'}
                      </div>
                    </div>
                    
                    <div className="flex items-center gap-2 ml-4 flex-wrap">
                      {/* 启用/禁用 */}
                      <button
                        onClick={() => toggleActive(cred.id, cred.is_active)}
                        className={`px-3 py-1.5 rounded text-xs font-medium ${
                          cred.is_active 
                            ? 'bg-amber-600 hover:bg-amber-500 text-white' 
                            : 'bg-green-600 hover:bg-green-500 text-white'
                        }`}
                      >
                        {cred.is_active ? '禁用' : '启用'}
                      </button>
                      
                      {/* 检测 */}
                      <button
                        onClick={() => verifyCred(cred.id, cred.email || cred.name)}
                        disabled={verifying === cred.id}
                        className="px-3 py-1.5 rounded text-xs font-medium bg-cyan-600 hover:bg-cyan-500 text-white disabled:opacity-50 flex items-center gap-1"
                      >
                        {verifying === cred.id ? (
                          <RefreshCw size={12} className="animate-spin" />
                        ) : (
                          <CheckCircle size={12} />
                        )}
                        检测
                      </button>
                      
                      {/* 刷新 Project ID */}
                      <button
                        onClick={() => refreshProjectId(cred.id, cred.email || cred.name)}
                        disabled={verifying === cred.id}
                        className="px-3 py-1.5 rounded text-xs font-medium bg-orange-600 hover:bg-orange-500 text-white disabled:opacity-50 flex items-center gap-1"
                        title="重新获取 Project ID"
                      >
                        <RefreshCw size={12} />
                        刷新ID
                      </button>
                      
                      {/* 查看额度 */}
                      <button
                        onClick={() => fetchQuota(cred.id, cred.email || cred.name)}
                        disabled={loadingQuota === cred.id || !cred.is_active}
                        className="px-3 py-1.5 rounded text-xs font-medium bg-emerald-600 hover:bg-emerald-500 text-white disabled:opacity-50 flex items-center gap-1"
                        title={!cred.is_active ? '凭证无效，无法查询额度' : '查看各模型额度'}
                      >
                        {loadingQuota === cred.id ? (
                          <RefreshCw size={12} className="animate-spin" />
                        ) : (
                          '📊'
                        )}
                        额度
                      </button>
                      
                      {/* 导出 */}
                      <button
                        onClick={() => exportCred(cred.id, cred.email)}
                        className="px-3 py-1.5 rounded text-xs font-medium bg-blue-600 hover:bg-blue-500 text-white flex items-center gap-1"
                      >
                        <Download size={12} />
                        导出
                      </button>
                      
                      {/* 捐赠/取消捐赠 */}
                      <button
                        onClick={() => togglePublic(cred.id, cred.is_public)}
                        disabled={!cred.is_public && !cred.is_active}
                        title={!cred.is_public && !cred.is_active ? '请先检测凭证有效后再设为公开' : ''}
                        className={`px-3 py-1.5 rounded text-xs font-medium ${
                          cred.is_public 
                            ? 'bg-gray-600 hover:bg-gray-500 text-white' 
                            : !cred.is_active
                              ? 'bg-gray-700 text-gray-500 cursor-not-allowed'
                              : 'bg-purple-600 hover:bg-purple-500 text-white'
                        }`}
                      >
                        {cred.is_public ? '取消公开' : '设为公开'}
                      </button>
                      
                      {/* 删除 */}
                      <button
                        onClick={() => deleteCred(cred.id)}
                        className="p-1.5 text-red-400 hover:text-red-300 hover:bg-red-500/10 rounded"
                        title="删除"
                      >
                        <Trash2 size={16} />
                      </button>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* 说明 */}
        <div className="mt-6 p-4 bg-orange-500/10 border border-orange-500/30 rounded-xl text-sm">
          <div className="text-orange-400 font-medium mb-2">🚀 Antigravity API 说明</div>
          <ul className="text-orange-300/70 space-y-1">
            <li>• Antigravity 凭证与 GeminiCLI 凭证是独立的，不能混用</li>
            <li>• 上传后会自动使用 Antigravity 方式获取 project_id</li>
            <li>• 调用端点: <code className="bg-dark-800 px-1 rounded">/agy/v1/chat/completions</code></li>
          </ul>
        </div>
      </div>

      {/* 检测结果弹窗 */}
      {verifyResult && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4">
          <div className="bg-dark-800 rounded-2xl w-full max-w-md overflow-hidden">
            <div className="flex items-center justify-between p-4 border-b border-dark-600">
              <h3 className="text-lg font-semibold flex items-center gap-2">
                {verifyResult.is_project_id_refresh ? (
                  <RefreshCw className={verifyResult.is_valid ? "text-green-400" : "text-red-400"} />
                ) : (
                  <CheckCircle className={verifyResult.is_valid ? "text-green-400" : "text-red-400"} />
                )}
                {verifyResult.is_project_id_refresh ? '刷新 Project ID 结果' : '凭证检测结果'}
              </h3>
              <button onClick={() => setVerifyResult(null)} className="p-2 hover:bg-dark-600 rounded-lg">
                <X size={20} />
              </button>
            </div>
            
            <div className="p-6 space-y-4">
              {/* 邮箱 */}
              <div className="text-gray-400 text-sm">{verifyResult.email}</div>
              
              {/* 状态 */}
              <div className="flex items-center gap-3">
                <span className="text-gray-400">状态</span>
                <span className={`px-3 py-1 rounded-full text-sm font-medium ${
                  verifyResult.is_valid ? 'bg-green-500/20 text-green-400' : 'bg-red-500/20 text-red-400'
                }`}>
                  {verifyResult.is_project_id_refresh 
                    ? (verifyResult.is_valid ? '✅ 刷新成功' : '❌ 刷新失败')
                    : (verifyResult.is_valid ? '✅ 有效' : '❌ 无效')}
                </span>
              </div>
              
              {/* Project ID */}
              {verifyResult.project_id && (
                <div className="flex items-center gap-3">
                  <span className="text-gray-400">Project ID</span>
                  <span className="px-3 py-1 rounded-full text-sm font-medium bg-orange-500/20 text-orange-400 truncate max-w-[200px]">
                    {verifyResult.project_id}
                  </span>
                </div>
              )}
              
              {verifyResult.is_project_id_refresh && verifyResult.old_project_id && verifyResult.is_valid && (
                <div className="flex items-center gap-3">
                  <span className="text-gray-400">旧 ID</span>
                  <span className="px-3 py-1 rounded-full text-sm font-medium bg-gray-600/50 text-gray-300 line-through truncate max-w-[200px]">
                    {verifyResult.old_project_id}
                  </span>
                </div>
              )}
              
              {/* 错误信息 */}
              {verifyResult.error && (
                <div className="p-3 bg-red-500/10 border border-red-500/30 rounded-lg text-red-400 text-sm">
                  {verifyResult.error}
                </div>
              )}
            </div>
            
            <div className="p-4 border-t border-dark-600 flex justify-end">
              <button
                onClick={() => setVerifyResult(null)}
                className="px-6 py-2 bg-dark-600 hover:bg-dark-500 text-white rounded-lg"
              >
                关闭
              </button>
            </div>
          </div>
        </div>
      )}

      {/* 额度查询弹窗 */}
      {quotaResult && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4">
          <div className="bg-dark-800 rounded-2xl w-full max-w-2xl max-h-[80vh] overflow-hidden">
            <div className="flex items-center justify-between p-4 border-b border-dark-600">
              <h3 className="text-lg font-semibold flex items-center gap-2">
                <span className="text-2xl">📊</span>
                额度信息详情
              </h3>
              <button onClick={() => setQuotaResult(null)} className="p-2 hover:bg-dark-600 rounded-lg">
                <X size={20} />
              </button>
            </div>
            
            <div className="p-6 overflow-y-auto max-h-[60vh]">
              {/* 凭证名称 */}
              <div className="text-sm text-gray-400 mb-4 bg-cyan-500/10 border border-cyan-500/30 rounded-lg p-2">
                文件: {quotaResult.filename || quotaResult.email}
              </div>
              
              {quotaResult.success ? (
                <>
                  {Object.keys(quotaResult.models || {}).length > 0 ? (
                    <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                      {Object.entries(quotaResult.models).map(([modelId, data]) => {
                        const remaining = data.remaining || 0
                        const colorClass = remaining >= 80 ? 'bg-green-500' :
                                          remaining >= 40 ? 'bg-yellow-500' :
                                          remaining >= 20 ? 'bg-orange-500' : 'bg-red-500'
                        return (
                          <div key={modelId} className="bg-dark-700 rounded-lg p-3">
                            <div className="text-xs text-gray-400 truncate mb-2" title={modelId}>
                              {modelId}
                            </div>
                            <div className="flex items-center justify-between mb-1">
                              <span className={`text-lg font-bold ${
                                remaining >= 80 ? 'text-green-400' :
                                remaining >= 40 ? 'text-yellow-400' :
                                remaining >= 20 ? 'text-orange-400' : 'text-red-400'
                              }`}>
                                {remaining}%
                              </span>
                            </div>
                            <div className="w-full bg-dark-600 rounded-full h-1.5 mb-2">
                              <div
                                className={`h-1.5 rounded-full ${colorClass}`}
                                style={{ width: `${Math.min(remaining, 100)}%` }}
                              />
                            </div>
                            <div className="text-[10px] text-gray-500 flex items-center gap-1">
                              📅 {data.resetTime || 'N/A'}
                            </div>
                          </div>
                        )
                      })}
                    </div>
                  ) : (
                    <div className="text-center py-8 text-gray-500">
                      没有额度数据
                    </div>
                  )}
                </>
              ) : (
                <div className="p-4 bg-red-500/10 border border-red-500/30 rounded-lg text-red-400">
                  {quotaResult.error || '获取额度失败'}
                </div>
              )}
            </div>
            
            <div className="p-4 border-t border-dark-600 flex justify-end">
              <button
                onClick={() => setQuotaResult(null)}
                className="px-6 py-2 bg-dark-600 hover:bg-dark-500 text-white rounded-lg"
              >
                关闭
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}