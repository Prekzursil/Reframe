import api from './api';

// Description: User login
// Endpoint: POST /api/auth/login
// Request: { email: string, password: string }
// Response: { accessToken: string, refreshToken: string }
export const login = async (email: string, password: string) => {
  // Mocking the response
  return new Promise((resolve) => {
    setTimeout(() => {
      resolve({
        accessToken: 'mock_access_token',
        refreshToken: 'mock_refresh_token'
      });
    }, 500);
  });
  // Uncomment below lines to make actual API call
  // try {
  //   const response = await api.post('/api/auth/login', { email, password });
  //   return response.data;
  // } catch (error) {
  //   throw new Error(error?.response?.data?.error || error.message);
  // }
};

// Description: User registration
// Endpoint: POST /api/auth/register
// Request: { email: string, password: string }
// Response: { success: boolean, message: string }
export const register = async (email: string, password: string) => {
  // Mocking the response
  return new Promise((resolve) => {
    setTimeout(() => {
      resolve({
        success: true,
        message: 'User registered successfully'
      });
    }, 500);
  });
  // Uncomment below lines to make actual API call
  // try {
  //   const response = await api.post('/api/auth/register', { email, password });
  //   return response.data;
  // } catch (error) {
  //   throw new Error(error?.response?.data?.error || error.message);
  // }
};

// Description: User logout
// Endpoint: POST /api/auth/logout
// Request: {}
// Response: { success: boolean }
export const logout = async () => {
  // Mocking the response
  return new Promise((resolve) => {
    setTimeout(() => {
      resolve({ success: true });
    }, 500);
  });
  // Uncomment below lines to make actual API call
  // try {
  //   const response = await api.post('/api/auth/logout');
  //   return response.data;
  // } catch (error) {
  //   throw new Error(error?.response?.data?.error || error.message);
  // }
};