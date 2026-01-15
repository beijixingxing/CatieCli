import { createContext, useContext, useEffect, useState } from 'react'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import api from './api'
import Announcement from './components/Announcement'
import Admin from './pages/Admin'
import AntigravityCredentials from './pages/AntigravityCredentials'
import AntigravityOAuth from './pages/AntigravityOAuth'
import Credentials from './pages/Credentials'
import Dashboard from './pages/Dashboard'
import ErrorMessages from './pages/ErrorMessages'
import Login from './pages/Login'
import OAuth from './pages/OAuth'
import Register from './pages/Register'
import Settings from './pages/Settings'
import Stats from './pages/Stats'

// 认证上下文
export const AuthContext = createContext(null)

export function useAuth() {
  return useContext(AuthContext)
}

function ProtectedRoute({ children, adminOnly = false }) {
  const { user, loading } = useAuth()
  
  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-purple-500"></div>
      </div>
    )
  }
  
  if (!user) {
    return <Navigate to="/login" />
  }
  
  if (adminOnly && !user.is_admin) {
    return <Navigate to="/dashboard" />
  }
  
  return children
}

function App() {
  const [user, setUser] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    const token = localStorage.getItem('token')
    if (token) {
      api.get('/api/auth/me')
        .then(res => setUser(res.data))
        .catch(() => localStorage.removeItem('token'))
        .finally(() => setLoading(false))
    } else {
      setLoading(false)
    }
  }, [])

  const login = (token, userData) => {
    localStorage.setItem('token', token)
    setUser(userData)
  }

  const logout = () => {
    localStorage.removeItem('token')
    setUser(null)
  }

  return (
    <AuthContext.Provider value={{ user, login, logout, loading }}>
      <BrowserRouter>
        <Announcement />
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="/register" element={<Register />} />
          <Route path="/dashboard" element={
            <ProtectedRoute><Dashboard /></ProtectedRoute>
          } />
          <Route path="/admin" element={
            <ProtectedRoute adminOnly><Admin /></ProtectedRoute>
          } />
          <Route path="/oauth" element={
            <ProtectedRoute><OAuth /></ProtectedRoute>
          } />
          <Route path="/credentials" element={
            <ProtectedRoute><Credentials /></ProtectedRoute>
          } />
          <Route path="/antigravity-credentials" element={
            <ProtectedRoute><AntigravityCredentials /></ProtectedRoute>
          } />
          <Route path="/antigravity-oauth" element={
            <ProtectedRoute><AntigravityOAuth /></ProtectedRoute>
          } />
          <Route path="/stats" element={
            <ProtectedRoute adminOnly><Stats /></ProtectedRoute>
          } />
          <Route path="/settings" element={
            <ProtectedRoute adminOnly><Settings /></ProtectedRoute>
          } />
          <Route path="/error-messages" element={
            <ProtectedRoute adminOnly><ErrorMessages /></ProtectedRoute>
          } />
          <Route path="/" element={<Navigate to="/dashboard" />} />
        </Routes>
      </BrowserRouter>
    </AuthContext.Provider>
  )
}

export default App
