import { ArrowLeft, Save, Settings as SettingsIcon } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import api from '../api'

export default function Settings() {
  const navigate = useNavigate()
  const [config, setConfig] = useState(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [message, setMessage] = useState(null)

  useEffect(() => {
    fetchConfig()
  }, [])

  const fetchConfig = async () => {
    try {
      const res = await api.get('/api/manage/config')
      setConfig(res.data)
    } catch (err) {
      if (err.response?.status === 401 || err.response?.status === 403) {
        navigate('/login')
      }
    } finally {
      setLoading(false)
    }
  }

  const handleSave = async () => {
    setSaving(true)
    setMessage(null)
    try {
      const formData = new FormData()
      formData.append('allow_registration', config.allow_registration)
      formData.append('discord_only_registration', config.discord_only_registration)
      formData.append('discord_oauth_only', config.discord_oauth_only)
      formData.append('no_cred_quota_flash', config.no_cred_quota_flash ?? 100)
      formData.append('no_cred_quota_25pro', config.no_cred_quota_25pro ?? 50)
      formData.append('no_cred_quota_30pro', config.no_cred_quota_30pro ?? 0)
      formData.append('cred25_quota_30pro', config.cred25_quota_30pro ?? 0)
      formData.append('credential_reward_quota', config.credential_reward_quota)
      formData.append('quota_flash', config.quota_flash ?? 1000)
      formData.append('quota_25pro', config.quota_25pro ?? 500)
      formData.append('quota_30pro', config.quota_30pro ?? 300)
      formData.append('base_rpm', config.base_rpm)
      formData.append('contributor_rpm', config.contributor_rpm)
      formData.append('error_retry_count', config.error_retry_count)
      formData.append('cd_flash', config.cd_flash ?? 0)
      formData.append('cd_pro', config.cd_pro ?? 4)
      formData.append('cd_30', config.cd_30 ?? 4)
      formData.append('credential_pool_mode', config.credential_pool_mode)
      formData.append('force_donate', config.force_donate)
      formData.append('lock_donate', config.lock_donate)
      formData.append('announcement_enabled', config.announcement_enabled)
      formData.append('announcement_title', config.announcement_title || '')
      formData.append('announcement_content', config.announcement_content || '')
      formData.append('announcement_read_seconds', config.announcement_read_seconds || 5)
      formData.append('stats_quota_flash', config.stats_quota_flash ?? 0)
      formData.append('stats_quota_25pro', config.stats_quota_25pro ?? 0)
      formData.append('stats_quota_30pro', config.stats_quota_30pro ?? 0)
      formData.append('antigravity_enabled', config.antigravity_enabled)
      
      await api.post('/api/manage/config', formData)
      setMessage({ type: 'success', text: '配置已保存！' })
      // 保存成功后滚动到顶部
      window.scrollTo({ top: 0, behavior: 'smooth' })
    } catch (err) {
      setMessage({ type: 'error', text: '保存失败: ' + (err.response?.data?.detail || err.message) })
    } finally {
      setSaving(false)
    }
  }

  if (loading) {
    return (
      <div className="min-h-screen bg-gray-900 flex items-center justify-center">
        <div className="text-white">加载中...</div>
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-gray-900 text-white p-6">
      <div className="max-w-2xl mx-auto">
        <div className="flex justify-between items-center mb-8">
          <h1 className="text-3xl font-bold flex items-center gap-3">
            <SettingsIcon className="text-purple-400" />
            系统设置
          </h1>
          <button
            onClick={() => navigate('/dashboard')}
            className="px-4 py-2 bg-gray-700 rounded-lg hover:bg-gray-600 flex items-center gap-2"
          >
            <ArrowLeft size={18} />
            返回
          </button>
        </div>

        {message && (
          <div className={`mb-6 p-4 rounded-lg ${message.type === 'success' ? 'bg-green-600/20 text-green-400' : 'bg-red-600/20 text-red-400'}`}>
            {message.text}
          </div>
        )}

        <div className="bg-gray-800 rounded-xl p-6 space-y-6">
          {/* 用户注册 */}
          <div className="flex justify-between items-center">
            <div>
              <h3 className="font-semibold">允许用户注册</h3>
              <p className="text-gray-400 text-sm">关闭后新用户无法注册账号</p>
            </div>
            <label className="relative inline-flex items-center cursor-pointer">
              <input
                type="checkbox"
                checked={config?.allow_registration || false}
                onChange={(e) => setConfig({ ...config, allow_registration: e.target.checked })}
                className="sr-only peer"
              />
              <div className="w-11 h-6 bg-gray-600 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-purple-600"></div>
            </label>
          </div>

          {/* 仅 Discord Bot 注册 */}
          <div className="flex justify-between items-center">
            <div>
              <h3 className="font-semibold">仅允许 Discord Bot 注册</h3>
              <p className="text-gray-400 text-sm">开启后只能通过 Discord Bot 注册，网页注册将被禁用</p>
            </div>
            <label className="relative inline-flex items-center cursor-pointer">
              <input
                type="checkbox"
                checked={config?.discord_only_registration || false}
                onChange={(e) => setConfig({ ...config, discord_only_registration: e.target.checked })}
                className="sr-only peer"
              />
              <div className="w-11 h-6 bg-gray-600 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-blue-600"></div>
            </label>
          </div>

          {/* 仅 Discord OAuth 注册 */}
          <div className="flex justify-between items-center">
            <div>
              <h3 className="font-semibold">仅允许 Discord 登录注册</h3>
              <p className="text-gray-400 text-sm">开启后只能通过网页 Discord 登录注册，普通注册将被禁用</p>
            </div>
            <label className="relative inline-flex items-center cursor-pointer">
              <input
                type="checkbox"
                checked={config?.discord_oauth_only || false}
                onChange={(e) => setConfig({ ...config, discord_oauth_only: e.target.checked })}
                className="sr-only peer"
              />
              <div className="w-11 h-6 bg-gray-600 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-indigo-600"></div>
            </label>
          </div>

          {/* 无凭证用户按模型配额 */}
          <div>
            <h3 className="font-semibold mb-2">无凭证用户按模型配额 🔒</h3>
            <p className="text-gray-400 text-sm mb-3">无凭证用户各类模型的每日配额（0 = 禁止使用该类模型）</p>
            <div className="grid grid-cols-3 gap-4">
              <div>
                <label className="text-sm text-gray-400 mb-1 block">Flash 配额</label>
                <input
                  type="number"
                  value={config?.no_cred_quota_flash ?? ''}
                  onChange={(e) => setConfig({ ...config, no_cred_quota_flash: e.target.value === '' ? '' : parseInt(e.target.value) })}
                  className="w-full bg-gray-700 rounded-lg px-4 py-2 focus:outline-none focus:ring-2 focus:ring-cyan-500"
                />
              </div>
              <div>
                <label className="text-sm text-gray-400 mb-1 block">2.5 Pro 配额</label>
                <input
                  type="number"
                  value={config?.no_cred_quota_25pro ?? ''}
                  onChange={(e) => setConfig({ ...config, no_cred_quota_25pro: e.target.value === '' ? '' : parseInt(e.target.value) })}
                  className="w-full bg-gray-700 rounded-lg px-4 py-2 focus:outline-none focus:ring-2 focus:ring-orange-500"
                />
              </div>
              <div>
                <label className="text-sm text-gray-400 mb-1 block">3.0 配额</label>
                <input
                  type="number"
                  value={config?.no_cred_quota_30pro ?? ''}
                  onChange={(e) => setConfig({ ...config, no_cred_quota_30pro: e.target.value === '' ? '' : parseInt(e.target.value) })}
                  className="w-full bg-gray-700 rounded-lg px-4 py-2 focus:outline-none focus:ring-2 focus:ring-pink-500"
                />
              </div>
            </div>
            <p className="text-gray-500 text-sm mt-2">
              💡 设为 0 表示禁止无凭证用户使用该类模型
            </p>
          </div>

          {/* 2.5凭证用户的3.0配额 */}
          <div>
            <h3 className="font-semibold mb-2">2.5凭证用户 3.0 配额 🎯</h3>
            <p className="text-gray-400 text-sm mb-3">只有2.5凭证（无3.0凭证）的用户可使用的3.0模型配额（0 = 禁止）</p>
            <input
              type="number"
              value={config?.cred25_quota_30pro ?? ''}
              onChange={(e) => setConfig({ ...config, cred25_quota_30pro: e.target.value === '' ? '' : parseInt(e.target.value) })}
              className="w-full bg-gray-700 rounded-lg px-4 py-2 focus:outline-none focus:ring-2 focus:ring-purple-500"
            />
            <p className="text-gray-500 text-sm mt-2">
              💡 允许2.5凭证用户体验3.0模型，设为0则只有3.0凭证用户可用
            </p>
          </div>

          {/* 全站统计额度配置 */}
          <div>
            <h3 className="font-semibold mb-2">全站统计额度 📊</h3>
            <p className="text-gray-400 text-sm mb-3">统计页面显示的每个凭证贡献的额度基数</p>
            <div className="grid grid-cols-3 gap-4">
              <div>
                <label className="text-sm text-gray-400 mb-1 block">Flash 额度/凭证</label>
                <input
                  type="number"
                  value={config?.stats_quota_flash ?? ''}
                  onChange={(e) => setConfig({ ...config, stats_quota_flash: e.target.value === '' ? '' : parseInt(e.target.value) })}
                  className="w-full bg-gray-700 rounded-lg px-4 py-2 focus:outline-none focus:ring-2 focus:ring-cyan-500"
                />
              </div>
              <div>
                <label className="text-sm text-gray-400 mb-1 block">2.5 Pro 额度/凭证</label>
                <input
                  type="number"
                  value={config?.stats_quota_25pro ?? ''}
                  onChange={(e) => setConfig({ ...config, stats_quota_25pro: e.target.value === '' ? '' : parseInt(e.target.value) })}
                  className="w-full bg-gray-700 rounded-lg px-4 py-2 focus:outline-none focus:ring-2 focus:ring-orange-500"
                />
              </div>
              <div>
                <label className="text-sm text-gray-400 mb-1 block">3.0 额度/凭证</label>
                <input
                  type="number"
                  value={config?.stats_quota_30pro ?? ''}
                  onChange={(e) => setConfig({ ...config, stats_quota_30pro: e.target.value === '' ? '' : parseInt(e.target.value) })}
                  className="w-full bg-gray-700 rounded-lg px-4 py-2 focus:outline-none focus:ring-2 focus:ring-pink-500"
                />
              </div>
            </div>
            <p className="text-gray-500 text-sm mt-2">
              💡 统计页显示: Flash={config?.stats_quota_flash || 1000}×活跃凭证数, 2.5Pro={config?.stats_quota_25pro || 250}×活跃凭证数, 3.0={config?.stats_quota_30pro || 200}×3.0凭证数
            </p>
          </div>

          {/* 凭证奖励 - 按模型分类 */}
          <div>
            <h3 className="font-semibold mb-2">凭证上传奖励额度 🎁</h3>
            <p className="text-gray-400 text-sm mb-3">按模型分类的额度配置，2.5凭证=Flash+2.5Pro，3.0凭证=Flash+2.5Pro+3.0</p>
            <div className="grid grid-cols-3 gap-4">
              <div>
                <label className="text-sm text-gray-400 mb-1 block">Flash 额度</label>
                <input
                  type="number"
                  value={config?.quota_flash ?? ''}
                  onChange={(e) => setConfig({ ...config, quota_flash: e.target.value === '' ? '' : parseInt(e.target.value) })}
                  className="w-full bg-gray-700 rounded-lg px-4 py-2 focus:outline-none focus:ring-2 focus:ring-cyan-500"
                />
              </div>
              <div>
                <label className="text-sm text-gray-400 mb-1 block">2.5 Pro 额度</label>
                <input
                  type="number"
                  value={config?.quota_25pro ?? ''}
                  onChange={(e) => setConfig({ ...config, quota_25pro: e.target.value === '' ? '' : parseInt(e.target.value) })}
                  className="w-full bg-gray-700 rounded-lg px-4 py-2 focus:outline-none focus:ring-2 focus:ring-orange-500"
                />
              </div>
              <div>
                <label className="text-sm text-gray-400 mb-1 block">3.0 额度</label>
                <input
                  type="number"
                  value={config?.quota_30pro ?? ''}
                  onChange={(e) => setConfig({ ...config, quota_30pro: e.target.value === '' ? '' : parseInt(e.target.value) })}
                  className="w-full bg-gray-700 rounded-lg px-4 py-2 focus:outline-none focus:ring-2 focus:ring-pink-500"
                />
              </div>
            </div>
            <p className="text-green-400 text-sm mt-2">
              💡 2.5凭证 +{(config?.quota_flash ?? 1000) + (config?.quota_25pro ?? 500)} | 3.0凭证 +{(config?.quota_flash ?? 1000) + (config?.quota_25pro ?? 500) + (config?.quota_30pro ?? 300)}
            </p>
          </div>

          {/* 凭证池模式 */}
          <div>
            <h3 className="font-semibold mb-2">凭证池模式 🏊</h3>
            <p className="text-gray-400 text-sm mb-3">控制用户如何共享凭证</p>
            <select
              value={config?.credential_pool_mode || 'full_shared'}
              onChange={(e) => setConfig({ ...config, credential_pool_mode: e.target.value })}
              className="w-full bg-gray-700 rounded-lg px-4 py-3 focus:outline-none focus:ring-2 focus:ring-purple-500"
            >
              <option value="private">🔒 私有模式 - 只能用自己的凭证</option>
              <option value="tier3_shared">⚡ 3.0小锅饭 - 适合凭证较少时</option>
              <option value="full_shared">🍲 大锅饭 - 适合凭证较多时</option>
            </select>
            <div className="mt-2 text-sm space-y-1">
              {config?.credential_pool_mode === 'private' && (
                <p className="text-yellow-400">⚠️ 用户只能使用自己上传的凭证</p>
              )}
              {config?.credential_pool_mode === 'tier3_shared' && (
                <>
                  <p className="text-blue-400">💎 有3.0凭证 → 可用公共3.0池 + 自己的</p>
                  <p className="text-cyan-400">📘 无3.0凭证 → 可用公共2.5凭证</p>
                </>
              )}
              {config?.credential_pool_mode === 'full_shared' && (
                <>
                  <p className="text-green-400">🎉 上传凭证后可使用所有公共凭证（2.5+3.0）</p>
                  <p className="text-gray-400">🚫 未上传只能用自己的凭证</p>
                </>
              )}
            </div>
          </div>

          {/* 强制公开 */}
          <div className="flex items-center justify-between bg-gray-700/50 rounded-lg px-4 py-3">
            <div>
              <h3 className="font-semibold">强制公开 🤝</h3>
              <p className="text-gray-400 text-sm">上传凭证时强制设为公开，不给选择</p>
            </div>
            <label className="relative inline-flex items-center cursor-pointer">
              <input
                type="checkbox"
                checked={config?.force_donate ?? false}
                onChange={(e) => setConfig({ ...config, force_donate: e.target.checked })}
                className="sr-only peer"
              />
              <div className="w-11 h-6 bg-gray-600 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-red-500"></div>
            </label>
          </div>

          {/* 锁定公开 */}
          <div className="flex items-center justify-between bg-gray-700/50 rounded-lg px-4 py-3">
            <div>
              <h3 className="font-semibold">锁定公开 🔒</h3>
              <p className="text-gray-400 text-sm">有效凭证不允许取消公开（失效的可以取消）</p>
            </div>
            <label className="relative inline-flex items-center cursor-pointer">
              <input
                type="checkbox"
                checked={config?.lock_donate ?? false}
                onChange={(e) => setConfig({ ...config, lock_donate: e.target.checked })}
                className="sr-only peer"
              />
              <div className="w-11 h-6 bg-gray-600 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-red-500"></div>
            </label>
          </div>

          {/* 速率限制 */}
          <div className="grid grid-cols-2 gap-4">
            <div>
              <h3 className="font-semibold mb-2">基础速率限制 ⏱️</h3>
              <p className="text-gray-400 text-sm mb-3">未上传凭证用户的每分钟请求数</p>
              <input
                type="number"
                value={config?.base_rpm ?? ''}
                onChange={(e) => setConfig({ ...config, base_rpm: e.target.value === '' ? '' : parseInt(e.target.value) })}
                className="w-full bg-gray-700 rounded-lg px-4 py-2 focus:outline-none focus:ring-2 focus:ring-purple-500"
              />
              <p className="text-gray-500 text-sm mt-1">次/分钟</p>
            </div>
            <div>
              <h3 className="font-semibold mb-2">上传者速率限制 🚀</h3>
              <p className="text-gray-400 text-sm mb-3">上传凭证用户的每分钟请求数</p>
              <input
                type="number"
                value={config?.contributor_rpm ?? ''}
                onChange={(e) => setConfig({ ...config, contributor_rpm: e.target.value === '' ? '' : parseInt(e.target.value) })}
                className="w-full bg-gray-700 rounded-lg px-4 py-2 focus:outline-none focus:ring-2 focus:ring-purple-500"
              />
              <p className="text-gray-500 text-sm mt-1">次/分钟</p>
            </div>
          </div>

          {/* 错误重试 */}
          <div>
            <h3 className="font-semibold mb-2">报错切换凭证重试次数 🔄</h3>
            <p className="text-gray-400 text-sm mb-3">遇到 API 错误（如 404、500 等）时自动切换凭证重试的次数</p>
            <input
              type="number"
              min="0"
              max="10"
              value={config?.error_retry_count ?? ''}
              onChange={(e) => setConfig({ ...config, error_retry_count: e.target.value === '' ? '' : parseInt(e.target.value) })}
              className="w-32 bg-gray-700 rounded-lg px-4 py-2 focus:outline-none focus:ring-2 focus:ring-purple-500"
            />
            <p className="text-gray-500 text-sm mt-1">设为 0 则不重试，直接返回错误</p>
            <p className="text-blue-400 text-sm mt-2">
              💡 当凭证请求失败时，系统会自动尝试切换到其他可用凭证重试
            </p>
          </div>

          {/* CD 机制 */}
          <div>
            <h3 className="font-semibold mb-2">凭证冷却时间 (CD) ⏱️</h3>
            <p className="text-gray-400 text-sm mb-3">按模型组设置凭证冷却时间，避免同一凭证被频繁调用（0=无CD）</p>
            <div className="grid grid-cols-3 gap-4">
              <div>
                <label className="text-sm text-gray-400 mb-1 block">Flash CD (秒)</label>
                <input
                  type="number"
                  min="0"
                  value={config?.cd_flash ?? 0}
                  onChange={(e) => setConfig({ ...config, cd_flash: e.target.value === '' ? 0 : parseInt(e.target.value) })}
                  className="w-full bg-gray-700 rounded-lg px-4 py-2 focus:outline-none focus:ring-2 focus:ring-cyan-500"
                />
              </div>
              <div>
                <label className="text-sm text-gray-400 mb-1 block">Pro CD (秒)</label>
                <input
                  type="number"
                  min="0"
                  value={config?.cd_pro ?? 4}
                  onChange={(e) => setConfig({ ...config, cd_pro: e.target.value === '' ? 0 : parseInt(e.target.value) })}
                  className="w-full bg-gray-700 rounded-lg px-4 py-2 focus:outline-none focus:ring-2 focus:ring-orange-500"
                />
              </div>
              <div>
                <label className="text-sm text-gray-400 mb-1 block">3.0 CD (秒)</label>
                <input
                  type="number"
                  min="0"
                  value={config?.cd_30 ?? 4}
                  onChange={(e) => setConfig({ ...config, cd_30: e.target.value === '' ? 0 : parseInt(e.target.value) })}
                  className="w-full bg-gray-700 rounded-lg px-4 py-2 focus:outline-none focus:ring-2 focus:ring-pink-500"
                />
              </div>
            </div>
            <p className="text-gray-500 text-sm mt-2">
              💡 同一凭证在 CD 期间内不会被同模型组再次选中，优先选择已冷却的凭证
            </p>
          </div>

          {/* 公告配置 */}
          <div className="pt-4 border-t border-gray-700">
            <div className="flex justify-between items-center mb-4">
              <div>
                <h3 className="font-semibold">📢 公告功能</h3>
                <p className="text-gray-400 text-sm">向所有用户显示重要通知</p>
              </div>
              <label className="relative inline-flex items-center cursor-pointer">
                <input
                  type="checkbox"
                  checked={config?.announcement_enabled || false}
                  onChange={(e) => setConfig({ ...config, announcement_enabled: e.target.checked })}
                  className="sr-only peer"
                />
                <div className="w-11 h-6 bg-gray-600 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-amber-600"></div>
              </label>
            </div>
            
            {config?.announcement_enabled && (
              <div className="space-y-4 bg-gray-700/30 rounded-lg p-4">
                <div>
                  <label className="block text-sm font-medium mb-2">公告标题</label>
                  <input
                    type="text"
                    value={config?.announcement_title || ''}
                    onChange={(e) => setConfig({ ...config, announcement_title: e.target.value })}
                    placeholder="例如：【重要通知】系统维护公告"
                    className="w-full bg-gray-700 rounded-lg px-4 py-2 focus:outline-none focus:ring-2 focus:ring-amber-500"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium mb-2">公告内容</label>
                  <textarea
                    value={config?.announcement_content || ''}
                    onChange={(e) => setConfig({ ...config, announcement_content: e.target.value })}
                    placeholder="在这里输入公告内容，支持多行文本..."
                    rows={6}
                    className="w-full bg-gray-700 rounded-lg px-4 py-2 focus:outline-none focus:ring-2 focus:ring-amber-500 resize-none"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium mb-2">阅读等待时间（秒）</label>
                  <input
                    type="number"
                    min="0"
                    max="60"
                    value={config?.announcement_read_seconds || 5}
                    onChange={(e) => setConfig({ ...config, announcement_read_seconds: parseInt(e.target.value) || 5 })}
                    className="w-32 bg-gray-700 rounded-lg px-4 py-2 focus:outline-none focus:ring-2 focus:ring-amber-500"
                  />
                  <p className="text-gray-500 text-sm mt-1">用户首次阅读需等待此时间才能关闭公告</p>
                </div>
              </div>
            )}
          </div>

          {/* Antigravity 反代 */}
          <div className="pt-4 border-t border-gray-700">
            <div className="flex justify-between items-center">
              <div>
                <h3 className="font-semibold">🚀 Antigravity 反代</h3>
                <p className="text-gray-400 text-sm">启用 Antigravity API 反代功能（/antigravity 路径）</p>
              </div>
              <label className="relative inline-flex items-center cursor-pointer">
                <input
                  type="checkbox"
                  checked={config?.antigravity_enabled || false}
                  onChange={(e) => setConfig({ ...config, antigravity_enabled: e.target.checked })}
                  className="sr-only peer"
                />
                <div className="w-11 h-6 bg-gray-600 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-green-600"></div>
              </label>
            </div>
            <p className="text-gray-500 text-sm mt-2">
              💡 Antigravity 使用沙盒 API 端点，支持动态模型列表获取
            </p>
          </div>

          {/* 保存按钮 */}
          <div className="pt-4 border-t border-gray-700">
            <button
              onClick={handleSave}
              disabled={saving}
              className="w-full py-3 bg-purple-600 hover:bg-purple-700 rounded-lg font-semibold flex items-center justify-center gap-2 disabled:opacity-50"
            >
              <Save size={18} />
              {saving ? '保存中...' : '保存配置'}
            </button>
          </div>
        </div>

        {/* 提示信息 */}
        <div className="mt-6 bg-green-900/20 border border-green-600/30 rounded-lg p-4">
          <h4 className="text-green-400 font-semibold mb-2">💾 自动保存</h4>
          <p className="text-green-200/80 text-sm">
            配置会自动保存到数据库，重启服务后依然生效。
          </p>
        </div>
      </div>
    </div>
  )
}
