import React, { createContext, useContext, useEffect, useState } from 'react';
import { User } from '../types';
import { getMeApi, loginApi } from '../api/auth';

interface AuthContextType {
  user: User | null;
  token: string | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  login: (email: string, password: string) => Promise<User>;
  logout: () => void;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [user, setUser] = useState<User | null>(null);
  const [token, setToken] = useState<string | null>(() => localStorage.getItem('plantiq_token'));
  const [isLoading, setIsLoading] = useState<boolean>(true);

  const logout = () => {
    localStorage.removeItem('plantiq_token');
    setToken(null);
    setUser(null);
  };

  useEffect(() => {
    async function initAuth() {
      const storedToken = localStorage.getItem('plantiq_token');
      if (storedToken) {
        try {
          const userData = await getMeApi();
          setUser(userData);
          setToken(storedToken);
        } catch (err) {
          console.warn('Invalid or expired authentication session:', err);
          logout();
        }
      } else {
        setUser(null);
        setToken(null);
      }
      setIsLoading(false);
    }

    initAuth();

    const handleUnauthorized = () => {
      logout();
    };

    window.addEventListener('plantiq_unauthorized', handleUnauthorized);
    return () => {
      window.removeEventListener('plantiq_unauthorized', handleUnauthorized);
    };
  }, []);

  const login = async (email: string, password: string): Promise<User> => {
    setIsLoading(true);
    try {
      const res = await loginApi(email, password);
      localStorage.setItem('plantiq_token', res.access_token);
      setToken(res.access_token);
      setUser(res.user);
      return res.user;
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <AuthContext.Provider
      value={{
        user,
        token,
        isAuthenticated: !!user && !!token,
        isLoading,
        login,
        logout,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
};

export const useAuth = (): AuthContextType => {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
};
