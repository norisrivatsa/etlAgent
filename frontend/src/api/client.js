/**
 * API client for ETL Agent backend
 */

async function request(path, options = {}) {
  const response = await fetch(path, {
    headers: { 'Content-Type': 'application/json', ...options.headers },
    ...options,
  })

  const text = await response.text()
  const data = text ? JSON.parse(text) : null

  if (!response.ok) {
    const detail = data?.detail || response.statusText
    throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail))
  }

  return data
}

export const api = {
  // Sessions
  async listSessions(limit = 50) {
    return request(`/sessions?limit=${limit}`)
  },

  async createSession(pipelineName, config = {}, initialRequirements = {}) {
    return request('/sessions', {
      method: 'POST',
      body: JSON.stringify({ pipeline_name: pipelineName, config, initial_requirements: initialRequirements }),
    })
  },

  async getSession(sessionId) {
    return request(`/sessions/${sessionId}`)
  },

  async getSessionState(sessionId) {
    return Promise.all([
      request(`/sessions/${sessionId}`),
      request(`/sessions/${sessionId}/events?limit=100`),
    ]).then(([session, eventList]) => ({
      session,
      events: eventList.events || [],
    }))
  },

  // Chat messages
  async getChatMessages(sessionId, limit = 100) {
    return request(`/sessions/${sessionId}/chat-messages?limit=${limit}`)
  },

  async sendChatMessage(sessionId, message, artifactId = null) {
    return request(`/sessions/${sessionId}/chat-messages`, {
      method: 'POST',
      body: JSON.stringify({ message, artifact_id: artifactId }),
    })
  },

  async starMessage(sessionId, messageId, starred) {
    return request(`/sessions/${sessionId}/chat-messages/${messageId}/star`, {
      method: 'POST',
      body: JSON.stringify({ starred }),
    })
  },

  // Legacy message endpoint (for backward compatibility)
  async sendMessage(sessionId, message) {
    return request(`/sessions/${sessionId}/message`, {
      method: 'POST',
      body: JSON.stringify({ message }),
    })
  },

  // Approval
  async approveSession(sessionId, approved, comment = null) {
    return request(`/sessions/${sessionId}/approve`, {
      method: 'POST',
      body: JSON.stringify({ approved, comment }),
    })
  },

  async approveArtifact(sessionId, artifactId, approved, comment = null) {
    return request(`/sessions/${sessionId}/artifacts/${artifactId}/approve`, {
      method: 'POST',
      body: JSON.stringify({ approved, comment }),
    })
  },

  // Deployment
  async deploySession(sessionId, mode = 'package') {
    return request(`/sessions/${sessionId}/deploy`, {
      method: 'POST',
      body: JSON.stringify({ mode }),
    })
  },

  // Verification
  async verifySession(sessionId, verificationRequest) {
    return request(`/sessions/${sessionId}/verify`, {
      method: 'POST',
      body: JSON.stringify(verificationRequest),
    })
  },

  // Events
  async getEvents(sessionId, after = null, limit = 100) {
    const afterParam = after ? `&after=${encodeURIComponent(after)}` : ''
    return request(`/sessions/${sessionId}/events?limit=${limit}${afterParam}`)
  },

  // Whiteboard
  async getWhiteboard(sessionId) {
    return request(`/sessions/${sessionId}/whiteboard`)
  },
}
