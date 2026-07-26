import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { AppShell } from './components/layout/AppShell'
import { WhiteboardPage } from './components/whiteboard/WhiteboardPage'
import { WorkspacePage } from './components/workspace/WorkspacePage'

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<AppShell />}>
          <Route path="/" element={<Navigate to="/session" replace />} />
          <Route path="/session" element={<WorkspacePage />} />
          <Route path="/session/:sessionId" element={<WorkspacePage />} />
          <Route path="/session/:sessionId/whiteboard" element={<WhiteboardPage />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}

export default App
