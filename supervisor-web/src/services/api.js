/**
 * API Service for Supervisor Console.
 * Interacts with FastAPI Backend Control Plane for call discovery,
 * supervisor stealth token generation, and full transcript inspection.
 */

const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

/**
 * Fetches recent call sessions from PostgreSQL for supervisor selection.
 * @param {number} limit
 * @returns {Promise<Array<{id: string, agent_id: string, room_name: string, status: string, created_at: string, started_at?: string, ended_at?: string}>>}
 */
export async function fetchCalls(limit = 50) {
  const response = await fetch(`${API_BASE_URL}/calls?limit=${limit}`, {
    headers: { 'Accept': 'application/json' },
  });
  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`Failed to load calls (${response.status}): ${errorText || response.statusText}`);
  }
  return response.json();
}

/**
 * Generates a restricted stealth supervisor token for an ongoing call.
 * Permissions: Audio subscribe only, data channel publish only, hidden participant.
 * @param {string} callId
 * @param {string} [supervisorName]
 * @param {string} [supervisorIdentity]
 * @returns {Promise<{call_id: string, room_name: string, supervisor_identity: string, livekit_url: string, livekit_token: string}>}
 */
export async function fetchSupervisorToken(callId, supervisorName = 'Supervisor', supervisorIdentity = '') {
  const payload = {
    supervisor_name: supervisorName,
    supervisor_identity: supervisorIdentity || undefined,
  };

  const response = await fetch(`${API_BASE_URL}/calls/${callId}/supervisor-token`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Accept': 'application/json',
    },
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    const errData = await response.json().catch(() => ({}));
    throw new Error(errData.detail || `Failed to generate supervisor token (${response.status})`);
  }

  return response.json();
}

/**
 * Retrieves call session details including private supervisor whispers (include_private=true).
 * @param {string} callId
 * @returns {Promise<{id: string, status: string, transcripts: Array<{speaker: string, text: string, relative_time_ms: number, is_private: boolean}>}>}
 */
export async function fetchSupervisorCallDetails(callId) {
  const response = await fetch(`${API_BASE_URL}/calls/${callId}?include_private=true`, {
    headers: { 'Accept': 'application/json' },
  });

  if (!response.ok) {
    throw new Error(`Failed to fetch call details (${response.status})`);
  }

  return response.json();
}
