import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { ChatPage } from './components/ChatPage'
import { WhiteboardPage } from './components/WhiteboardPage'
import './App.css'

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Navigate to="/chat" replace />} />
        <Route path="/chat" element={<ChatPage />} />
        <Route path="/chat/:sessionId" element={<ChatPage />} />
        <Route path="/whiteboard/:sessionId" element={<WhiteboardPage />} />
      </Routes>
    </BrowserRouter>
  )
}

export default App
