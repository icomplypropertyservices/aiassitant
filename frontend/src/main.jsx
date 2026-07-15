import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { ConfigProvider } from 'antd'
import App from './App'

ReactDOM.createRoot(document.getElementById('root')).render(
  <ConfigProvider theme={{ token: { colorPrimary: '#1668dc', borderRadius: 6 } }}>
    <BrowserRouter><App /></BrowserRouter>
  </ConfigProvider>
)
