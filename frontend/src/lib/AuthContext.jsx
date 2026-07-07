import React, { createContext, useState, useContext, useEffect, useCallback } from 'react';
import { federation } from '@/api/federationClient';
import { appParams } from '@/lib/app-params';

const AuthContext = createContext();

export const AuthProvider = ({ children }) => {
  const [user, setUser] = useState(null);
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [isLoadingAuth, setIsLoadingAuth] = useState(true);
  const [isLoadingPublicSettings, setIsLoadingPublicSettings] = useState(true);
  const [authError, setAuthError] = useState(null);
  const [authChecked, setAuthChecked] = useState(false);
  const [appPublicSettings, setAppPublicSettings] = useState(null);

  const checkUserAuth = useCallback(async (authRequired = true) => {
    try {
      setIsLoadingAuth(true);
      const currentUser = await federation.auth.me();
      setUser(currentUser);
      setIsAuthenticated(true);
      setAuthError(null);
    } catch (error) {
      setUser(null);
      setIsAuthenticated(false);
      if (error.status === 401 || error.status === 403) {
        if (authRequired) {
          setAuthError({ type: 'auth_required', message: 'Authentication required' });
        } else {
          // Public/diagnostic mode: a stale stored token must not trap the
          // session in a login redirect — drop it and continue anonymously.
          // appParams.token is captured at module load and request() prefers
          // it over storage, so clear the in-memory copy too.
          federation.auth.setToken(null);
          appParams.token = null;
        }
      } else if (appParams.requireAuth) {
        setAuthError({ type: 'unknown', message: error.message || 'Authentication check failed' });
      }
    } finally {
      setIsLoadingAuth(false);
      setAuthChecked(true);
    }
  }, []);

  const checkAppState = useCallback(async () => {
    try {
      setIsLoadingPublicSettings(true);
      setAuthError(null);
      const publicSettings = await federation.system.publicSettings();
      setAppPublicSettings(publicSettings);

      const authRequired = Boolean(
        publicSettings?.public_settings?.requires_auth || appParams.requireAuth
      );
      if (federation.auth.isAuthenticated()) {
        await checkUserAuth(authRequired);
      } else {
        setIsAuthenticated(false);
        setIsLoadingAuth(false);
        setAuthChecked(true);
        if (authRequired) {
          setAuthError({ type: 'auth_required', message: 'Authentication required' });
        }
      }
    } catch (error) {
      setAuthError({ type: 'unknown', message: error.message || 'Failed to load application settings' });
      setIsLoadingAuth(false);
      setAuthChecked(true);
    } finally {
      setIsLoadingPublicSettings(false);
    }
  }, [checkUserAuth]);

  useEffect(() => {
    checkAppState();
  }, [checkAppState]);

  const logout = (shouldRedirect = true) => {
    setUser(null);
    setIsAuthenticated(false);
    federation.auth.logout(shouldRedirect ? window.location.href : undefined);
  };

  const navigateToLogin = () => {
    federation.auth.redirectToLogin(window.location.href);
  };

  return (
    <AuthContext.Provider value={{
      user,
      isAuthenticated,
      isLoadingAuth,
      isLoadingPublicSettings,
      authError,
      appPublicSettings,
      authChecked,
      logout,
      navigateToLogin,
      checkUserAuth,
      checkAppState,
    }}>
      {children}
    </AuthContext.Provider>
  );
};

export const useAuth = () => {
  const context = useContext(AuthContext);
  if (!context) throw new Error('useAuth must be used within an AuthProvider');
  return context;
};
