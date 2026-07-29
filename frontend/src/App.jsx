import { Toaster } from "@/components/ui/toaster"
import { QueryClientProvider } from '@tanstack/react-query'
import { queryClientInstance } from '@/lib/query-client'
import { BrowserRouter as Router, Route, Routes, Navigate } from 'react-router-dom';
import PageNotFound from './lib/PageNotFound';
import ErrorBoundary from '@/components/ErrorBoundary';
import { AuthProvider, useAuth } from '@/lib/AuthContext';
import UserNotRegisteredError from '@/components/UserNotRegisteredError';
import { SkywatcherDataProvider } from '@/lib/SkywatcherData';
import { DrawerHubProvider } from '@/components/skywatcher/drawers/DrawerHub';
import Layout from '@/components/skywatcher/Layout';
import Dashboard from '@/pages/Dashboard';
import Observations from '@/pages/Observations';
import Aircraft from '@/pages/Aircraft';
import FR24Intake from '@/pages/FR24Intake';
import RoutesPage from '@/pages/Routes';
import Infrastructure from '@/pages/Infrastructure';
import Airports from '@/pages/Airports';
import ManualReview from '@/pages/ManualReview';
import ExportCenter from '@/pages/ExportCenter';
import Readiness from '@/pages/Readiness';
import Calibration from '@/pages/Calibration';
import Login from '@/pages/Login';
import Register from '@/pages/Register';
import ForgotPassword from '@/pages/ForgotPassword';
import ResetPassword from '@/pages/ResetPassword';
import LoadingState from '@/components/skywatcher/LoadingState';
import { appParams } from '@/lib/app-params';

const AuthenticatedApp = () => {
  const { appPublicSettings, isLoadingPublicSettings } = useAuth();

  // Wait for public settings before routing. appPublicSettings is null until
  // AuthContext.checkAppState() resolves, so routing on it early would treat a
  // backend that reports requires_auth=true as diagnostic mode for one render —
  // long enough to redirect a direct visit to /login away to /, after which the
  // login page is unreachable because the URL has already changed.
  if (isLoadingPublicSettings) {
    return <LoadingState />;
  }

  // Same signal AuthContext uses to decide whether authentication is required.
  const authRequired = Boolean(
    appPublicSettings?.public_settings?.requires_auth || appParams.requireAuth
  );

  return (
    <SkywatcherDataProvider>
      <DrawerHubProvider>
        <Routes>
          <Route element={<Layout />}>
            <Route path="/" element={<Dashboard />} />
            <Route path="/observations" element={<Observations />} />
            <Route path="/aircraft" element={<Aircraft />} />
            <Route path="/fr24" element={<FR24Intake />} />
            <Route path="/routes" element={<RoutesPage />} />
            <Route path="/infrastructure" element={<Infrastructure />} />
            <Route path="/airports" element={<Airports />} />
            <Route path="/review" element={<ManualReview />} />
            <Route path="/export" element={<ExportCenter />} />
            <Route path="/readiness" element={<Readiness />} />
            <Route path="/calibration" element={<Calibration />} />
          </Route>
          {/* Auth routes render only when authentication is actually required.
              In diagnostic mode the backend implements no /auth/login,
              /auth/register, /auth/verify-otp or /auth/password/* endpoint (they
              404) and /api/auth/me returns 401, so these forms could never
              complete a sign-in. Gate them on the same signal AuthContext uses. */}
          {authRequired ? (
            <>
              <Route path="/login" element={<Login />} />
              <Route path="/register" element={<Register />} />
              <Route path="/forgot-password" element={<ForgotPassword />} />
              <Route path="/reset-password" element={<ResetPassword />} />
            </>
          ) : (
            <>
              <Route path="/login" element={<Navigate to="/" replace />} />
              <Route path="/register" element={<Navigate to="/" replace />} />
              <Route path="/forgot-password" element={<Navigate to="/" replace />} />
              <Route path="/reset-password" element={<Navigate to="/" replace />} />
            </>
          )}
          <Route path="*" element={<PageNotFound />} />
        </Routes>
      </DrawerHubProvider>
    </SkywatcherDataProvider>
  );
};

function App() {
  return (
    <ErrorBoundary>
      <AuthProvider>
        <QueryClientProvider client={queryClientInstance}>
          <Router>
            <AuthenticatedApp />
          </Router>
          <Toaster />
        </QueryClientProvider>
      </AuthProvider>
    </ErrorBoundary>
  )
}

export default App
