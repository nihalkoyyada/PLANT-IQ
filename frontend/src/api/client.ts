import axios from 'axios';

// Base API URL using relative /api path (proxied by Vite) or fallback to direct FastAPI server
const BASE_URL = import.meta.env.VITE_API_URL || '/api';

export const apiClient = axios.create({
  baseURL: BASE_URL,
  timeout: 30000,
});

// Request Interceptor: Automatically attach Bearer token if present
apiClient.interceptors.request.use(
  (config) => {
    const token = localStorage.getItem('plantiq_token');
    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }
    // CRITICAL: Do NOT set a global Content-Type header here so FormData multipart boundaries remain intact.
    return config;
  },
  (error) => Promise.reject(error)
);

// Response Interceptor: Catch 401 Unauthorized errors and clear invalid session
apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      localStorage.removeItem('plantiq_token');
      // Dispatch custom event so AuthContext updates state cleanly
      window.dispatchEvent(new Event('plantiq_unauthorized'));
    } else {
      console.error('API Call Error:', error.response?.status, error.response?.data || error.message);
    }
    return Promise.reject(error);
  }
);
